#!/usr/bin/env python3
"""connector-mac: Jarvis Connector V1 (docs/CONNECTOR_PROTOCOL_V1.md).

Loopback by default; --lan binds all interfaces (token still required).
Grants are ro subtrees; deny-list enforced at grant time AND read time;
reads are range-capped; every request carries an audit id logged to
~/Library/Logs/uyp/connector.log.

P8: a background watcher turns grant-tree changes into an append-only event
log (events_log.jsonl); GET /events?since=<id> is a pure read of that log.
"""
from __future__ import annotations
import base64, hashlib, json, os, re, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"
STATE_PATH = os.path.expanduser("~/.config/uyp/connector.json")
SNAPSHOT_PATH = os.path.expanduser("~/.config/uyp/manifest_snapshot.json")
EVENTS_PATH = os.path.expanduser("~/.config/uyp/events_log.jsonl")
LOG_PATH = os.path.expanduser("~/Library/Logs/uyp/connector.log")
PAGE_CAP = 2000
READ_CAP = 1024 * 1024
FILE_CAP = 16 * 1024 * 1024
EVENTS_PAGE_CAP = 500
POLL_INTERVAL = float(os.environ.get("UYP_WATCHER_POLL_SECONDS", "30"))

DENY = [re.compile(p, re.I) for p in (
    r"(^|/)\.ssh(/|$)", r"(^|/)\.config(/|$)", r"keychain", r"\.pem$", r"\.p12$",
    r"\.env", r"credential", r"id_rsa", r"id_ed25519", r"\.kwallet", r"secret",
)]
EXCLUDE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".Trash", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vscode"}

def _log(audit, **kw):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": time.strftime("%FT%T"), "audit": audit, **kw},
                            ensure_ascii=False) + "\n")

def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return {"device_token": None, "pairing": None, "grants": []}

def save_state(st):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)
    os.chmod(STATE_PATH, 0o600)

def denied(relpath: str) -> bool:
    return any(r.search(relpath) for r in DENY)

def scan_grant(root: str) -> dict:
    """relpath -> {size, mtime, kind}. Exclusions + deny-list applied."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        filenames = [f for f in filenames if f != ".DS_Store"]
        for f in filenames:
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root)
            if denied(rel):
                continue
            try:
                st = os.stat(full, follow_symlinks=False)
            except OSError:
                continue
            if os.path.islink(full):
                continue
            if st.st_size > 64 * 1024 * 1024:
                out[rel] = {"size": st.st_size, "mtime": int(st.st_mtime), "kind": "blob"}
            else:
                out[rel] = {"size": st.st_size, "mtime": int(st.st_mtime), "kind": "file"}
    return out

def find_grant(st, gid):
    return next((g for g in st["grants"] if g["id"] == gid), None)


# ---------------------------------------------------------------------------
# P8 change watcher: manifest-diff (always) + FSEvents (when watchdog is
# importable) -> append-only event log under ~/.config/uyp/events_log.jsonl.
#
# One dedupe authority: the per-grant snapshot (the same manifest_snapshot.json
# the previous /events handler wrote, same shape, so old snapshots load as-is).
# FSEvents callbacks and the periodic manifest-diff pass both funnel through
# Watcher.record_change, so a change seen by both is logged exactly once. The
# log is append-only jsonl and survives restarts; the id counter is recovered
# from the log tail so ids never repeat. GET /events never scans: it reads the
# log. watcher_ok reports the active mode honestly (fsevents|poll|off).
# ---------------------------------------------------------------------------

try:  # stdlib-first: FSEvents via watchdog when present, poll otherwise
    from watchdog.events import FileSystemEventHandler as _WatchdogHandler
    from watchdog.observers import Observer as _WatchdogObserver
except Exception:  # ImportError on a stock mac; poll is the honest fallback
    _WatchdogHandler = None
    _WatchdogObserver = None
WATCHDOG_AVAILABLE = _WatchdogObserver is not None


def detect_watcher_mode() -> str:
    """The watcher mode this process will run: fsevents | poll | off."""
    requested = os.environ.get("UYP_WATCHER", "").strip().lower()
    if requested == "off":
        return "off"
    if requested == "poll":
        return "poll"
    if requested == "fsevents" and not WATCHDOG_AVAILABLE:
        return "poll"  # forced but unavailable: poll, never a fake fsevents
    return "fsevents" if WATCHDOG_AVAILABLE else "poll"


def parse_event_id(value) -> int:
    """'e_42' or '42' -> 42. Raises ValueError on anything else."""
    raw = str(value if value is not None else "").strip()
    if raw.startswith("e_"):
        raw = raw[2:]
    if not raw.isdigit():
        raise ValueError(f"bad event id: {value!r}")
    return int(raw)


def read_event_log(path=None) -> list:
    """Read the append-only event log; torn/corrupt lines are skipped."""
    path = path or EVENTS_PATH
    events = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue  # torn tail from a crash mid-append
                if isinstance(item, dict) and item.get("id"):
                    events.append(item)
    except FileNotFoundError:
        return []
    return events


def read_last_event_id(path=None) -> str | None:
    """Tail-read the log for the newest event id (cheap enough for /status)."""
    path = path or EVENTS_PATH
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            end = fh.tell()
            data = b""
            while end > 0 and data.count(b"\n") < 2:
                step = min(4096, end)
                end -= step
                fh.seek(end)
                data = fh.read(step) + data
        lines = [ln for ln in data.decode("utf-8", "replace").splitlines() if ln.strip()]
        if not lines:
            return None
        return str(json.loads(lines[-1]).get("id"))
    except (OSError, json.JSONDecodeError, ValueError, AttributeError):
        return None


class _GrantDispatchPlain:
    """Duck-typed watchdog handler for environments without watchdog."""

    def __init__(self, watcher: "Watcher", grant_id: str):
        self.watcher = watcher
        self.grant_id = grant_id

    def dispatch(self, event):
        try:
            self.watcher.on_fs_event(self.grant_id, event)
        except Exception:
            pass  # the observer thread must survive; the poll pass backstops


if _WatchdogHandler is not None:
    class _GrantDispatch(_WatchdogHandler):
        def __init__(self, watcher: "Watcher", grant_id: str):
            super().__init__()
            self.watcher = watcher
            self.grant_id = grant_id

        def on_any_event(self, event):
            try:
                self.watcher.on_fs_event(self.grant_id, event)
            except Exception:
                pass  # see _GrantDispatchPlain
else:
    _GrantDispatch = _GrantDispatchPlain


class Watcher:
    """Snapshot-diff change detection feeding the append-only event log."""

    def __init__(self, *, state_path=None, snapshot_path=None, events_path=None,
                 interval=None, mode=None, observer_factory=None):
        self.state_path = state_path or STATE_PATH
        self.snapshot_path = snapshot_path or SNAPSHOT_PATH
        self.events_path = events_path or EVENTS_PATH
        self.interval = POLL_INTERVAL if interval is None else max(float(interval), 0.05)
        self.mode = detect_watcher_mode() if mode is None else str(mode)
        self.observer_factory = observer_factory
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.observer = None
        self.watches = {}
        self.snapshots = None      # lazy: {gid: {rel: {size, mtime, kind}}}
        self.dirty = False
        self.seq = 0
        self._recover_seq()

    # ---- event log ----
    def _recover_seq(self):
        for event in read_event_log(self.events_path):
            try:
                self.seq = max(self.seq, parse_event_id(event.get("id")))
            except ValueError:
                continue

    def _append_event(self, grant_id, relpath, kind) -> dict:
        self.seq += 1
        event = {"id": f"e_{self.seq}", "ts": int(time.time()),
                 "grant": grant_id, "relpath": relpath, "kind": kind}
        os.makedirs(os.path.dirname(self.events_path) or ".", exist_ok=True)
        with open(self.events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            fh.flush()
        return event

    # ---- snapshots (dedupe authority) ----
    def _load_snapshots(self) -> dict:
        if self.snapshots is None:
            try:
                with open(self.snapshot_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self.snapshots = data if isinstance(data, dict) else {}
            except (OSError, json.JSONDecodeError):
                self.snapshots = {}
        return self.snapshots

    def _persist_snapshots(self):
        if self.snapshots is None:
            return
        os.makedirs(os.path.dirname(self.snapshot_path) or ".", exist_ok=True)
        tmp = self.snapshot_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.snapshots, fh, ensure_ascii=False)
        os.replace(tmp, self.snapshot_path)
        os.chmod(self.snapshot_path, 0o600)
        self.dirty = False

    def _snapshots_are_loadable(self) -> bool:
        try:
            with open(self.snapshot_path, encoding="utf-8") as fh:
                return isinstance(json.load(fh), dict)
        except (OSError, json.JSONDecodeError):
            return False

    def _grant_roots(self) -> dict:
        try:
            st = load_state()
        except (OSError, json.JSONDecodeError):
            return {}
        return {g["id"]: g["path"] for g in st.get("grants", [])
                if g.get("id") and g.get("path")}

    # ---- change recording (FSEvents + poll both end here) ----
    def record_change(self, grant_id: str, relpath: str, kind_hint: str) -> dict | None:
        """Append one event iff the snapshot confirms a real change.

        ``kind_hint`` is only a hint: for created/modified the snapshot decides
        the honest kind (tracked + different stat -> modified, untracked ->
        created, same stat -> duplicate, skip). A deleted hint for a path we
        never tracked is editor/temp noise and is ignored.
        """
        with self.lock:
            root = self._grant_roots().get(grant_id)
            if root is None:
                return None  # grant vanished: no event for it
            snap = self._load_snapshots().setdefault(grant_id, {})
            if kind_hint == "deleted":
                if relpath not in snap:
                    return None
                del snap[relpath]
                self.dirty = True
                return self._append_event(grant_id, relpath, "deleted")
            full = os.path.join(root, relpath)
            try:
                st = os.stat(full, follow_symlinks=False)
            except OSError:
                if relpath in snap:  # created/modified hint but file is gone
                    del snap[relpath]
                    self.dirty = True
                    return self._append_event(grant_id, relpath, "deleted")
                return None
            if os.path.islink(full):
                return None
            current = {"size": st.st_size, "mtime": int(st.st_mtime),
                       "kind": "blob" if st.st_size > 64 * 1024 * 1024 else "file"}
            old = snap.get(relpath)
            if old == current:
                return None  # duplicate notification: already recorded
            kind = "modified" if old is not None else "created"
            snap[relpath] = current
            self.dirty = True
            return self._append_event(grant_id, relpath, kind)

    def poll_once(self) -> int:
        """Manifest-diff pass over every grant; returns how many events logged.

        In fsevents mode this is the safety net the protocol requires (network
        watchers are not trusted); in poll mode it is the only source. It also
        resyncs the observer's watches with the current grant set.
        """
        logged = 0
        with self.lock:
            roots = self._grant_roots()
            snaps = self._load_snapshots()
            for gid, root in roots.items():
                snap = snaps.setdefault(gid, {})
                current = scan_grant(root)
                for rel, meta in current.items():
                    if snap.get(rel) != meta:
                        kind = "modified" if rel in snap else "created"
                        self._append_event(gid, rel, kind)
                        snap[rel] = meta
                        logged += 1
                for rel in [r for r in snap if r not in current]:
                    del snap[rel]
                    self._append_event(gid, rel, "deleted")
                    logged += 1
            self.dirty = True
            self._persist_snapshots()
            self._sync_observer(roots)
        return logged

    def baseline_if_needed(self) -> bool:
        """First start (or lost snapshot): record current state WITHOUT events.

        Flood-logging every file as 'created' would force a full re-index for
        what is really 'no baseline yet'; the indexer's own manifest fetch,
        done_before skipping, and source epoch already cover first-scan
        correctness. A corrupt snapshot file counts as lost (rebaseline, no
        flood of invented events).
        """
        with self.lock:
            if self._snapshots_are_loadable():
                return False
            snaps = {}
            for gid, root in self._grant_roots().items():
                snaps[gid] = scan_grant(root)
            self.snapshots = snaps
            self._persist_snapshots()
            return True

    # ---- FSEvents plumbing ----
    def _sync_observer(self, roots):
        if self.mode != "fsevents" or self.observer is None:
            return
        for gid in list(self.watches):
            if gid not in roots:
                try:
                    self.observer.unschedule(self.watches[gid])
                except Exception:
                    pass
                del self.watches[gid]
        for gid, root in roots.items():
            if gid in self.watches or not os.path.isdir(root):
                continue
            self.watches[gid] = self.observer.schedule(
                _GrantDispatch(self, gid), root, recursive=True)

    def on_fs_event(self, grant_id: str, event) -> None:
        """Map one watchdog event to record_change calls (moved -> del+new)."""
        if getattr(event, "is_directory", False):
            return
        root = self._grant_roots().get(grant_id)
        if root is None:
            return
        etype = str(getattr(event, "event_type", ""))
        src = getattr(event, "src_path", "")
        if etype == "moved":
            # Renames are deliberately emitted as a deleted+created pair; the
            # protocol's `renamed` kind (carrying `from`) is not implemented.
            self._dispatch_path(grant_id, root, src, "deleted")
            dest = getattr(event, "dest_path", "")
            if dest:
                self._dispatch_path(grant_id, root, dest, "created")
            return
        if etype not in {"created", "modified", "deleted"}:
            return  # opened/closed etc. carry no change information
        self._dispatch_path(grant_id, root, src, etype)

    def _dispatch_path(self, grant_id, root, full, kind_hint):
        rel = os.path.relpath(full, root)
        if rel.startswith(".."):
            return
        if denied(rel):
            return
        # same exclusions as scan_grant: excluded dirs, .DS_Store
        parts = rel.split(os.sep)
        if any(p in EXCLUDE_DIRS for p in parts[:-1]):
            return
        if parts[-1] == ".DS_Store":
            return
        self.record_change(grant_id, rel, kind_hint)

    # ---- lifecycle ----
    def start(self):
        if self.mode == "off":
            return self
        self.baseline_if_needed()
        if self.mode == "fsevents":
            factory = self.observer_factory or (lambda: _WatchdogObserver())
            self.observer = factory()
            with self.lock:
                self._sync_observer(self._grant_roots())
            self.observer.start()
        self.thread = threading.Thread(target=self._loop, name="uyp-watcher", daemon=True)
        self.thread.start()
        return self

    def _loop(self):
        next_poll = time.monotonic() + self.interval
        while not self.stop_event.wait(0.5):
            with self.lock:
                if self.dirty:
                    self._persist_snapshots()  # batch FSEvents bursts
            if time.monotonic() >= next_poll:
                next_poll = time.monotonic() + self.interval
                try:
                    self.poll_once()
                except Exception:
                    pass  # retried next cycle; the log stays consistent
        with self.lock:
            if self.dirty:
                self._persist_snapshots()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
            self.thread = None
        if self.observer is not None:
            try:
                self.observer.stop()
                self.observer.join(timeout=5)
            except Exception:
                pass
            self.observer = None
            self.watches = {}


WATCHER: Watcher | None = None


def active_watcher_mode() -> str:
    """Honest answer for /status: the mode actually running, or 'off'."""
    watcher = WATCHER
    if watcher is None or watcher.mode == "off":
        return "off"
    if watcher.thread is None or not watcher.thread.is_alive():
        return "off"
    return watcher.mode

class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200, audit=None):
        audit = audit or str(uuid.uuid4())
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-UYP-Audit-Id", audit)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self) -> bool:
        st = load_state()
        tok = st.get("device_token")
        return bool(tok) and self.headers.get("Authorization", "") == f"Bearer {tok}"

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    # ---- routes ----
    def do_GET(self):
        audit = str(uuid.uuid4())
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/status":
            st = load_state()
            return self._json({"state": "online", "connector_version": VERSION,
                               "grants_active": len(st.get("grants", [])),
                               "watcher_ok": active_watcher_mode(),
                               "last_event_id": read_last_event_id()}, audit=audit)
        if not self._auth():
            return self._json({"ok": False, "error": "unauthorized"}, 401, audit)
        st = load_state()
        if u.path == "/grants":
            return self._json({"grants": st["grants"]}, audit=audit)
        if u.path == "/manifest":
            g = find_grant(st, (q.get("grant") or [""])[0])
            if not g:
                return self._json({"ok": False, "error": "no_such_grant"}, 404, audit)
            files = scan_grant(g["path"])
            items = sorted(files.items())
            cursor = (q.get("cursor") or ["0"])[0]
            try:
                start = int(base64.urlsafe_b64decode(cursor).decode()) if cursor not in ("0", "") else 0
            except Exception:
                start = 0
            page = items[start:start + PAGE_CAP]
            nxt = start + PAGE_CAP
            return self._json({
                "grant": g["id"], "root_name": os.path.basename(g["path"]),
                "files": [{"id": "f_" + hashlib.sha256(r.encode()).hexdigest()[:16],
                           "relpath": r, **meta} for r, meta in page],
                "next_cursor": base64.urlsafe_b64encode(str(nxt).encode()).decode() if nxt < len(items) else None,
                "has_more": nxt < len(items), "total": len(items)}, audit=audit)
        if u.path == "/read":
            g = find_grant(st, (q.get("grant") or [""])[0])
            rel = (q.get("relpath") or [""])[0]
            if not g or not rel:
                return self._json({"ok": False, "error": "bad_request"}, 400, audit)
            if denied(rel):
                _log(audit, op="read", denied=True, path=rel)
                return self._json({"ok": False, "error": "denied_pattern"}, 403, audit)
            full = os.path.realpath(os.path.join(g["path"], rel))
            root = os.path.realpath(g["path"])
            if not full.startswith(root + os.sep) or not os.path.isfile(full):
                return self._json({"ok": False, "error": "not_found"}, 404, audit)
            try:
                off = int((q.get("offset") or ["0"])[0])
                ln = min(int((q.get("length") or [READ_CAP])[0]), READ_CAP)
            except ValueError:
                return self._json({"ok": False, "error": "bad_range"}, 400, audit)
            # Cap is on the readable WINDOW, not the file: a 1KB triage
            # peek into a 100MB log is harmless; slurping past 16MB is not.
            if off + ln > FILE_CAP:
                return self._json({"ok": False, "error": "range_beyond_cap"}, 413, audit)
            with open(full, "rb") as fh:
                fh.seek(off)
                data = fh.read(ln)
            _log(audit, op="read", path=rel, offset=off, length=len(data))
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("X-UYP-Audit-Id", audit)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return None
        if u.path == "/events":
            # P8: pure read of the append-only log the watcher maintains.
            # No scan, no snapshot mutation: change detection belongs to the
            # watcher thread, serving belongs here.
            grant_param = (q.get("grant") or [""])[0]
            if grant_param:
                if not find_grant(st, grant_param):
                    return self._json({"ok": False, "error": "no_such_grant"}, 404, audit)
            try:
                since = parse_event_id((q.get("since") or ["0"])[0])
            except ValueError:
                return self._json({"ok": False, "error": "bad_since"}, 400, audit)
            matched = []
            for event in read_event_log():
                try:
                    eid = parse_event_id(event.get("id"))
                except ValueError:
                    continue
                if eid <= since:
                    continue
                if grant_param and event.get("grant") != grant_param:
                    continue
                matched.append(event)
            page = matched[:EVENTS_PAGE_CAP]
            out = {"events": page, "truncated": len(matched) > len(page),
                   "last_event_id": page[-1]["id"] if page else read_last_event_id()}
            if grant_param:
                out["grant"] = grant_param
            return self._json(out, audit=audit)
        return self._json({"ok": False, "error": "not_found"}, 404, audit)

    def do_POST(self):
        audit = str(uuid.uuid4())
        from urllib.parse import urlparse
        u = urlparse(self.path)
        st = load_state()
        if u.path == "/pair":
            body = self._body()
            p = st.get("pairing") or {}
            if not p.get("code") or time.time() > p.get("expires", 0) or body.get("pairing_code") != p["code"]:
                return self._json({"ok": False, "error": "bad_or_expired_code"}, 403, audit)
            tok = "uyp_t_" + base64.urlsafe_b64encode(os.urandom(24)).decode().rstrip("=")
            st["device_token"] = tok
            st["pairing"] = None
            st["paired"] = [{"jetson_id": body.get("jetson_id"),
                             "jetson_pubkey_fp": body.get("jetson_pubkey_fp"),
                             "at": time.strftime("%FT%T")}]
            save_state(st)
            _log(audit, op="pair", jetson=body.get("jetson_id"))
            return self._json({"ok": True, "device_token": tok,
                               "connector_version": VERSION,
                               "hostname": os.uname().nodename,
                               "os": f"macos {sys.platform}"}, audit=audit)
        if not self._auth():
            return self._json({"ok": False, "error": "unauthorized"}, 401, audit)
        if u.path == "/grants":
            body = self._body()
            path = os.path.realpath(os.path.expanduser(body.get("path", "")))
            home = os.path.realpath(os.path.expanduser("~"))
            if not path.startswith(home + os.sep) or not os.path.isdir(path):
                return self._json({"ok": False, "error": "path_not_grantable"}, 400, audit)
            if denied(os.path.relpath(path, home)):
                return self._json({"ok": False, "error": "denied_pattern"}, 403, audit)
            gid = "g_" + uuid.uuid4().hex[:8]
            st["grants"].append({"id": gid, "path": path, "mode": "ro",
                                 "granted_at": time.strftime("%FT%T")})
            save_state(st)
            _log(audit, op="grant", gid=gid, path=path)
            return self._json({"ok": True, "id": gid, "path": path}, audit=audit)
        return self._json({"ok": False, "error": "not_found"}, 404, audit)

    def do_DELETE(self):
        audit = str(uuid.uuid4())
        from urllib.parse import urlparse
        gid = urlparse(self.path).path.rsplit("/", 1)[-1]
        if not self._auth():
            return self._json({"ok": False, "error": "unauthorized"}, 401, audit)
        st = load_state()
        before = len(st["grants"])
        st["grants"] = [g for g in st["grants"] if g["id"] != gid]
        save_state(st)
        _log(audit, op="revoke", gid=gid, revoked=before != len(st["grants"]))
        return self._json({"ok": True, "revoked": before != len(st["grants"])}, audit=audit)

    def log_message(self, *a):
        pass

def new_pairing_code() -> str:
    import random
    st = load_state()
    code = str(random.randint(100000, 999999))
    st["pairing"] = {"code": code, "expires": time.time() + 600}
    save_state(st)
    print(code)
    return code

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "pair-code":
        new_pairing_code()
        sys.exit(0)
    host = "0.0.0.0" if "--lan" in sys.argv else "127.0.0.1"
    mode = detect_watcher_mode()
    if mode != "off":
        WATCHER = Watcher(mode=mode)
        WATCHER.start()
        print(f"watcher: {WATCHER.mode} (poll every {WATCHER.interval:.0f}s, log: {EVENTS_PATH})", flush=True)
    else:
        print("watcher: off (UYP_WATCHER=off)", flush=True)
    print(f"connector-mac v{VERSION} on {host}:7121 (state: {STATE_PATH})", flush=True)
    ThreadingHTTPServer((host, 7121), Handler).serve_forever()
