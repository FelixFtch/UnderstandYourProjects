"""P8 connector change-event tests: watcher, event log, and GET /events.

The fsevents path is exercised with an injected fake observer (watchdog is
not a dependency, so the real FSEvents backend is only present on machines
that installed it); the poll path is exercised directly and synchronously.
"""
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import main  # noqa: E402


class FakeEvent:
    def __init__(self, event_type, src_path, dest_path=None, is_directory=False):
        self.event_type = event_type
        self.src_path = src_path
        self.dest_path = dest_path
        self.is_directory = is_directory


class FakeObserver:
    """Records schedules; tests drive handlers the way watchdog would."""

    def __init__(self):
        self.scheduled = []      # (handler, path, recursive)
        self.tokens = []
        self.started = False
        self.stopped = False

    def schedule(self, handler, path, recursive=False):
        token = object()
        self.scheduled.append((handler, path, recursive))
        self.tokens.append(token)
        return token

    def unschedule(self, token):
        if token in self.tokens:
            self.tokens.remove(token)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def join(self, timeout=None):
        pass


class ConnectorEventsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        saved = {name: getattr(main, name) for name in
                 ("STATE_PATH", "SNAPSHOT_PATH", "EVENTS_PATH", "LOG_PATH", "WATCHER")}
        self.addCleanup(lambda: [setattr(main, k, v) for k, v in saved.items()])
        main.STATE_PATH = str(self.root / "connector.json")
        main.SNAPSHOT_PATH = str(self.root / "manifest_snapshot.json")
        main.EVENTS_PATH = str(self.root / "events_log.jsonl")
        main.LOG_PATH = str(self.root / "connector.log")
        main.WATCHER = None
        self.grant_dir = self.root / "grant"
        self.grant_dir.mkdir()
        (self.grant_dir / "a.py").write_text("print(1)\n", encoding="utf-8")
        (self.grant_dir / "c.py").write_text("print(2)\n", encoding="utf-8")
        for i, name in enumerate(("a.py", "c.py")):
            os.utime(self.grant_dir / name, (1000 + i, 1000 + i))
        main.save_state({"device_token": "tok-1", "pairing": None, "grants": [
            {"id": "g1", "path": str(self.grant_dir), "mode": "ro", "granted_at": "2026-10-10T00:00:00"}]})

    def make_watcher(self, **kwargs):
        watcher = main.Watcher(**kwargs)
        self.addCleanup(watcher.stop)
        return watcher

    def log_events(self):
        return main.read_event_log()

    # ---- poll mode ----

    def test_baseline_then_poll_emits_created_modified_deleted(self):
        watcher = self.make_watcher()
        self.assertTrue(watcher.baseline_if_needed())
        self.assertEqual(self.log_events(), [])  # baseline never floods events

        # modify a.py (distinct size+mtime), create b.py, delete c.py
        (self.grant_dir / "a.py").write_text("print(1 + 1)\n", encoding="utf-8")
        os.utime(self.grant_dir / "a.py", (2000, 2000))
        (self.grant_dir / "b.py").write_text("new\n", encoding="utf-8")
        os.utime(self.grant_dir / "b.py", (2000, 2000))
        (self.grant_dir / "c.py").unlink()

        self.assertEqual(watcher.poll_once(), 3)
        by_rel = {e["relpath"]: e for e in self.log_events()}
        self.assertEqual(by_rel["a.py"]["kind"], "modified")
        self.assertEqual(by_rel["b.py"]["kind"], "created")
        self.assertEqual(by_rel["c.py"]["kind"], "deleted")
        for event in self.log_events():
            self.assertEqual(event["grant"], "g1")
            self.assertEqual(set(event), {"id", "ts", "grant", "relpath", "kind"})

        # idempotent: a second pass with no further changes logs nothing
        self.assertEqual(watcher.poll_once(), 0)
        self.assertEqual(len(self.log_events()), 3)

        # snapshot on disk matches the tree (dedupe authority persisted)
        snap = json.loads(Path(main.SNAPSHOT_PATH).read_text(encoding="utf-8"))
        self.assertEqual(sorted(snap["g1"]), ["a.py", "b.py"])

    def test_second_baseline_without_snapshot_does_not_flood(self):
        watcher = self.make_watcher()
        watcher.baseline_if_needed()
        watcher.poll_once()
        # snapshot lost (or corrupt): rebaseline silently, no invented events
        Path(main.SNAPSHOT_PATH).write_text("{not json", encoding="utf-8")
        rebuilt = self.make_watcher()
        self.assertTrue(rebuilt.baseline_if_needed())
        self.assertEqual(self.log_events(), [])

    def test_excluded_and_denied_paths_never_emit_events(self):
        watcher = self.make_watcher()
        watcher.baseline_if_needed()
        (self.grant_dir / ".git").mkdir()
        (self.grant_dir / ".git" / "config").write_text("x", encoding="utf-8")
        (self.grant_dir / ".DS_Store").write_bytes(b"\x00")
        (self.grant_dir / "secrets.pem").write_text("x", encoding="utf-8")
        (self.grant_dir / "sub" / "node_modules").mkdir(parents=True)
        (self.grant_dir / "sub" / "node_modules" / "pkg.js").write_text("x", encoding="utf-8")
        self.assertEqual(watcher.poll_once(), 0)
        self.assertEqual(self.log_events(), [])

        # the fsevents dispatch path applies the same exclusions
        (self.grant_dir / "normal.py").write_text("ok\n", encoding="utf-8")
        os.utime(self.grant_dir / "normal.py", (9000, 9000))
        watcher.record_change("g1", "normal.py", "created")
        watcher.on_fs_event("g1", FakeEvent("created", str(self.grant_dir / ".git" / "hook")))
        watcher.on_fs_event("g1", FakeEvent("created", str(self.grant_dir / ".DS_Store")))
        watcher.on_fs_event("g1", FakeEvent("created", str(self.grant_dir / "id_rsa")))
        self.assertEqual([e["relpath"] for e in self.log_events()], ["normal.py"])

    def test_deleted_hint_for_untracked_path_is_noise(self):
        watcher = self.make_watcher()
        watcher.baseline_if_needed()
        self.assertIsNone(watcher.record_change("g1", "temp-file.py", "deleted"))
        # modified hint for an untracked file resolves honestly to "created"
        (self.grant_dir / "fresh.py").write_text("x", encoding="utf-8")
        os.utime(self.grant_dir / "fresh.py", (3000, 3000))
        event = watcher.record_change("g1", "fresh.py", "modified")
        self.assertEqual((event["kind"], event["relpath"]), ("created", "fresh.py"))
        # duplicate notification with identical stat is deduped
        self.assertIsNone(watcher.record_change("g1", "fresh.py", "modified"))

    def test_snapshot_dedupes_between_fsevents_and_poll(self):
        watcher = self.make_watcher()
        watcher.baseline_if_needed()
        (self.grant_dir / "a.py").write_text("changed\n", encoding="utf-8")
        os.utime(self.grant_dir / "a.py", (4000, 4000))
        watcher.on_fs_event("g1", FakeEvent("modified", str(self.grant_dir / "a.py")))
        self.assertEqual(len(self.log_events()), 1)
        # the poll safety net must not log the same change a second time
        self.assertEqual(watcher.poll_once(), 0)
        self.assertEqual(len(self.log_events()), 1)

    # ---- fsevents mode via injected fake observer ----

    def test_fsevents_mode_schedules_watches_and_maps_events(self):
        observer = FakeObserver()
        watcher = self.make_watcher(mode="fsevents", interval=3600,
                                    observer_factory=lambda: observer)
        watcher.start()
        self.addCleanup(observer.stop)
        self.assertTrue(observer.started)
        self.assertEqual(len(observer.scheduled), 1)
        handler, path, recursive = observer.scheduled[0]
        self.assertEqual(path, str(self.grant_dir))
        self.assertTrue(recursive)
        self.assertEqual(watcher.mode, "fsevents")

        # created -> created; moved -> deleted(old) + created(new)
        (self.grant_dir / "new.py").write_text("n", encoding="utf-8")
        os.utime(self.grant_dir / "new.py", (5000, 5000))
        handler.dispatch(FakeEvent("created", str(self.grant_dir / "new.py")))
        (self.grant_dir / "renamed.py").write_text("r", encoding="utf-8")
        os.utime(self.grant_dir / "renamed.py", (5001, 5001))
        handler.dispatch(FakeEvent("moved", str(self.grant_dir / "new.py"),
                                   dest_path=str(self.grant_dir / "renamed.py")))
        kinds = [(e["relpath"], e["kind"]) for e in self.log_events()]
        self.assertEqual(kinds, [("new.py", "created"),
                                 ("new.py", "deleted"),
                                 ("renamed.py", "created")])
        watcher.stop()
        self.assertTrue(observer.stopped)

    def test_fsevents_watch_set_follows_grant_changes(self):
        observer = FakeObserver()
        watcher = self.make_watcher(mode="fsevents", interval=3600,
                                    observer_factory=lambda: observer)
        watcher.observer = observer
        watcher.baseline_if_needed()
        watcher.poll_once()
        self.assertEqual(len(observer.tokens), 1)
        # grant revoked: next poll pass unschedules its watch
        main.save_state({"device_token": "tok-1", "pairing": None, "grants": []})
        watcher.poll_once()
        self.assertEqual(observer.tokens, [])

    # ---- restart persistence ----

    def test_event_log_and_seq_survive_restart(self):
        first = self.make_watcher()
        first.baseline_if_needed()
        (self.grant_dir / "a.py").write_text("v2\n", encoding="utf-8")
        os.utime(self.grant_dir / "a.py", (6000, 6000))
        first.poll_once()
        self.assertEqual(len(self.log_events()), 1)

        # "restart": a fresh Watcher over the same paths
        second = self.make_watcher()
        self.assertFalse(second.baseline_if_needed())  # snapshot survived
        (self.grant_dir / "b.py").write_text("v1\n", encoding="utf-8")
        os.utime(self.grant_dir / "b.py", (6001, 6001))
        second.poll_once()

        events = self.log_events()
        self.assertEqual([e["id"] for e in events], ["e_1", "e_2"])  # no id reuse
        self.assertEqual([e["relpath"] for e in events], ["a.py", "b.py"])

    def test_watcher_thread_polls_autonomously(self):
        watcher = self.make_watcher(interval=0.2)
        watcher.start()
        self.assertTrue(watcher.thread.is_alive())
        (self.grant_dir / "threaded.py").write_text("t\n", encoding="utf-8")
        os.utime(self.grant_dir / "threaded.py", (9500, 9500))
        deadline = time.time() + 5
        while time.time() < deadline and not any(
                e["relpath"] == "threaded.py" for e in self.log_events()):
            time.sleep(0.05)
        self.assertTrue(any(e["relpath"] == "threaded.py" for e in self.log_events()),
                        "watcher loop never logged the change")
        watcher.stop()
        self.assertIsNone(watcher.thread)

    # ---- HTTP surface ----

    def start_server(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def get(self, path, token="tok-1"):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def record_three_events(self):
        watcher = self.make_watcher()
        watcher.baseline_if_needed()
        (self.grant_dir / "n1.py").write_text("1\n", encoding="utf-8")
        (self.grant_dir / "n2.py").write_text("2\n", encoding="utf-8")
        os.utime(self.grant_dir / "n1.py", (7000, 7000))
        os.utime(self.grant_dir / "n2.py", (7001, 7001))
        (self.grant_dir / "a.py").unlink()
        watcher.poll_once()
        return watcher

    def test_events_endpoint_serves_log_with_since_cursor(self):
        self.record_three_events()
        self.start_server()

        status, body = self.get("/events")
        self.assertEqual(status, 200)
        self.assertEqual([e["id"] for e in body["events"]], ["e_1", "e_2", "e_3"])
        self.assertFalse(body["truncated"])
        self.assertEqual(body["last_event_id"], "e_3")

        status, page = self.get("/events?since=e_1")
        self.assertEqual(status, 200)
        self.assertEqual([e["id"] for e in page["events"]], ["e_2", "e_3"])
        self.assertEqual(page["last_event_id"], "e_3")

        # caught up: nothing new, last_event_id still advances the cursor
        status, caught = self.get("/events?since=e_3")
        self.assertEqual((status, caught["events"], caught["last_event_id"]), (200, [], "e_3"))

    def test_events_endpoint_filters_by_grant_and_validates_input(self):
        self.record_three_events()
        main.save_state({"device_token": "tok-1", "pairing": None, "grants": [
            {"id": "g1", "path": str(self.grant_dir), "mode": "ro", "granted_at": "x"},
            {"id": "g2", "path": str(self.root / "other"), "mode": "ro", "granted_at": "x"}]})
        self.start_server()

        status, body = self.get("/events?grant=g1")
        self.assertEqual(status, 200)
        self.assertEqual(body["grant"], "g1")
        self.assertTrue(all(e["grant"] == "g1" for e in body["events"]))

        self.assertEqual(self.get("/events?grant=g_nope")[0], 404)
        self.assertEqual(self.get("/events?since=abc")[0], 400)
        self.assertEqual(self.get("/events", token=None)[0], 401)   # no token
        self.assertEqual(self.get("/events", token="wrong")[0], 401)

    def test_events_endpoint_pages_when_log_exceeds_cap(self):
        self.record_three_events()
        saved_cap = main.EVENTS_PAGE_CAP
        self.addCleanup(setattr, main, "EVENTS_PAGE_CAP", saved_cap)
        main.EVENTS_PAGE_CAP = 2
        self.start_server()

        status, page1 = self.get("/events")
        self.assertEqual([e["id"] for e in page1["events"]], ["e_1", "e_2"])
        self.assertTrue(page1["truncated"])
        self.assertEqual(page1["last_event_id"], "e_2")

        status, page2 = self.get(f"/events?since={page1['last_event_id']}")
        self.assertEqual([e["id"] for e in page2["events"]], ["e_3"])
        self.assertFalse(page2["truncated"])

    def test_status_reports_watcher_mode_and_last_event_honestly(self):
        self.start_server()
        # no watcher running in this process: off, and no invented last id
        status, body = self.get("/status", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(body["watcher_ok"], "off")
        self.assertIsNone(body["last_event_id"])

        watcher = self.make_watcher(mode="poll", interval=3600)
        watcher.start()
        main.WATCHER = watcher
        (self.grant_dir / "z.py").write_text("z\n", encoding="utf-8")
        os.utime(self.grant_dir / "z.py", (8000, 8000))
        watcher.poll_once()

        status, body = self.get("/status", token=None)
        self.assertEqual(body["watcher_ok"], "poll")
        self.assertEqual(body["last_event_id"], "e_1")

        watcher.stop()
        status, body = self.get("/status", token=None)
        self.assertEqual(body["watcher_ok"], "off")  # thread gone: honest off

    def test_detect_watcher_mode_is_honest_about_availability(self):
        saved_available = main.WATCHDOG_AVAILABLE
        self.addCleanup(setattr, main, "WATCHDOG_AVAILABLE", saved_available)

        main.WATCHDOG_AVAILABLE = True
        self.assertEqual(_mode_with_env(None), "fsevents")
        self.assertEqual(_mode_with_env("poll"), "poll")
        self.assertEqual(_mode_with_env("off"), "off")
        self.assertEqual(_mode_with_env("fsevents"), "fsevents")

        main.WATCHDOG_AVAILABLE = False
        self.assertEqual(_mode_with_env(None), "poll")
        self.assertEqual(_mode_with_env("fsevents"), "poll")  # never fake it
        self.assertEqual(_mode_with_env("off"), "off")


def _mode_with_env(value):
    if value is None:
        os.environ.pop("UYP_WATCHER", None)
    else:
        os.environ["UYP_WATCHER"] = value
    try:
        return main.detect_watcher_mode()
    finally:
        os.environ.pop("UYP_WATCHER", None)


if __name__ == "__main__":
    unittest.main()
