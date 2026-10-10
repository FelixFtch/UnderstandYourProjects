"""Synthesis prompt contract for knowledge_search (de-hedging, 2026-10).

The live voice loop kept getting answers that opened with "I cannot locate
specific information about ..." and then named the correct file: retrieval
was right, synthesis was timid. These tests pin the prompt that fixes it -
the indexed knowledge is ground truth (no apologies, no hedging), the answer
leads with the file path(s), and a genuine miss is exactly the canonical
"Not in the indexed projects." sentence. No Ollama is needed: the model
call is faked at the subprocess (curl) seam and the prompt is inspected.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import knowledge_search  # noqa: E402


def fixture_items() -> list[dict]:
    return [
        {
            "file": "src/delegation.py",
            "derived": {
                "purpose": "Signs delegation requests with HMAC.",
                "key_points": ["sign_request builds the HMAC payload (L12-L40)"],
                "components": ["sign_request"],
            },
        },
        {
            "file": "src/unrelated.py",
            "derived": {"purpose": "Helpers for an unrelated topic."},
        },
    ]


class FakeCurl:
    """Records the curl argv so tests can assert on the request body."""

    def __init__(self, content: str = "委托签名在 src/delegation.py；它构造并签署 HMAC 载荷。"):
        self.calls: list = []
        self.content = content

    def __call__(self, args, capture_output, text):
        self.calls.append(args)
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps({"message": {"content": self.content}}), stderr="")


class SynthesisPromptTests(unittest.TestCase):
    def answer_with_fake_model(self, question="哪里实现了委托签名"):
        curl = FakeCurl()
        with patch.object(knowledge_search.subprocess, "run", curl):
            result = knowledge_search.answer(question, fixture_items())
        self.assertEqual(len(curl.calls), 1, "exactly one model call per answer")
        argv = curl.calls[0]
        request = json.loads(argv[argv.index("-d") + 1])
        return result, request, request["messages"][0]["content"]

    def test_prompt_declares_indexed_knowledge_ground_truth_no_hedging(self):
        _result, _request, prompt = self.answer_with_fake_model()
        self.assertIn("IS the ground truth", prompt)
        self.assertIn("do NOT apologize", prompt)
        self.assertIn("state them directly as fact", prompt)

    def test_prompt_pins_leading_file_path_shape_and_banned_preambles(self):
        _result, _request, prompt = self.answer_with_fake_model()
        self.assertIn("names the file path(s)", prompt)
        self.assertIn("based on the provided documents", prompt)  # named as banned
        self.assertIn("then stop", prompt)
        self.assertIn("Max 2 sentences", prompt)

    def test_prompt_defines_canonical_not_found_sentence(self):
        _result, _request, prompt = self.answer_with_fake_model()
        self.assertIn("'Not in the indexed projects.'", prompt)
        self.assertIn("no partial hedging", prompt)

    def test_prompt_carries_question_matched_files_and_language_pin(self):
        question = "哪里实现了委托签名"
        _result, _request, prompt = self.answer_with_fake_model(question)
        self.assertIn(question, prompt)
        # Only the lexically matched item is offered as context, never the
        # whole store.
        self.assertIn("FILE: src/delegation.py", prompt)
        self.assertNotIn("src/unrelated.py", prompt)
        self.assertIn("Answer in the question's language", prompt)

    def test_model_call_stays_think_false_on_qwen_route(self):
        # AGENTS.md rule 4: enrichment calls always use "think": false.
        _result, request, _prompt = self.answer_with_fake_model()
        self.assertEqual(request["model"], "qwen3.5-route")
        self.assertIs(request["think"], False)

    def test_answer_returns_model_content_with_sources(self):
        result, _request, _prompt = self.answer_with_fake_model()
        self.assertEqual(result["answer"], "委托签名在 src/delegation.py；它构造并签署 HMAC 载荷。")
        self.assertEqual(result["sources"][0]["file"], "src/delegation.py")
        self.assertIn(result["confidence"], {"high", "medium"})

    def test_no_lexical_match_returns_exactly_canonical_sentence(self):
        # No item matches, so the model is never called and the deterministic
        # branch must return the same canonical sentence the prompt demands -
        # no partial hedging from either path.
        curl = FakeCurl()
        with patch.object(knowledge_search.subprocess, "run", curl):
            result = knowledge_search.answer("量子退火算法在哪里实现", fixture_items())
        self.assertEqual(result["answer"], "Not in the indexed projects.")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["confidence"], "none")
        self.assertEqual(curl.calls, [])


if __name__ == "__main__":
    unittest.main()
