"""Conformance tests for the fail-closed group device-action adapter."""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import query_api  # noqa: E402
from group_device_actions import GroupDeviceActionError, validate_group_device_action  # noqa: E402
from groups import GroupRegistry  # noqa: E402


def future_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")


def context(**overrides) -> dict:
    value = {
        "group_id": "group:demo",
        "member_id": "ly",
        "jarvis_node_id": "jetson-1",
        "project_ids": ["project:demo"],
        "source_ids": ["connector:demo"],
        "grant_epoch": "epoch-homehub",
        "policy_digest": "sha256:policy",
        "expires_at": future_iso(),
        "audit_id": "audit-group",
        # Opaque to UYP: presence is checked locally, the cryptographic
        # verification is HomeHub's online hook.
        "cardId": "hhgdg-test",
        "signature": "sig-test",
    }
    value.update(overrides)
    return value


def action(**overrides) -> dict:
    value = {
        "schema_version": "homehub-device-action-request-v1",
        "home_device_id": "home-device-kitchen-light",
        "action_id": "home.light.turn_on",
        "parameters": {},
        "execution_mode": "dry_run",
        "request_id": "group-test-1",
    }
    value.update(overrides)
    return value


class GroupDeviceActionUnitTests(unittest.TestCase):
    def test_missing_capability_scopes_fail_closed(self):
        with self.assertRaises(GroupDeviceActionError) as raised:
            validate_group_device_action(context(), action())
        self.assertEqual(raised.exception.code, "group_device_scope_missing")

    def test_dry_run_returns_homehub_forward_envelope(self):
        result = validate_group_device_action(context(
            device_ids=["home-device-kitchen-light"],
            action_ids=["home.light.turn_on"],
        ), action())
        self.assertTrue(result["allowed"])
        self.assertFalse(result["executed"])
        self.assertEqual(result["forwardRoute"], "/api/studio/home-devices/home-device-kitchen-light/actions")
        self.assertEqual(result["forwardEnvelope"]["execution_mode"], "dry_run")

    def test_live_fails_closed_when_verify_is_unreachable(self):
        # P1b: the old group_device_action_pending stub is gone; live now
        # re-verifies the signed context online and fails closed when HomeHub
        # cannot be reached.  A just-closed loopback port guarantees refused.
        import socket

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
        sock.close()
        old = os.environ.get("UYP_HOMEHUB_INTERNAL_URL")
        os.environ["UYP_HOMEHUB_INTERNAL_URL"] = f"http://127.0.0.1:{closed_port}"
        try:
            with self.assertRaises(GroupDeviceActionError) as raised:
                validate_group_device_action(context(
                    device_ids=["home-device-kitchen-light"],
                    action_ids=["home.light.turn_on"],
                ), action(execution_mode="live"))
        finally:
            if old is None:
                os.environ.pop("UYP_HOMEHUB_INTERNAL_URL", None)
            else:
                os.environ["UYP_HOMEHUB_INTERNAL_URL"] = old
        self.assertEqual(raised.exception.code, "group_context_invalid")

    def test_unsigned_context_is_rejected_for_dry_run_and_live(self):
        unsigned = context(
            device_ids=["home-device-kitchen-light"],
            action_ids=["home.light.turn_on"],
        )
        del unsigned["signature"]
        del unsigned["cardId"]
        for mode in ("dry_run", "live"):
            with self.assertRaises(GroupDeviceActionError) as raised:
                validate_group_device_action(unsigned, action(execution_mode=mode))
            self.assertEqual(raised.exception.code, "group_device_signature_missing")

    def test_device_and_action_scopes_are_independent(self):
        with self.assertRaises(GroupDeviceActionError) as raised:
            validate_group_device_action(context(
                device_ids=["home-device-living-room-light"],
                action_ids=["home.light.turn_on"],
            ), action())
        self.assertEqual(raised.exception.code, "group_device_not_granted")


class QueryApiGroupDeviceActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old = {key: os.environ.get(key) for key in ("UYP_STATE_ROOT", "UYP_GROUPS_FILE")}
        os.environ["UYP_STATE_ROOT"] = str(root / "state")
        os.environ["UYP_GROUPS_FILE"] = str(root / "state" / "groups.json")
        GroupRegistry().upsert({
            "group_id": "group:demo",
            "name": "Demo",
            "owner_member": "ly",
            "member_members": ["ly"],
            "knowledge_view": {"project_ids": ["project:demo"], "source_ids": ["connector:demo"]},
        })
        self.api = ThreadingHTTPServer(("127.0.0.1", 0), query_api.QueryHandler)
        self.api.loopback_voice = True
        threading.Thread(target=self.api.serve_forever, daemon=True).start()

    def tearDown(self):
        self.api.shutdown()
        self.api.server_close()
        for key, old in self.old.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        self.tmp.cleanup()

    def request(self, body, projection):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.api.server_address[1]}/api/groups/group:demo/device-actions",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Group-Context": json.dumps(projection),
                "X-Agent-Member": "ly",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def request_without_member_credential(self, body, projection):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.api.server_address[1]}/api/groups/group:demo/device-actions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-Group-Context": json.dumps(projection)},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_endpoint_dry_run_is_non_mutating(self):
        status, body = self.request(action(), context(
            device_ids=["home-device-kitchen-light"],
            action_ids=["home.light.turn_on"],
        ))
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["executed"])
        self.assertEqual(body["status"], "dry_run")

    def test_endpoint_rejects_knowledge_only_context(self):
        status, body = self.request(action(), context())
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "group_device_scope_missing")

    def test_endpoint_does_not_treat_group_projection_as_caller_credential(self):
        status, body = self.request_without_member_credential(action(), context(
            device_ids=["home-device-kitchen-light"],
            action_ids=["home.light.turn_on"],
        ))
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "group_device_credentials_required")


class _FakeHomeHubHandler(BaseHTTPRequestHandler):
    """Configurable in-process stand-in for the HomeHub internal hooks."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            body = {}
        if self.path == "/internal/studio/group-device/verify":
            self._reply(200, dict(self.server.verify_response))
            return
        if self.path.startswith("/api/studio/home-devices/") and self.path.endswith("/actions"):
            self.server.action_calls.append(body)
            if body.get("action_id") == "home.device.read_state":
                self._reply(200, {
                    "status": "ok", "allowed": True, "executed": True,
                    "state": self.server.readback_state, "auditRef": "audit-read-1",
                })
            else:
                self._reply(200, {
                    "status": "ok", "allowed": True, "executed": True,
                    "state": self.server.executed_state, "auditRef": "audit-live-1",
                })
            return
        self._reply(404, {"error": "not_found"})

    def _reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class QueryApiGroupDeviceActionLiveTests(unittest.TestCase):
    """P1b live path: online verify -> forward with bearer -> readback."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old = {key: os.environ.get(key) for key in (
            "UYP_STATE_ROOT", "UYP_GROUPS_FILE",
            "UYP_HOMEHUB_INTERNAL_URL", "UYP_HOMEHUB_TOKEN_FILE",
        )}
        os.environ["UYP_STATE_ROOT"] = str(root / "state")
        os.environ["UYP_GROUPS_FILE"] = str(root / "state" / "groups.json")
        token_file = root / "homehub.token"
        token_file.write_text("fake-homehub-service-token", encoding="utf-8")
        os.environ["UYP_HOMEHUB_TOKEN_FILE"] = str(token_file)
        GroupRegistry().upsert({
            "group_id": "group:demo",
            "name": "Demo",
            "owner_member": "ly",
            "member_members": ["ly"],
            "knowledge_view": {"project_ids": ["project:demo"], "source_ids": ["connector:demo"]},
        })
        self.homehub = ThreadingHTTPServer(("127.0.0.1", 0), _FakeHomeHubHandler)
        self.homehub.verify_response = {"ok": True, "checks": {}, "reason": None}
        self.homehub.executed_state = {"power": "on"}
        self.homehub.readback_state = {"power": "on"}
        self.homehub.action_calls = []
        threading.Thread(target=self.homehub.serve_forever, daemon=True).start()
        os.environ["UYP_HOMEHUB_INTERNAL_URL"] = (
            f"http://127.0.0.1:{self.homehub.server_address[1]}")
        self.api = ThreadingHTTPServer(("127.0.0.1", 0), query_api.QueryHandler)
        self.api.loopback_voice = True
        threading.Thread(target=self.api.serve_forever, daemon=True).start()

    def tearDown(self):
        self.api.shutdown()
        self.api.server_close()
        self.homehub.shutdown()
        self.homehub.server_close()
        for key, old in self.old.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        self.tmp.cleanup()

    def request(self, body, projection):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.api.server_address[1]}/api/groups/group:demo/device-actions",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Group-Context": json.dumps(projection),
                "X-Agent-Member": "ly",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def signed_action(self, **overrides):
        return action(execution_mode="live", **overrides)

    def signed_context(self, **overrides):
        return context(
            device_ids=["home-device-kitchen-light"],
            action_ids=["home.light.turn_on", "home.device.read_state"],
            **overrides,
        )

    def test_live_success_with_matching_readback_returns_audit_ref(self):
        status, body = self.request(self.signed_action(), self.signed_context())
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["executed"])
        self.assertEqual(body["status"], "live")
        self.assertEqual(body["auditRef"], "audit-live-1")
        # B3: the HomeHub grant audit id survives; the local one is separate.
        self.assertEqual(body["auditId"], "audit-group")
        self.assertTrue(body["uypAuditId"])
        # The forward carried the live mode; the readback rode the same route.
        modes = [call.get("execution_mode") for call in self.homehub.action_calls]
        self.assertEqual(modes, ["live", "live"])
        self.assertEqual(
            [call.get("action_id") for call in self.homehub.action_calls],
            ["home.light.turn_on", "home.device.read_state"])
        self.assertEqual(
            self.homehub.action_calls[0].get("request_id"),
            self.signed_action().get("request_id"))

    def test_live_refused_when_homehub_verify_says_revoked(self):
        self.homehub.verify_response = {"ok": False, "checks": {}, "reason": "revoked"}
        status, body = self.request(self.signed_action(), self.signed_context())
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "group_context_invalid")
        self.assertIn("revoked", body["message"])
        self.assertEqual(self.homehub.action_calls, [])

    def test_live_readback_mismatch_is_honest(self):
        self.homehub.readback_state = {"power": "off"}
        status, body = self.request(self.signed_action(), self.signed_context())
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "group_device_readback_mismatch")
        self.assertNotEqual(body.get("executed"), True)

    def test_live_without_signed_context_is_rejected(self):
        unsigned = self.signed_context()
        del unsigned["signature"]
        del unsigned["cardId"]
        status, body = self.request(self.signed_action(), unsigned)
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "group_device_signature_missing")
        self.assertEqual(self.homehub.action_calls, [])


if __name__ == "__main__":
    unittest.main()
