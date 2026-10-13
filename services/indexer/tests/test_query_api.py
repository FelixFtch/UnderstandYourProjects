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

    def test_health_count_is_scope_filtered_like_search(self):
        # P7 acceptance finding 1: health must report the same scope-filtered
        # count search would query, never the unscoped output total.
        other = Path(query_api.output_root()) / "other-project"
        other.mkdir(parents=True)
        (other / "lib__py.knowledge.json").write_text(json.dumps({
            "file": "lib.py",
            "version": {"mtime": "2026-10-09T12:00:00Z"},
            "verdict": "quick-summary",
            "analyzed_at": "2026-10-09T12:00:00Z",
        }), encoding="utf-8")
        context = query_api.load_access_context()
        self.assertEqual(len(query_api.scoped_items(context)), 1)
        health = query_api.health_payload()
        self.assertEqual(health["knowledgeItems"], 1)
        self.assertTrue(health["accessContext"])
        # Narrow the HomeHub scope the way a revocation would: search sees
        # nothing, so health must not keep reporting the on-disk total.
        narrowed = json.loads(self.context.read_text(encoding="utf-8"))
        narrowed["projectScopes"] = ["somewhere-else"]
        narrowed["sourceScopes"] = ["connector:somewhere-else"]
        self.context.write_text(json.dumps(narrowed), encoding="utf-8")
        self.assertEqual(query_api.scoped_items(query_api.load_access_context()), [])
        narrowed_health = query_api.health_payload()
        self.assertEqual(narrowed_health["knowledgeItems"], 0)
        self.assertTrue(narrowed_health["accessContext"])

    def test_health_reports_zero_without_access_context(self):
        os.environ.pop("UYP_ACCESS_CONTEXT_FILE", None)
        health = query_api.health_payload()
        self.assertEqual(health["knowledgeItems"], 0)
        self.assertFalse(health["accessContext"])

    def test_snapshot_projects_anchor_top_into_evidence(self):
        # The Studio evidence badge (studio-contracts.ts EvidenceRef.anchorTop)
        # was waiting for this projection: v3.2 anchored enrichment writes
        # anchor_top onto each KnowledgeItem, and the panel renders the
        # primary-actor badge from the projected anchorTop.
        item_path = Path(query_api.output_root()) / "demo-project" / "src__main.py.knowledge.json"
        item = json.loads(item_path.read_text(encoding="utf-8"))
        item["anchor_top"] = "main L10-L42"
        item_path.write_text(json.dumps(item), encoding="utf-8")
        snapshot = query_api.project_snapshot()
        self.assertEqual(snapshot["evidence"][0]["anchorTop"], "main L10-L42")

    def test_evidence_without_anchor_top_omits_the_field(self):
        # A pre-anchored item must not carry a null badge field: the Studio
        # contract keeps anchorTop optional and the badge simply stays dark.
        snapshot = query_api.project_snapshot()
        self.assertEqual(len(snapshot["evidence"]), 1)
        self.assertNotIn("anchorTop", snapshot["evidence"][0])

    def test_search_citations_project_sources_into_contract(self):
        context = query_api.load_access_context()
        scoped = query_api.scoped_items(context)
        citations = query_api.search_citations(
            [{"file": "src/main.py", "match": 4.0}, {"file": "other.py", "match": 9.0}],
            scoped,
            context,
        )
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["projectId"], "project:demo-project")
        self.assertEqual(citations[0]["sourceId"], "connector:demo-project")
        self.assertEqual(citations[0]["file"], "src/main.py")
        self.assertEqual(citations[0]["knowledgeVersion"], "2026-10-09T12:00:00Z")
        self.assertEqual(citations[0]["sourceEpoch"], "2026-10-09T12:00:00Z")
        self.assertEqual(citations[0]["evidenceLevel"], "inference")
        self.assertEqual(citations[0]["producingJarvis"], "jetson-test")
        self.assertFalse(citations[0]["allowedToShare"])


if __name__ == "__main__":
    unittest.main()
