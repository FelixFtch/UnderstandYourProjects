#!/usr/bin/env python3
"""Offline tests for gbrain_mirror_requeue (failed-queue governance).

All state is a temporary MirrorJobStore; the ledger and access context
are plain dicts (the live HTTP/URL transports are thin wrappers around
the pure classifier under test).  English-only by owner ruling.

Run from services/indexer:

    python3 -m pytest tests/test_gbrain_mirror_requeue.py -q
    # or: python3 -m unittest tests.test_gbrain_mirror_requeue
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gbrain_publisher import MirrorJobStore  # noqa: E402
import gbrain_mirror_requeue as rq  # noqa: E402


def _ledger(epoch="90", sources=None):
    return {"jarvis-homehub": {
        "epoch": epoch,
        "sources": set(sources or ["mac-connector",
                                    "connector:jarvis-homehub"]),
        "expires_at": "2099-01-01T00:00:00Z"}}


def _context(projects=("jarvis-homehub",)):
    return {"principalId": "felix", "projectScopes": list(projects),
            "sourceScopes": ["*"], "grantEpoch": "90"}


def _rec(store, mid, *, project="jarvis-homehub", version="v1",
         epoch="90", source="mac-connector", phase="failed",
         last_error="TimeoutError: timed out", attempts=3,
         updated="2026-10-19T10:00:00Z", **extra):
    record = {
        "schemaVersion": "1.0", "mirrorJobId": mid,
        "indexJobId": "idx-" + mid, "projectId": project,
        "sourceId": source, "knowledgeRoot": "/tmp/x",
        "knowledgeVersion": version, "sourceEpoch": version,
        "grantEpoch": epoch, "publishedAt": updated, "phase": phase,
        "attempts": attempts, "maxAttempts": 3, "nextAttemptAt": None,
        "lastError": last_error, "createdAt": updated,
        "updatedAt": updated, "events": 3,
    }
    record.update(extra)
    if store is not None:
        path = store.directory / ("%s.json" % mid)
        store._write_atomic(path, record)
    return record


class ClassifyTests(unittest.TestCase):

    def test_transport_failure_on_current_state_is_retryable(self):
        store_rows = [_rec(None, "m1")]
        rows = rq.classify_failed_jobs(store_rows, _ledger(), _context())
        self.assertEqual(rows[0]["klass"], "retryable")

    def test_old_epoch_is_terminal_expired_never_retryable(self):
        # E-epoch 68 vs live 90: the ADR class - never back to queued.
        rows = rq.classify_failed_jobs(
            [_rec(None, "m1", epoch="68")], _ledger(), _context())
        self.assertEqual(rows[0]["klass"], "terminal_expired")
        self.assertIn("active epoch", rows[0]["reason"])

    def test_no_active_grant_is_policy_blocked(self):
        rows = rq.classify_failed_jobs([_rec(None, "m1")], {}, _context())
        self.assertEqual(rows[0]["klass"], "policy_blocked")

    def test_project_out_of_context_is_policy_blocked(self):
        rows = rq.classify_failed_jobs(
            [_rec(None, "m1")], _ledger(), _context(projects=("other",)))
        self.assertEqual(rows[0]["klass"], "policy_blocked")

    def test_source_dropped_from_grant_scope_is_policy_blocked(self):
        rows = rq.classify_failed_jobs(
            [_rec(None, "m1", source="old-connector")], _ledger(), _context())
        self.assertEqual(rows[0]["klass"], "policy_blocked")
        self.assertIn("source scope", rows[0]["reason"])

    def test_older_version_is_superseded(self):
        records = [
            _rec(None, "m-new", version="v2", updated="2026-10-19T12:00:00Z",
                 phase="succeeded"),
            _rec(None, "m-old", version="v1", updated="2026-10-19T10:00:00Z"),
        ]
        rows = {r["mirrorJobId"]: r for r in
                rq.classify_failed_jobs(records, _ledger(), _context())}
        self.assertEqual(rows["m-old"]["klass"], "superseded")

    def test_same_version_epoch_already_succeeded_is_superseded(self):
        records = [
            _rec(None, "m-ok", version="v1", phase="succeeded",
                 updated="2026-10-19T11:00:00Z"),
            _rec(None, "m-fail", version="v1",
                 updated="2026-10-19T10:00:00Z"),
        ]
        rows = {r["mirrorJobId"]: r for r in
                rq.classify_failed_jobs(records, _ledger(), _context())}
        self.assertEqual(rows["m-fail"]["klass"], "superseded")
        self.assertIn("already mirrored", rows["m-fail"]["reason"])

    def test_live_queued_job_covering_same_target_is_superseded(self):
        records = [
            _rec(None, "m-live", version="v1", phase="queued",
                 updated="2026-10-19T11:00:00Z"),
            _rec(None, "m-fail", version="v1",
                 updated="2026-10-19T10:00:00Z"),
        ]
        rows = {r["mirrorJobId"]: r for r in
                rq.classify_failed_jobs(records, _ledger(), _context())}
        self.assertEqual(rows["m-fail"]["klass"], "superseded")

    def test_duplicate_in_batch_keeps_only_the_newest(self):
        records = [
            _rec(None, "m-dup-a", updated="2026-10-19T12:00:00Z"),
            _rec(None, "m-dup-b", updated="2026-10-19T10:00:00Z"),
        ]
        rows = {r["mirrorJobId"]: r for r in
                rq.classify_failed_jobs(records, _ledger(), _context())}
        self.assertEqual(rows["m-dup-a"]["klass"], "retryable")
        self.assertEqual(rows["m-dup-b"]["klass"], "superseded")
        self.assertIn("duplicate", rows["m-dup-b"]["reason"])

    def test_capacity_rejection_is_retryable_but_bounded(self):
        records = [_rec(None, "m-cap",
                        last_error="GbrainRejectedError: put_page rejected "
                        "for project_knowledge/jarvis-homehub/90/x: "
                        "queue_capacity")]
        rows = rq.classify_failed_jobs(records, _ledger(), _context())
        self.assertEqual(rows[0]["klass"], "retryable")
        # ...but a job that already used its operator requeue is terminal.
        records[0]["operatorRequeues"] = 1
        rows = rq.classify_failed_jobs(records, _ledger(), _context())
        self.assertEqual(rows[0]["klass"], "permanent_failed")

    def test_configuration_error_is_not_retryable(self):
        rows = rq.classify_failed_jobs(
            [_rec(None, "m-cfg", last_error="GbrainPublishError: live "
              "publish requires --url/UYP_GBRAIN_URL")],
            _ledger(), _context())
        self.assertEqual(rows[0]["klass"], "configuration_error")

    def test_unknown_error_is_permanent_failed(self):
        rows = rq.classify_failed_jobs(
            [_rec(None, "m-x", last_error="SomethingNewError: wat")],
            _ledger(), _context())
        self.assertEqual(rows[0]["klass"], "permanent_failed")

    def test_non_failed_phases_are_ignored(self):
        rows = rq.classify_failed_jobs(
            [_rec(None, "m-q", phase="queued"),
             _rec(None, "m-t", phase="terminal_expired")],
            _ledger(), _context())
        self.assertEqual(rows, [])


class ExecuteRollbackTests(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="mirror-requeue-tests-")
        self.store = MirrorJobStore(self.tmp)

    def test_dry_run_core_writes_nothing(self):
        _rec(self.store, "m1")
        records = self.store.list()
        rows = rq.classify_failed_jobs(records, _ledger(), _context())
        # classify is pure: no file changed, no events bumped
        after = self.store.get("m1")
        self.assertEqual(after["phase"], "failed")
        self.assertEqual(after["events"], 3)
        self.assertTrue(rows)

    def test_execute_requeues_only_retryable_and_keeps_audit(self):
        _rec(self.store, "m-ok")                        # retryable
        _rec(self.store, "m-old-epoch", epoch="68")     # terminal_expired
        rows = rq.classify_failed_jobs(self.store.list(), _ledger(),
                                       _context())
        manifest = rq.execute(self.tmp, rows, max_requeue=10,
                              store=self.store)
        self.assertEqual(len(manifest["jobs"]), 1)
        requeued = self.store.get("m-ok")
        self.assertEqual(requeued["phase"], "queued")
        self.assertEqual(requeued["attempts"], 0)
        self.assertEqual(requeued["operatorRequeues"], 1)
        self.assertEqual(requeued["requeuedBy"], "operator")
        # audit preserved: lastError kept, events counter advanced
        self.assertIn("TimeoutError", requeued["lastError"])
        self.assertEqual(requeued["events"], 4)
        # the old-epoch job was NOT touched
        stale = self.store.get("m-old-epoch")
        self.assertEqual(stale["phase"], "failed")
        self.assertNotIn("operatorRequeues", stale)

    def test_max_requeue_caps_the_batch(self):
        # One project can hold at most ONE retryable job (the newest
        # version, deduped); a capped batch therefore needs several
        # projects, each with its own current-version failure.
        projects = ["proj-%d" % i for i in range(5)]
        ledger = {p: {"epoch": "9", "sources": {"mac-connector"},
                      "expires_at": "2099-01-01T00:00:00Z"}
                  for p in projects}
        for i, project in enumerate(projects):
            _rec(self.store, "m-%d" % i, project=project,
                 epoch="9", updated="2026-10-19T1%d:00:00Z" % i)
        rows = rq.classify_failed_jobs(self.store.list(), ledger,
                                       _context(projects=projects))
        self.assertEqual(sum(1 for r in rows if r["klass"] == "retryable"), 5)
        manifest = rq.execute(self.tmp, rows, max_requeue=2, store=self.store)
        self.assertEqual(len(manifest["jobs"]), 2)

    def test_rollback_restores_prior_state(self):
        _rec(self.store, "m1")
        rows = rq.classify_failed_jobs(self.store.list(), _ledger(),
                                       _context())
        manifest = rq.execute(self.tmp, rows, max_requeue=5,
                              store=self.store)
        result = rq.rollback(self.tmp, manifest["manifestPath"],
                             store=self.store)
        self.assertEqual(result["restored"], ["m1"])
        back = self.store.get("m1")
        self.assertEqual(back["phase"], "failed")
        self.assertEqual(back["attempts"], 3)
        self.assertIn("TimeoutError", back["lastError"])

    def test_rollback_refuses_jobs_the_worker_already_ran(self):
        _rec(self.store, "m1")
        rows = rq.classify_failed_jobs(self.store.list(), _ledger(),
                                       _context())
        manifest = rq.execute(self.tmp, rows, max_requeue=5,
                              store=self.store)
        # the worker succeeds the job before the operator rolls back
        self.store.event("m1", "succeeded", {"lastError": None})
        result = rq.rollback(self.tmp, manifest["manifestPath"],
                             store=self.store)
        self.assertEqual(result["restored"], [])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(self.store.get("m1")["phase"], "succeeded")

    def test_rollback_without_manifest_reports_error(self):
        result = rq.rollback(self.tmp, None, store=self.store)
        self.assertIn("error", result)


class EndToEndDryRunTests(unittest.TestCase):

    def test_cli_dry_run_writes_nothing(self):
        import tempfile
        import shutil
        from unittest.mock import patch
        tmp = tempfile.mkdtemp(prefix="mirror-requeue-cli-")
        try:
            store = MirrorJobStore(tmp)
            _rec(store, "m1")
            before = json.dumps(store.get("m1"), sort_keys=True)
            with patch.object(rq, "load_access_context",
                              return_value=_context()), \
                    patch.object(rq, "active_ledger_grants",
                                 return_value=_ledger()):
                rc = rq.main(["--state-root", tmp, "--json"])
            self.assertEqual(rc, 0)
            after = json.dumps(store.get("m1"), sort_keys=True)
            self.assertEqual(before, after)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cli_fails_closed_without_context(self):
        import tempfile
        import shutil
        from unittest.mock import patch
        tmp = tempfile.mkdtemp(prefix="mirror-requeue-cli-nc-")
        try:
            MirrorJobStore(tmp)
            with patch.object(rq, "load_access_context",
                              return_value=None):
                rc = rq.main(["--state-root", tmp])
            self.assertEqual(rc, 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
