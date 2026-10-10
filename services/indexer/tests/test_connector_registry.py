import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import connector_registry  # noqa: E402


class ConnectorRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state" / "connectors" / "registry.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_is_durable_and_merges_health_without_secrets(self):
        connector_registry.upsert_connector({
            "connectorId": "connector:macbook",
            "nodeId": "jarvis-home-01",
            "kind": "local",
            "label": "Felix MacBook",
            "state": "current",
            "manifestState": "ready",
            "sourceIds": ["source:repo", "/Users/felixfang/private"],
            "transport": "cloudflare",
            "endpoint": "https://example.test/status?token=secret",
            "token": "never-persist",
            "manifest": {"state": "ready", "total": 12, "files": [{"path": "/secret"}]},
        }, self.path)
        connector_registry.update_health("connector:macbook", state="offline", detail="timeout", path=self.path)
        document = connector_registry.load_registry(self.path)
        self.assertEqual(len(document["connectors"]), 1)
        record = document["connectors"][0]
        self.assertEqual(record["state"], "offline")
        self.assertEqual(record["manifest"]["total"], 12)
        self.assertEqual(record["sourceIds"], ["source:repo"])
        self.assertNotIn("token", json.dumps(document))
        self.assertNotIn("secret", json.dumps(document))
        self.assertEqual(record["endpoint"], "https://example.test")
        self.assertEqual(Path(self.path).stat().st_mode & 0o777, 0o600)

    def test_manifest_update_keeps_only_bounded_metadata(self):
        connector_registry.upsert_connector({"connectorId": "c1", "nodeId": "n1"}, self.path)
        connector_registry.update_manifest("c1", {
            "state": "ready", "sourceEpoch": "e-2", "generatedAt": "2026-10-09T12:00:00Z",
            "cursor": "cursor-1", "fileCount": 4, "files": [{"relpath": "private.py"}],
        }, path=self.path)
        record = connector_registry.load_registry(self.path)["connectors"][0]
        self.assertEqual(record["manifestState"], "ready")
        self.assertEqual(record["manifest"]["fileCount"], 4)
        self.assertNotIn("files", record["manifest"])
        self.assertNotIn("cursor", record["manifest"])
        self.assertEqual(record["sourceEpoch"], "e-2")

    def test_invalid_document_is_non_authorizing_and_public_projection_redacts_sources(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")
        document = connector_registry.load_registry(self.path)
        self.assertEqual(document["connectors"], [])
        self.assertIn("warning", document)
        connector_registry.upsert_connector({
            "connectorId": "c2", "nodeId": "n2", "label": "Research NAS",
            "sourceIds": ["source:nas"], "state": "current", "manifestState": "ready",
        }, self.path)
        redacted = connector_registry.public_projection(connector_registry.load_registry(self.path))
        self.assertEqual(redacted[0]["label"], "Connector metadata pending")
        self.assertEqual(redacted[0]["sourceIds"], [])
        full = connector_registry.public_projection(connector_registry.load_registry(self.path), include_sources=True)
        self.assertEqual(full[0]["label"], "Research NAS")
        self.assertEqual(full[0]["sourceIds"], ["source:nas"])

    def test_forget_only_removes_local_metadata(self):
        connector_registry.upsert_connector({"connectorId": "c1", "nodeId": "n1"}, self.path)
        self.assertTrue(connector_registry.forget_connector("c1", self.path))
        self.assertFalse(connector_registry.forget_connector("c1", self.path))
        self.assertEqual(connector_registry.load_registry(self.path)["connectors"], [])


if __name__ == "__main__":
    unittest.main()

