import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import query_api  # noqa: E402


class QueryApiProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        output = root / "output" / "demo-project"
        output.mkdir(parents=True)
        (output / "src__main.py.knowledge.json").write_text(json.dumps({
            "file": "src/main.py",
            "version": {"mtime": "2026-10-09T12:00:00Z"},
            "verdict": "quick-summary",
            "analyzed_at": "2026-10-09T12:00:00Z",
            "derived": {"purpose": "Entry point"},
        }), encoding="utf-8")
        self.context = root / "access.json"
        self.context.write_text(json.dumps({
            "principalId": "p1", "sessionId": "s1", "jarvisNodeId": "jetson-test",
            "projectScopes": ["demo-project"], "sourceScopes": ["connector:demo-project"], "grantEpoch": "g1",
            "policyDigest": "pd1", "expiresAt": "2099-01-01T00:00:00Z", "auditId": "a1",
        }), encoding="utf-8")
        state_project = root / "state" / "demo-project" / "ua"
        state_project.mkdir(parents=True)
        (state_project / "knowledge-graph.json").write_text(json.dumps({
            "version": "1.0.0",
            "project": {"name": "demo-project", "languages": ["python"], "frameworks": []},
            "nodes": [
                {"id": "file:src/main.py", "type": "file", "filePath": "src/main.py"},
                {"id": "function:src/main.py:main", "type": "function", "filePath": "src/main.py"},
            ],
            "edges": [{"source": "file:src/main.py", "target": "function:src/main.py:main", "type": "contains"}],
            "layers": [], "tour": [],
        }), encoding="utf-8")
        self.old = {key: os.environ.get(key) for key in ("UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_ACCESS_CONTEXT_FILE")}
        os.environ["UYP_OUTPUT_ROOT"] = str(root / "output")
        os.environ["UYP_STATE_ROOT"] = str(root / "state")
        os.environ["UYP_ACCESS_CONTEXT_FILE"] = str(self.context)

    def tearDown(self):
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def test_snapshot_publishes_evidence_and_node_projection(self):
        snapshot = query_api.project_snapshot()
        self.assertEqual(snapshot["project"]["name"], "demo-project")
        self.assertEqual(snapshot["health"]["coverage"]["filesIndexed"], 1)
        self.assertEqual(snapshot["access"]["jarvisNodeId"], "jetson-test")
        self.assertEqual(len(snapshot["evidence"]), 1)
        self.assertEqual(len(snapshot["agentNodes"]), 1)

    def test_snapshot_projects_authorized_ua_graph(self):
        snapshot = query_api.project_snapshot()
        self.assertEqual(snapshot["project"]["counts"], {"files": 1, "nodes": 2, "relations": 1, "layers": 0})
        self.assertEqual(snapshot["project"]["languages"], ["python"])
        self.assertIn("graph", snapshot)
        self.assertEqual(len(snapshot["graph"]["nodes"]), 2)

    def test_scope_filter_rejects_other_project(self):
        context = query_api.load_access_context()
        item = {"file": "src/main.py", "_out_path": "/tmp/output/other-project/file.knowledge.json"}
        self.assertFalse(query_api.scope_allows(context, item))

    def test_source_scope_is_a_capability_id(self):
        context = query_api.load_access_context()
        context["sourceScopes"] = ["connector:demo-project"]
        item = {"file": "src/main.py", "_out_path": "/tmp/output/demo-project/file.knowledge.json"}
        self.assertTrue(query_api.scope_allows(context, item))

    def test_snapshot_redacts_output_without_context(self):
        os.environ.pop("UYP_ACCESS_CONTEXT_FILE", None)
        snapshot = query_api.project_snapshot()
        self.assertEqual(snapshot["health"]["coverage"]["filesIndexed"], 0)
        self.assertEqual(snapshot["evidence"], [])
        self.assertEqual(snapshot["project"]["name"], "Project scope unavailable")
        self.assertNotIn("graph", snapshot)

    def test_snapshot_does_not_fallback_to_another_project(self):
        snapshot = query_api.project_snapshot("project:other-project")
        self.assertEqual(snapshot["project"]["name"], "Project scope unavailable")
        self.assertEqual(snapshot["evidence"], [])
        self.assertEqual(snapshot["jobs"], [])


if __name__ == "__main__":
    unittest.main()
