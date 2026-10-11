import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import index_project  # noqa: E402


NORMAL_PY = (
    '"""Module doc."""\n'
    "import json\n"
    "import os\n"
    "\n"
    "def route(intent):\n"
    "    for tool in TOOLS:\n"
    "        if tool.match(intent):\n"
    "            return tool.name\n"
    "    return 'unknown'\n"
)

MINIFIED_JS = (
    "// Version 1.43.5 force-graph\n"
    "!function(t,n){\"object\"==typeof exports&&\"undefined\"!=typeof module?module.exports=n():"
    "1}".ljust(1500, "1") + "\n"
)


class TestRulePretriage(unittest.TestCase):
    def test_binary_and_archive_exts_skip_without_llm(self):
        for rel in ("a.png", "b.JPEG", "c.zip", "d.gguf", "e.woff2", "f.webp", "g.whl"):
            self.assertEqual(index_project.rule_pretriage(rel, 100, "x"), "skip", rel)

    def test_min_js_suffix_skips_despite_js_ext(self):
        self.assertEqual(
            index_project.rule_pretriage("services/page/public/force-graph.min.js", 161000, MINIFIED_JS),
            "skip")

    def test_minification_heuristic_skips_dense_head(self):
        # .js would normally go to Laya; dense single-line head -> rule skip.
        self.assertEqual(index_project.rule_pretriage("vendor/bundle.js", 90000, MINIFIED_JS), "skip")

    def test_normal_code_head_goes_to_laya(self):
        self.assertIsNone(index_project.rule_pretriage("pkg/router.py", 8000, NORMAL_PY))

    def test_docs_go_to_laya(self):
        self.assertIsNone(index_project.rule_pretriage("README.md", 3000, "# title\n"))

    def test_manifest_exts_structure_only(self):
        for rel in ("requirements.txt", "pyproject.toml", "conf.yaml", "x.json"):
            self.assertEqual(index_project.rule_pretriage(rel, 500, "..."), "structure-only", rel)

    def test_empty_file_and_unknown_ext(self):
        self.assertEqual(index_project.rule_pretriage("x.py", 0, ""), "skip")
        self.assertEqual(index_project.rule_pretriage("data.xyz", 10, "??"), "structure-only")


class TestMinifiedHeuristic(unittest.TestCase):
    def test_empty_head_is_not_minified(self):
        self.assertFalse(index_project.minified(""))

    def test_dense_head_is_minified(self):
        self.assertTrue(index_project.minified(MINIFIED_JS))

    def test_normal_head_is_not_minified(self):
        self.assertFalse(index_project.minified(NORMAL_PY))


def _laya_response(choice="deep-analysis", noul=0.9):
    m = MagicMock()
    m.read.return_value = json.dumps(
        {"answers": {"triage": {"choice": choice}, "thinking": {"noul": noul}}}
    ).encode()
    return m


class TestLayaDecide(unittest.TestCase):
    def test_state_is_head600_ellipsis_mid600(self):
        head = "H" * 1500
        mid = "M" * 1500
        with patch("urllib.request.urlopen", return_value=_laya_response()) as up:
            choice, gate = index_project.laya_decide(head, mid)
        self.assertEqual(choice, "deep-analysis")
        self.assertEqual(gate, 0.9)
        sent = json.loads(up.call_args[0][0].data)
        self.assertEqual(
            sent["state"],
            "repository file content:\n" + "H" * 600 + "\n...\n" + "M" * 600)

    def test_mid_optional(self):
        with patch("urllib.request.urlopen", return_value=_laya_response()) as up:
            index_project.laya_decide("short head")
        sent = json.loads(up.call_args[0][0].data)
        self.assertEqual(sent["state"], "repository file content:\nshort head")
        self.assertNotIn("...", sent["state"].replace("repository file content:\n", ""))

    def test_criteria_reworded(self):
        with patch("urllib.request.urlopen", return_value=_laya_response()) as up:
            index_project.laya_decide("x", "y")
        crit = json.loads(up.call_args[0][0].data)["questions"]["triage"]["criteria"]
        self.assertEqual(crit["skip"],
                         "minified/vendored bundles, generated files, binary/non-text assets")
        self.assertEqual(crit["structure-only"],
                         "pure manifest of dependencies/settings, no executable logic")
        self.assertEqual(crit["quick-summary"],
                         "natural-language prose/docs (any language) worth one line, not code")
        self.assertEqual(crit["deep-analysis"],
                         "contains executable logic: functions/classes implementing behavior")

    def test_rule_fallback_on_outage_when_opted_in(self):
        import urllib.error
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("down")), \
             patch.dict(os.environ, {"UYP_LAYA_FALLBACK": "rule"}):
            self.assertEqual(index_project.laya_decide("x", "y"), ("quick-summary", 0.0))


def manifest_files():
    return [
        {"relpath": "a.py", "size": 1, "mtime": 10, "kind": "file"},
        {"relpath": "b.py", "size": 2, "mtime": 20, "kind": "file"},
        {"relpath": "c.md", "size": 3, "mtime": 30, "kind": "file"},
    ]


class TestChangedSelection(unittest.TestCase):
    def test_only_changed_restricts_pool_and_reports_missing(self):
        # a.py already processed at this version -> skipped by done_before
        done = lambda f: f["relpath"] == "a.py"
        files, skipped, missing = index_project.select_files(
            manifest_files(), limit=0, done_before=done,
            only={"a.py", "b.py", "deleted_upstream.py"})
        self.assertEqual([f["relpath"] for f in files], ["b.py"])
        self.assertEqual(skipped, 1)
        self.assertEqual(missing, 1)  # deleted/excluded relpaths are reported, not invented

    def test_limit_applies_within_the_changed_pool(self):
        files, _, _ = index_project.select_files(
            manifest_files(), limit=1, done_before=lambda f: False, only={"a.py", "b.py"})
        self.assertEqual([f["relpath"] for f in files], ["a.py"])

    def test_force_reprocesses_changed_pool_despite_done_before(self):
        files, skipped, _ = index_project.select_files(
            manifest_files(), limit=0, done_before=lambda f: True, only={"a.py"}, force=True)
        self.assertEqual([f["relpath"] for f in files], ["a.py"])
        self.assertEqual(skipped, 0)

    def test_no_only_selection_keeps_full_project_behavior(self):
        files, skipped, missing = index_project.select_files(
            manifest_files(), limit=0, done_before=lambda f: f["relpath"] == "c.md")
        self.assertEqual([f["relpath"] for f in files], ["a.py", "b.py"])
        self.assertEqual((skipped, missing), (1, 0))

    def test_changed_pool_exhausted_by_done_before(self):
        files, skipped, _ = index_project.select_files(
            manifest_files(), limit=0, done_before=lambda f: True, only={"a.py"})
        self.assertEqual(files, [])
        self.assertEqual(skipped, 1)


class TestLoadChangedPaths(unittest.TestCase):
    def changes_file(self, payload):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        changes = Path(tmp.name) / "changed.json"
        changes.write_text(json.dumps(payload), encoding="utf-8")
        return str(changes)

    def test_merges_args_and_file_with_dedupe(self):
        changes = self.changes_file(["b.py", "a.py", "b.py"])
        merged = index_project.load_changed_paths(["a.py", "c.py"], changes)
        self.assertEqual(merged, {"a.py", "b.py", "c.py"})

    def test_none_when_no_selection_given(self):
        self.assertIsNone(index_project.load_changed_paths(None, None))
        self.assertIsNone(index_project.load_changed_paths([], None))

    def test_rejects_non_array_changes_file(self):
        changes = self.changes_file({"a.py": 1})
        with self.assertRaises(ValueError):
            index_project.load_changed_paths(None, changes)


class TestPreemptiveYield(unittest.TestCase):
    """Slot pacing was superseded by the preemptive kill+redo design
    (merge a308264; friendly-fire fix 7704047): instead of probing shared
    ollama load (_ollama_inflight/_pace_llm_slots, removed), every qwen
    enrichment first yields to the interactive lock - a FRESH lock kills the
    in-flight index curl outright so the GPU goes to voice immediately - and
    each index curl is marked X-UYP-Worker: index so preemption can never
    hit voice or knowledge-search traffic."""

    def _lock_file(self, ts):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".lock", delete=False)
        self.addCleanup(os.unlink, tmp.name)
        tmp.write(str(ts))
        tmp.close()
        return tmp.name

    def test_yield_returns_immediately_without_lock_file(self):
        with patch.object(index_project, "INTERACTIVE_LOCK",
                          "/nonexistent/uyp_interactive.lock"), \
             patch.object(index_project.subprocess, "run") as run, \
             patch.object(index_project.time, "sleep") as sleep:
            index_project._yield_to_interactive()
        run.assert_not_called()
        sleep.assert_not_called()

    def test_yield_returns_without_preempt_when_lock_is_stale(self):
        # Older than the 30s interactive window: indexing resumes untouched.
        lock = self._lock_file(100.0)
        with patch.object(index_project, "INTERACTIVE_LOCK", lock), \
             patch.object(index_project.time, "time", return_value=131.0), \
             patch.object(index_project.subprocess, "run") as run, \
             patch.object(index_project.time, "sleep") as sleep:
            index_project._yield_to_interactive()
        run.assert_not_called()
        sleep.assert_not_called()

    def test_fresh_lock_preempts_index_workers_until_it_goes_stale(self):
        lock = self._lock_file(100.0)
        with patch.object(index_project, "INTERACTIVE_LOCK", lock), \
             patch.object(index_project.time, "time",
                          side_effect=[100.5, 100.6, 131.0]), \
             patch.object(index_project.subprocess, "run") as run, \
             patch.object(index_project.time, "sleep") as sleep:
            index_project._yield_to_interactive()
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [["pkill", "-f",
              "X-UYP-Worker: index 127[.]0[.]0[.]1:11434/api/chat"]] * 2)
        self.assertEqual([call.args[0] for call in sleep.call_args_list],
                         [0.5, 0.5])

    def test_preempt_pattern_targets_only_index_marked_curls(self):
        # Friendly-fire contract (7704047 + 2026-10-10 second incident): the
        # pkill pattern is anchored to the index marker + ollama URL so it
        # can never cross into the -d body.  The search synthesis prompt
        # contains the word "indexed" - the old "X-UYP-Worker.*index"
        # pattern matched it across the command line and every preempt
        # killed the in-flight search curl too.
        lock = self._lock_file(100.0)
        with patch.object(index_project, "INTERACTIVE_LOCK", lock), \
             patch.object(index_project.time, "time", return_value=100.5), \
             patch.object(index_project.subprocess, "run") as run, \
             patch.object(index_project.time, "sleep"):
            index_project._yield_to_interactive(max_wait_s=0.5)
        self.assertEqual(run.call_count, 1)
        pattern = run.call_args_list[0].args[0][2]
        self.assertRegex(
            "curl -s -H X-UYP-Worker: index 127.0.0.1:11434/api/chat "
            "-d {\"model\": \"qwen3.5-route\"} --max-time 400", pattern)
        self.assertNotRegex(
            "curl -s -H X-UYP-Worker: search 127.0.0.1:11434/api/chat "
            "-d {\"messages\": [{\"content\": \"Answer using ONLY the "
            "indexed file knowledge below.\"}}}", pattern)
        self.assertNotRegex(
            "curl -s -H X-UYP-Worker: voice 127.0.0.1:11434", pattern)

    def test_yield_wait_is_bounded_by_max_wait_s(self):
        # A lock that stays fresh forever still cannot stall the index past
        # max_wait_s: the loop exits and enrichment proceeds.
        lock = self._lock_file(100.0)
        with patch.object(index_project, "INTERACTIVE_LOCK", lock), \
             patch.object(index_project.time, "time", return_value=100.1), \
             patch.object(index_project.subprocess, "run") as run, \
             patch.object(index_project.time, "sleep") as sleep:
            index_project._yield_to_interactive(max_wait_s=1.0)
        self.assertEqual(run.call_count, 2)  # waited 0.5 + 0.5 -> bound hit
        self.assertEqual(sleep.call_count, 2)

    def test_qwen_enrich_yields_and_marks_curl_as_index_worker(self):
        yielded = []
        curl = MagicMock(returncode=0, stdout=json.dumps(
            {"message": {"content": "{}"}, "eval_count": 1}))
        with patch.object(index_project, "_yield_to_interactive",
                          side_effect=lambda: yielded.append(1)), \
             patch.object(index_project.subprocess, "run", return_value=curl) as run:
            content, tokens = index_project.qwen_enrich("x = 1", False)
        self.assertEqual(yielded, [1])
        self.assertEqual(content, "{}")
        self.assertEqual(tokens, 1)
        argv = run.call_args_list[0].args[0]
        self.assertIn("X-UYP-Worker: index", argv)


class TestTransportRetries(unittest.TestCase):
    """ba8bc9f port contract: api() retries transport blips (the launchd
    ssh -R tunnel to the connector restarts on network changes, observed
    2026-10-10 killing whole jobs) but NEVER masks HTTP policy answers
    (403 deny / 404 no-such-grant / 413 range-cap are final)."""

    def _ok(self, payload=None):
        m = MagicMock()
        m.read.return_value = json.dumps(payload or {"ok": True}).encode()
        m.__enter__ = MagicMock(return_value=m)
        m.__exit__ = MagicMock(return_value=False)
        return m

    def test_tunnel_blips_retry_until_success(self):
        import urllib.error
        good = self._ok()
        with patch("urllib.request.urlopen",
                   side_effect=[urllib.error.URLError("reset"),
                                ConnectionResetError("reset"), good]) as up, \
             patch.object(index_project.time, "sleep") as sleep:
            result = index_project.api("http://connector", "t", "/manifest")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(up.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 10])

    def test_policy_http_errors_are_final(self):
        import urllib.error
        for code in (403, 404, 413):
            with patch("urllib.request.urlopen",
                       side_effect=urllib.error.HTTPError("u", code, "no", None, None)) as up, \
                 patch.object(index_project.time, "sleep") as sleep:
                with self.assertRaises(urllib.error.HTTPError):
                    index_project.api("http://connector", "t", "/read?grant=g")
            up.assert_called_once()
            sleep.assert_not_called()

    def test_exhausted_retries_raise_last_error_without_trailing_sleep(self):
        import urllib.error
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("down")) as up, \
             patch.object(index_project.time, "sleep") as sleep:
            with self.assertRaises(urllib.error.URLError):
                index_project.api("http://connector", "t", "/manifest")
        self.assertEqual(up.call_count, 5)
        # no backoff after the FINAL failure: the job's failure must record
        # promptly instead of sleeping a pointless 60s
        self.assertEqual(sleep.call_count, 4)

    def test_torn_json_body_is_treated_as_transport(self):
        torn = MagicMock()
        torn.read.return_value = b"{trunc"
        torn.__enter__ = MagicMock(return_value=torn)
        torn.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", side_effect=[torn, self._ok()]), \
             patch.object(index_project.time, "sleep"):
            self.assertEqual(index_project.api("http://connector", "t", "/manifest"),
                             {"ok": True})

    def test_cjk_relpath_is_percent_encoded_not_crashed(self):
        # 2026-10-11 field crash: a CJK-named source file put raw UTF-8 into
        # the request line and http.client raised UnicodeEncodeError, killing
        # the whole worker.  api() must percent-encode non-ASCII instead.
        seen = {}

        def fake_urlopen(req, timeout=90):
            seen["url"] = req.full_url
            return self._ok()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            index_project.api(
                "http://connector", "t",
                "/read?grant=g&relpath=audit/\u65b9\u5929/\u6587\u4ef6.md&length=2048",
                binary=True)
        url = seen["url"]
        self.assertEqual(url,
                         "http://connector/read?grant=g&relpath=audit/%E6%96%B9%E5%A4%A9/%E6%96%87%E4%BB%B6.md&length=2048")
        # pure-ASCII paths are untouched
        seen.clear()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            index_project.api("http://connector", "t", "/manifest")
        self.assertEqual(seen["url"], "http://connector/manifest")



if __name__ == "__main__":
    unittest.main()
