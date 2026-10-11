import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import index_job  # noqa: E402
import connector_registry  # noqa: E402


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

    def worker_kwargs(self, **overrides):
        kwargs = {
            "context": access_context(),
            "connector_host": "http://connector",
            "token_file": str(self.token),
            "ua_root": str(self.root / "ua"),
            "output_root": str(self.root / "output"),
        }
        kwargs.update(overrides)
        return kwargs

    def refuse_to_run(self, command, env):
        # AssertionError is deliberately outside run_job's failure tuple, so
        # an unexpected execution fails the test instead of being recorded.
        raise AssertionError("run_pending must not execute this job")

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

    def test_job_persists_connector_capability_separately(self):
        job = self.make_job()
        self.assertEqual(job["connectorGrantId"], "grant-1")
        self.assertNotIn("grantId", job)

    def test_scheduler_leaves_queue_untouched_without_homehub_context(self):
        job = self.make_job()
        result = index_job.run_pending(
            self.store,
            context=None,
            connector_host="http://connector",
            token_file=str(self.token),
            ua_root=str(self.root / "ua"),
            output_root=str(self.root / "output"),
        )
        self.assertEqual(result["scheduled"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.store.get(job["jobId"])["phase"], "discovered")

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
        registry = connector_registry.load_registry(self.root / "state" / "connectors" / "registry.json")
        self.assertEqual(registry["connectors"][0]["connectorId"], "connector:demo")
        self.assertEqual(registry["connectors"][0]["sourceIds"], ["connector:demo"])
        self.assertEqual(registry["connectors"][0]["manifestState"], "ready")
        self.assertNotIn("grantId", json.dumps(registry))

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

    def test_source_epoch_is_captured_when_manifest_has_none(self):
        # P7 acceptance finding 2: the Connector manifest carries no explicit
        # epoch, so authorization must pin a derived one instead of null.
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

        manifest = {"root_name": "demo", "total": 2, "has_more": False, "files": [
            {"id": "f_a", "relpath": "a.py", "size": 10, "mtime": 100, "kind": "file"},
            {"id": "f_b", "relpath": "b.py", "size": 20, "mtime": 200, "kind": "file"},
        ]}
        with patch.object(index_job, "connector_call", return_value=manifest):
            result = index_job.run_job(
                self.store, job["jobId"], context=access_context(), connector_host="http://connector",
                token_file=str(self.token), ua_root=str(self.root / "ua"), output_root=str(output),
                runner=fake_runner, ua_runner=fake_ua,
            )
        self.assertEqual(result["phase"], "published")
        epoch = index_job.derive_source_epoch(manifest)
        self.assertTrue(epoch)
        self.assertEqual(result["sourceEpoch"], epoch)
        events = read_events(self.store, job["jobId"])
        authorized = next(event for event in events if event["phase"] == "authorized")
        self.assertEqual(authorized["details"]["sourceEpoch"], epoch)
        published = next(event for event in events if event["phase"] == "published")
        self.assertEqual(published["details"]["sourceEpoch"], epoch)
        self.assertEqual(published["details"]["knowledgeVersion"], epoch)
        registry = connector_registry.load_registry(self.root / "state" / "connectors" / "registry.json")
        self.assertEqual(registry["connectors"][0]["sourceEpoch"], epoch)

    def test_captured_epoch_rebases_when_source_drifts(self):
        """2026-10-10 现场活锁修复: 漂移不再 retry_wait(活仓库漂移永续->永续等待),
        而是 rebase 到新 epoch 继续跑(全量=接受时快照, 变更走 P8 增量波)。"""
        first = {"root_name": "demo", "total": 1, "files": [
            {"relpath": "a.py", "size": 10, "mtime": 100},
        ]}
        second = {"root_name": "demo", "total": 1, "files": [
            {"relpath": "a.py", "size": 10, "mtime": 900},
        ]}
        job = self.make_job(source_epoch=index_job.derive_source_epoch(first))
        with patch.object(index_job, "connector_call", return_value=second):
            result = index_job.run_job(
                self.store, job["jobId"], context=access_context(), connector_host="http://connector",
                token_file=str(self.token), ua_root=str(self.root / "ua"), output_root=str(self.root / "output"),
            )
        # rebase 后继续执行(worker 是假的会失败, 但 phase 必须不是 retry_wait,
        # 且 durable 记录的 sourceEpoch 已更新为新值)
        self.assertNotEqual(result["reason"], "source_epoch_changed")
        record = self.store.get(job["jobId"])
        self.assertEqual(str(record.get("sourceEpoch")),
                         str(index_job.derive_source_epoch(second)))

    def test_derive_source_epoch_is_deterministic_and_fail_closed(self):
        a = {"total": 2, "files": [
            {"relpath": "b.py", "size": 2, "mtime": 20},
            {"relpath": "a.py", "size": 1, "mtime": 10},
        ]}
        b = {"total": 2, "files": [
            {"relpath": "a.py", "size": 1, "mtime": 10},
            {"relpath": "b.py", "size": 2, "mtime": 20},
        ]}
        self.assertEqual(index_job.derive_source_epoch(a), index_job.derive_source_epoch(b))
        changed_mtime = {"total": 2, "files": [
            {"relpath": "a.py", "size": 1, "mtime": 11},
            {"relpath": "b.py", "size": 2, "mtime": 20},
        ]}
        self.assertNotEqual(index_job.derive_source_epoch(a), index_job.derive_source_epoch(changed_mtime))
        added_file = {"total": 3, "files": b["files"] + [{"relpath": "c.py", "size": 3, "mtime": 30}]}
        self.assertNotEqual(index_job.derive_source_epoch(a), index_job.derive_source_epoch(added_file))
        self.assertIsNone(index_job.derive_source_epoch({"total": 0, "files": []}))
        self.assertIsNone(index_job.derive_source_epoch({"total": 1, "files": [{"size": 1}]}))

    def test_source_capability_id_may_be_github_style(self):
        record = self.store.create(
            project_id="repo",
            source_id="github:org/repository",
            grant_id="grant-2",
        )
        self.assertEqual(record["sourceId"], "github:org/repository")

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
        # A crashed worker is retryable now: the job waits for a bounded retry
        # instead of ending terminal, while the previous stable version stays
        # queryable either way (publish never ran for the candidate).
        self.assertEqual(result["phase"], "retry_wait")
        self.assertEqual((stable / "stable.json").read_text(encoding="utf-8"), "stable")

    def test_worker_crash_schedules_bounded_retry_with_backoff(self):
        job = self.make_job()

        def crashing_runner(command, env):
            raise RuntimeError("model unavailable")

        with patch.object(index_job, "connector_call", return_value={"root_name": "demo", "total": 3, "source_epoch": "e1"}):
            result = index_job.run_job(self.store, job["jobId"], **self.worker_kwargs(runner=crashing_runner))
        self.assertEqual(result["phase"], "retry_wait")
        self.assertEqual(result["reason"], "worker_command_failed")
        self.assertEqual(result["retryCount"], 1)
        due = datetime.fromisoformat(result["nextAttemptAt"].replace("Z", "+00:00"))
        self.assertGreater(due, datetime.now(timezone.utc))
        self.assertEqual(
            [event["phase"] for event in read_events(self.store, job["jobId"])],
            ["discovered", "authorized", "queued", "running", "failed", "retry_wait"])

    def test_connector_manifest_and_transport_failures_are_retryable(self):
        missing = self.make_job()
        with patch.object(index_job, "connector_call",
                          side_effect=urllib.error.HTTPError("http://connector/manifest", 404, "Not Found", None, None)):
            result = index_job.run_job(self.store, missing["jobId"], **self.worker_kwargs())
        self.assertEqual(result["phase"], "retry_wait")
        self.assertEqual(result["reason"], "connector_manifest_not_found")
        self.assertEqual(result["retryCount"], 1)
        self.assertIn("nextAttemptAt", result)

        unreachable = self.make_job()
        with patch.object(index_job, "connector_call", side_effect=urllib.error.URLError("tunnel blip")):
            result = index_job.run_job(self.store, unreachable["jobId"], **self.worker_kwargs())
        self.assertEqual(result["phase"], "retry_wait")
        self.assertEqual(result["reason"], "connector_unavailable")
        self.assertEqual(result["retryCount"], 1)

    def test_authorization_failures_stay_terminal(self):
        mismatch = self.make_job()
        with patch.object(index_job, "connector_call", return_value={"root_name": "other", "total": 1}):
            result = index_job.run_job(self.store, mismatch["jobId"], **self.worker_kwargs())
        self.assertEqual(result["phase"], "failed")
        self.assertEqual(result["reason"], "manifest_project_mismatch")
        self.assertNotIn("retryCount", result)
        self.assertNotIn("nextAttemptAt", result)

        dead_grant = self.make_job()
        with patch.object(index_job, "connector_call",
                          side_effect=urllib.error.HTTPError("http://connector/manifest", 401, "Unauthorized", None, None)):
            result = index_job.run_job(self.store, dead_grant["jobId"], **self.worker_kwargs())
        self.assertEqual(result["phase"], "revoked")

        drifted_epoch = self.make_job()
        with patch.object(index_job, "connector_call", return_value={"root_name": "demo", "total": 1, "source_epoch": "e1"}):
            result = index_job.run_job(
                self.store, drifted_epoch["jobId"], **self.worker_kwargs(context=access_context(epoch="g2")))
        self.assertEqual(result["phase"], "revoked")

        # none of the terminal jobs above may be requeued by the scheduler
        summary = index_job.run_pending(self.store, **self.worker_kwargs(runner=self.refuse_to_run))
        self.assertEqual(summary["recovered"], 0)
        self.assertEqual(summary["scheduled"], 0)
        self.assertEqual(self.store.get(mismatch["jobId"])["phase"], "failed")
        self.assertEqual(self.store.get(dead_grant["jobId"])["phase"], "revoked")
        self.assertEqual(self.store.get(drifted_epoch["jobId"])["phase"], "revoked")

    def test_publish_failure_stays_terminal_and_keeps_stable_output(self):
        job = self.make_job()
        stable = self.root / "output" / "demo"
        stable.mkdir(parents=True)
        (stable / "stable.json").write_text("stable", encoding="utf-8")

        def fake_runner(command, env):
            candidate = Path(env["UYP_OUTPUT_ROOT"]) / "demo"
            candidate.mkdir(parents=True)
            (candidate / "main.py.knowledge.json").write_text(json.dumps({"file": "main.py"}), encoding="utf-8")

        def lazy_ua(**kwargs):
            # reports success but never writes the staged UA graph, so the
            # second half of publish fails and the first half rolls back
            return {"stagedFiles": 1, "nodes": 0, "edges": 0}

        with patch.object(index_job, "connector_call", return_value={"root_name": "demo", "total": 1, "source_epoch": "e1"}):
            result = index_job.run_job(
                self.store, job["jobId"], **self.worker_kwargs(runner=fake_runner, ua_runner=lazy_ua))
        self.assertEqual(result["phase"], "failed")
        self.assertEqual(result["reason"], "publish_failed")
        self.assertNotIn("retryCount", result)
        self.assertEqual((stable / "stable.json").read_text(encoding="utf-8"), "stable")

        # a publish failure is deliberately outside the retryable set
        summary = index_job.run_pending(self.store, **self.worker_kwargs(runner=self.refuse_to_run))
        self.assertEqual(summary["recovered"], 0)
        self.assertEqual(self.store.get(job["jobId"])["phase"], "failed")

    def test_run_pending_resumes_retry_wait_only_after_backoff(self):
        job = self.make_job()

        def crashing_runner(command, env):
            raise RuntimeError("worker killed")

        with patch.object(index_job, "connector_call", return_value={"root_name": "demo", "total": 1, "source_epoch": "e1"}):
            failed = index_job.run_job(self.store, job["jobId"], **self.worker_kwargs(runner=crashing_runner))
        self.assertEqual(failed["phase"], "retry_wait")
        due = datetime.fromisoformat(failed["nextAttemptAt"].replace("Z", "+00:00"))

        # before the backoff elapses the timer must leave the job alone
        early = index_job.run_pending(
            self.store, **self.worker_kwargs(runner=self.refuse_to_run, now=due - timedelta(seconds=1)))
        self.assertEqual(early["scheduled"], 0)
        self.assertEqual(self.store.get(job["jobId"])["phase"], "retry_wait")

        def fake_runner(command, env):
            candidate = Path(env["UYP_OUTPUT_ROOT"]) / "demo"
            candidate.mkdir(parents=True)
            (candidate / "main.py.knowledge.json").write_text(json.dumps({"file": "main.py"}), encoding="utf-8")

        def fake_ua(**kwargs):
            graph_dir = Path(kwargs["state_root"]) / "demo" / "ua"
            graph_dir.mkdir(parents=True)
            (graph_dir / "knowledge-graph.json").write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
            return {"stagedFiles": 1, "nodes": 0, "edges": 0}

        # once due, run-pending resumes it end to end and records the pickup
        with patch.object(index_job, "connector_call", return_value={"root_name": "demo", "total": 1, "source_epoch": "e1"}):
            late = index_job.run_pending(
                self.store, **self.worker_kwargs(runner=fake_runner, ua_runner=fake_ua, now=due + timedelta(seconds=1)))
        self.assertEqual(late["scheduled"], 1)
        self.assertEqual(self.store.get(job["jobId"])["phase"], "published")
        events = read_events(self.store, job["jobId"])
        resumed = next(event for event in events if event["phase"] == "resumed")
        self.assertEqual(resumed["details"]["reason"], "worker_command_failed")
        self.assertEqual(resumed["details"]["retryCount"], 1)

    def test_retry_budget_exhaustion_escalates_to_permanent_failure(self):
        job = self.make_job()

        def crashing_runner(command, env):
            raise RuntimeError("model unavailable")

        manifest = {"root_name": "demo", "total": 1, "source_epoch": "e1"}
        with patch.object(index_job, "connector_call", return_value=manifest):
            for expected in (1, 2, 3):
                result = index_job.run_job(self.store, job["jobId"], **self.worker_kwargs(runner=crashing_runner))
                self.assertEqual(result["phase"], "retry_wait")
                self.assertEqual(result["retryCount"], expected)
            # the fourth failure has no budget left: permanent, terminal failed
            final = index_job.run_job(self.store, job["jobId"], **self.worker_kwargs(runner=crashing_runner))
        self.assertEqual(final["phase"], "failed")
        self.assertEqual(final["reason"], "worker_command_failed")
        terminal = [event for event in read_events(self.store, job["jobId"]) if event["phase"] == "failed"][-1]
        self.assertTrue(terminal["details"]["retriesExhausted"])
        self.assertEqual(terminal["details"]["retryCount"], 3)

        # the scheduler must not resurrect an exhausted job
        summary = index_job.run_pending(self.store, **self.worker_kwargs(runner=self.refuse_to_run))
        self.assertEqual(summary["recovered"], 0)
        self.assertEqual(summary["scheduled"], 0)
        self.assertEqual(self.store.get(job["jobId"])["phase"], "failed")

    def test_resume_reuses_staged_output_instead_of_restarting(self):
        job = self.make_job()
        stage_root = self.root / "state" / "index-jobs" / job["jobId"] / "staged"

        def crashing_runner(command, env):
            # the worker writes two items incrementally, then dies mid-run
            candidate = Path(env["UYP_OUTPUT_ROOT"]) / "demo"
            candidate.mkdir(parents=True, exist_ok=True)
            (candidate / "a.py.knowledge.json").write_text(
                json.dumps({"file": "a.py", "version": {"mtime": 1}}), encoding="utf-8")
            (candidate / "b.py.knowledge.json").write_text(
                json.dumps({"file": "b.py", "version": {"mtime": 2}}), encoding="utf-8")
            raise RuntimeError("worker killed mid-run")

        manifest = {"root_name": "demo", "total": 3, "source_epoch": "e1"}
        with patch.object(index_job, "connector_call", return_value=manifest):
            failed = index_job.run_job(self.store, job["jobId"], **self.worker_kwargs(runner=crashing_runner))
        self.assertEqual(failed["phase"], "retry_wait")
        # durable progress reports what survived the crash
        self.assertEqual(failed["progress"]["processed"], 2)
        self.assertEqual(len(list((stage_root / "output" / "demo").glob("*.knowledge.json"))), 2)
        # the previous candidate is reused, not archived away
        self.assertEqual(list(stage_root.parent.glob("staged-previous-*")), [])
        first_item = (stage_root / "output" / "demo" / "a.py.knowledge.json").read_text(encoding="utf-8")

        observed = []

        def resuming_runner(command, env):
            # index_project.py skips same-version staged items; the resumed
            # worker must see the previous attempt's two items
            candidate = Path(env["UYP_OUTPUT_ROOT"]) / "demo"
            observed.append(sorted(path.name for path in candidate.glob("*.knowledge.json")))
            (candidate / "c.py.knowledge.json").write_text(
                json.dumps({"file": "c.py", "version": {"mtime": 3}}), encoding="utf-8")

        def fake_ua(**kwargs):
            graph_dir = Path(kwargs["state_root"]) / "demo" / "ua"
            graph_dir.mkdir(parents=True, exist_ok=True)
            (graph_dir / "knowledge-graph.json").write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
            return {"stagedFiles": 3, "nodes": 0, "edges": 0}

        due = datetime.fromisoformat(failed["nextAttemptAt"].replace("Z", "+00:00"))
        with patch.object(index_job, "connector_call", return_value=manifest):
            resumed = index_job.run_pending(
                self.store, **self.worker_kwargs(runner=resuming_runner, ua_runner=fake_ua, now=due + timedelta(seconds=1)))
        self.assertEqual(resumed["scheduled"], 1)
        # the resumed worker skipped, not restarted: it saw both prior items
        self.assertEqual(observed, [["a.py.knowledge.json", "b.py.knowledge.json"]])
        self.assertEqual(self.store.get(job["jobId"])["phase"], "published")
        # prior items survived the resume untouched and all three published
        self.assertEqual(
            (stage_root / "output" / "demo" / "a.py.knowledge.json").read_text(encoding="utf-8"),
            first_item)
        published = sorted(path.name for path in (self.root / "output" / "demo").glob("*.knowledge.json"))
        self.assertEqual(published, ["a.py.knowledge.json", "b.py.knowledge.json", "c.py.knowledge.json"])
        running = [event for event in read_events(self.store, job["jobId"]) if event["phase"] == "running"][-1]
        self.assertEqual(running["details"]["resumedFromStagedItems"], 2)

    def test_run_pending_requeues_retryable_terminal_jobs_once(self):
        # a job that crashed before retry accounting existed: terminal failed
        job = self.make_job()
        for phase in ("authorized", "queued", "running"):
            self.store.event(job["jobId"], phase, {})
        self.store.event(job["jobId"], "failed", {"reason": "worker_command_failed"})
        self.assertNotIn("retryCount", self.store.get(job["jobId"]))

        # the scheduler requeues it into retry_wait with the same budget and
        # backoff; it does not execute it in the same pass
        result = index_job.run_pending(self.store, **self.worker_kwargs(runner=self.refuse_to_run))
        self.assertEqual(result["recovered"], 1)
        self.assertEqual(result["scheduled"], 0)
        record = self.store.get(job["jobId"])
        self.assertEqual(record["phase"], "retry_wait")
        self.assertEqual(record["retryCount"], 1)
        self.assertIn("nextAttemptAt", record)

        # the requeued job is no longer terminal: a second pass must neither
        # inflate the retry count nor schedule it before the backoff elapses
        again = index_job.run_pending(self.store, **self.worker_kwargs(runner=self.refuse_to_run))
        self.assertEqual(again["recovered"], 0)
        self.assertEqual(again["scheduled"], 0)
        self.assertEqual(self.store.get(job["jobId"])["retryCount"], 1)

    # ---- escape hatch: any non-terminal phase -> discovered ---------------

    def test_any_nonterminal_phase_may_reset_to_discovered(self):
        # Root-cause fix (2026-10-10): the state machine must never strand a
        # job.  "discovered" re-validates manifest, scope and both epochs from
        # scratch, so it is admissible from every phase that is not a
        # recorded answer.  Field evidence: three running->authorized
        # transition errors in one night, each needing a manual kick script.
        paths = {
            "authorized": ("authorized",),
            "queued": ("authorized", "queued"),
            "running": ("authorized", "queued", "running"),
            "staged": ("authorized", "queued", "running", "staged"),
            "retry_wait": ("retry_wait",),
        }
        for phase, path in paths.items():
            job = self.make_job()
            for step in path:
                self.store.event(job["jobId"], step, {})
            self.store.event(job["jobId"], "discovered", {"reason": "manual_reset"})
            record = self.store.get(job["jobId"])
            self.assertEqual(record["phase"], "discovered", phase)
            self.assertEqual(record["reason"], "manual_reset", phase)

    def test_terminal_phases_stay_terminal_for_discovered(self):
        # published/revoked/blocked/offline/failed are answers, not stranded
        # work; resetting them would bypass the retry budget and revocation.
        terminals = {
            "published": ("authorized", "queued", "running", "staged", "published"),
            "revoked": ("revoked",),
            "blocked": ("blocked",),
            "offline": ("offline",),
            "failed": ("failed",),
        }
        for phase, path in terminals.items():
            job = self.make_job()
            for step in path:
                self.store.event(job["jobId"], step, {})
            with self.assertRaises(index_job.JobError):
                self.store.event(job["jobId"], "discovered", {"reason": "must_refuse"})
            self.assertEqual(self.store.get(job["jobId"])["phase"], phase)

    def test_recover_stranded_cli_pushes_running_jobs_to_discovered(self):
        # The CLI shipped with the running->discovered edge called
        # store.list_jobs(), which does not exist -- it crashed with
        # AttributeError instead of recovering anything.
        job = self.make_job()
        for step in ("authorized", "queued", "running"):
            self.store.event(job["jobId"], step, {})
        argv = ["index_job.py", "--state-root", str(self.root / "state"),
                "--output-root", str(self.root / "output"), "--ua-root", str(self.root / "ua"),
                "recover-stranded"]
        with patch.object(sys, "argv", argv), patch("builtins.print") as printed:
            index_job.main()
        self.assertEqual(self.store.get(job["jobId"])["phase"], "discovered")
        self.assertEqual(
            json.loads(printed.call_args[0][0]), {"recovered": 1})

    # ---- P8 incremental: changed_files -> worker command ----

    def publishing_runner(self, captured):
        def fake_runner(command, env):
            captured.append(list(command))
            candidate = Path(env["UYP_OUTPUT_ROOT"]) / "demo"
            candidate.mkdir(parents=True, exist_ok=True)
            (candidate / "a.py.knowledge.json").write_text(
                json.dumps({"file": "a.py"}), encoding="utf-8")
        return fake_runner

    @staticmethod
    def fake_ua(**kwargs):
        graph_dir = Path(kwargs["state_root"]) / "demo" / "ua"
        graph_dir.mkdir(parents=True, exist_ok=True)
        (graph_dir / "knowledge-graph.json").write_text("{}", encoding="utf-8")
        return {"stagedFiles": 1, "nodes": 0, "edges": 0}

    def test_incremental_job_pins_changed_files_for_the_worker(self):
        job = self.store.create(
            project_id="demo", source_id="connector:demo", grant_id="grant-1", grant_epoch="g1",
            metadata={"limit": 0, "changed_files": ["src/b.py", "src/a.py", "src/b.py"]})
        captured = []
        with patch.object(index_job, "connector_call",
                          return_value={"root_name": "demo", "total": 5, "source_epoch": "e1"}):
            result = index_job.run_job(
                self.store, job["jobId"],
                **self.worker_kwargs(runner=self.publishing_runner(captured), ua_runner=self.fake_ua))
        self.assertEqual(result["phase"], "published")
        command = captured[0]
        self.assertIn("--changes-file", command)
        changes_path = Path(command[command.index("--changes-file") + 1])
        # sorted, deduped - the worker sees exactly the reconcile's list
        self.assertEqual(json.loads(changes_path.read_text(encoding="utf-8")), ["src/a.py", "src/b.py"])
        # the changes file lives in the job's own staging root, not argv
        self.assertIn(str(self.root / "state" / "index-jobs" / job["jobId"]), str(changes_path))
        self.assertEqual(command[command.index("--limit") + 1], "0")

    def test_full_job_command_carries_no_changes_file_flag(self):
        job = self.make_job()
        captured = []
        with patch.object(index_job, "connector_call",
                          return_value={"root_name": "demo", "total": 1, "source_epoch": "e1"}):
            result = index_job.run_job(
                self.store, job["jobId"],
                **self.worker_kwargs(runner=self.publishing_runner(captured), ua_runner=self.fake_ua))
        self.assertEqual(result["phase"], "published")
        self.assertNotIn("--changes-file", captured[0])

    def test_run_pending_cli_reconciles_events_before_scheduling(self):
        import incremental

        calls = []

        def fake_reconcile(store, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "enqueued": [], "deferred": [], "dropped": [],
                    "changed": {}, "fetched": 0, "error": None}

        argv = ["index_job.py", "--state-root", str(self.root / "state"),
                "--output-root", str(self.root / "output"), "--ua-root", str(self.root / "ua"),
                "run-pending"]
        with patch.object(index_job, "load_context", return_value=access_context()), \
             patch.object(incremental, "reconcile_and_enqueue", side_effect=fake_reconcile), \
             patch.object(sys, "argv", argv), \
             patch("builtins.print"):
            index_job.main()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["connector_host"], "http://127.0.0.1:7121")
        self.assertIn("token_file", calls[0])

    def test_run_pending_cli_skips_reconcile_without_homehub_context(self):
        import incremental

        calls = []
        argv = ["index_job.py", "--state-root", str(self.root / "state"),
                "--output-root", str(self.root / "output"), "--ua-root", str(self.root / "ua"),
                "run-pending"]
        with patch.object(index_job, "load_context", return_value=None), \
             patch.object(incremental, "reconcile_and_enqueue",
                          side_effect=lambda *a, **k: calls.append(k)), \
             patch.object(sys, "argv", argv), \
             patch("builtins.print"):
            index_job.main()
        self.assertEqual(calls, [])  # no context -> silent skip, like today


def read_events(store, job_id):
    path = store._event_path(job_id)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
