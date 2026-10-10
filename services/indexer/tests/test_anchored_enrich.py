"""v3.3 anchored-enrichment rules (2026-10-10 re-audit prescriptions).

Fixtures use the REAL tree-sitter symbol tables extracted by the vendored
Understand Anything extractor from the audit's own subject files:
  - packages/agent_contracts/src/agent_contracts/signing.py
    (v3.2 anchored the SeenDelegations helper so sign/verify never appeared)
  - packages/orchestrator/platform_policy.py
    (LocalPolicyEngine IS the central actor and must stay the anchor)
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import anchored_enrich as ae  # noqa: E402


# Real extraction of signing.py, span-sorted the way load_symbols orders it
# (stable sort: canonical_bytes precedes verify at equal span 11).
SIGNING_SYMS = [
    {"name": "SeenDelegations", "kind": "class", "lo": 123, "hi": 147},
    {"name": "split_wire", "kind": "function", "lo": 108, "hi": 120},
    {"name": "canonical_bytes", "kind": "function", "lo": 64, "hi": 75},
    {"name": "verify", "kind": "function", "lo": 94, "hi": 105},
    {"name": "sign", "kind": "function", "lo": 83, "hi": 91},
    {"name": "_sig_b64", "kind": "function", "lo": 78, "hi": 80},
]
SIGNING_REL = "packages/agent_contracts/src/agent_contracts/signing.py"

# Real extraction of platform_policy.py (largest public symbol = LocalPolicyEngine).
POLICY_SYMS = [
    {"name": "LocalPolicyEngine", "kind": "class", "lo": 245, "hi": 348},
    {"name": "EgressLedger", "kind": "class", "lo": 351, "hi": 413},
    {"name": "principal_from_payload", "kind": "function", "lo": 164, "hi": 242},
    {"name": "sanitize_for_ledger", "kind": "function", "lo": 125, "hi": 154},
    {"name": "_safe_url_summary", "kind": "function", "lo": 115, "hi": 122},
]
POLICY_REL = "packages/orchestrator/platform_policy.py"

CLEAN_RESPONSE = """P: sign mints the delegation wire value
K: [fact] sign mints payload_b64.sig with an optional kid segment (L83-L91)
K: [structure] canonical_bytes sorts keys and drops None values (L64-L75)
C: sign (L83-L91)
D: base64
"""


class SelectAnchorTests(unittest.TestCase):
    """Prescription 2: anchor by role, prefer EXPORTED symbols."""

    def test_signing_py_anchors_sign_not_the_seen_delegations_helper(self):
        anchor = ae.select_anchor(SIGNING_SYMS, SIGNING_REL)
        self.assertEqual(anchor["name"], "sign")  # the audit case: sign/verify appear
        self.assertEqual((anchor["lo"], anchor["hi"]), (83, 91))

    def test_public_symbol_beats_larger_private_span(self):
        syms = [
            {"name": "_internal_helper", "kind": "function", "lo": 10, "hi": 200},
            {"name": "public_entry", "kind": "function", "lo": 300, "hi": 320},
        ]
        self.assertEqual(ae.select_anchor(syms, "pkg/somewhere.py")["name"], "public_entry")

    def test_falls_back_to_largest_span_when_no_public_symbol(self):
        syms = [
            {"name": "_private_big", "kind": "function", "lo": 1, "hi": 90},
            {"name": "_private_small", "kind": "function", "lo": 95, "hi": 99},
        ]
        self.assertEqual(ae.select_anchor(syms, "pkg/priv.py")["name"], "_private_big")

    def test_platform_policy_keeps_local_policy_engine(self):
        # No symbol is named after the file, so the prescribed public/largest
        # rule applies — and the engine class stays the anchor.
        anchor = ae.select_anchor(POLICY_SYMS, POLICY_REL)
        self.assertEqual(anchor["name"], "LocalPolicyEngine")

    def test_role_affinity_requires_four_shared_characters(self):
        syms = [
            {"name": "BigService", "kind": "class", "lo": 1, "hi": 60},
            {"name": "app_run", "kind": "function", "lo": 70, "hi": 74},
        ]
        # app.py: stem "app" is only 3 chars -> no role match, public largest wins
        self.assertEqual(ae.select_anchor(syms, "src/app.py")["name"], "BigService")

    def test_empty_table_returns_none(self):
        self.assertIsNone(ae.select_anchor([], "x/y.py"))


class LeakValidationTests(unittest.TestCase):
    """Prescription 1: reject protocol leaks in purpose / key_points / components."""

    def test_instruction_fragments_are_rejected(self):
        for bad in [
            "sign is the PRIMARY ACTOR of this file",
            "the purpose MUST be about sign",
            "verify follows per instruction above",
            "ranges come from the symbol table rows",
            "the class was found by tree-sitter (L123-L147)",
            "the span 123-147 is the largest (L123-L147)",
        ]:
            self.assertIsNotNone(ae.leak_reason(bad), bad)

    def test_fragment_matching_respects_word_boundaries(self):
        for ok in [
            "the parser handles Spanish text (L1-L2)",
            "SeenDelegations spans 25 lines (L123-L147)",
        ]:
            self.assertIsNone(ae.leak_reason(ok), ok)

    def test_unparsed_label_placeholder_is_rejected(self):
        self.assertIsNotNone(
            ae.leak_reason("[fact|structure|inference] sign mints the wire (L83-L91)"))

    def test_mid_sentence_citation_is_rejected(self):
        self.assertIsNotNone(
            ae.leak_reason("[fact] sign mints the wire (L83-L91) for the delegation header"))

    def test_citation_between_two_ranges_is_rejected(self):
        # Earlier citation followed by continuation words = mid-sentence splice.
        self.assertIsNotNone(
            ae.leak_reason("[fact] sign mints (L83-L91) and verify checks (L94-L105)"))

    def test_final_citation_with_punctuation_passes(self):
        self.assertIsNone(ae.leak_reason("[fact] sign mints the wire value (L83-L91)."))
        self.assertIsNone(ae.leak_reason("[fact] 签名并校验委托头 (L83-L91)。"))

    def test_docstring_stale_marker_after_citation_passes(self):
        self.assertIsNone(
            ae.leak_reason("[fact] pending facts score 0.99 (L120-L135) [docstring-stale]"))

    def test_unverified_citation_is_allowed_when_final(self):
        self.assertIsNone(
            ae.leak_reason("[fact] overlay appends pending hits (unverified L500-L600)"))


class SnapAndParseTests(unittest.TestCase):
    """Prescription 3: honest citation marking, components included."""

    def test_snap_marks_non_table_ranges_unverified(self):
        self.assertIn("(unverified L500-L600)",
                      ae.snap_all("point about lines 500-600", SIGNING_SYMS))

    def test_snap_covers_components_too(self):
        parsed = ae.parse_response("C: mystery_helper (L500-L600)", SIGNING_SYMS)
        self.assertEqual(parsed["components"], ["mystery_helper (unverified L500-L600)"])

    def test_parse_splits_embedded_markers_and_snaps_ranges(self):
        raw = ("```python\n"
               "P: sign mints the delegation wire value K: [fact] mints payload.sig (L83-91) "
               "C: verify (L94-105) D: base64\n```")
        parsed = ae.parse_response(raw, SIGNING_SYMS)
        self.assertEqual(parsed["purpose"], "sign mints the delegation wire value")
        self.assertEqual(parsed["key_points"], ["[fact] mints payload.sig (L83-L91)"])
        self.assertEqual(parsed["components"], ["verify (L94-L105)"])
        self.assertEqual(parsed["depends_on"], ["base64"])

    def test_parse_returns_none_for_non_protocol_text(self):
        self.assertIsNone(ae.parse_response("I cannot analyze this file.", SIGNING_SYMS))

    def test_settle_stale_marker_moves_trailing_marker_before_citation(self):
        settled = ae.settle_stale_marker("[fact] code contradicts header (L120-L135) [docstring-stale]")
        self.assertEqual(settled, "[fact] code contradicts header [docstring-stale] (L120-L135)")

    def test_settle_stale_marker_keeps_marker_before_citation_untouched(self):
        text = "[fact] code contradicts header [docstring-stale] (L120-L135)"
        self.assertEqual(ae.settle_stale_marker(text), text)


class ValidateAndNudgeTests(unittest.TestCase):
    def test_validate_accepts_clean_parse(self):
        parsed = ae.parse_response(CLEAN_RESPONSE, SIGNING_SYMS)
        self.assertEqual(ae.validate(parsed), [])

    def test_validate_rejects_leaky_purpose(self):
        parsed = ae.parse_response(
            "P: sign is the PRIMARY ACTOR here\nK: [fact] sign mints the wire (L83-L91)",
            SIGNING_SYMS)
        reasons = ae.validate(parsed)
        self.assertTrue(any("purpose" in r and "fragment" in r for r in reasons))

    def test_validate_flags_empty_key_points(self):
        parsed = ae.parse_response("P: sign mints the delegation wire value", SIGNING_SYMS)
        self.assertIn("key_points empty", ae.validate(parsed))

    def test_validate_none_parse_reports_no_protocol(self):
        self.assertEqual(ae.validate(None), ["no protocol lines"])

    def test_empty_kp_nudge_uses_prescribed_wording(self):
        nudge = ae.nudge_for(["key_points empty"])
        self.assertIn("include at least two key_points about what the code DOES", nudge)

    def test_leak_nudge_names_the_protocol_violations(self):
        nudge = ae.nudge_for(["key_point citation not final (mid-sentence splice)"])
        self.assertIn("(L<lo>-L<hi>)", nudge)
        self.assertIn("final tokens", nudge)

    def test_component_fallback_is_top3_table_rows_verbatim(self):
        self.assertEqual(
            ae.component_fallback(SIGNING_SYMS),
            ["SeenDelegations (L123-L147)", "split_wire (L108-L120)",
             "canonical_bytes (L64-L75)"])


class MainFlowTests(unittest.TestCase):
    """End-to-end: retry-once-then-raw_head, empty-KP retry, component fallback."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "output"
        self.out.mkdir()
        graph = {"nodes": [
            {"type": t, "name": n, "filePath": "pkgs/signing.py", "lineRange": [lo, hi]}
            for (n, t, lo, hi) in [
                ("canonical_bytes", "function", 64, 75),
                ("_sig_b64", "function", 78, 80),
                ("sign", "function", 83, 91),
                ("verify", "function", 94, 105),
                ("split_wire", "function", 108, 120),
                ("SeenDelegations", "class", 123, 147),
            ]
        ]}
        self.graph_path = self.root / "graph.json"
        self.graph_path.write_text(json.dumps(graph), encoding="utf-8")
        self.item = self.out / "pkgs__signing.py.knowledge.json"
        self.item.write_text(json.dumps({"file": "pkgs/signing.py", "verdict": "deep"}),
                             encoding="utf-8")
        self.token = self.root / "token"
        self.token.write_text("tok", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, responses):
        argv = ["anchored_enrich.py",
                "--graph", str(self.graph_path),
                "--output-root", str(self.out),
                "--token-file", str(self.token),
                "--grant", "g_test"]
        calls = []
        with patch.object(sys, "argv", argv), \
             patch.object(ae, "qwen", side_effect=responses) as qwen, \
             patch.object(ae, "api", return_value=b"def sign(): pass") as fake_api:
            ae.main()
            calls = [c.args[0] for c in qwen.call_args_list]
        return json.loads(self.item.read_text(encoding="utf-8")), calls

    def test_clean_first_pass_anchors_without_retry(self):
        item, calls = self.run_main([(CLEAN_RESPONSE, 100)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(item["anchor_top"], "sign L83-L91")  # role anchor, not SeenDelegations
        self.assertEqual(item["derived"]["purpose"], "sign mints the delegation wire value")
        self.assertEqual(len(item["derived"]["key_points"]), 2)
        self.assertEqual(item["derived"]["components"], ["sign (L83-L91)"])
        self.assertNotIn("raw_head", item["derived"])

    def test_leaky_first_pass_recovers_via_corrective_retry(self):
        leaky = ("P: sign is the PRIMARY ACTOR of this file\n"
                 "K: [fact|structure|inference] sign mints the wire (L83-L91)\n"
                 "C: sign (L83-L91)\n")
        item, calls = self.run_main([(leaky, 100), (CLEAN_RESPONSE, 120)])
        self.assertEqual(len(calls), 2)
        self.assertIn("CORRECTION", calls[1])
        self.assertEqual(item["derived"]["purpose"], "sign mints the delegation wire value")
        self.assertEqual(len(item["derived"]["key_points"]), 2)

    def test_second_leak_falls_back_to_raw_head(self):
        leaky1 = "P: v1 the PRIMARY ACTOR is sign\nK: [fact] x (L83-L91)\n"
        leaky2 = "P: v2 the symbol table says sign\nK: [fact] x (L83-L91)\n"
        item, _ = self.run_main([(leaky1, 100), (leaky2, 120)])
        self.assertTrue(item["derived"]["anchored"])
        self.assertIn("v2", item["derived"]["raw_head"])  # raw_head of the LAST attempt
        self.assertNotIn("key_points", item["derived"])

    def test_empty_key_points_gets_one_prescribed_retry(self):
        no_kp = "P: sign mints the delegation wire value\nC: sign (L83-L91)\n"
        item, calls = self.run_main([(no_kp, 100), (CLEAN_RESPONSE, 120)])
        self.assertEqual(len(calls), 2)
        self.assertIn("include at least two key_points about what the code DOES", calls[1])
        self.assertEqual(len(item["derived"]["key_points"]), 2)

    def test_empty_key_points_after_retry_falls_back_to_raw_head(self):
        no_kp = "P: sign mints the delegation wire value\nC: sign (L83-L91)\n"
        item, _ = self.run_main([(no_kp, 100), (no_kp, 120)])
        self.assertIn("raw_head", item["derived"])

    def test_missing_components_fall_back_to_top3_table_rows(self):
        no_c = ("P: sign mints the delegation wire value\n"
                "K: [fact] sign mints payload_b64.sig (L83-L91)\n"
                "K: [structure] canonical_bytes sorts keys and drops None (L64-L75)\n")
        item, calls = self.run_main([(no_c, 100)])
        self.assertEqual(len(calls), 1)  # deterministic fallback: no retry
        self.assertEqual(item["derived"]["components"],
                         ["SeenDelegations (L123-L147)", "split_wire (L108-L120)",
                          "canonical_bytes (L64-L75)"])
        self.assertTrue(item["derived"]["components_table_fallback"])

    def test_role_anchor_line_and_full_table_are_both_passed(self):
        with patch.object(sys, "argv", ["anchored_enrich.py",
                                        "--graph", str(self.graph_path),
                                        "--output-root", str(self.out),
                                        "--token-file", str(self.token),
                                        "--grant", "g_test"]), \
             patch.object(ae, "qwen", side_effect=[(CLEAN_RESPONSE, 100)]) as qwen, \
             patch.object(ae, "api", return_value=b"def sign(): pass"):
            ae.main()
        prompt = qwen.call_args_list[0].args[0]
        self.assertIn("PRIMARY ACTOR: sign L83-L91", prompt)
        self.assertIn("SYMBOL TABLE", prompt)
        self.assertIn("SeenDelegations  L123-L147", prompt)  # full table stays
        self.assertIn("docstring may be STALE", prompt)      # prescription 4
        self.assertIn("[docstring-stale]", prompt)


if __name__ == "__main__":
    unittest.main()
