#!/usr/bin/env python3
"""connector-mac: Jarvis Connector V1 skeleton.

Routes (CONNECTOR_PROTOCOL_V1.md): /pair /grants /manifest /read /events /status.
This skeleton binds loopback, serves /status, and returns 501 for the rest
until the handlers land. No grants exist before the owner creates them.
"""
from __future__ import annotations
import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.1.0-skeleton"
STATE_PATH = os.path.expanduser("~/.config/uyp/connector.json")

def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return {"device_token": None, "paired": [], "grants": []}

class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-UYP-Audit-Id", str(uuid.uuid4()))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        state = load_state()
        tok = state.get("device_token")
        header = self.headers.get("Authorization", "")
        return bool(tok) and header == f"Bearer {tok}"

    def do_GET(self):
        if self.path == "/status":
            state = load_state()
            return self._json({"state": "online", "connector_version": VERSION,
                               "grants_active": len(state.get("grants", [])),
                               "watcher_ok": False, "last_event_id": None})
        if not self._authorized():
            return self._json({"ok": False, "error": "unauthorized"}, 401)
        for route in ("/grants", "/manifest", "/read", "/events"):
            if self.path.startswith(route):
                return self._json({"ok": False, "error": "not_implemented_yet"}, 501)
        return self._json({"ok": False, "error": "not_found"}, 404)

    def do_POST(self):
        if not self._authorized():
            return self._json({"ok": False, "error": "unauthorized"}, 401)
        return self._json({"ok": False, "error": "not_implemented_yet"}, 501)

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", 7121), Handler).serve_forever()
