#!/usr/bin/env python3
"""Kiwix app manager for Home Assistant.

Runs five things in one small process (standard library only):

* a supervisor that keeps ``kiwix-serve`` running for every ZIM file in the
  library directory and restarts it whenever the library changes (one
  instance on a published port, one behind Home Assistant ingress),
* a reverse proxy that exposes the ingress instance as ``reader/``,
* a publisher that exposes the library as ``sensor.kiwix_library`` in Home
  Assistant (for dashboards and automations),
* a client for the public Kiwix catalog (OPDS), and
* a resumable download manager, exposed through a small web UI that is
  served via Home Assistant ingress.
"""

import base64
import http.client
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LIBRARY_DIR = Path(os.environ.get("KIWIX_LIBRARY_DIR", "/share/kiwix"))
QUEUE_FILE = LIBRARY_DIR / ".downloads.json"
CATALOG_URL = os.environ.get(
    "KIWIX_CATALOG_URL", "https://library.kiwix.org/catalog/v2/entries"
)
DOWNLOAD_HOST = os.environ.get("KIWIX_DOWNLOAD_HOST", "download.kiwix.org")
KIWIX_SERVE = os.environ.get("KIWIX_SERVE_BIN", "/usr/local/bin/kiwix-serve")
KIWIX_PORT = int(os.environ.get("KIWIX_PORT", "8080"))
READER_PORT = int(os.environ.get("KIWIX_READER_PORT", "8081"))
MANAGER_PORT = int(os.environ.get("MANAGER_PORT", "8099"))
# Home Assistant's ingress gateway; only it (and localhost) may reach the UI.
ALLOWED_CLIENTS = set(
    os.environ.get("KIWIX_ALLOWED_CLIENTS", "172.30.32.2,127.0.0.1").split(",")
)
HA_API_URL = os.environ.get("KIWIX_HA_API_URL", "http://supervisor/core/api")
HA_WS_ADDRESS = (os.environ.get("KIWIX_HA_WS_HOST", "supervisor"), int(os.environ.get("KIWIX_HA_WS_PORT", "80")))
SENSOR_ENTITY = "sensor.kiwix_library"
USER_AGENT = "ha-addon-kiwix (+https://github.com/okristensen/ha-addon-kiwix)"
WEB_DIR = Path(__file__).resolve().parent / "web"
SPACE_MARGIN = 1 << 30  # always keep 1 GiB free
FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.zim")
ZIM_NAME_RE = re.compile(r"(.+)_(\d{4}-\d{2})\.zim")
INGRESS_PATH_RE = re.compile(r"/api/hassio_ingress/[A-Za-z0-9_-]+")
HOP_BY_HOP = {
    "connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
    "proxy-authenticate", "proxy-authorization", "server", "date",
}
FORWARDED_HEADERS = {
    "accept", "accept-language", "if-modified-since", "if-none-match", "range",
    "referer", "user-agent",
}

STATIC_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
}


def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)


# --------------------------------------------------------------------------
# kiwix-serve supervisor
# --------------------------------------------------------------------------
class KiwixServer:
    """Keeps one kiwix-serve process running for all ZIM files.

    ``root`` is the URL prefix kiwix-serve generates links for. An instance
    created with ``needs_root=True`` stays idle until a root has been set.
    """

    def __init__(self, name, port, needs_root=False):
        self.name = name
        self.port = port
        self.root = None
        self._needs_root = needs_root
        self._proc = None
        self._lock = threading.Lock()
        self._last_start = 0.0

    def set_root(self, root):
        if root != self.root:
            self.root = root
            self.restart()

    @staticmethod
    def zim_files():
        return sorted(LIBRARY_DIR.glob("*.zim"))

    @property
    def running(self):
        return self._proc is not None and self._proc.poll() is None

    def restart(self):
        with self._lock:
            self._stop()
            self._start()

    def stop(self):
        with self._lock:
            self._stop()

    def ensure_running(self):
        """Watchdog: bring the server back if it died (at most every 30 s)."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is not None:
                log(f"{self.name}: kiwix-serve exited with code {self._proc.returncode}")
                self._proc = None
            if (
                self._proc is None
                and self.zim_files()
                and time.monotonic() - self._last_start > 30
            ):
                self._start()

    def _start(self):
        if self._needs_root and not self.root:
            return
        files = self.zim_files()
        self._last_start = time.monotonic()
        if not files:
            log(f"{self.name}: no ZIM files yet - kiwix-serve not started")
            return
        command = [KIWIX_SERVE, f"--port={self.port}"]
        if self.root:
            command.append(f"--urlRootLocation={self.root}")
        log(f"{self.name}: starting kiwix-serve with {len(files)} ZIM file(s)")
        self._proc = subprocess.Popen([*command, *map(str, files)])

    def _stop(self):
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._proc = None


kiwix = KiwixServer("direct", KIWIX_PORT)
reader = KiwixServer("ingress", READER_PORT, needs_root=True)
SERVERS = (kiwix, reader)


def restart_servers():
    for server in SERVERS:
        server.restart()
    publish_sensor()


def note_ingress_path(path):
    """Remember where Home Assistant mounts this app and serve the reader there."""
    if path and INGRESS_PATH_RE.fullmatch(path):
        reader.set_root(f"{path}/reader")


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------
def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child_text(element, name):
    for child in element:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _is_download_host(hostname):
    """True for the Kiwix download host and its subdomains (e.g. lb.download...)."""
    hostname = (hostname or "").lower()
    return hostname == DOWNLOAD_HOST or hostname.endswith("." + DOWNLOAD_HOST)


def normalize_download_url(url):
    """Strip the Metalink suffix and upgrade Kiwix's http links to https."""
    if url.endswith(".meta4"):
        url = url[: -len(".meta4")]
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "http" and _is_download_host(parsed.hostname):
        url = parsed._replace(scheme="https").geturl()
    return url


def is_allowed_download_url(url):
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and _is_download_host(parsed.hostname)
        and parsed.path.endswith(".zim")
    )


SEARCH_PAGE_CSS = """
:root{color-scheme:light dark;--bg:#f3f5f8;--card:#fff;--text:#14181d;--muted:#66707c;--border:#e1e5ea;--accent:#0a8ee8;--accent2:#5b6cf0;--chip:#eef1f5}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#1a1e24;--text:#eceff3;--muted:#8d97a3;--border:#292f37;--chip:#252b33}}
html,body{background:var(--bg)!important;color:var(--text)!important}
body{margin:0!important;padding:14px 14px calc(88px + env(safe-area-inset-bottom))!important;
 font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif!important}
.header{font-size:14px!important;color:var(--muted)!important;margin:4px 2px 14px!important}
.header b{color:var(--text)!important}
ul{list-style:none!important;margin:0!important;padding:0!important}
.results li,li.result{background:var(--card)!important;border:1px solid var(--border)!important;border-radius:18px!important;
 padding:14px 16px!important;margin:0 0 12px!important;box-shadow:0 1px 2px rgba(16,24,40,.06),0 6px 18px rgba(16,24,40,.06);overflow:hidden}
.results a{color:var(--text)!important;text-decoration:none!important;font-weight:700!important;font-size:18px!important;
 line-height:1.3;overflow-wrap:anywhere;display:inline-block}
cite{display:block!important;font-style:normal!important;font-size:14px!important;color:var(--muted)!important;margin-top:6px;
 overflow-wrap:anywhere;max-height:6.6em;overflow:hidden}
cite b{color:var(--text)!important}
.book-title,.informations{display:inline-block!important;margin:10px 6px 0 0!important;padding:2px 10px;border-radius:999px;
 background:var(--chip)!important;color:var(--muted)!important;font-size:12px!important;font-weight:600}
footer{margin-top:18px}
footer ul{display:flex!important;flex-wrap:wrap;gap:8px;justify-content:center}
footer li a{display:block;padding:9px 15px;border-radius:12px;background:var(--card);border:1px solid var(--border);
 color:var(--text)!important;text-decoration:none!important;font-weight:600}
#kiwix-home-bar{position:fixed;left:0;right:0;bottom:0;z-index:2147483647;display:flex;justify-content:flex-start;
 padding:10px 14px calc(10px + env(safe-area-inset-bottom));background:color-mix(in srgb,var(--bg) 82%,transparent);
 -webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);border-top:1px solid var(--border)}
#kiwix-home-bar a{display:inline-flex;align-items:center;gap:6px;padding:10px 18px;border-radius:999px;color:#fff!important;
 text-decoration:none!important;font:600 15px system-ui,sans-serif;background:linear-gradient(135deg,var(--accent),var(--accent2))}
"""


def add_back_link(html, accept_language, ingress_path):
    """Style a search result page like the front page and add a bar leading back to it."""
    label = "\u2190 Forside" if accept_language.lower().startswith("da") else "\u2190 Home"
    style = ("<style>" + SEARCH_PAGE_CSS + "</style>").encode()
    bar = f'<div id="kiwix-home-bar"><a href="{ingress_path}/reader/">{label}</a></div>'.encode()
    lowered = html.lower()
    head = lowered.rfind(b"</head>")
    html = style + html if head == -1 else html[:head] + style + html[head:]
    index = html.lower().rfind(b"</body>")
    if index == -1:
        return html + bar
    return html[:index] + bar + html[index:]


def add_home_button(html, accept_language, ingress_path):
    """Add a floating "front page" button, bottom left, to a reader page.

    It is shown on every page that fills the window (viewer, articles opened
    from search results, error pages). An article shown inside the viewer's
    iframe stays without one, since the viewer page carries it (decided in the
    browser by checking whether the page sits in a frame).
    """
    label = "\u2190 Forside" if accept_language.lower().startswith("da") else "\u2190 Home"
    snippet = (
        '<a id="kiwix-home-btn" href="' + ingress_path + '/reader/" style="display:none;position:fixed;left:12px;'
        "bottom:calc(12px + env(safe-area-inset-bottom));z-index:2147483647;align-items:center;"
        "padding:10px 18px;border-radius:999px;color:#fff;text-decoration:none;"
        "font:600 15px system-ui,sans-serif;background:linear-gradient(135deg,#0a8ee8,#5b6cf0);"
        'box-shadow:0 4px 14px rgba(0,0,0,.3)">' + label + "</a>"
        "<script>(function(){var framed=false;"
        "try{framed=parent!==window}catch(e){framed=true}"
        'if(!framed){document.getElementById("kiwix-home-btn").style.display="inline-flex";'
        'document.body.style.paddingBottom="calc(76px + env(safe-area-inset-bottom))"}})();</script>'
    ).encode()
    index = html.lower().rfind(b"</body>")
    if index == -1:
        return html + snippet
    return html[:index] + snippet + html[index:]


def parse_catalog(xml_bytes):
    """Parse a Kiwix OPDS feed into ``(total_results, entries)``."""
    root = ET.fromstring(xml_bytes)
    total = _to_int(_child_text(root, "totalResults"))
    entries = []
    for entry in root:
        if _local(entry.tag) != "entry":
            continue
        url, size = "", 0
        for link in entry:
            if _local(link.tag) == "link" and link.get("type") == "application/x-zim":
                url = link.get("href", "")
                size = _to_int(link.get("length"))
        url = normalize_download_url(url)
        if not url:
            continue
        entries.append(
            {
                "file": url.rsplit("/", 1)[-1],
                "url": url,
                "size": size,
                "title": _child_text(entry, "title"),
                "description": _child_text(entry, "summary"),
                "language": _child_text(entry, "language"),
                "category": _child_text(entry, "category"),
                "flavour": _child_text(entry, "flavour"),
                "updated": _child_text(entry, "updated")[:10],
                "articles": _to_int(_child_text(entry, "articleCount")),
            }
        )
    return total, entries


def fetch_catalog(query, lang, category, start, count=20):
    params = {"count": count, "start": start}
    if query:
        params["q"] = query
    if lang:
        params["lang"] = lang
    if category:
        params["category"] = category
    request = urllib.request.Request(
        f"{CATALOG_URL}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        total, entries = parse_catalog(response.read())
    return {"total": total, "start": start, "entries": entries}


# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------
class Job:
    def __init__(self, url, filename, size):
        self.url = url
        self.file = filename
        self.total = size
        self.done = 0
        self.status = "queued"  # queued | downloading | error
        self.error = ""
        self.cancel = threading.Event()

    def to_dict(self):
        return {
            "file": self.file,
            "total": self.total,
            "done": self.done,
            "status": self.status,
            "error": self.error,
        }


class DownloadManager:
    """Downloads one ZIM at a time, resuming partial files."""

    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()
        self._slot = threading.Semaphore(1)

    def snapshot(self):
        with self._lock:
            return [job.to_dict() for job in self._jobs.values()]

    def _save_locked(self):
        """Remember unfinished downloads so they continue after a restart."""
        pending = [
            {"url": job.url, "size": job.total}
            for job in self._jobs.values()
            if job.status != "error" and not job.cancel.is_set()
        ]
        try:
            if pending:
                QUEUE_FILE.write_text(json.dumps(pending))
            else:
                QUEUE_FILE.unlink(missing_ok=True)
        except OSError as error:
            log(f"Could not save the download queue: {error}")

    def resume(self):
        """Restart downloads that were running when the app was stopped."""
        try:
            pending = json.loads(QUEUE_FILE.read_text())
        except (OSError, ValueError):
            return
        for entry in pending if isinstance(pending, list) else []:
            try:
                self.start(str(entry.get("url", "")), _to_int(entry.get("size")))
                log(f"Resuming download of {str(entry.get('url', '')).rsplit('/', 1)[-1]}")
            except (ValueError, AttributeError) as error:
                log(f"Not resuming a download: {error}")
        with self._lock:
            self._save_locked()

    def start(self, url, size):
        url = normalize_download_url(url)
        if not is_allowed_download_url(url):
            log(f"Rejected download URL: {url!r}")
            raise ValueError("Unsupported download URL")
        filename = url.rsplit("/", 1)[-1]
        if not FILENAME_RE.fullmatch(filename):
            raise ValueError("Unsupported file name")
        if (LIBRARY_DIR / filename).exists():
            raise ValueError("Already installed")
        with self._lock:
            existing = self._jobs.get(filename)
            if existing and existing.status != "error":
                raise ValueError("Already downloading")
            job = Job(url, filename, size)
            self._jobs[filename] = job
            self._save_locked()
        threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def cancel(self, filename):
        """Cancel a running job, or dismiss a failed one."""
        with self._lock:
            job = self._jobs.get(filename)
            if job is None:
                return
            if job.status == "error":
                del self._jobs[filename]
            else:
                job.cancel.set()
            self._save_locked()

    def _finish(self, job):
        with self._lock:
            self._jobs.pop(job.file, None)
            self._save_locked()
        publish_sensor()

    def _run(self, job):
        part = LIBRARY_DIR / f"{job.file}.part"
        with self._slot:
            if job.cancel.is_set():
                self._finish(job)
                return
            job.status = "downloading"
            publish_sensor()
            try:
                self._download(job, part)
            except Exception as error:  # noqa: BLE001 - report any failure in the UI
                job.status = "error"
                job.error = str(error)
                log(f"Download of {job.file} failed: {error}")
                with self._lock:
                    self._save_locked()
                publish_sensor()
                return
        if job.cancel.is_set():
            part.unlink(missing_ok=True)
            self._finish(job)
            return
        part.rename(LIBRARY_DIR / job.file)
        log(f"Downloaded {job.file}")
        self._finish(job)
        restart_servers()

    def _download(self, job, part):
        offset = part.stat().st_size if part.exists() else 0
        job.done = offset
        if job.total and offset >= job.total:
            return  # partial file is already complete
        needed = max(job.total - offset, 0)
        free = shutil.disk_usage(LIBRARY_DIR).free
        if needed + SPACE_MARGIN > free:
            raise OSError("Not enough free disk space")

        headers = {"User-Agent": USER_AGENT}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(job.url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            if offset and response.status != 206:
                offset = 0  # server ignored Range - start over
            length = _to_int(response.headers.get("Content-Length"))
            if length:
                job.total = offset + length
            job.done = offset
            with open(part, "ab" if offset else "wb") as out:
                while True:
                    if job.cancel.is_set():
                        return
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    job.done += len(chunk)


downloads = DownloadManager()


# --------------------------------------------------------------------------
# Home Assistant sensor
# --------------------------------------------------------------------------
GIB = 1 << 30


def sensor_payload():
    """Build the ``sensor.kiwix_library`` state: ZIM count plus details."""
    files = []
    total = 0
    for path in kiwix.zim_files():
        size = path.stat().st_size
        total += size
        match = ZIM_NAME_RE.fullmatch(path.name)
        name = (match.group(1) if match else path.stem).replace("_", " ")
        files.append(
            {
                "name": name[:1].upper() + name[1:],
                "file": path.name,
                "date": match.group(2) if match else "",
                "size_gb": round(size / GIB, 2),
            }
        )
    active = [
        {
            "file": job["file"],
            "status": job["status"],
            "percent": int(job["done"] * 100 / job["total"]) if job["total"] else 0,
        }
        for job in downloads.snapshot()
        if job["status"] != "error"
    ]
    return {
        "state": len(files),
        "attributes": {
            "friendly_name": "Kiwix library",
            "icon": "mdi:book-open-page-variant",
            "files": files,
            "total_size_gb": round(total / GIB, 2),
            "free_space_gb": round(shutil.disk_usage(LIBRARY_DIR).free / GIB, 1),
            "reader_running": kiwix.running,
            "downloads": active,
        },
    }


def publish_sensor():
    """Write the library to Home Assistant. Never raises: it is best effort."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    try:
        request = urllib.request.Request(
            f"{HA_API_URL}/states/{SENSOR_ENTITY}",
            data=json.dumps(sensor_payload()).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        urllib.request.urlopen(request, timeout=10).close()
    except Exception as error:  # noqa: BLE001 - best effort, report once per failure
        log(f"Could not update {SENSOR_ENTITY}: {error}")


# --------------------------------------------------------------------------
# Who is an administrator?
# --------------------------------------------------------------------------
# Home Assistant ingress tells the app which user is calling (X-Remote-User-Id)
# but not whether that user is an administrator, so the list of users is read
# from Home Assistant's websocket API with the app's own token.
class _WebSocket:
    """Just enough of a websocket client to ask Home Assistant one question."""

    def __init__(self, address, path, timeout=10):
        self.sock = socket.create_connection(address, timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\nHost: {address[0]}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        self.buffer = b""
        while b"\r\n\r\n" not in self.buffer:
            self.buffer += self._read(4096)
        head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise OSError("websocket upgrade refused")

    def _read(self, size):
        chunk = self.sock.recv(size)
        if not chunk:
            raise OSError("websocket closed")
        return chunk

    def _take(self, size):
        while len(self.buffer) < size:
            self.buffer += self._read(65536)
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def send(self, payload):
        data = json.dumps(payload).encode()
        mask = os.urandom(4)
        size = len(data)
        if size < 126:
            header = bytes([0x81, 0x80 | size])
        elif size < 65536:
            header = bytes([0x81, 0x80 | 126]) + struct.pack(">H", size)
        else:
            header = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", size)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        self.sock.sendall(header + mask + masked)

    def receive(self):
        message = b""
        while True:
            first, second = self._take(2)
            size = second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._take(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._take(8))[0]
            data = self._take(size)  # server frames are not masked
            opcode = first & 0x0F
            if opcode == 8:
                raise OSError("websocket closed")
            if opcode in (9, 10):
                continue  # ping/pong
            message += data
            if first & 0x80:
                return json.loads(message)

    def close(self):
        self.sock.close()


def fetch_admin_ids():
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise OSError("no SUPERVISOR_TOKEN")
    ws = _WebSocket(HA_WS_ADDRESS, "/core/websocket")
    try:
        ws.receive()  # auth_required
        ws.send({"type": "auth", "access_token": token})
        if ws.receive().get("type") != "auth_ok":
            raise OSError("Home Assistant refused the app token")
        ws.send({"id": 1, "type": "config/auth/list"})
        while True:
            reply = ws.receive()
            if reply.get("id") == 1:
                break
        if not reply.get("success"):
            raise OSError(f"could not list users: {reply.get('error')}")
        return {
            user["id"]
            for user in reply["result"]
            if user.get("is_owner") or "system-admin" in user.get("group_ids", [])
        }
    finally:
        ws.close()


class Admins:
    """Cached list of Home Assistant administrators."""

    def __init__(self, ttl=60):
        self._ttl = ttl
        self._ids = set()
        self._fetched = None
        self._lock = threading.Lock()

    def is_admin(self, user_id):
        if not user_id:
            return False
        with self._lock:
            now = time.monotonic()
            if self._fetched is None or now - self._fetched > self._ttl:
                try:
                    self._ids = fetch_admin_ids()
                    self._fetched = now
                except (OSError, ValueError, KeyError) as error:
                    log(f"Could not read the administrator list: {error}")
                    self._fetched = now - self._ttl + 10  # try again in 10 s
            return user_id in self._ids


admins = Admins()


# --------------------------------------------------------------------------
# HTTP API
# --------------------------------------------------------------------------
def library_state():
    files = []
    for path in kiwix.zim_files():
        info = path.stat()
        files.append({"file": path.name, "size": info.st_size, "mtime": int(info.st_mtime)})
    return {
        "running": kiwix.running,
        "reader": reader.running,
        "port": KIWIX_PORT,
        "free": shutil.disk_usage(LIBRARY_DIR).free,
        "library": files,
        "downloads": downloads.snapshot(),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "KiwixManager"

    def log_message(self, fmt, *args):
        log(f"{self.client_address[0]} {fmt % args}")

    # -- helpers ---------------------------------------------------------
    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _body(self):
        length = min(_to_int(self.headers.get("Content-Length")), 65536)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}

    def _guard(self):
        if self.client_address[0] not in ALLOWED_CLIENTS:
            self._json(403, {"error": "Forbidden"})
            return False
        return True

    def _is_admin(self):
        return admins.is_admin(self.headers.get("X-Remote-User-Id", "").strip())

    # -- routes ----------------------------------------------------------
    def do_GET(self):  # noqa: N802 - http.server naming
        if not self._guard():
            return
        note_ingress_path(self.headers.get("X-Ingress-Path", ""))
        parsed = urllib.parse.urlparse(self.path)
        route = "/" + parsed.path.strip("/")
        if route == "/reader" and not parsed.path.endswith("/"):
            self.send_response(302)
            self.send_header("Location", "reader/")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif route == "/reader":
            # The reader's own front page is replaced by ours (web/home.html).
            self._send(200, (WEB_DIR / "home.html").read_bytes(), "text/html; charset=utf-8")
        elif route.startswith("/reader/"):
            self._proxy_reader()
        elif route == "/api/state":
            self._json(200, library_state())
        elif route == "/api/me":
            self._json(200, {"admin": self._is_admin()})
        elif route == "/api/catalog":
            if self._is_admin():
                self._catalog(urllib.parse.parse_qs(parsed.query))
            else:
                self._json(403, {"error": "Administrators only"})
        elif route in ("/", "/index.html") and not self._is_admin():
            # Managing content is for administrators; everyone else gets the reader.
            self.send_response(302)
            self.send_header("Location", "reader/")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            name = "index.html" if route == "/" else route.lstrip("/")
            if name in STATIC_TYPES:
                self._send(200, (WEB_DIR / name).read_bytes(), STATIC_TYPES[name])
            else:
                self._json(404, {"error": "Not found"})

    def do_POST(self):  # noqa: N802
        if not self._guard():
            return
        route = "/" + urllib.parse.urlparse(self.path).path.strip("/")
        if not self._is_admin():
            self._json(403, {"error": "Administrators only"})
            return
        body = self._body()
        try:
            if route == "/api/download":
                downloads.start(str(body.get("url", "")), _to_int(body.get("size")))
            elif route == "/api/cancel":
                downloads.cancel(str(body.get("file", "")))
            elif route == "/api/delete":
                self._delete(str(body.get("file", "")))
            else:
                self._json(404, {"error": "Not found"})
                return
        except ValueError as error:
            self._json(400, {"error": str(error)})
            return
        self._json(200, {"ok": True})

    def _proxy_reader(self):
        """Forward a request to the ingress kiwix-serve instance."""
        if not reader.running or not reader.root:
            self._json(503, {"error": "The reader is not running yet"})
            return
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() in FORWARDED_HEADERS
        }
        headers["Host"] = self.headers.get("Host", "")
        # kiwix-serve is configured with the full ingress prefix as its root,
        # so the prefix Home Assistant strips has to be added back.
        ingress_path = reader.root.removesuffix("/reader")
        upstream_path = ingress_path + self.path
        connection = http.client.HTTPConnection("127.0.0.1", reader.port, timeout=60)
        started = False
        try:
            connection.request("GET", upstream_path, headers=headers)
            upstream = connection.getresponse()
            # Search result pages and articles opened on their own have no way
            # back to the front page, so they get one; the viewer has a toolbar.
            body = None
            page = self.path.split("?", 1)[0]
            decorate = None
            if page.rstrip("/") == "/reader/search":
                decorate = add_back_link
            elif page.startswith("/reader/") and page != "/reader/":
                decorate = add_home_button
            if (
                decorate
                and upstream.getheader("Content-Type", "").startswith("text/html")
                and not upstream.getheader("Content-Encoding")
            ):
                body = decorate(
                    upstream.read(),
                    self.headers.get("Accept-Language", ""),
                    ingress_path,
                )
            self.send_response(upstream.status)
            for key, value in upstream.getheaders():
                if key.lower() in HOP_BY_HOP or (body is not None and key.lower() == "content-length"):
                    continue
                self.send_header(key, value)
            if body is not None:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            started = True
            if body is not None:
                self.wfile.write(body)
            else:
                while chunk := upstream.read(65536):
                    self.wfile.write(chunk)
        except (OSError, http.client.HTTPException) as error:
            log(f"Reader proxy error: {error}")
            if not started:
                self._json(502, {"error": "The reader did not respond"})
        finally:
            connection.close()

    def _catalog(self, query):
        def first(key):
            return query.get(key, [""])[0]

        try:
            result = fetch_catalog(
                first("q"),
                first("lang"),
                first("category"),
                max(_to_int(first("start")), 0),
            )
        except (urllib.error.URLError, ET.ParseError, OSError) as error:
            log(f"Catalog request failed: {error}")
            self._json(502, {"error": "Could not reach the Kiwix catalog"})
            return
        self._json(200, result)

    @staticmethod
    def _delete(filename):
        if not FILENAME_RE.fullmatch(filename):
            raise ValueError("Invalid file name")
        path = LIBRARY_DIR / filename
        if not path.is_file():
            raise ValueError("File not found")
        path.unlink()
        log(f"Deleted {filename}")
        restart_servers()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def watchdog(interval=15, publish_every=60):
    elapsed = 0
    while True:
        time.sleep(interval)
        elapsed += interval
        for server in SERVERS:
            server.ensure_running()
        if elapsed >= publish_every:
            # Re-publish regularly: the entity disappears when Home Assistant restarts.
            elapsed = 0
            publish_sensor()


def main():
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", MANAGER_PORT), Handler)

    def shutdown(*_):
        log("Shutting down")
        for kiwix_server in SERVERS:
            kiwix_server.stop()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    restart_servers()
    downloads.resume()
    threading.Thread(target=watchdog, daemon=True).start()

    log(f"Manager listening on port {MANAGER_PORT}, library in {LIBRARY_DIR}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
