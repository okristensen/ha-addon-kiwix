#!/usr/bin/env python3
"""Outbound-only bridge between Home Assistant and a Supabase database.

The bridge holds outbound connections only; nothing needs to reach Home
Assistant from outside. It does three things:

* publishes the state of the entities you list to a table, so an app that
  cannot reach Home Assistant can still show them,
* writes a heartbeat row, so that app can tell when the house is offline,
* optionally copies the picture of ``image`` entities (e.g. a vacuum map) to a
  table, because a picture cannot travel as entity state,
* runs commands that users put in a queue table -- but only commands on its
  own allow-list (the ``commands`` option), with typed, range-checked
  arguments. Whatever the database says, nothing else is ever executed.

It signs in to Supabase as an ordinary user (email + password) and relies on
row level security; it never needs the service-role key.
"""

import asyncio
import base64
import fnmatch
import json
import logging
import os
import re
import secrets
import signal
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import aiohttp

VERSION = "0.2.1"
OPTIONS_FILE = os.environ.get("BRIDGE_OPTIONS", "/data/options.json")
HA_WS = os.environ.get("BRIDGE_HA_WS", "ws://supervisor/core/websocket")
HA_HTTP = os.environ.get("BRIDGE_HA_HTTP", "http://supervisor/core/api")
HA_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

# Never published, whatever the entity: tokens and signed URLs live here.
BLOCKED_ATTRIBUTES = {"access_token", "entity_picture", "entity_picture_local", "token", "stream_source"}
MAX_STATE_BYTES = 15000
HEARTBEAT_SECONDS = 20
POLL_SECONDS_NO_REALTIME = 3
POLL_SECONDS_REALTIME = 15
MIN_SECONDS_BETWEEN_WRITES = 2  # per entity, unless the pattern sets its own "seconds"
MAX_IMAGE_BYTES = 400_000
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
ALARM_SECONDS = 30 * 60  # at most one alarm of each kind per 30 minutes
ALARM_PHONE_SERVICE = "notify/mobile_app_oles_iphone"
CANARY_COMMAND = "vagt_kanarie"  # never on the allow-list; if it shows up in the queue, someone is probing

log = logging.getLogger("bridge")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class ConfigError(Exception):
    pass


class AlarmThrottle:
    """Lets an alarm through at most once per ``seconds`` for each kind."""

    def __init__(self, seconds=ALARM_SECONDS, clock=time.monotonic):
        self.seconds = seconds
        self.clock = clock
        self.last = {}

    def allow(self, kind):
        now = self.clock()
        last = self.last.get(kind)
        if last is not None and now - last < self.seconds:
            return False
        self.last[kind] = now
        return True


def is_unlisted_command(commands, row):
    """True for the canary command and for any command not on the bridge's own allow-list."""
    name = str(row.get("kommando") or "")
    return name == CANARY_COMMAND or (str(row.get("app") or ""), name) not in commands


def clean_text(value, limit=60):
    """Text from the database, made harmless for a notification (data, never instructions)."""
    return re.sub(r"[^\w .:/-]", "?", str(value or ""))[:limit]


# ---------------------------------------------------------------- options


def load_options():
    with open(OPTIONS_FILE, encoding="utf-8") as fh:
        raw = json.load(fh)
    url = str(raw.get("supabase_url") or "").rstrip("/")
    if not url.startswith("https://") and not os.environ.get("BRIDGE_ALLOW_HTTP"):
        raise ConfigError("supabase_url must start with https://")
    for key in ("supabase_anon_key", "email", "password"):
        if not raw.get(key):
            raise ConfigError(f"option '{key}' is empty")

    entities = []
    for item in raw.get("entities") or []:
        pattern = str(item.get("pattern") or "").strip()
        apps = [str(a) for a in (item.get("apps") or []) if a]
        if not pattern or "." not in pattern or pattern.startswith("*"):
            raise ConfigError(f"entity pattern '{pattern}' must name a domain, e.g. sensor.vacuum_*")
        if not apps:
            raise ConfigError(f"entity pattern '{pattern}' has no apps")
        entities.append((pattern, apps, max(1, int(item.get("seconds") or MIN_SECONDS_BETWEEN_WRITES))))

    images = []
    for item in raw.get("images") or []:
        entity_id = str(item.get("entity_id") or "").strip()
        apps = [str(a) for a in (item.get("apps") or []) if a]
        if not entity_id.startswith("image.") or "*" in entity_id or not apps:
            raise ConfigError(f"image '{entity_id}' needs an image.* entity_id (no wildcards) and apps")
        images.append({"entity_id": entity_id, "apps": apps, "seconds": max(10, int(item.get("seconds") or 60))})

    commands = {}
    for item in raw.get("commands") or []:
        app, name = str(item.get("app") or ""), str(item.get("command") or "")
        service, entity_id = str(item.get("service") or ""), str(item.get("entity_id") or "")
        if not app or not name or service.count(".") != 1 or entity_id.count(".") != 1:
            raise ConfigError(f"command '{app}/{name}' needs app, command, service (domain.service) and entity_id")
        try:
            data = json.loads(item["data"]) if item.get("data") else {}
            args = json.loads(item["args"]) if item.get("args") else {}
        except ValueError as err:
            raise ConfigError(f"command '{app}/{name}': data/args is not valid JSON ({err})") from None
        if not isinstance(data, dict) or not isinstance(args, dict):
            raise ConfigError(f"command '{app}/{name}': data and args must be JSON objects")
        for arg, spec in args.items():
            if not isinstance(spec, dict) or spec.get("type") not in ("int", "int_list"):
                raise ConfigError(f"command '{app}/{name}': argument '{arg}' needs type int or int_list")
        commands[(app, name)] = {"service": service, "entity_id": entity_id, "data": data, "args": args}

    responses = []
    for item in raw.get("responses") or []:
        rid, service, entity_id = str(item.get("id") or ""), str(item.get("service") or ""), str(item.get("entity_id") or "")
        apps = [str(a) for a in (item.get("apps") or []) if a]
        if "." not in rid or service.count(".") != 1 or entity_id.count(".") != 1 or not apps:
            raise ConfigError(f"response '{rid}' needs id (like bridge.rooms), apps, service and entity_id")
        responses.append({"id": rid, "apps": apps, "service": service, "entity_id": entity_id,
                          "interval": int(item.get("interval_minutes") or 60) * 60})

    return {
        "url": url,
        "anon_key": str(raw["supabase_anon_key"]),
        "email": str(raw["email"]),
        "password": str(raw["password"]),
        "entities": entities,
        "commands": commands,
        "responses": responses,
        "images": images,
        "images_table": str(raw.get("images_table") or "bro_billeder"),
        "max_per_minute": int(raw.get("max_commands_per_minute") or 30),
        "states_table": str(raw.get("states_table") or "bro_tilstande"),
        "commands_table": str(raw.get("commands_table") or "bro_kommandoer"),
        "heartbeat_table": str(raw.get("heartbeat_table") or "bro_puls"),
        "log_level": str(raw.get("log_level") or "info").upper(),
    }


# ---------------------------------------------------------------- arguments


class Rejected(Exception):
    """A command that will not be run; the message goes back to the user."""


def check_int(name, value, spec):
    if isinstance(value, bool) or not isinstance(value, int):
        raise Rejected(f"argument '{name}' must be a whole number")
    low, high = int(spec.get("min", 0)), int(spec.get("max", 1_000_000))
    if not low <= value <= high:
        raise Rejected(f"argument '{name}' must be between {low} and {high}")
    return value


def build_arguments(command, given):
    """Validate ``given`` against the command's typed argument spec."""
    spec = command["args"]
    if not isinstance(given, dict):
        raise Rejected("arguments must be an object")
    unknown = set(given) - set(spec)
    if unknown:
        raise Rejected(f"unknown argument: {sorted(unknown)[0]}")
    values = {}
    for name, rule in spec.items():
        if name not in given:
            if "default" in rule:
                values[name] = rule["default"]
                continue
            raise Rejected(f"argument '{name}' is missing")
        value = given[name]
        if rule["type"] == "int":
            values[name] = check_int(name, value, rule)
        else:
            if not isinstance(value, list) or not 1 <= len(value) <= int(rule.get("max_items", 30)):
                raise Rejected(f"argument '{name}' must be a list of 1-{int(rule.get('max_items', 30))} numbers")
            values[name] = [check_int(name, v, rule) for v in value]
    return values


def fill(template, values):
    """Replace "$name" strings in the data template with validated values."""
    if isinstance(template, str) and template.startswith("$") and template[1:] in values:
        return values[template[1:]]
    if isinstance(template, list):
        return [fill(item, values) for item in template]
    if isinstance(template, dict):
        return {key: fill(item, values) for key, item in template.items()}
    return template


# ---------------------------------------------------------------- Supabase


class Supabase:
    def __init__(self, session, options):
        self.session = session
        self.url = options["url"]
        self.anon_key = options["anon_key"]
        self.email = options["email"]
        self.password = options["password"]
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0
        self.token_listeners = []
        self._lock = asyncio.Lock()

    async def _token_request(self, grant, body):
        async with self.session.post(
            f"{self.url}/auth/v1/token?grant_type={grant}",
            json=body, headers={"apikey": self.anon_key}, timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200 or not isinstance(data, dict) or not data.get("access_token"):
                message = data.get("error_description") or data.get("msg") or data.get("message") if isinstance(data, dict) else None
                raise RuntimeError(f"sign-in failed ({resp.status}): {message or 'no token returned'}")
        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token")
        self.expires_at = time.time() + int(data.get("expires_in") or 3600)
        for listener in self.token_listeners:
            listener(self.access_token)

    async def token(self):
        async with self._lock:
            if self.access_token and time.time() < self.expires_at - 120:
                return self.access_token
            if self.refresh_token:
                try:
                    await self._token_request("refresh_token", {"refresh_token": self.refresh_token})
                    return self.access_token
                except Exception as err:  # fall back to a fresh sign-in
                    log.warning("token refresh failed, signing in again: %s", err)
            await self._token_request("password", {"email": self.email, "password": self.password})
            log.info("signed in to Supabase")
            return self.access_token

    async def rest(self, method, table, params=None, body=None, prefer=None):
        headers = {"apikey": self.anon_key, "Authorization": f"Bearer {await self.token()}"}
        if prefer:
            headers["Prefer"] = prefer
        async with self.session.request(
            method, f"{self.url}/rest/v1/{quote(table)}", params=params, json=body, headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            text = await resp.text()
            if resp.status == 401:
                self.expires_at = 0  # force a new token next time
            if resp.status >= 300:
                raise RuntimeError(f"{method} {table} failed ({resp.status}): {text[:200]}")
            return json.loads(text) if text else None


# ---------------------------------------------------------------- Home Assistant


class HomeAssistant:
    def __init__(self, session, on_state):
        self.session = session
        self.on_state = on_state
        self.ws = None
        self.next_id = 1
        self.pending = {}
        self.connected = asyncio.Event()

    async def run(self):
        delay = 2
        while True:
            try:
                await self._connect()
                delay = 2
            except asyncio.CancelledError:
                raise
            except Exception as err:
                log.warning("Home Assistant connection lost: %s", err)
            self.connected.clear()
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("Home Assistant connection lost"))
            self.pending.clear()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def _connect(self):
        async with self.session.ws_connect(HA_WS, heartbeat=30, max_msg_size=0) as ws:
            self.ws = ws
            first = await ws.receive_json()
            if first.get("type") == "auth_required":
                await ws.send_json({"type": "auth", "access_token": HA_TOKEN})
                reply = await ws.receive_json()
                if reply.get("type") != "auth_ok":
                    raise RuntimeError("Home Assistant refused the token")
            log.info("connected to Home Assistant")
            reader = asyncio.create_task(self._read(ws))
            try:
                states = await self.request({"type": "get_states"}, wait_connected=False)
                await self.request({"type": "subscribe_events", "event_type": "state_changed"}, wait_connected=False)
                self.connected.set()
                for state in states or []:
                    self.on_state(state.get("entity_id"), state, initial=True)
                self.on_state(None, None, initial=True)  # marks the end of the first batch
                await reader
            finally:
                reader.cancel()

    async def _read(self, ws):
        async for message in ws:
            if message.type != aiohttp.WSMsgType.TEXT:
                continue
            data = json.loads(message.data)
            if data.get("type") == "event":
                event = data.get("event") or {}
                if event.get("event_type") == "state_changed":
                    payload = event.get("data") or {}
                    self.on_state(payload.get("entity_id"), payload.get("new_state"), initial=False)
            elif data.get("type") == "result":
                future = self.pending.pop(data.get("id"), None)
                if future and not future.done():
                    if data.get("success"):
                        future.set_result(data.get("result"))
                    else:
                        future.set_exception(RuntimeError((data.get("error") or {}).get("message") or "request failed"))
        raise RuntimeError("websocket closed")

    async def request(self, message, wait_connected=True, timeout=30):
        if wait_connected:
            await asyncio.wait_for(self.connected.wait(), timeout)
        message = dict(message, id=self.next_id)
        self.next_id += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[message["id"]] = future
        await self.ws.send_json(message)
        return await asyncio.wait_for(future, timeout)

    async def image(self, entity_id):
        """The current picture of an image entity: (content type, bytes)."""
        async with self.session.get(
            f"{HA_HTTP}/image_proxy/{quote(entity_id)}", headers={"Authorization": f"Bearer {HA_TOKEN}"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"image_proxy answered {resp.status}")
            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            body = await resp.content.read(MAX_IMAGE_BYTES + 1)
            return content_type, body

    async def rest_service(self, path, data):
        """Plain REST service call (/api/services/...), used for the alarms only."""
        async with self.session.post(
            f"{HA_HTTP}/services/{path}", json=data, headers={"Authorization": f"Bearer {HA_TOKEN}"},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"{path} answered {resp.status}")

    async def call_service(self, service, entity_id, data, return_response=False):
        domain, name = service.split(".")
        message = {"type": "call_service", "domain": domain, "service": name,
                   "service_data": data or {}, "target": {"entity_id": entity_id}}
        if return_response:
            message["return_response"] = True
        return await self.request(message)


# ---------------------------------------------------------------- the bridge


class Bridge:
    def __init__(self, options, session):
        self.options = options
        self.supabase = Supabase(session, options)
        self.ha = HomeAssistant(session, self.on_state)
        self.session = session
        self.dirty = {}          # entity_id -> row waiting to be written
        self.last_write = {}     # entity_id -> monotonic time of last write
        self.image_state = {}    # image entity_id -> state (a timestamp) last seen
        self.image_sent = {}     # image entity_id -> state last uploaded
        self.published = set()   # entity ids seen in the first batch
        self.first_batch_done = asyncio.Event()
        self.handled = set()     # command ids already run (never run twice)
        self.recent_commands = []
        self.poll_now = asyncio.Event()
        self.realtime_joined = False
        self.run_id = secrets.token_hex(8)  # tells this run's heartbeat from anyone else's
        self.run_id_column = True           # False when bro_puls has no "koersel" column
        self.wrote_run_id = False
        self.alarms = AlarmThrottle()

    # -- alarms

    async def alarm(self, kind, title, message, notification_id):
        """A persistent notification plus a phone push, at most once per 30 minutes per kind."""
        if not self.alarms.allow(kind):
            log.debug("alarm %s held back (sent less than 30 minutes ago)", kind)
            return
        log.warning("ALARM: %s - %s", title, message)
        for path, data in (
            ("persistent_notification/create", {"title": title, "message": message, "notification_id": notification_id}),
            (ALARM_PHONE_SERVICE, {"title": title, "message": message}),
        ):
            try:
                await self.ha.rest_service(path, data)
            except Exception as err:
                log.warning("could not send the alarm through %s: %s", path, err)

    # -- states

    def apps_for(self, entity_id):
        apps = []
        for pattern, pattern_apps, _seconds in self.options["entities"]:
            if fnmatch.fnmatchcase(entity_id, pattern):
                apps.extend(a for a in pattern_apps if a not in apps)
        for image in self.options["images"]:  # an image entity's own state is published too
            if image["entity_id"] == entity_id:
                apps.extend(a for a in image["apps"] if a not in apps)
        return apps

    def seconds_for(self, entity_id):
        """Shortest time between two writes of this entity (the largest value among matching patterns)."""
        values = [seconds for pattern, _apps, seconds in self.options["entities"] if fnmatch.fnmatchcase(entity_id, pattern)]
        return max(values) if values else MIN_SECONDS_BETWEEN_WRITES

    def on_state(self, entity_id, state, initial):
        if entity_id is None:
            self.first_batch_done.set()
            return
        apps = self.apps_for(entity_id)
        if not apps:
            return
        if initial:
            self.published.add(entity_id)
        if entity_id.startswith("image.") and state is not None:
            self.image_state[entity_id] = state.get("state")
        self.dirty[entity_id] = self.row(entity_id, apps, state)

    @staticmethod
    def row(entity_id, apps, state):
        if state is None:  # entity removed
            body = {"state": "unavailable", "attributes": {}}
        else:
            attributes = {k: v for k, v in (state.get("attributes") or {}).items() if k not in BLOCKED_ATTRIBUTES}
            body = {"state": state.get("state"), "attributes": attributes,
                    "last_changed": state.get("last_changed"), "last_updated": state.get("last_updated")}
            # Too big for the table: drop the largest attributes until it fits.
            while len(json.dumps(body)) > MAX_STATE_BYTES and body["attributes"]:
                biggest = max(body["attributes"], key=lambda k: len(json.dumps(body["attributes"][k])))
                del body["attributes"][biggest]
                body["truncated"] = True
        return {"entity_id": entity_id, "apps": apps, "tilstand": body, "opdateret": now_iso()}

    async def write_states(self):
        table = self.options["states_table"]
        while True:
            await asyncio.sleep(0.5)
            now = time.monotonic()
            ready = [eid for eid in self.dirty if now - self.last_write.get(eid, 0) >= self.seconds_for(eid)]
            if not ready:
                continue
            rows = [self.dirty.pop(eid) for eid in ready[:200]]
            try:
                await self.supabase.rest("POST", table, params={"on_conflict": "entity_id"}, body=rows,
                                         prefer="resolution=merge-duplicates,return=minimal")
                for row in rows:
                    self.last_write[row["entity_id"]] = now
                log.debug("wrote %d state(s)", len(rows))
            except Exception as err:
                log.warning("could not write states: %s", err)
                for row in rows:  # keep them for the next round unless something newer arrived
                    self.dirty.setdefault(row["entity_id"], row)
                await asyncio.sleep(5)

    async def remove_stale_states(self):
        """After the first full batch, delete rows for entities no longer published."""
        await self.first_batch_done.wait()
        table = self.options["states_table"]
        keep = set(self.published) | {r["id"] for r in self.options["responses"]}
        try:
            rows = await self.supabase.rest("GET", table, params={"select": "entity_id"}) or []
            stale = [r["entity_id"] for r in rows if r["entity_id"] not in keep]
            for entity_id in stale:
                await self.supabase.rest("DELETE", table, params={"entity_id": f"eq.{entity_id}"}, prefer="return=minimal")
            log.info("publishing %d entities%s", len(self.published), f", removed {len(stale)} stale" if stale else "")
        except Exception as err:
            log.warning("could not clean up old states: %s", err)

    async def publish_responses(self):
        """Service responses (e.g. a vacuum's room list) published as pseudo-entities."""
        if not self.options["responses"]:
            return
        next_run = {item["id"]: 0 for item in self.options["responses"]}
        while True:
            for item in self.options["responses"]:
                if time.monotonic() < next_run[item["id"]]:
                    continue
                try:
                    result = await self.ha.call_service(item["service"], item["entity_id"], {}, return_response=True)
                    response = (result or {}).get("response")
                    state = {"state": "ok", "attributes": {"response": response}, "last_updated": now_iso()}
                    next_run[item["id"]] = time.monotonic() + item["interval"]
                except Exception as err:
                    log.warning("response %s failed: %s", item["id"], err)
                    state = {"state": "unavailable", "attributes": {}, "last_updated": now_iso()}
                    next_run[item["id"]] = time.monotonic() + 300
                self.dirty[item["id"]] = self.row(item["id"], item["apps"], state)
            await asyncio.sleep(30)

    # -- images

    async def publish_images(self):
        """Copies the picture of each listed image entity whenever its state (a timestamp) has changed."""
        if not self.options["images"]:
            return
        table = self.options["images_table"]
        await self.first_batch_done.wait()
        next_run = {image["entity_id"]: 0 for image in self.options["images"]}
        while True:
            for image in self.options["images"]:
                entity_id = image["entity_id"]
                state = self.image_state.get(entity_id)
                if state in (None, "unknown", "unavailable") or state == self.image_sent.get(entity_id):
                    continue
                if time.monotonic() < next_run[entity_id]:
                    continue
                next_run[entity_id] = time.monotonic() + image["seconds"]
                try:
                    content_type, body = await self.ha.image(entity_id)
                    if content_type not in IMAGE_TYPES:
                        raise RuntimeError(f"unexpected content type {content_type or '(none)'}")
                    if len(body) > MAX_IMAGE_BYTES:
                        raise RuntimeError(f"picture is larger than {MAX_IMAGE_BYTES} bytes")
                    await self.supabase.rest("POST", table, params={"on_conflict": "id"}, body={
                        "id": entity_id, "apps": image["apps"], "type": content_type,
                        "data": base64.b64encode(body).decode("ascii"), "opdateret": now_iso()},
                        prefer="resolution=merge-duplicates,return=minimal")
                    self.image_sent[entity_id] = state
                    log.debug("wrote image %s (%d bytes)", entity_id, len(body))
                except Exception as err:
                    log.warning("image %s failed: %s", entity_id, err)
                    next_run[entity_id] = time.monotonic() + 300
            await asyncio.sleep(5)

    # -- heartbeat

    async def read_run_id(self, table):
        rows = await self.supabase.rest("GET", table, params={"select": "koersel", "id": "eq.1"}) or []
        return rows[0].get("koersel") if rows else None

    async def check_run_id(self, table):
        """Someone else writing as the bridge shows up as another run id in the row."""
        seen = await self.read_run_id(table)
        if seen is not None and seen != self.run_id:
            await self.alarm("fremmed", "Klar-bro: fremmed skriver",
                             "Klar-bro: en anden skriver som broen. Skift broens Supabase-kodeord og tjek bro_puls.",
                             "klar_bro_fremmed")

    async def heartbeat(self):
        table = self.options["heartbeat_table"]
        await self.ha.connected.wait()
        while True:
            if self.ha.connected.is_set():  # no pulse while the house itself is unreachable
                try:
                    body = {"id": 1, "sidst": now_iso(), "version": VERSION}
                    if self.run_id_column:
                        if self.wrote_run_id:
                            await self.check_run_id(table)  # anything written since our last pulse
                        body["koersel"] = self.run_id
                    try:
                        await self.supabase.rest("POST", table, params={"on_conflict": "id"}, body=body,
                                                 prefer="resolution=merge-duplicates,return=minimal")
                    except Exception as err:
                        if not self.run_id_column or "koersel" not in str(err):
                            raise
                        log.warning("the heartbeat table has no 'koersel' column; run id check is off (%s)", err)
                        self.run_id_column = False
                        del body["koersel"]
                        await self.supabase.rest("POST", table, params={"on_conflict": "id"}, body=body,
                                                 prefer="resolution=merge-duplicates,return=minimal")
                    if self.run_id_column:
                        self.wrote_run_id = True
                        await self.check_run_id(table)  # read back right after our own write
                except Exception as err:
                    log.warning("heartbeat failed: %s", err)
            await asyncio.sleep(HEARTBEAT_SECONDS)

    # -- commands

    async def commands(self):
        table = self.options["commands_table"]
        while True:
            try:
                rows = await self.supabase.rest("GET", table, params={
                    "select": "id,user_id,app,kommando,argumenter,udloeber", "status": "eq.ny",
                    "order": "oprettet.asc", "limit": "20"}) or []
                for row in rows:
                    await self.handle(table, row)
            except Exception as err:
                log.warning("could not read the command queue: %s", err)
                await asyncio.sleep(5)
            self.poll_now.clear()
            wait = POLL_SECONDS_REALTIME if self.realtime_joined else POLL_SECONDS_NO_REALTIME
            try:
                await asyncio.wait_for(self.poll_now.wait(), wait)
            except asyncio.TimeoutError:
                pass

    async def handle(self, table, row):
        command_id = row.get("id")
        if command_id in self.handled:
            return
        self.handled.add(command_id)
        if len(self.handled) > 5000:
            self.handled = set(list(self.handled)[-1000:])
        if is_unlisted_command(self.options["commands"], row):
            await self.alarm("kanarie", "Klar-bro: kanarie-kommando i køen",
                             f"Kommando '{clean_text(row.get('kommando'))}' (app '{clean_text(row.get('app'))}') "
                             f"fra bruger {clean_text(row.get('user_id'), 8)} står ikke på broens liste. Den er afvist og ikke kørt.",
                             "klar_bro_kanarie")
        status, answer = await self.decide(row)
        log.info("command %s/%s -> %s%s", row.get("app"), row.get("kommando"), status, f" ({answer})" if answer else "")
        try:
            await self.supabase.rest("PATCH", table, params={"id": f"eq.{command_id}", "status": "eq.ny"},
                                     body={"status": status, "svar": (answer or None) and answer[:250], "afgjort": now_iso()},
                                     prefer="return=minimal")
        except Exception as err:
            log.warning("could not record the outcome of %s: %s", command_id, err)

    async def decide(self, row):
        expires = parse_time(row.get("udloeber"))
        if expires is None or expires < datetime.now(timezone.utc):
            return "udloebet", "for gammel"
        command = self.options["commands"].get((row.get("app"), row.get("kommando")))
        if command is None or row.get("kommando") == CANARY_COMMAND:  # the canary is never run
            return "afvist", "ukendt kommando"
        now = time.monotonic()
        self.recent_commands = [t for t in self.recent_commands if now - t < 60]
        if len(self.recent_commands) >= self.options["max_per_minute"]:
            return "afvist", "for mange kommandoer"
        try:
            values = build_arguments(command, row.get("argumenter") or {})
        except Rejected as err:
            return "afvist", str(err)
        self.recent_commands.append(now)
        try:
            await self.ha.call_service(command["service"], command["entity_id"], fill(command["data"], values))
        except Exception as err:
            return "afvist", f"Home Assistant: {err}"
        return "udfoert", None

    # -- realtime (only a doorbell: any change on the queue triggers a poll)

    async def realtime(self):
        host = urlsplit(self.options["url"])
        scheme = "wss" if host.scheme == "https" else "ws"
        url = f"{scheme}://{host.netloc}/realtime/v1/websocket?apikey={quote(self.options['anon_key'])}&vsn=1.0.0"
        topic = "realtime:bridge-commands"
        delay = 5
        while True:
            try:
                token = await self.supabase.token()
                async with self.session.ws_connect(url, heartbeat=None) as ws:
                    await ws.send_json({"topic": topic, "event": "phx_join", "ref": "1", "payload": {
                        "config": {"broadcast": {"self": False}, "presence": {"key": ""},
                                   "postgres_changes": [{"event": "INSERT", "schema": "public",
                                                         "table": self.options["commands_table"]}]},
                        "access_token": token}})

                    def new_token(value, ws=ws):
                        asyncio.ensure_future(ws.send_json(
                            {"topic": topic, "event": "access_token", "ref": None, "payload": {"access_token": value}}))
                    self.supabase.token_listeners = [new_token]

                    async def beat(ws=ws):
                        ref = 2
                        while True:
                            await asyncio.sleep(25)
                            await self.supabase.token()  # keeps the token fresh for the channel too
                            await ws.send_json({"topic": "phoenix", "event": "heartbeat", "payload": {}, "ref": str(ref)})
                            ref += 1
                    beater = asyncio.create_task(beat())
                    try:
                        async for message in ws:
                            if message.type != aiohttp.WSMsgType.TEXT:
                                continue
                            data = json.loads(message.data)
                            event = data.get("event")
                            if event == "phx_reply" and data.get("topic") == topic:
                                ok = (data.get("payload") or {}).get("status") == "ok"
                                if ok and not self.realtime_joined:
                                    log.info("listening for commands (realtime)")
                                    delay = 5
                                self.realtime_joined = ok or self.realtime_joined
                            elif event in ("postgres_changes", "system"):
                                self.poll_now.set()
                            elif event in ("phx_error", "phx_close"):
                                raise RuntimeError(f"channel closed ({event})")
                    finally:
                        beater.cancel()
                raise RuntimeError("websocket closed")
            except asyncio.CancelledError:
                raise
            except Exception as err:
                if self.realtime_joined:
                    log.warning("realtime lost (%s); polling every %ds until it is back", err, POLL_SECONDS_NO_REALTIME)
                else:
                    log.debug("realtime not available: %s", err)
            self.realtime_joined = False
            self.supabase.token_listeners = []
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)

    async def run(self):
        await self.supabase.token()  # fail early and clearly on a wrong login
        tasks = [asyncio.create_task(coro) for coro in (
            self.ha.run(), self.write_states(), self.remove_stale_states(), self.publish_responses(), self.publish_images(),
            self.heartbeat(), self.commands(), self.realtime())]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()


async def main():
    try:
        options = load_options()
    except (ConfigError, OSError, ValueError) as err:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        log.error("Configuration: %s. Fill in the app's Configuration tab and start it again.", err)
        await asyncio.sleep(3600)  # do not restart-loop on a missing setting
        return 1
    logging.basicConfig(level=getattr(logging, options["log_level"], logging.INFO),
                        format="%(asctime)s %(levelname)s %(message)s")
    log.info("Supabase bridge %s: %d entity pattern(s), %d command(s) on the allow-list",
             VERSION, len(options["entities"]), len(options["commands"]))
    for (app, name), command in sorted(options["commands"].items()):
        log.info("  allowed: %s/%s -> %s on %s", app, name, command["service"], command["entity_id"])
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    async with aiohttp.ClientSession() as session:
        runner = asyncio.create_task(Bridge(options, session).run())
        stopper = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({runner, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if runner in done:
            try:
                runner.result()
            except Exception as err:
                log.error("stopped: %s", err)
                await asyncio.sleep(60)
                return 1
        runner.cancel()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
