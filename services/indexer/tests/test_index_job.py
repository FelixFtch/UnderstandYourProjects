import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import index_job  # noqa: E402


def access_context(*, epoch="g1", projects=None, sources=None):
    return {
        "principalId": "p1",
        "sessionId": "s1",
        "jarvisNodeId": "jetson-test",
        "projectScopes": projects or ["demo"],
        "sourceScopes": sources or ["connector:demo"],
        "grantEpoch": epoch,
        "policyDigest": "policy-1",
        "expiresAt": "2099-01-01T00:00:00Z",
        "auditId": "audit-1",
        "validation": "active",
    }


class IndexJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = index_job.IndexJobStore(self.root / "state")
        self.token = self.root / "token"
        self.token.write_text("token", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def make_job(self, **kwargs):
        return self.store.create(
            project_id="demo", source_id="connector:demo", grant_id="grant-1",
            grant_epoch="g1", **kwargs,
        )

    def test_missing_access_context_is_blocked_without_running_worker(self):
        self.make_job()
        called = []
        result = index_job.run_job(
            self.store, self.store.list()[0]["jobId"],
            context=None, connector_host="http://connector", token_file=str(self.token),
            ua_root=str(self.root / "ua"), output_root=str(self.root / "output"),
            runner=lambda command, env: called.append(command),
        )
        self.assertEqual(result["phase"], "blocked")
        self.assertEqual(called, [])
        self.assertEqual(result["events"], 2)

    def test_authorized_job_stages_then_publishes_atomically(self):
        job = self.make_job()
        output = self.root / "output"

        def fake_runner(command, env):
            candidate = Path(env["UYP_OUTPUT_ROOT"]) / "demo"
            candidate.mkdir(parents=True)
            (candidate / "main.py.knowledge.json").write_text(json.dumps({"file": "main.py"}), encoding="utf-8")

        def fake_ua(**kwargs):
            graph_dir = Path(kwargs["state_root"]) / "demo" / "ua"
            graph_dir.mkdir(parents=True)
            (graph_dir / "knowledge-graph.json").write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
            return {"stagedFiles": 1, "nodes": 0, "edges": 0}

        with patch.object(index_job, "connector_call", return_value={"root_name": "demo", "total": 1, "source_epoch": "e1"}):
            result = index_job.run_job(
                self.store, job["jobId"], context=access_context(), connector_host="http://connector",
                token_file=str(self.token), ua_root=str(self.root / "ua"), output_root=str(output),
                runner=fake_runner, ua_runner=fake_ua,
            )
        self.assertEqual(result["phase"], "published")
        self.assertEqual([event["phase"] for event in read_events(self.store, job["jobId"])],
                         ["discovered", "authorized", "queued", "running", "staged", "published"])
        self.assertTrue((output / "demo" / "main.py.knowledge.json").exists())
        self.assertTrue((self.root / "state" / "demo" / "ua" / "knowledge-graph.json").exists())

    def test_epoch_mismatch_revokes_before_worker(self):
        job = self.make_job()
        with patch.object(index_job, "connector_call", return_value={"root_name": "demo", "total": 1, "source_epoch": "e1"}):
            result = index_job.run_job(
                self.store, job["jobId"], context=access_context(epoch="g2"), connector_host="http://connector",
                token_file=str(self.token), ua_root=str(self.root / "ua"), output_root=str(self.root / "output"),
            )
        self.assertEqual(result["phase"], "revoked")

    def test_source_epoch_change_waits_for_fresh_manifest(self):
        job = self.make_job(source_epoch="old-source")
        with patch.object(index_job, "connector_call", return_value={"root_name": "demo", "total": 1, "source_epoch": "new-source"}):
            result = index_job.run_job(
                self.store, job["jobId"], context=access_context(), connector_host="http://connector",
                token_file=str(self.token), ua_root=str(self.root / "ua"), output_root=str(self.root / "output"),
            )
        self.assertEqual(result["phase"], "retry_wait")

    def test_revoked_context_is_recorded_as_revoked(self):
        job = self.make_job()
        revoked = access_context()
        revoked["revoked"] = True
        result = index_job.run_job(
            self.store, job["jobId"], context=revoked, connector_host="http://connector",
            token_file=str(self.token), ua_root=str(self.root / "ua"), output_root=str(self.root / "output"),
        )
        self.assertEqual(result["phase"], "revoked")

    def test_failed_candidate_does_not_replace_stable_output(self):
        job = self.make_job()
        stable = self.root / "output" / "demo"
        stable.mkdir(parents=True)
        (stable / "stable.json").write_text("stable", encoding="utf-8")

        def failing_runner(command, env):
            raise RuntimeError("model unavailable")

        with patch.object(index_job, "connector_call", return_value={"root_name": "demo", "total": 1}):
            result = index_job.run_job(
                self.store, job["jobId"], context=access_context(), connector_host="http://connector",
                token_file=str(self.token), ua_root=str(self.root / "ua"), output_root=str(self.root / "output"),
                runner=failing_runner,
            )
        self.assertEqual(result["phase"], "failed")
        self.assertEqual((stable / "stable.json").read_text(encoding="utf-8"), "stable")


def read_events(store, job_id):
    path = store._event_path(job_id)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
