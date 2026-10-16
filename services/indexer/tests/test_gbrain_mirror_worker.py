"""Tests for the one-shot, HomeHub-gated gBrain mirror worker."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import gbrain_mirror_worker as worker  # noqa: E402
import gbrain_publisher as gp  # noqa: E402


class MirrorWorkerTests(unittest.TestCase):
    def test_status_hides_local_knowledge_root(self):
        with tempfile.TemporaryDirectory() as directory:
            gp.enqueue_mirror(
                state_root=directory, index_job_id="job-1", project_id="demo",
                knowledge_root="/private/source/project", version="v1",
                source_epoch="source-1", grant_epoch="grant-1")
            result = worker.queue_status(directory)
            self.assertEqual(result["counts"], {"queued": 1})
            serialized = json.dumps(result)
            self.assertNotIn("knowledgeRoot", serialized)
            self.assertNotIn("/private/source/project", serialized)

    def test_run_once_requires_homehub_context_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            gp.enqueue_mirror(
                state_root=directory, index_job_id="job-1", project_id="demo",
                knowledge_root="/private/source/project", version="v1",
                source_epoch="source-1", grant_epoch="grant-1")
            with patch.object(worker, "load_context", return_value=None):
                result = worker.run_once(
                    state_root=directory, base_url="http://127.0.0.1:1",
                    creds=None, access_context=None)
            self.assertEqual(result["reason"], "homehub_access_context_unavailable")
            self.assertEqual(result["scheduled"], 0)
            self.assertEqual(gp.MirrorJobStore(directory).list()[0]["phase"], "queued")


if __name__ == "__main__":
    unittest.main()
