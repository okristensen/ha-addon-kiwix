#!/usr/bin/env python3
"""Kiwix app manager for Home Assistant.

Runs three things in one small process (standard library only):

* a supervisor that keeps ``kiwix-serve`` running for every ZIM file in the
  library directory and restarts it whenever the library changes,
* a client for the public Kiwix catalog (OPDS), and
* a resumable download manager, exposed through a small web UI that is
  served via Home Assistant ingress.
"""

import json
import os
import re
import shutil
import signal
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
CATALOG_URL = os.environ.get(
    "KIWIX_CATALOG_URL", "https://library.kiwix.org/catalog/v2/entries"
)
DOWNLOAD_PREFIX = os.environ.get("KIWIX_DOWNLOAD_PREFIX", "https://download.kiwix.org/")
KIWIX_SERVE = os.environ.get("KIWIX_SERVE_BIN", "/usr/local/bin/kiwix-serve")
KIWIX_PORT = int(os.environ.get("KIWIX_PORT", "8080"))
MANAGER_PORT = int(os.environ.get("MANAGER_PORT", "8099"))
# Home Assistant's ingress gateway; only it (and localhost) may reach the UI.
ALLOWED_CLIENTS = set(
    os.environ.get("KIWIX_ALLOWED_CLIENTS", "172.30.32.2,127.0.0.1").split(",")
)
USER_AGENT = "ha-addon-kiwix (+https://github.com/okristensen/ha-addon-kiwix)"
WEB_DIR = Path(__file__).resolve().parent / "web"
SPACE_MARGIN = 1 << 30  # always keep 1 GiB free
FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.zim")

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
    """Keeps one kiwix-serve process running for all ZIM files."""

    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()
        self._last_start = 0.0

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
                log(f"kiwix-serve exited with code {self._proc.returncode}")
                self._proc = None
            if (
                self._proc is None
                and self.zim_files()
                and time.monotonic() - self._last_start > 30
            ):
                self._start()

    def _start(self):
        files = self.zim_files()
        self._last_start = time.monotonic()
        if not files:
            log("No ZIM files yet - kiwix-serve not started")
            return
        log(f"Starting kiwix-serve with {len(files)} ZIM file(s)")
        self._proc = subprocess.Popen(
            [KIWIX_SERVE, f"--port={KIWIX_PORT}", *map(str, files)]
        )

    def _stop(self):
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._proc = None


kiwix = KiwixServer()


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


def normalize_download_url(url):
    """Strip the Metalink suffix and upgrade Kiwix's http links to https."""
    if url.endswith(".meta4"):
        url = url[: -len(".meta4")]
    if url.startswith("http://download.kiwix.org/"):
        url = "https://" + url[len("http://"):]
    return url


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

    def start(self, url, size):
        url = normalize_download_url(url)
        if not url.startswith(DOWNLOAD_PREFIX) or not url.endswith(".zim"):
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

    def _finish(self, job):
        with self._lock:
            self._jobs.pop(job.file, None)

    def _run(self, job):
        part = LIBRARY_DIR / f"{job.file}.part"
        with self._slot:
            if job.cancel.is_set():
                self._finish(job)
                return
            job.status = "downloading"
            try:
                self._download(job, part)
            except Exception as error:  # noqa: BLE001 - report any failure in the UI
                job.status = "error"
                job.error = str(error)
                log(f"Download of {job.file} failed: {error}")
                return
        if job.cancel.is_set():
            part.unlink(missing_ok=True)
            self._finish(job)
            return
        part.rename(LIBRARY_DIR / job.file)
        log(f"Downloaded {job.file}")
        self._finish(job)
        kiwix.restart()

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
# HTTP API
# --------------------------------------------------------------------------
def library_state():
    files = []
    for path in kiwix.zim_files():
        info = path.stat()
        files.append({"file": path.name, "size": info.st_size, "mtime": int(info.st_mtime)})
    return {
        "running": kiwix.running,
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

    # -- routes ----------------------------------------------------------
    def do_GET(self):  # noqa: N802 - http.server naming
        if not self._guard():
            return
        parsed = urllib.parse.urlparse(self.path)
        route = "/" + parsed.path.strip("/")
        if route == "/api/state":
            self._json(200, library_state())
        elif route == "/api/catalog":
            self._catalog(urllib.parse.parse_qs(parsed.query))
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
        kiwix.restart()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def watchdog(interval=15):
    while True:
        time.sleep(interval)
        kiwix.ensure_running()


def main():
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", MANAGER_PORT), Handler)

    def shutdown(*_):
        log("Shutting down")
        kiwix.stop()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    kiwix.restart()
    threading.Thread(target=watchdog, daemon=True).start()

    log(f"Manager listening on port {MANAGER_PORT}, library in {LIBRARY_DIR}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
