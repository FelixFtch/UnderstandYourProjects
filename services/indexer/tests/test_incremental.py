"""P8 incremental reconcile tests: connector events -> targeted IndexJobs.

The Connector is faked entirely (events + grants fetchers); the job store is
real, so cursor persistence, deterministic job ids, and deferral all run
against the same durable records the timer uses.
"""
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import incremental  # noqa: E402
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


G1_EVENTS = [
    {"id": "e_1", "ts": 1, "grant": "g1", "relpath": "src/a.py", "kind": "modified"},
    {"id": "e_2", "ts": 2, "grant": "g1", "relpath": "src/new.py", "kind": "created"},
    {"id": "e_3", "ts": 3, "grant": "g1", "relpath": "src/gone.py", "kind": "deleted"},
    {"id": "e_4", "ts": 4, "grant": "g1", "relpath": "src/b.py", "kind": "modified"},
    {"id": "e_5", "ts": 5, "grant": "g1", "relpath": "src/b.py", "kind": "deleted"},
]


class GroupChangesTests(unittest.TestCase):
    def test_per_grant_buckets_with_last_kind_wins(self):
        buckets = incremental.group_changes(G1_EVENTS, {})
        self.assertEqual(sorted(buckets), ["g1"])
        bucket = buckets["g1"]
        # src/b.py was modified then deleted: a delete, not a change
        self.assertEqual(bucket["changed"], ["src/a.py", "src/new.py"])
        self.assertEqual(bucket["deleted"], 2)  # src/gone.py + src/b.py
        self.assertEqual(bucket["lastEventId"], 5)

    def test_cursors_filter_already_consumed_events(self):
        cursors = {"g1": "e_3", "g2": "e_9"}
        events = G1_EVENTS + [{"id": "e_7", "ts": 7, "grant": "g2", "relpath": "x.py", "kind": "created"}]
        buckets = incremental.group_changes(events, cursors)
        # g1's cursor (e_3) leaves only e_4/e_5 (src/b.py modified then
        # deleted -> a delete); g2's cursor (e_9) is ahead of its only
        # event, so no bucket is created for it at all
        self.assertEqual(sorted(buckets), ["g1"])
        self.assertEqual(buckets["g1"]["lastEventId"], 5)
        self.assertEqual(buckets["g1"]["changed"], [])
        self.assertEqual(buckets["g1"]["deleted"], 1)

    def test_unparseable_ids_and_malformed_events_are_ignored(self):
        events = [
            {"id": "junk", "ts": 1, "grant": "g1", "relpath": "a.py", "kind": "modified"},
            {"id": "e_2", "ts": 2, "grant": "", "relpath": "a.py", "kind": "modified"},
            {"id": "e_3", "ts": 3, "grant": "g1", "relpath": "", "kind": "modified"},
            "not-a-dict",
            {"id": "e_5", "ts": 5, "grant": "g1", "relpath": "a.py", "kind": "modified"},
        ]
        buckets = incremental.group_changes(events, {})
        self.assertEqual(buckets, {"g1": {"lastEventId": 5, "changed": ["a.py"], "deleted": 0}})

    def test_parse_event_id_is_fail_closed(self):
        self.assertEqual(incremental.parse_event_id("e_42"), 42)
        self.assertEqual(incremental.parse_event_id("42"), 42)
        self.assertEqual(incremental.parse_event_id(None), 0)
        self.assertEqual(incremental.parse_event_id("nope"), 0)


class ReconcileTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = index_job.IndexJobStore(self.root / "state")
        self.token = self.root / "token"
        self.token.write_text("connector-token", encoding="utf-8")
        # a previously indexed project: the incremental mapping target
        self.prior = self.store.create(
            project_id="demo", source_id="connector:demo", grant_id="g1", grant_epoch="g1")
        for phase in ("authorized", "queued", "running", "staged", "published"):
            self.store.event(self.prior["jobId"], phase, {})

    def reconcile(self, events, grants=(("g1", "/Users/x/demo"),), **kwargs):
        return incremental.reconcile_and_enqueue(
            self.store,
            connector_host="http://connector",
            token_file=str(self.token),
            events_fetcher=lambda since: {"events": events},
            grants_fetcher=lambda: [{"id": gid, "path": path, "mode": "ro"} for gid, path in grants],
            **kwargs)

    def cursor(self):
        return incremental.load_cursors(self.store.root)

    def test_changes_create_one_job_with_pinned_changed_files(self):
        summary = self.reconcile(G1_EVENTS)
        self.assertTrue(summary["ok"])
        self.assertEqual(len(summary["enqueued"]), 1)
        self.assertEqual(summary["changed"], {"g1": {"changed": 2, "deleted": 2}})
        entry = summary["enqueued"][0]
        self.assertEqual(entry["grant"], "g1")
        self.assertEqual(entry["changed"], 2)
        self.assertEqual(entry["deleted"], 2)

        job = self.store.get(entry["jobId"])
        self.assertNotEqual(job["jobId"], self.prior["jobId"])
        self.assertEqual(job["phase"], "discovered")
        self.assertEqual(job["projectId"], "demo")
        self.assertEqual(job["sourceId"], "connector:demo")
        self.assertEqual(job["connectorGrantId"], "g1")
        self.assertEqual(job["metadata"]["changed_files"], ["src/a.py", "src/new.py"])
        self.assertEqual(job["metadata"]["changedCount"], 2)
        self.assertEqual(job["metadata"]["deletedCount"], 2)
        self.assertEqual(job["metadata"]["limit"], 0)
        self.assertTrue(job["metadata"]["incremental"])
        # cursor advanced past the consumed wave
        self.assertEqual(self.cursor(), {"g1": "e_5"})

    def test_second_pass_with_no_new_events_creates_nothing(self):
        self.reconcile(G1_EVENTS)
        again = self.reconcile(G1_EVENTS)  # same log, cursors filter it out
        self.assertEqual(again["enqueued"], [])
        self.assertEqual(len(self.store.list()), 2)
        self.assertEqual(self.cursor(), {"g1": "e_5"})

    def test_new_wave_after_cursor_creates_a_new_job(self):
        first = self.reconcile(G1_EVENTS)
        # the first wave's job must resolve before the next wave enqueues
        job_id = first["enqueued"][0]["jobId"]
        for phase in ("authorized", "queued", "running", "staged", "published"):
            self.store.event(job_id, phase, {})
        wave2 = [
            {"id": "e_6", "ts": 6, "grant": "g1", "relpath": "src/a.py", "kind": "modified"},
            {"id": "e_7", "ts": 7, "grant": "g1", "relpath": "src/c.py", "kind": "created"},
        ]
        summary = self.reconcile(G1_EVENTS + wave2)
        self.assertEqual(len(summary["enqueued"]), 1)
        self.assertEqual(summary["enqueued"][0]["changed"], 2)
        self.assertEqual(self.store.get(summary["enqueued"][0]["jobId"])["metadata"]["changed_files"],
                         ["src/a.py", "src/c.py"])
        self.assertEqual(self.cursor(), {"g1": "e_7"})

    def test_replay_after_crash_does_not_duplicate_the_job(self):
        # first pass creates the job but "crashes" before saving the cursor
        def crash(state_root, cursors):
            raise OSError("disk full")

        with patch.object(incremental, "save_cursors", crash):
            with self.assertRaises(OSError):
                self.reconcile(G1_EVENTS)
        created = [job for job in self.store.list() if job.get("metadata", {}).get("incremental")]
        self.assertEqual(len(created), 1)
        self.assertEqual(self.cursor(), {})  # cursor was never saved

        # replay while that job is still pending: deferred, not duplicated
        deferred = self.reconcile(G1_EVENTS)
        self.assertEqual(deferred["enqueued"], [])
        self.assertEqual(deferred["deferred"], [{"grant": "g1"}])
        self.assertEqual(len(self.store.list()), 2)

        # once it resolves, the replay hits the same deterministic job id and
        # finally consumes the events
        for phase in ("authorized", "queued", "running", "staged", "published"):
            self.store.event(created[0]["jobId"], phase, {})
        summary = self.reconcile(G1_EVENTS)
        self.assertEqual(len(summary["enqueued"]), 1)
        self.assertTrue(summary["enqueued"][0]["replayed"])
        self.assertEqual(len(self.store.list()), 2)  # still no duplicate
        self.assertEqual(self.cursor(), {"g1": "e_5"})

    def test_pending_job_defers_and_consumes_after_it_resolves(self):
        # a non-terminal full job for the same grant blocks incremental work
        running = self.store.create(
            project_id="demo", source_id="connector:demo", grant_id="g1", grant_epoch="g1",
            job_id="job-full-scan")
        for phase in ("authorized", "queued", "running"):
            self.store.event(running["jobId"], phase, {})
        self.assertEqual(self.store.get(running["jobId"])["phase"], "running")

        summary = self.reconcile(G1_EVENTS)
        self.assertEqual(summary["enqueued"], [])
        self.assertEqual(summary["deferred"], [{"grant": "g1"}])
        self.assertEqual(self.cursor(), {})  # cursor untouched: retried later

        # the pending job resolves; the same events now enqueue
        self.store.event(running["jobId"], "staged", {})
        self.store.event(running["jobId"], "published", {})
        summary = self.reconcile(G1_EVENTS)
        self.assertEqual(len(summary["enqueued"]), 1)
        self.assertEqual(self.cursor(), {"g1": "e_5"})

    def test_unknown_project_and_inactive_grant_events_are_dropped(self):
        events = G1_EVENTS + [
            {"id": "e_6", "ts": 6, "grant": "g_never_indexed", "relpath": "x.py", "kind": "created"},
            {"id": "e_7", "ts": 7, "grant": "g_revoked", "relpath": "y.py", "kind": "created"},
        ]
        # g_never_indexed is active on the connector but has no prior job;
        # g_revoked is not listed at all
        summary = self.reconcile(events, grants=(("g1", "/Users/x/demo"),
                                                 ("g_never_indexed", "/Users/x/other")))
        reasons = {item["grant"]: item["reason"] for item in summary["dropped"]}
        self.assertEqual(reasons, {"g_never_indexed": "unknown_project",
                                   "g_revoked": "grant_not_active"})
        self.assertEqual(len(summary["enqueued"]), 1)
        self.assertEqual(self.cursor(), {"g1": "e_5",
                                         "g_never_indexed": "e_6",
                                         "g_revoked": "e_7"})

    def test_deletes_only_advance_cursor_without_a_job(self):
        deletes = [
            {"id": "e_1", "ts": 1, "grant": "g1", "relpath": "src/gone.py", "kind": "deleted"},
        ]
        summary = self.reconcile(deletes)
        self.assertEqual(summary["enqueued"], [])
        self.assertEqual(summary["dropped"], [{"grant": "g1", "reason": "deletes_only"}])
        self.assertEqual(self.cursor(), {"g1": "e_1"})
        self.assertEqual(len(self.store.list()), 1)

    def test_fetch_failure_is_fail_closed(self):
        def broken_fetch(since):
            raise urllib.error.URLError("tunnel blip")

        summary = incremental.reconcile_and_enqueue(
            self.store, connector_host="http://connector", token_file=str(self.token),
            events_fetcher=broken_fetch,
            grants_fetcher=lambda: [])
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["error"], "URLError")
        self.assertEqual(summary["enqueued"], [])
        self.assertEqual(self.cursor(), {})  # nothing consumed, nothing invented
        self.assertEqual(len(self.store.list()), 1)

    def test_grants_fetch_failure_is_fail_closed(self):
        summary = incremental.reconcile_and_enqueue(
            self.store, connector_host="http://connector", token_file=str(self.token),
            events_fetcher=lambda since: {"events": G1_EVENTS},
            grants_fetcher=lambda: (_ for _ in ()).throw(urllib.error.HTTPError(
                "http://connector/grants", 401, "Unauthorized", None, None)))
        self.assertFalse(summary["ok"])
        self.assertEqual(self.cursor(), {})
        self.assertEqual(len(self.store.list()), 1)

    def test_bad_response_shapes_fail_closed(self):
        for payload in ({"events": "nope"}, {"no_events": []}, [1, 2, 3], None):
            summary = incremental.reconcile_and_enqueue(
                self.store, connector_host="http://connector", token_file=str(self.token),
                events_fetcher=lambda since, p=payload: p,
                grants_fetcher=lambda: [])
            self.assertFalse(summary["ok"])
        self.assertEqual(self.cursor(), {})
        self.assertEqual(len(self.store.list()), 1)

    def test_default_fetchers_read_the_connector_token(self):
        # the production fetchers are closures over the token file: a missing
        # token must surface as a fail-closed pass, not an unhandled crash
        summary = incremental.reconcile_and_enqueue(
            self.store, connector_host="http://connector",
            token_file=str(self.root / "missing-token"))
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["error"], "FileNotFoundError")

    def test_hostile_grant_id_is_dropped_not_persisted(self):
        # a path-escaping grant id cannot have a prior IndexJob (create
        # validates ids), so it lands in unknown_project and never reaches
        # the job store's path-joining code
        events = [{"id": "e_1", "ts": 1, "grant": "../escape", "relpath": "x.py", "kind": "created"}]
        summary = self.reconcile(events, grants=(("../escape", "/Users/x/demo"),))
        self.assertEqual(summary["dropped"], [{"grant": "../escape", "reason": "unknown_project"}])
        self.assertEqual(len(self.store.list()), 1)


class ReconcileEndToEndTests(unittest.TestCase):
    """Fake connector + real store: events -> job -> worker command."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = index_job.IndexJobStore(self.root / "state")
        self.token = self.root / "token"
        self.token.write_text("connector-token", encoding="utf-8")
        self.prior = self.store.create(
            project_id="demo", source_id="connector:demo", grant_id="g1", grant_epoch="g1")
        for phase in ("authorized", "queued", "running", "staged", "published"):
            self.store.event(self.prior["jobId"], phase, {})

    def test_events_become_a_published_job_targeting_changed_files(self):
        events = [
            {"id": "e_1", "ts": 1, "grant": "g1", "relpath": "src/a.py", "kind": "modified"},
            {"id": "e_2", "ts": 2, "grant": "g1", "relpath": "src/new.py", "kind": "created"},
            {"id": "e_3", "ts": 3, "grant": "g1", "relpath": "src/gone.py", "kind": "deleted"},
            {"id": "e_4", "ts": 4, "grant": "g_other", "relpath": "x.py", "kind": "created"},
        ]
        summary = incremental.reconcile_and_enqueue(
            self.store, connector_host="http://connector", token_file=str(self.token),
            events_fetcher=lambda since: {"events": events},
            grants_fetcher=lambda: [{"id": "g1", "path": "/Users/x/demo", "mode": "ro"}])
        self.assertTrue(summary["ok"])
        self.assertEqual(len(summary["enqueued"]), 1)
        job_id = summary["enqueued"][0]["jobId"]

        captured = []

        def fake_runner(command, env):
            captured.append(list(command))
            candidate = Path(env["UYP_OUTPUT_ROOT"]) / "demo"
            candidate.mkdir(parents=True)
            (candidate / "src__a.py.knowledge.json").write_text(
                json.dumps({"file": "src/a.py", "version": {"mtime": 1}}), encoding="utf-8")

        def fake_ua(**kwargs):
            graph_dir = Path(kwargs["state_root"]) / "demo" / "ua"
            graph_dir.mkdir(parents=True)
            (graph_dir / "knowledge-graph.json").write_text("{}", encoding="utf-8")
            return {"stagedFiles": 1, "nodes": 0, "edges": 0}

        with patch.object(index_job, "connector_call",
                          return_value={"root_name": "demo", "total": 3, "source_epoch": "e9"}):
            result = index_job.run_pending(
                self.store, context=access_context(), connector_host="http://connector",
                token_file=str(self.token), ua_root=str(self.root / "ua"),
                output_root=str(self.root / "output"),
                runner=fake_runner, ua_runner=fake_ua, max_jobs=5)

        self.assertEqual(result["scheduled"], 1)
        self.assertEqual(self.store.get(job_id)["phase"], "published")

        command = captured[0]
        self.assertIn("--changes-file", command)
        changes_path = Path(command[command.index("--changes-file") + 1])
        # the deleted and unknown-grant paths never reach the worker
        self.assertEqual(json.loads(changes_path.read_text(encoding="utf-8")),
                         ["src/a.py", "src/new.py"])
        # the full-scan prior job is terminal: it must not have been re-run
        self.assertEqual(len(captured), 1)


if __name__ == "__main__":
    unittest.main()
