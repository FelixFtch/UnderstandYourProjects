import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import connector_registry  # noqa: E402
import query_api  # noqa: E402


class QueryApiRegistryProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = {key: os.environ.get(key) for key in ("UYP_STATE_ROOT", "UYP_CONNECTOR_REGISTRY_FILE")}
        os.environ["UYP_STATE_ROOT"] = str(self.root / "state")
        os.environ.pop("UYP_CONNECTOR_REGISTRY_FILE", None)
        connector_registry.upsert_connector({
            "connectorId": "connector:mac",
            "nodeId": "jetson-1",
            "kind": "local",
            "label": "Mac source",
            "state": "current",
            "manifestState": "ready",
            "sourceIds": ["source:mac"],
            "transport": "cloudflare",
            "capabilities": ["manifest", "read_range"],
            "lastSeen": "2026-10-09T12:00:00Z",
        })

    def tearDown(self):
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def test_without_homehub_context_is_metadata_only(self):
        projection = query_api.connector_registry_projection(None)
        self.assertEqual(projection[0]["connectorId"], "connector:mac")
        self.assertEqual(projection[0]["label"], "Connector metadata pending")
        self.assertEqual(projection[0]["sourceIds"], [])

    def test_homehub_source_scope_reveals_only_authorized_connector(self):
        context = {"sourceScopes": ["source:mac"]}
        projection = query_api.connector_registry_projection(context)
        self.assertEqual(projection[0]["label"], "Mac source")
        self.assertEqual(projection[0]["sourceIds"], ["source:mac"])
        self.assertEqual(query_api.connector_registry_projection({"sourceScopes": ["source:other"]}), [])

    def test_persisted_index_jobs_are_scope_filtered_and_redacted(self):
        jobs = self.root / "state" / "index-jobs"
        jobs.mkdir(parents=True)
        (jobs / "job-a.json").write_text(
            '{"jobId":"job-a","projectId":"project-a","sourceId":"connector:a",'
            '"grantId":"secret-grant","phase":"running","progress":{"processed":2,"total":4},'
            '"outputPath":"/private/path","updatedAt":"2026-10-09T12:00:00Z"}',
            encoding="utf-8",
        )
        (jobs / "job-b.json").write_text(
            '{"jobId":"job-b","projectId":"project-b","sourceId":"connector:b",'
            '"phase":"published","progress":{"processed":1,"total":1}}',
            encoding="utf-8",
        )
        self.assertEqual(query_api.load_persisted_index_jobs(context=None), [])
        result = query_api.load_persisted_index_jobs(context={"projectScopes": ["project-a"], "sourceScopes": ["connector:a"]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["projectId"], "project:project-a")
        self.assertNotIn("grantId", result[0])
        self.assertNotIn("outputPath", result[0])
        self.assertEqual(query_api.load_persisted_index_jobs(context={"projectScopes": ["*"] , "sourceScopes": ["connector:a"]})[0]["jobId"], "job-a")


if __name__ == "__main__":
    unittest.main()

