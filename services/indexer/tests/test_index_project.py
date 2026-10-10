import json
import os
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


if __name__ == "__main__":
    unittest.main()
