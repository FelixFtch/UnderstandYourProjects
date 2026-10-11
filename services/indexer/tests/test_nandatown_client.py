#!/usr/bin/env python3
"""NandaTown client + query-api peers endpoint tests.

The mock coordinator below is a faithful in-thread miniature of the real
town surface the client is written against (join/session auth, the
participant directory, per-recipient messages, and the claim/ack mailbox
with 204-on-empty and retryable re-offer), so the round-trip tests
exercise the mapping, not a mirror of the client's own assumptions.
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import nandatown_client  # noqa: E402
import query_api  # noqa: E402


def _iso(year: int) -> str:
    return datetime(year, 1, 1, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


class MockTownHandler(BaseHTTPRequestHandler):
    """The town's participant surface: health, join, directory, mailbox."""

    def log_message(self, *args):  # keep test output quiet
        pass

    @property
    def town(self):
        return self.server

    def _json(self, status, value):
        body = json.dumps(value).encode("utf-8") if value is not None else b""
        self.send_response(status)
        if value is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _owner(self):
        return self.town.sessions.get(self.headers.get("X-Town-Session", ""))

    def do_GET(self):
        if self.town.slow:
            time.sleep(1.0)
        if self.path == "/health":
            self._json(200, {"ok": True})
            return
        if self.path.endswith("/participants"):
            owner = self._owner()
            if not owner:
                self._json(401, {"detail": "valid session required"})
                return
            self._json(200, [
                {"name": name, "role": record["role"],
                 "capabilities": list(record["capabilities"])}
                for name, record in sorted(self.town.participants.items())
            ])
            return
        self._json(404, {"detail": "not found"})

    def do_POST(self):
        if self.town.slow:
            time.sleep(1.0)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        parts = self.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "runs" and parts[2] == "join":
            if parts[1] not in self.town.runs:
                self._json(404, {"detail": "unknown run"})
                return
            record = self.town.participants.get(body.get("name"))
            if not record or record["token"] != body.get("token"):
                self._json(403, {"detail": "join rejected"})
                return
            if not record["session"]:
                record["session"] = f"ses-{body['name']}"
                self.town.sessions[record["session"]] = body["name"]
            self._json(200, {
                "session": record["session"],
                "participant_id": body["name"],
                "run": {"run_id": parts[1], "task": {}, "roles": {},
                        "lease_seconds": 3600.0},
            })
            return
        owner = self._owner()
        if not owner:
            self._json(401, {"detail": "valid session required"})
            return
        if self.path.endswith("/messages"):
            self.town.mailbox.setdefault(body["to"], []).append({
                "message_id": body["message_id"], "kind": body["kind"],
                "body": body["body"], "from": owner, "status": "accepted",
            })
            self._json(202, {"message_id": body["message_id"],
                             "accepted_at": time.time(), "replay": False})
            return
        if self.path.endswith("/inbox/claim"):
            pending = [m for m in self.town.mailbox.get(owner, [])
                       if m["status"] == "accepted"]
            if not pending:
                self._json(204, None)
                return
            message = pending[0]
            message["status"] = "claimed"
            message["fence"] = "fence-1"
            self._json(200, {
                "message_id": message["message_id"], "kind": message["kind"],
                "body": message["body"], "from": message["from"],
                "attempt": 1, "fence": "fence-1",
                "lease_expires_at": time.time() + 3600.0, "duplicate": False,
            })
            return
        if self.path.endswith("/inbox/ack"):
            for message in self.town.mailbox.get(owner, []):
                if message["message_id"] == body["message_id"]:
                    message["status"] = ("accepted" if body["status"] == "retryable"
                                         else "done")
            self._json(200, {"recorded": True})
            return
        self._json(404, {"detail": "not found"})


class MockTown(ThreadingHTTPServer):
    """Two provisioned participants (home/clinic) sharing one run."""

    def __init__(self):
        super().__init__(("127.0.0.1", 0), MockTownHandler)
        self.runs = {"run-test"}
        self.slow = False
        self.participants = {
            "home": {"token": "tok-home", "role": "buyer",
                     "capabilities": ["index"], "session": None},
            "clinic": {"token": "tok-clinic", "role": "seller",
                       "capabilities": [], "session": None},
        }
        self.sessions = {}
        self.mailbox = {}


class NandaTownClientTests(unittest.TestCase):
    def setUp(self):
        self.town = MockTown()
        threading.Thread(target=self.town.serve_forever, daemon=True).start()
        self.addCleanup(self.town.server_close)
        self.addCleanup(self.town.shutdown)
        self.url = f"http://127.0.0.1:{self.town.server_port}"
        self.old = {key: os.environ.get(key) for key in (
            "UYP_NANDATOWN_URL", "UYP_NANDATOWN_RUN_ID",
            "UYP_NANDATOWN_JOIN_TOKEN", "UYP_NANDATOWN_PARTICIPANT",
            "UYP_NANDATOWN_CACHE_TTL")}
        os.environ["UYP_NANDATOWN_URL"] = self.url
        os.environ["UYP_NANDATOWN_RUN_ID"] = "run-test"
        os.environ["UYP_NANDATOWN_JOIN_TOKEN"] = "tok-home"
        os.environ["UYP_NANDATOWN_PARTICIPANT"] = "home"
        os.environ["UYP_NANDATOWN_CACHE_TTL"] = "0"

    def tearDown(self):
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def client(self, **kwargs):
        kwargs.setdefault("base_url", self.url)
        kwargs.setdefault("run_id", "run-test")
        kwargs.setdefault("join_token", "tok-home")
        kwargs.setdefault("participant", "home")
        return nandatown_client.NandaTownClient(**kwargs)

    def test_health_and_env_configured_defaults(self):
        client = nandatown_client.NandaTownClient()  # env-configured only
        self.assertTrue(client.health())
        self.assertIsNone(client.error_code)

    def test_register_and_list_peers_round_trip(self):
        client = self.client()
        record = client.register_peer("jetson-node-1", "home", ["index", "search"])
        self.assertIsNotNone(record)
        self.assertEqual(record["peer_id"], "home")
        self.assertEqual(record["node_id"], "jetson-node-1")
        # Advertised capabilities stay local truth; town truth is separate.
        self.assertEqual(record["advertised_capabilities"], ["index", "search"])
        self.assertEqual(record["town_capabilities"], ["index"])
        self.assertEqual(record["role"], "buyer")
        self.assertIsNone(client.error_code)
        peers = client.list_peers()
        self.assertIsNone(client.error_code)
        self.assertEqual([peer["nodeId"] for peer in peers], ["clinic", "home"])
        home = peers[1]
        self.assertEqual(home["peerId"], "town:run-test:home")
        self.assertEqual(home["displayLabel"], "home")
        self.assertEqual(home["transport"], "nandatown")
        self.assertEqual(home["trust"], "advertised")
        self.assertEqual(home["status"], "available")
        self.assertEqual(home["capabilities"], ["buyer", "index"])

    def test_send_fanout_and_poll_round_trip(self):
        home = self.client()
        clinic = self.client(join_token="tok-clinic", participant="clinic")
        results = home.send_group_message("group-a", "home", "hello clinic")
        self.assertEqual(len(results), 1)  # fan-out excludes the sender
        self.assertEqual(results[0]["to"], "clinic")
        self.assertTrue(results[0]["ok"])
        self.assertTrue(results[0]["message_id"].startswith("msg-"))
        messages = clinic.poll_group_messages("group-a")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["from"], "home")
        self.assertEqual(messages[0]["body"]["text"], "hello clinic")
        self.assertEqual(messages[0]["body"]["group_id"], "group-a")
        self.assertEqual(messages[0]["group_id"], "group-a")
        self.assertTrue(messages[0]["acknowledged"])
        self.assertEqual(clinic.poll_group_messages("group-a"), [])  # consumed
        # Consumed town-side too, not just filtered locally.
        self.assertEqual(self.town.mailbox["clinic"][0]["status"], "done")

    def test_poll_reoffers_messages_of_other_groups(self):
        self.town.mailbox["clinic"] = [{
            "message_id": "m-foreign", "kind": "group.message", "from": "home",
            "status": "accepted",
            "body": {"group_id": "group-b", "text": "not for you",
                     "sent_at": _iso(2030)},
        }]
        clinic = self.client(join_token="tok-clinic", participant="clinic")
        self.assertEqual(clinic.poll_group_messages("group-a"), [])
        self.assertEqual(self.town.mailbox["clinic"][0]["status"], "accepted")
        self.assertEqual(len(clinic.poll_group_messages("group-b")), 1)

    def test_poll_since_ts_filters_sender_declared_timestamps(self):
        self.town.mailbox["clinic"] = [
            {"message_id": "m-old", "kind": "group.message", "from": "home",
             "status": "accepted",
             "body": {"group_id": "group-a", "text": "old", "sent_at": _iso(2020)}},
            {"message_id": "m-new", "kind": "group.message", "from": "home",
             "status": "accepted",
             "body": {"group_id": "group-a", "text": "new", "sent_at": _iso(2030)}},
        ]
        clinic = self.client(join_token="tok-clinic", participant="clinic")
        cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
        got = clinic.poll_group_messages("group-a", since_ts=cutoff)
        self.assertEqual([m["message_id"] for m in got], ["m-new"])
        # Both were still consumed: the window filters, the mailbox drains.
        self.assertEqual({m["status"] for m in self.town.mailbox["clinic"]},
                         {"done"})

    def test_slow_town_times_out_to_empty_list(self):
        self.town.slow = True
        client = self.client(timeout=0.3)
        started = time.monotonic()
        self.assertEqual(client.list_peers(), [])
        self.assertLess(time.monotonic() - started, 4.0)
        self.assertEqual(client.error_code, nandatown_client.ERROR_UNREACHABLE)
        self.assertTrue(client.unreachable)
        self.assertIsNone(client.register_peer("n", "home", []))

    def test_unreachable_town_fails_closed_everywhere(self):
        client = nandatown_client.NandaTownClient(
            base_url="http://127.0.0.1:1", run_id="run-test",
            join_token="tok-home", participant="home", timeout=0.5)
        self.assertFalse(client.health())
        self.assertEqual(client.list_peers(), [])
        self.assertEqual(client.send_group_message("g", "home", "x"), [])
        self.assertEqual(client.poll_group_messages("g"), [])
        self.assertEqual(client.error_code, nandatown_client.ERROR_UNREACHABLE)
        self.assertTrue(client.unreachable)

    def test_missing_join_token_is_honest_unconfigured(self):
        client = self.client(join_token="")
        self.assertEqual(client.list_peers(), [])
        self.assertEqual(client.error_code, nandatown_client.ERROR_UNCONFIGURED)
        self.assertFalse(client.unreachable)

    def test_wrong_token_is_unauthorized(self):
        client = self.client(join_token="wrong-token")
        self.assertIsNone(client.register_peer("n", "home", []))
        self.assertEqual(client.error_code, nandatown_client.ERROR_UNAUTHORIZED)
        self.assertEqual(client.list_peers(), [])

    def test_unknown_run_is_reported(self):
        client = self.client(run_id="run-nope")
        self.assertEqual(client.list_peers(), [])
        self.assertEqual(client.error_code, nandatown_client.ERROR_UNKNOWN_RUN)


class QueryApiNandaTownEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "output").mkdir(parents=True)
        self.town = MockTown()
        threading.Thread(target=self.town.serve_forever, daemon=True).start()
        self.addCleanup(self.town.server_close)
        self.addCleanup(self.town.shutdown)
        self.api = ThreadingHTTPServer(("127.0.0.1", 0), query_api.QueryHandler)
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.addCleanup(self.api.server_close)
        self.addCleanup(self.api.shutdown)
        self.old = {key: os.environ.get(key) for key in (
            "UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_ACCESS_CONTEXT_FILE",
            "UYP_NANDATOWN_URL", "UYP_NANDATOWN_RUN_ID",
            "UYP_NANDATOWN_JOIN_TOKEN", "UYP_NANDATOWN_PARTICIPANT",
            "UYP_NANDATOWN_CACHE_TTL")}
        os.environ["UYP_OUTPUT_ROOT"] = str(root / "output")
        os.environ["UYP_STATE_ROOT"] = str(root / "state")
        os.environ.pop("UYP_ACCESS_CONTEXT_FILE", None)
        os.environ["UYP_NANDATOWN_URL"] = f"http://127.0.0.1:{self.town.server_port}"
        os.environ["UYP_NANDATOWN_RUN_ID"] = "run-test"
        os.environ["UYP_NANDATOWN_JOIN_TOKEN"] = "tok-home"
        os.environ["UYP_NANDATOWN_PARTICIPANT"] = "home"
        os.environ["UYP_NANDATOWN_CACHE_TTL"] = "0"

    def tearDown(self):
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def _get(self, path):
        url = f"http://127.0.0.1:{self.api.server_port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_peers_endpoint_serves_live_town_directory(self):
        status, body = self._get("/api/nandatown/peers")
        self.assertEqual(status, 200)
        self.assertEqual(body["source"], "town")
        self.assertFalse(body["metadataOnly"])
        self.assertEqual([peer["nodeId"] for peer in body["peers"]],
                         ["clinic", "home"])
        self.assertTrue(all(peer["transport"] == "nandatown"
                            for peer in body["peers"]))

    def test_peers_endpoint_is_honest_503_when_town_unreachable(self):
        os.environ["UYP_NANDATOWN_URL"] = "http://127.0.0.1:1"
        status, body = self._get("/api/nandatown/peers")
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "nandatown_unreachable")
        self.assertEqual(body["peers"], [])
        self.assertTrue(body["metadataOnly"])
        self.assertIn("NandaTown directory unavailable", body["message"])

    def test_peers_endpoint_reports_unconfigured_town_honestly(self):
        os.environ["UYP_NANDATOWN_JOIN_TOKEN"] = ""
        status, body = self._get("/api/nandatown/peers")
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "nandatown_unconfigured")

    def test_snapshot_peers_fall_back_to_empty_when_town_down(self):
        os.environ["UYP_NANDATOWN_URL"] = "http://127.0.0.1:1"
        self.assertEqual(query_api.project_snapshot()["peers"], [])


if __name__ == "__main__":
    unittest.main()
