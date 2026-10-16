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

    def test_will_synthesize_flags_exactly_the_slow_path(self):
        # Slow-hint predicate (root-cause fix, 2026-10-10): a retrieval HIT
        # means qwen synthesis (the wait X-UYP-Slow-Hint exists to flag); a
        # miss is answered instantly and must never be hinted slow.  The
        # predicate shares _retrieval with answer(), so it can never
        # disagree with the answer path.
        self.assertTrue(knowledge_search.will_synthesize("哪里实现了委托签名", fixture_items()))
        self.assertFalse(knowledge_search.will_synthesize("量子退火算法在哪里实现", fixture_items()))
        self.assertFalse(knowledge_search.will_synthesize("哪里实现了委托签名", []))


class FreshnessAnswerTests(unittest.TestCase):
    """Time/freshness questions route to the temporal path (2026-10 incident:
    group search confidently invented 'no changes today' because synthesis
    never saw time metadata).  Fresh data -> ordered, timestamped synthesis;
    stale or undated index -> an honest fallback, never a fabrication."""

    def dated_items(self, now: float) -> list[dict]:
        return [
            {
                "file": "services/homehub/src/api.py",
                "version": {"mtime": now - 3600, "size": 100},
                "analyzed_at": "2026-10-16T21:00:00",
                "derived": {"purpose": "HomeHub HTTP API surface.",
                            "key_points": ["member endpoints"]},
            },
            {
                "file": "services/homehub/src/policy.py",
                "version": {"mtime": now - 2 * 86400, "size": 100},
                "derived": {"purpose": "HomeHub policy engine."},
            },
            {
                "file": "services/indexer/src/groups.py",
                "version": {"mtime": now - 10 * 86400, "size": 100},
                "derived": {"purpose": "Group scoped retrieval."},
            },
        ]

    def answer_with_fake_model(self, question, items, content="最近的改动在 services/homehub/src/api.py。"):
        curl = FakeCurl(content)
        with patch.object(knowledge_search.subprocess, "run", curl):
            result = knowledge_search.answer(question, items)
        prompt = ""
        if curl.calls:
            argv = curl.calls[0]
            prompt = json.loads(argv[argv.index("-d") + 1])["messages"][0]["content"]
        return result, curl, prompt

    def test_temporal_question_detection_zh_and_en(self):
        for q in ("今天 homehub 仓改了什么", "最近有什么变更", "昨天索引更新了吗",
                  "what changed today", "latest commits yesterday", "this week updates"):
            self.assertTrue(knowledge_search.is_temporal_question(q), q)
        for q in ("哪里实现了委托签名", "how does HMAC signing work", "什么是知识图谱"):
            self.assertFalse(knowledge_search.is_temporal_question(q), q)

    def test_fresh_data_answers_with_timestamps_newest_first(self):
        now = __import__("time").time()
        result, curl, prompt = self.answer_with_fake_model(
            "今天 homehub 仓改了什么", self.dated_items(now))
        self.assertEqual(len(curl.calls), 1)
        # Only the topically matched (homehub) dated items enter the prompt,
        # each carrying its own MODIFIED timestamp, newest first.
        self.assertIn("MODIFIED: ", prompt)
        self.assertLess(prompt.index("api.py"), prompt.index("policy.py"))
        self.assertNotIn("groups.py", prompt)
        self.assertIn("index snapshot is as of", prompt)
        self.assertEqual(result["sources"][0]["file"], "services/homehub/src/api.py")
        self.assertIn("ts", result["sources"][0])
        self.assertTrue(result["index_as_of"])

    def test_stale_index_answers_honestly_without_model_call(self):
        now = __import__("time").time()
        old = now - 3 * 86400
        items = [
            {"file": "services/homehub/src/api.py",
             "version": {"mtime": old, "size": 100},
             "derived": {"purpose": "HomeHub HTTP API surface."}},
            {"file": "services/homehub/src/policy.py",
             "version": {"mtime": old - 86400, "size": 100},
             "derived": {"purpose": "HomeHub policy engine."}},
        ]
        result, curl, _prompt = self.answer_with_fake_model("今天 homehub 仓改了什么", items)
        self.assertEqual(curl.calls, [], "stale index must not reach synthesis")
        self.assertIn("索引最新内容止于", result["answer"])
        self.assertIn("无法据索引回答", result["answer"])
        self.assertNotIn("无改动", result["answer"])
        self.assertEqual(result["sources"][0]["file"], "services/homehub/src/api.py")
        self.assertEqual(result["confidence"], "medium")
        self.assertTrue(result["index_as_of"])

    def test_stale_index_honest_fallback_english(self):
        now = __import__("time").time()
        items = [{"file": "src/api.py", "version": {"mtime": now - 5 * 86400, "size": 1}}]
        result, curl, _prompt = self.answer_with_fake_model("what changed today", items)
        self.assertEqual(curl.calls, [])
        self.assertIn("newest content stops at", result["answer"])
        self.assertIn("not indexed", result["answer"])

    def test_undated_index_says_so_without_model_call(self):
        items = [{"file": "src/api.py", "derived": {"purpose": "No timestamps here."}}]
        result, curl, _prompt = self.answer_with_fake_model("最近改了什么", items)
        self.assertEqual(curl.calls, [])
        self.assertIn("没有时间元数据", result["answer"])
        self.assertEqual(result["confidence"], "none")
        self.assertIsNone(result["index_as_of"])

    def test_yesterday_window_passes_when_data_is_from_yesterday(self):
        now = __import__("time").time()
        items = [{"file": "src/api.py", "version": {"mtime": now - 86400 - 60, "size": 1},
                  "derived": {"purpose": "Changed yesterday."}}]
        _result, curl, _prompt = self.answer_with_fake_model("昨天改了什么", items)
        self.assertEqual(len(curl.calls), 1, "yesterday data satisfies the yesterday window")

    def test_non_temporal_questions_keep_the_old_path(self):
        now = __import__("time").time()
        items = fixture_items()
        items[0]["version"] = {"mtime": now, "size": 100}
        curl = FakeCurl()
        with patch.object(knowledge_search.subprocess, "run", curl):
            result = knowledge_search.answer("哪里实现了委托签名", items)
        self.assertEqual(result["answer"], "委托签名在 src/delegation.py；它构造并签署 HMAC 载荷。")
        self.assertEqual(result["sources"][0]["file"], "src/delegation.py")
        self.assertIn("match", result["sources"][0])  # lexical scoring untouched
        self.assertTrue(result["index_as_of"])        # snapshot stamp rides along
        # Canonical miss is unchanged for non-temporal questions.
        with patch.object(knowledge_search.subprocess, "run", curl):
            miss = knowledge_search.answer("量子退火算法在哪里实现", items)
        self.assertEqual(miss["answer"], "Not in the indexed projects.")


if __name__ == "__main__":
    unittest.main()
