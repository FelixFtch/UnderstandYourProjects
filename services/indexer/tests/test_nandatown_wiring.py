#!/usr/bin/env python3
"""NandaTown group messaging wiring tests (audit A2, P10/G9).

Pins the send/receive/history wiring between the groups engine, the
query API, and the NandaTown transport:

* POST /api/groups/{id}/messages - a member's send fans out per
  recipient (distinct message_ids, declared sender = the member), the
  local echo persists, a non-member gets an honest 403, and a transport
  failure answers 503 with the client's error_code and persists NOTHING
  (delivery is never faked).
* The run mapping v1 - a group's ``town_run_id`` wins, the deployment
  default (``UYP_NANDATOWN_RUN_ID``) is next, and with neither the
  endpoint refuses with 503 ``nandatown_run_unconfigured`` instead of
  guessing the client's hardcoded DEFAULT_RUN_ID.
* The receive loop (``poll_nandatown_groups``) routes inbound messages
  into ``<state>/groups/<id>/messages.jsonl``, re-offers (never
  consumes) foreign-group messages, dedupes on message_id, and stays
  quiet + disabled when the transport env is absent.
* GET /api/groups/{id}/messages - the member-scoped local log a chat
  UI polls.

The mock coordinator is the same faithful miniature as
test_nandatown_client.py (join/session auth, directory, per-recipient
messages, claim/ack mailbox with 204-on-empty and retryable re-offer),
extended with a second run, per-run inboxes, a record of every sent
message (with its run), and a reject switch for per-recipient failures.
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
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import query_api  # noqa: E402
from groups import GroupRegistry  # noqa: E402


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


class MockTownHandler(BaseHTTPRequestHandler):
    """The town surface the wiring depends on, minus the town itself."""

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
            session = self.town.joined.get((parts[1], body["name"]))
            if not session:
                session = f"ses-{parts[1]}-{body['name']}"
                self.town.joined[(parts[1], body["name"])] = session
                self.town.sessions[session] = (parts[1], body["name"])
            self._json(200, {
                "session": session,
                "participant_id": body["name"],
                "run": {"run_id": parts[1], "task": {}, "roles": {},
                        "lease_seconds": 3600.0},
            })
            return
        owner = self._owner()
        if not owner:
            self._json(401, {"detail": "valid session required"})
            return
        run = owner[0]
        if self.path.endswith("/messages"):
            if self.town.reject_messages:
                self._json(500, {"detail": "town exploded"})
                return
            self.town.sent.append((run, body))
            self.town.mailbox.setdefault((run, body["to"]), []).append({
                "message_id": body["message_id"], "kind": body["kind"],
                "body": body["body"], "from": owner[1], "status": "accepted",
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
            queue = self.town.mailbox.get(owner, [])
            for message in queue:
                if message["message_id"] == body["message_id"]:
                    if body["status"] == "retryable":
                        # A sane town re-queues a re-offered message at the
                        # back, so a poll for one group cannot starve the
                        # messages of another behind it.
                        message["status"] = "accepted"
                        queue.remove(message)
                        queue.append(message)
                    else:
                        message["status"] = "done"
            self._json(200, {"recorded": True})
            return
        self._json(404, {"detail": "not found"})


class MockTown(ThreadingHTTPServer):
    """Three provisioned participants across two runs."""

    def __init__(self):
        super().__init__(("127.0.0.1", 0), MockTownHandler)
        self.runs = {"run-test", "run-alt"}
        self.reject_messages = False
        self.participants = {
            "home": {"token": "tok-home", "role": "buyer",
                     "capabilities": ["index"], "session": None},
            "clinic": {"token": "tok-clinic", "role": "seller",
                       "capabilities": [], "session": None},
            "lab": {"token": "tok-lab", "role": "seller",
                    "capabilities": [], "session": None},
        }
        self.joined = {}
        self.sessions = {}
        self.mailbox = {}
        self.sent = []


class NandatownWiringTests(unittest.TestCase):
    """The HTTP surface: send, history, membership, run mapping, errors."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "output").mkdir(parents=True)
        self.context_file = root / "access.json"
        self._write_principal("felix")
        self.groups_file = root / "state" / "groups.json"
        self.town = MockTown()
        threading.Thread(target=self.town.serve_forever, daemon=True).start()
        self.addCleanup(self.town.server_close)
        self.addCleanup(self.town.shutdown)
        self.api = ThreadingHTTPServer(("127.0.0.1", 0), query_api.QueryHandler)
        self.api.loopback_voice = True
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.addCleanup(self.api.server_close)
        self.addCleanup(self.api.shutdown)
        self.env_old = {key: os.environ.get(key) for key in (
            "UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_GROUPS_FILE",
            "UYP_ACCESS_CONTEXT_FILE", "UYP_HOMEHUB_ACCESS_CONTEXT_URL",
            "UYP_HOMEHUB_TOKEN_FILE", "UYP_OWNER_MEMBER",
            "UYP_NANDATOWN_URL", "UYP_NANDATOWN_RUN_ID",
            "UYP_NANDATOWN_JOIN_TOKEN", "UYP_NANDATOWN_PARTICIPANT",
            "UYP_NANDATOWN_CACHE_TTL", "UYP_NANDATOWN_POLL_SECONDS")}
        os.environ["UYP_OUTPUT_ROOT"] = str(root / "output")
        os.environ["UYP_STATE_ROOT"] = str(root / "state")
        os.environ["UYP_GROUPS_FILE"] = str(self.groups_file)
        os.environ["UYP_ACCESS_CONTEXT_FILE"] = str(self.context_file)
        os.environ.pop("UYP_HOMEHUB_ACCESS_CONTEXT_URL", None)
        os.environ.pop("UYP_HOMEHUB_TOKEN_FILE", None)
        os.environ.pop("UYP_OWNER_MEMBER", None)
        os.environ["UYP_NANDATOWN_URL"] = f"http://127.0.0.1:{self.town.server_port}"
        os.environ["UYP_NANDATOWN_RUN_ID"] = "run-test"
        os.environ["UYP_NANDATOWN_JOIN_TOKEN"] = "tok-home"
        os.environ["UYP_NANDATOWN_PARTICIPANT"] = "home"
        os.environ["UYP_NANDATOWN_CACHE_TTL"] = "0"
        os.environ.pop("UYP_NANDATOWN_POLL_SECONDS", None)

    def tearDown(self):
        for key, value in self.env_old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    # ---- helpers ------------------------------------------------------------

    def _write_principal(self, principal: str) -> None:
        self.context_file.write_text(json.dumps({
            "principalId": principal,
            "sessionId": f"session-{principal}",
            "jarvisNodeId": "jetson-1",
            "projectScopes": ["*"],
            "sourceScopes": ["*"],
            "grantEpoch": f"epoch-{principal}",
            "policyDigest": "sha256:policy",
            "expiresAt": "2099-01-01T00:00:00Z",
            "auditId": f"audit-{principal}",
        }), encoding="utf-8")

    def _request(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.api.server_address[1], path),
            data=data,
            headers={"Content-Type": "application/json", **(headers or {})},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def _create_group(self, **overrides):
        body = {
            "group_id": "group:demo",
            "name": "Demo group",
            "owner_member": "felix",
            "member_members": ["felix", "ly"],
            "knowledge_view": {"project_ids": ["demo-project"], "source_ids": ["connector:demo-project"]},
        }
        body.update(overrides)
        return self._request("POST", "/api/groups", body)

    def _send(self, text="hello from the test", group_id="group:demo", **extra):
        body = {"text": text, "member_id": "ly"}
        body.update(extra)
        return self._request("POST", f"/api/groups/{group_id}/messages", body)

    def _log_path(self, group_id="group:demo") -> Path:
        return Path(os.environ["UYP_STATE_ROOT"]) / "groups" / group_id / "messages.jsonl"

    def _log_rows(self, group_id="group:demo") -> list:
        path = self._log_path(group_id)
        if not path.exists():
            return []
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # ---- send: fan-out, echo, membership -----------------------------------

    def test_member_send_fans_out_per_recipient_with_distinct_ids(self):
        status, body = self._create_group()
        self.assertEqual(status, 201)
        status, body = self._send()
        self.assertEqual(status, 201)
        self.assertTrue(body["ok"])
        self.assertEqual(body["memberId"], "ly")
        # Directory minus this box's own participant (home): clinic + lab.
        self.assertEqual(sorted(body["deliveredTo"]), ["clinic", "lab"])
        runs = {run for run, _ in self.town.sent}
        self.assertEqual(runs, {"run-test"})
        envelopes = [payload for _, payload in self.town.sent]
        ids = {payload["message_id"] for payload in envelopes}
        self.assertEqual(len(envelopes), 2)
        self.assertEqual(len(ids), 2)  # distinct message_id per recipient
        self.assertTrue(all(payload["kind"] == "group.message" for payload in envelopes))
        for payload in envelopes:
            # The declared sender is the MEMBER; transport attribution is the
            # joined session (home), which the town records itself.
            self.assertEqual(payload["body"]["sender"], "ly")
            self.assertEqual(payload["body"]["group_id"], "group:demo")
            self.assertEqual(payload["body"]["text"], "hello from the test")
            self.assertTrue(payload["body"]["sent_at"])
        # The peers' inboxes hold exactly what was fanned out to each.
        self.assertEqual({m["message_id"] for m in self.town.mailbox[("run-test", "clinic")]},
                         {p["message_id"] for p in envelopes if p["to"] == "clinic"})
        self.assertEqual({m["message_id"] for m in self.town.mailbox[("run-test", "lab")]},
                         {p["message_id"] for p in envelopes if p["to"] == "lab"})
        # Local echo persisted once, with the honest per-recipient delivery.
        rows = self._log_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], "out")
        self.assertEqual(rows[0]["sender"], "ly")
        self.assertEqual(rows[0]["text"], "hello from the test")
        self.assertEqual(rows[0]["group_id"], "group:demo")
        self.assertTrue(rows[0]["sent_at"])
        self.assertEqual(sorted(entry["to"] for entry in rows[0]["delivery"]),
                         ["clinic", "lab"])
        self.assertTrue(all(entry["ok"] for entry in rows[0]["delivery"]))

    def test_owner_and_voice_member_can_send(self):
        self._create_group()
        # The owner sends without an explicit member_id: the caller principal.
        status, body = self._send(text="owner speaks", member_id=None)
        self.assertEqual(status, 201)
        self.assertEqual(body["memberId"], "felix")
        # The voice tier on loopback: X-Agent-Member selects the member.
        status, body = self._request(
            "POST", "/api/groups/group:demo/messages",
            body={"text": "spoken"}, headers={"X-Agent-Member": "ly"})
        self.assertEqual(status, 201)
        self.assertEqual(body["memberId"], "ly")

    def test_non_member_send_is_403_and_sends_nothing(self):
        self._create_group()
        status, body = self._send(member_id="stranger")
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "not_a_member")
        # Nothing left the box and nothing was echoed into history.
        self.assertEqual(self.town.sent, [])
        self.assertFalse(self._log_path().exists())
        # An expired / malformed presented context is also refused.
        status, body = self._request(
            "POST", "/api/groups/group:demo/messages",
            body={"text": "hi"},
            headers={"X-Group-Context": json.dumps({"group_id": "group:demo"})})
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "group_context_invalid")

    def test_send_validation_and_unknown_group(self):
        self._create_group()
        status, body = self._send(text="   ")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "message_text_required")
        status, body = self._send(text="x" * (query_api.MAX_MESSAGE_TEXT + 1))
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "message_too_long")
        status, body = self._send(group_id="group:ghost")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "group_not_found")
        # No member resolvable at all: fail closed, never assume the box.
        os.environ.pop("UYP_ACCESS_CONTEXT_FILE", None)
        status, body = self._request("POST", "/api/groups/group:demo/messages",
                                     body={"text": "hi"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "member_required")
        self.assertEqual(self.town.sent, [])

    # ---- honest transport failures ------------------------------------------

    def test_unreachable_town_is_honest_503_no_echo(self):
        self._create_group()
        os.environ["UYP_NANDATOWN_URL"] = "http://127.0.0.1:1"
        status, body = self._send()
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "nandatown_unreachable")
        self.assertIn("NandaTown refused this send", body["message"])
        self.assertFalse(self._log_path().exists())
        # Unconfigured transport (no join token) is equally honest.
        os.environ["UYP_NANDATOWN_URL"] = f"http://127.0.0.1:{self.town.server_port}"
        os.environ["UYP_NANDATOWN_JOIN_TOKEN"] = ""
        status, body = self._send()
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "nandatown_unconfigured")
        self.assertFalse(self._log_path().exists())

    def test_all_recipient_failures_report_error_and_skip_echo(self):
        self._create_group()
        self.town.reject_messages = True
        status, body = self._send()
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "nandatown_bad_response")
        self.assertEqual(len(body["delivery"]), 2)
        self.assertFalse(any(entry["ok"] for entry in body["delivery"]))
        self.assertFalse(self._log_path().exists())

    # ---- run mapping v1 -----------------------------------------------------

    def test_run_mapping_override_default_and_unconfigured(self):
        # Override: the group's own town_run_id wins.
        status, body = self._create_group(town_run_id="run-alt")
        self.assertEqual(status, 201)
        self.assertEqual(body["group"]["town_run_id"], "run-alt")
        status, body = self._send()
        self.assertEqual(status, 201)
        self.assertEqual({run for run, _ in self.town.sent}, {"run-alt"})
        # Default: no town_run_id, the deployment's UYP_NANDATOWN_RUN_ID.
        self._create_group(group_id="group:plain", town_run_id=None)
        status, body = self._send(group_id="group:plain")
        self.assertEqual(status, 201)
        self.assertIn("run-test", {run for run, _ in self.town.sent})
        # Unconfigured: neither per-group nor deployment run -> honest 503,
        # never a silent guess of the client's DEFAULT_RUN_ID.
        os.environ.pop("UYP_NANDATOWN_RUN_ID", None)
        self._create_group(group_id="group:orphan")
        before = list(self.town.sent)
        status, body = self._send(group_id="group:orphan")
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "nandatown_run_unconfigured")
        self.assertEqual(self.town.sent, before)
        # ...while the per-group mapping still routes with the env gone.
        status, body = self._send()
        self.assertEqual(status, 201)
        self.assertEqual({run for run, _ in self.town.sent}, {"run-alt", "run-test"})

    # ---- history endpoint ---------------------------------------------------

    def test_history_is_member_scoped_and_limited(self):
        self._create_group()
        self._send(text="first")
        self._send(text="second")
        status, body = self._request(
            "GET", "/api/groups/group:demo/messages?member_id=ly")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["memberId"], "ly")
        self.assertEqual([row["text"] for row in body["messages"]],
                         ["first", "second"])
        self.assertEqual(body["total"], 2)
        # limit= keeps the newest tail only.
        status, body = self._request(
            "GET", "/api/groups/group:demo/messages?member_id=ly&limit=1")
        self.assertEqual([row["text"] for row in body["messages"]], ["second"])
        # A non-member learns nothing, not even that history exists.
        status, body = self._request(
            "GET", "/api/groups/group:demo/messages?member_id=stranger")
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "not_a_member")
        status, body = self._request(
            "GET", "/api/groups/group:ghost/messages?member_id=ly")
        self.assertEqual(status, 404)
        # The voice tier reads history too (the loopback pin).
        status, body = self._request(
            "GET", "/api/groups/group:demo/messages",
            headers={"X-Agent-Member": "ly"})
        self.assertEqual(status, 200)
        self.assertEqual(body["memberId"], "ly")


class PollLoopTests(unittest.TestCase):
    """The receive loop: routing, persistence, re-offer, dedupe, gating."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "output").mkdir(parents=True)
        self.state = root / "state"
        self.groups_file = self.state / "groups.json"
        self.town = MockTown()
        threading.Thread(target=self.town.serve_forever, daemon=True).start()
        self.addCleanup(self.town.server_close)
        self.addCleanup(self.town.shutdown)
        self.env_old = {key: os.environ.get(key) for key in (
            "UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_GROUPS_FILE",
            "UYP_ACCESS_CONTEXT_FILE", "UYP_NANDATOWN_URL",
            "UYP_NANDATOWN_RUN_ID", "UYP_NANDATOWN_JOIN_TOKEN",
            "UYP_NANDATOWN_PARTICIPANT", "UYP_NANDATOWN_CACHE_TTL",
            "UYP_NANDATOWN_POLL_SECONDS")}
        os.environ["UYP_OUTPUT_ROOT"] = str(root / "output")
        os.environ["UYP_STATE_ROOT"] = str(self.state)
        os.environ["UYP_GROUPS_FILE"] = str(self.groups_file)
        os.environ.pop("UYP_ACCESS_CONTEXT_FILE", None)
        os.environ["UYP_NANDATOWN_URL"] = f"http://127.0.0.1:{self.town.server_port}"
        os.environ["UYP_NANDATOWN_RUN_ID"] = "run-test"
        os.environ["UYP_NANDATOWN_JOIN_TOKEN"] = "tok-home"
        os.environ["UYP_NANDATOWN_PARTICIPANT"] = "home"
        os.environ["UYP_NANDATOWN_CACHE_TTL"] = "0"
        os.environ.pop("UYP_NANDATOWN_POLL_SECONDS", None)

    def tearDown(self):
        for key, value in self.env_old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    # ---- helpers ------------------------------------------------------------

    def _register_group(self, group_id="group:demo", town_run_id=None):
        return GroupRegistry(str(self.groups_file)).upsert({
            "group_id": group_id,
            "name": f"Group {group_id}",
            "owner_member": "felix",
            "member_members": ["felix", "ly"],
            "knowledge_view": {"project_ids": ["*"], "source_ids": ["*"]},
            "town_run_id": town_run_id,
        })

    def _deliver(self, message_id, text, group_id="group:demo", run="run-test",
                 to="home", sender="clinic", sent_at=None):
        """Prime this box's inbox the way a peer's fan-out would have."""
        self.town.mailbox.setdefault((run, to), []).append({
            "message_id": message_id, "kind": "group.message", "from": sender,
            "status": "accepted",
            "body": {"group_id": group_id, "text": text, "sender": sender,
                     "sent_at": sent_at or _iso(datetime.now(timezone.utc))},
        })

    def _rows(self, group_id="group:demo") -> list:
        path = self.state / "groups" / group_id / "messages.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _poll(self):
        return query_api.poll_nandatown_groups()

    # ---- routing + persistence ----------------------------------------------

    def test_poll_routes_inbound_to_their_group_log(self):
        self._register_group()
        self._deliver("m-1", "printer fix: refill tray 2", sender="clinic")
        self._deliver("m-2", "second note", sender="lab")
        report = self._poll()
        self.assertIsNone(report["error"])
        self.assertEqual(report["polled_runs"], 1)
        self.assertEqual(report["polled_groups"], 1)
        self.assertEqual(report["received"], 2)
        self.assertEqual(report["stored"], 2)
        rows = self._rows()
        self.assertEqual([row["text"] for row in rows],
                         ["printer fix: refill tray 2", "second note"])
        for row in rows:
            self.assertEqual(row["direction"], "in")
            self.assertEqual(row["group_id"], "group:demo")
            self.assertTrue(row["sent_at"])
            self.assertTrue(row["received_at"])
        self.assertEqual([row["sender"] for row in rows], ["clinic", "lab"])
        # Consumed town-side (acked received), not merely filtered locally.
        statuses = {m["status"] for m in self.town.mailbox[("run-test", "home")]}
        self.assertEqual(statuses, {"done"})

    def test_poll_does_not_consume_foreign_group_messages(self):
        self._register_group("group:demo")
        self._register_group("group:other")
        self._deliver("m-foreign", "not for this group's poll",
                      group_id="group:unmapped")
        report = self._poll()
        self.assertEqual(report["received"], 0)
        # The client re-offered it (retryable), so it is still pending for
        # whoever DOES map that group - never lost, never consumed here.
        self.assertEqual(self.town.mailbox[("run-test", "home")][0]["status"],
                         "accepted")
        self.assertEqual(self._rows("group:demo"), [])
        # A later poll for a group that knows it can still claim it.
        self._register_group("group:unmapped")
        report = self._poll()
        self.assertEqual(report["stored"], 1)
        self.assertEqual(self._rows("group:unmapped")[0]["text"],
                         "not for this group's poll")

    def test_poll_dedupes_replays_on_message_id(self):
        self._register_group()
        self._deliver("m-dup", "once")
        self.assertEqual(self._poll()["stored"], 1)
        # Lease expiry re-offers the same message: at-least-once transport,
        # exactly-once local log (dedupe on message_id).
        for message in self.town.mailbox[("run-test", "home")]:
            message["status"] = "accepted"
        report = self._poll()
        self.assertEqual(report["received"], 1)
        self.assertEqual(report["stored"], 0)
        self.assertEqual(len(self._rows()), 1)

    def test_poll_watermark_tracks_inbound_only(self):
        self._register_group()
        now = datetime.now(timezone.utc)
        self._deliver("m-1", "first inbound",
                      sent_at=_iso(now - timedelta(seconds=60)))
        self.assertEqual(self._poll()["stored"], 1)
        # A replay older than the newest inbound row is dropped by the filter.
        self._deliver("m-old", "stale replay",
                      sent_at=_iso(now - timedelta(days=365)))
        for message in self.town.mailbox[("run-test", "home")]:
            message["status"] = "accepted"
        self.assertEqual(self._poll()["stored"], 0)
        self.assertEqual(len(self._rows()), 1)
        # Our own later OUTBOUND echo must not raise the watermark: a peer
        # whose clock sits between the last inbound and our echo still gets
        # through (skewed clocks never hide mail behind our own sends).
        echo = {"message_id": "local-echo", "group_id": "group:demo",
                "sender": "ly", "sent_at": _iso(now),
                "text": "our own send", "direction": "out"}
        self.assertTrue(query_api.append_group_message("group:demo", echo))
        self._deliver("m-skew", "peer clock behind our echo",
                      sent_at=_iso(now - timedelta(seconds=30)))
        self.assertEqual(self._poll()["stored"], 1)
        self.assertEqual(self._rows()[-1]["text"], "peer clock behind our echo")

    def test_poll_skips_groups_without_a_run(self):
        self._register_group(town_run_id=None)
        os.environ.pop("UYP_NANDATOWN_RUN_ID", None)
        self._deliver("m-1", "waits for a mapping")
        report = self._poll()
        self.assertEqual(report["polled_groups"], 0)
        self.assertEqual(report["polled_runs"], 0)
        # Nothing was claimed: the message waits in the inbox untouched.
        self.assertEqual(self.town.mailbox[("run-test", "home")][0]["status"],
                         "accepted")

    def test_poll_per_group_run_override(self):
        self._register_group("group:demo", town_run_id="run-alt")
        self._deliver("m-alt", "on the other run", run="run-alt")
        self._deliver("m-test", "on the default run", run="run-test")
        report = self._poll()
        self.assertEqual(report["polled_runs"], 1)
        rows = self._rows()
        self.assertEqual([row["text"] for row in rows], ["on the other run"])
        # The default-run message was never touched by this group's poll.
        self.assertEqual(self.town.mailbox[("run-test", "home")][0]["status"],
                         "accepted")

    def test_poll_disabled_without_transport_env(self):
        self._register_group()
        self._deliver("m-1", "quiet box")
        os.environ["UYP_NANDATOWN_JOIN_TOKEN"] = ""
        report = self._poll()
        self.assertEqual(report["error"], "nandatown_unconfigured")
        self.assertEqual(report["polled_groups"], 0)
        self.assertEqual(self.town.mailbox[("run-test", "home")][0]["status"],
                         "accepted")
        self.assertFalse(self.town.joined)  # never even attempted a join
        # The background loop refuses to start in the same state.
        self.assertFalse(query_api.start_nandatown_poller())

    def test_poller_loop_gating_and_interval(self):
        self.assertEqual(query_api.nandatown_poll_seconds(), 15.0)
        os.environ["UYP_NANDATOWN_POLL_SECONDS"] = "0.25"
        self.assertEqual(query_api.nandatown_poll_seconds(), 0.25)
        os.environ["UYP_NANDATOWN_POLL_SECONDS"] = "not-a-number"
        self.assertEqual(query_api.nandatown_poll_seconds(), 15.0)
        # Zero or below is an explicit deployment disable.
        os.environ["UYP_NANDATOWN_POLL_SECONDS"] = "0"
        self.assertFalse(query_api.start_nandatown_poller())
        # With transport configured the loop starts once and polls.
        os.environ["UYP_NANDATOWN_POLL_SECONDS"] = "0.05"
        self._register_group()
        self._deliver("m-loop", "drained by the loop")
        self.assertTrue(query_api.start_nandatown_poller())
        # A second start is a no-op (one loop per process).
        self.assertFalse(query_api.start_nandatown_poller())
        self.addCleanup(self._stop_poller)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self._rows():
                break
            time.sleep(0.05)
        self.assertEqual([row["text"] for row in self._rows()], ["drained by the loop"])

    @staticmethod
    def _stop_poller() -> None:
        """Stop the module-level loop and reset its state for the next test."""
        query_api._nandatown_poll_stop.set()
        if query_api._nandatown_poll_thread is not None:
            query_api._nandatown_poll_thread.join(timeout=2.0)
        query_api._nandatown_poll_thread = None
        query_api._nandatown_poll_stop = threading.Event()
        query_api.nandatown_poll_status.update({"started": False,
                                                "interval_seconds": None,
                                                "last_report": None})


if __name__ == "__main__":
    unittest.main()
