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


class TestSlotPacing(unittest.TestCase):
    """GPU-aware yield (root-cause fix, 2026-10-10): the interactive lock
    only helps while a query is IN FLIGHT; between queries the index workers
    must not fill every ollama slot, or the NEXT voice/text query waits for
    a slot.  Pacing checks the shared load before each qwen call and waits
    below the UYP_MAX_CONCURRENT ceiling."""

    def _ps_response(self, payload):
        m = MagicMock()
        m.read.return_value = json.dumps(payload).encode()
        m.__enter__ = MagicMock(return_value=m)
        m.__exit__ = MagicMock(return_value=False)
        return m

    def test_inflight_from_reporting_ps_endpoint(self):
        # A server that reports its own concurrency is honored directly.
        with patch("urllib.request.urlopen",
                   return_value=self._ps_response({"concurrent": 4, "models": []})):
            self.assertEqual(index_project._ollama_inflight(), 4)

    def test_stock_ps_falls_back_to_established_socket_count(self):
        # Stock ollama /api/ps lists models only: count ESTABLISHED sockets
        # on the ollama port instead (one per in-flight request).
        ps = self._ps_response({"models": [{"name": "qwen3.5-route"}]})
        ss = MagicMock(returncode=0,
                       stdout="ESTAB 0 0 127.0.0.1:1 127.0.0.1:11434\n\n"
                              "ESTAB 0 0 127.0.0.1:2 127.0.0.1:11434\n")
        with patch("urllib.request.urlopen", return_value=ps), \
             patch.object(index_project.subprocess, "run", return_value=ss) as run:
            self.assertEqual(index_project._ollama_inflight(), 2)
            self.assertEqual(run.call_args[0][0][0], "ss")

    def test_probe_failure_means_unknown_and_disables_pacing(self):
        with patch("urllib.request.urlopen", side_effect=OSError("down")), \
             patch.object(index_project.subprocess, "run",
                          side_effect=FileNotFoundError("ss")):
            self.assertEqual(index_project._ollama_inflight(), 0)

    def test_pacing_sleeps_while_at_or_above_ceiling(self):
        levels = iter([3, 3, 1])
        with patch.object(index_project, "_ollama_inflight",
                          side_effect=lambda: next(levels)), \
             patch.object(index_project.time, "sleep") as sleep:
            index_project._pace_llm_slots()
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 2])

    def test_pacing_ceiling_default_and_env(self):
        # Default 3: 2 proceeds, 3 waits.  UYP_MAX_CONCURRENT=5: 4 proceeds, 5 waits.
        with patch.object(index_project, "_ollama_inflight", return_value=2), \
             patch.object(index_project.time, "sleep") as sleep:
            index_project._pace_llm_slots()
        sleep.assert_not_called()
        with patch.dict(os.environ, {"UYP_MAX_CONCURRENT": "5"}), \
             patch.object(index_project, "_ollama_inflight", side_effect=[5, 4]), \
             patch.object(index_project.time, "sleep") as sleep:
            index_project._pace_llm_slots()
        self.assertEqual(sleep.call_count, 1)

    def test_qwen_enrich_paces_before_each_call(self):
        paced = []
        curl = MagicMock(returncode=0, stdout=json.dumps(
            {"message": {"content": "{}"}, "eval_count": 1}))
        with patch.object(index_project, "_pace_llm_slots",
                          side_effect=lambda: paced.append(1)), \
             patch.object(index_project.subprocess, "run", return_value=curl):
            content, tokens = index_project.qwen_enrich("x = 1", False)
        self.assertEqual(paced, [1])
        self.assertEqual(content, "{}")
        self.assertEqual(tokens, 1)


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


if __name__ == "__main__":
    unittest.main()
