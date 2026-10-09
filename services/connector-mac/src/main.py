#!/usr/bin/env python3
"""connector-mac: Jarvis Connector V1 (docs/CONNECTOR_PROTOCOL_V1.md).

Loopback by default; --lan binds all interfaces (token still required).
Grants are ro subtrees; deny-list enforced at grant time AND read time;
reads are range-capped; every request carries an audit id logged to
~/Library/Logs/uyp/connector.log.
"""
from __future__ import annotations
import base64, hashlib, json, os, re, sys, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"
STATE_PATH = os.path.expanduser("~/.config/uyp/connector.json")
SNAPSHOT_PATH = os.path.expanduser("~/.config/uyp/manifest_snapshot.json")
LOG_PATH = os.path.expanduser("~/Library/Logs/uyp/connector.log")
PAGE_CAP = 2000
READ_CAP = 1024 * 1024
FILE_CAP = 16 * 1024 * 1024

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
                               "watcher_ok": False,
                               "last_event_id": None}, audit=audit)
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
            if os.path.getsize(full) > FILE_CAP:
                return self._json({"ok": False, "error": "file_too_large"}, 413, audit)
            try:
                off = int((q.get("offset") or ["0"])[0])
                ln = min(int((q.get("length") or [READ_CAP])[0]), READ_CAP)
            except ValueError:
                return self._json({"ok": False, "error": "bad_range"}, 400, audit)
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
            g = find_grant(st, (q.get("grant") or [""])[0])
            if not g:
                return self._json({"ok": False, "error": "no_such_grant"}, 404, audit)
            current = scan_grant(g["path"])
            snap = {}
            if os.path.exists(SNAPSHOT_PATH):
                snap = json.load(open(SNAPSHOT_PATH)).get(g["id"], {})
            events, i = [], 0
            for rel, meta in current.items():
                old = snap.get(rel)
                if old is None:
                    events.append({"id": f"e_{i}", "ts": meta["mtime"], "relpath": rel, "kind": "created"}); i += 1
                elif (old["size"], old["mtime"]) != (meta["size"], meta["mtime"]):
                    events.append({"id": f"e_{i}", "ts": meta["mtime"], "relpath": rel, "kind": "modified"}); i += 1
            for rel in snap:
                if rel not in current:
                    events.append({"id": f"e_{i}", "ts": int(time.time()), "relpath": rel, "kind": "deleted"}); i += 1
            snap_all = json.load(open(SNAPSHOT_PATH)) if os.path.exists(SNAPSHOT_PATH) else {}
            snap_all[g["id"]] = current
            os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
            json.dump(snap_all, open(SNAPSHOT_PATH, "w"))
            os.chmod(SNAPSHOT_PATH, 0o600)
            return self._json({"grant": g["id"], "events": events[:500]}, audit=audit)
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
    print(f"connector-mac v{VERSION} on {host}:7121 (state: {STATE_PATH})", flush=True)
    ThreadingHTTPServer((host, 7121), Handler).serve_forever()
