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
from http.server import ThreadingHTTPServer
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

    def test_live_is_pending_even_with_capability_scopes(self):
        with self.assertRaises(GroupDeviceActionError) as raised:
            validate_group_device_action(context(
                device_ids=["home-device-kitchen-light"],
                action_ids=["home.light.turn_on"],
            ), action(execution_mode="live"))
        self.assertEqual(raised.exception.code, "group_device_action_pending")

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


if __name__ == "__main__":
    unittest.main()
