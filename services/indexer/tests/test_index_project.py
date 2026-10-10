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


if __name__ == "__main__":
    unittest.main()
