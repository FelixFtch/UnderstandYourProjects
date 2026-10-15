#!/usr/bin/env python3
"""Tests for ua_llm_client (UA 云端/本地分析模式, owner decision 2026-10-15)
and its three call-site integrations (index_project enrichment,
anchored_enrich, project_digest.ask) plus the ua_bridge uaSummary flag.

Contract under test:
  * missing config (or mode != "cloud") -> local, byte-identical behavior;
  * cloud mode builds a client for qwen/openai/claude/gemini/deepseek with
    the right request dialect (OpenAI-compatible vs claude native messages);
  * a missing/empty key file is an honest CloudConfigError (paths named,
    key material never printed);
  * one cloud failure degrades THAT file to structure-only + warning;
  * 5 consecutive failures trip the breaker: the rest of the job degrades to
    structure-only and the run-state carries cloud_enrich_broken, which
    ua_bridge surfaces on the job's uaSummary.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import anchored_enrich as ae  # noqa: E402
import index_project  # noqa: E402
import project_digest  # noqa: E402
import ua_bridge  # noqa: E402
import ua_llm_client as ua_llm  # noqa: E402

SECRET = "sk-test-DEADBEEF-secret"


class UaTestCase(unittest.TestCase):
    """Pins UYP_UA_CLOUD_CONFIG at a tmp path so the suite stays hermetic on
    machines where a real ~/dev/uyp/state/ua-cloud.json exists."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.root = Path(self.tmp)
        self.cfg_path = self.root / "ua-cloud.json"
        patcher = patch.dict(os.environ, {ua_llm.CONFIG_ENV: str(self.cfg_path)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_cloud_config(self, provider="qwen", model="test-model",
                           key=SECRET, extra=None):
        cfg = {"mode": "cloud", "provider": provider, "model": model}
        if key is not None:
            key_file = self.root / f"{provider}.key"
            key_file.write_text(key + "\n", encoding="utf-8")
            cfg["api_key_file"] = str(key_file)
        if extra:
            cfg.update(extra)
        self.cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        return self.cfg_path

    def fake_urlopen(self, payload=None, error=None, capture=None):
        """A urlopen stand-in: records the Request, then returns `payload` as
        a JSON body or raises `error`."""
        def fake(req, timeout=None):
            if capture is not None:
                capture.append(req)
            if error is not None:
                raise error
            resp = MagicMock()
            resp.__enter__.return_value.read.return_value = json.dumps(payload).encode()
            return resp
        return fake

    def http_500(self, body=b'{"error": "boom"}'):
        return urllib.error.HTTPError("https://provider.invalid", 500,
                                      "Internal Server Error", {}, io.BytesIO(body))


class TestLoadConfig(UaTestCase):
    def test_missing_config_is_local(self):
        self.assertIsNone(ua_llm.load_client())

    def test_explicit_local_mode_is_local(self):
        self.cfg_path.write_text(json.dumps({"mode": "local"}), encoding="utf-8")
        self.assertIsNone(ua_llm.load_client())

    def test_missing_mode_defaults_to_local(self):
        self.cfg_path.write_text(json.dumps({"provider": "qwen"}), encoding="utf-8")
        self.assertIsNone(ua_llm.load_client())

    def test_malformed_json_is_honest_error(self):
        self.cfg_path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ua_llm.CloudConfigError) as ctx:
            ua_llm.load_client()
        self.assertIn(str(self.cfg_path), str(ctx.exception))

    def test_non_object_config_is_honest_error(self):
        self.cfg_path.write_text("[1, 2]", encoding="utf-8")
        with self.assertRaises(ua_llm.CloudConfigError):
            ua_llm.load_client()

    def test_unknown_provider_is_honest_error(self):
        self.write_cloud_config(provider="bogus")
        with self.assertRaises(ua_llm.CloudConfigError) as ctx:
            ua_llm.load_client()
        self.assertIn("bogus", str(ctx.exception))
        for known in ua_llm.PROVIDERS:
            self.assertIn(known, str(ctx.exception))

    def test_cloud_mode_requires_model(self):
        self.write_cloud_config(model="")
        with self.assertRaises(ua_llm.CloudConfigError) as ctx:
            ua_llm.load_client()
        self.assertIn("model", str(ctx.exception))

    def test_missing_key_file_is_honest_error(self):
        self.write_cloud_config(provider="deepseek")
        cfg = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        os.unlink(cfg["api_key_file"])
        with self.assertRaises(ua_llm.CloudConfigError) as ctx:
            ua_llm.load_client()
        # the error names the PATH, never key material
        self.assertIn(cfg["api_key_file"], str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_empty_key_file_is_honest_error(self):
        self.write_cloud_config(provider="openai", key="")
        with self.assertRaises(ua_llm.CloudConfigError) as ctx:
            ua_llm.load_client()
        self.assertIn("empty", str(ctx.exception))

    def test_default_key_file_path_per_provider(self):
        # no api_key_file -> ~/.config/homehub/<provider>.key
        cfg = {"mode": "cloud", "provider": "gemini", "model": "m"}
        self.cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        with self.assertRaises(ua_llm.CloudConfigError) as ctx:
            ua_llm.load_client()
        self.assertIn(os.path.join(".config", "homehub", "gemini.key"), str(ctx.exception))

    def test_cloud_mode_constructs_client(self):
        self.write_cloud_config(provider="qwen", model="qwen3.5-plus")
        client = ua_llm.load_client()
        self.assertIsNotNone(client)
        self.assertEqual(client.provider, "qwen")
        self.assertEqual(client.model, "qwen3.5-plus")
        # the key is held for headers but never leaks into repr/str
        self.assertNotIn(SECRET, repr(client))

    def test_homehub_source_reads_owner_only_key_file(self):
        key_file = self.root / "qwen.key"
        key_file.write_text(SECRET + "\n", encoding="utf-8")
        self.cfg_path.write_text(json.dumps({
            "mode": "cloud", "provider": "qwen", "model": "qwen3.5-plus",
            "api_key_source": "homehub", "api_key_file": str(key_file),
        }), encoding="utf-8")
        client = ua_llm.load_client()
        self.assertEqual(client.provider, "qwen")
        self.assertEqual(client.model, "qwen3.5-plus")

    def test_unknown_key_source_is_rejected(self):
        self.write_cloud_config(extra={"api_key_source": "http"})
        with self.assertRaises(ua_llm.CloudConfigError) as ctx:
            ua_llm.load_client()
        self.assertIn("api_key_source", str(ctx.exception))


class TestRequestShapes(UaTestCase):
    """Five-provider dialect contract: four OpenAI-compatible, claude native."""

    def test_openai_compat_shape_all_four(self):
        bases = {"qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                 "openai": "https://api.openai.com/v1",
                 "deepseek": "https://api.deepseek.com/v1",
                 "gemini": "https://generativelanguage.googleapis.com/v1beta/openai"}
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
        bases.update({"grok": "https://api.x.ai/v1", "muse": "https://api.meta.ai/v1"})
        for provider, base in bases.items():
            with self.subTest(provider=provider):
                client = ua_llm.CloudClient(provider, "m-x", SECRET)
                url, payload, headers = client.build_request(messages, 512)
                self.assertEqual(url, base + "/chat/completions")
                self.assertEqual(headers, {"Authorization": f"Bearer {SECRET}"})
                self.assertEqual(payload["model"], "m-x")
                self.assertEqual(payload["max_tokens"], 512)
                self.assertIs(payload["stream"], False)
                if provider == "qwen":
                    self.assertIs(payload["enable_thinking"], False)
                else:
                    self.assertNotIn("enable_thinking", payload)
                # compat dialect keeps system inside messages, order preserved
                self.assertEqual(payload["messages"], messages)

    def test_custom_openai_compatible_base_url(self):
        client = ua_llm.CloudClient("custom", "my-model", SECRET,
                                    base_url="http://127.0.0.1:9000/v1/")
        url, payload, _ = client.build_request([{"role": "user", "content": "u"}], 128)
        self.assertEqual(url, "http://127.0.0.1:9000/v1/chat/completions")
        self.assertEqual(payload["model"], "my-model")

    def test_base_url_rejects_credentials_query_and_endpoint_path(self):
        for base in ("https://user:pass@example.test/v1",
                     "https://example.test/v1?token=secret",
                     "https://example.test/v1/chat/completions"):
            with self.subTest(base=base), self.assertRaises(ua_llm.CloudConfigError):
                ua_llm.CloudClient("custom", "m", SECRET, base_url=base)

    def test_claude_native_shape(self):
        client = ua_llm.CloudClient("claude", "claude-x", SECRET)
        messages = [{"role": "system", "content": "sys text"},
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "prev"},
                    {"role": "user", "content": "again"}]
        url, payload, headers = client.build_request(messages, 300)
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers["x-api-key"], SECRET)
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertNotIn("Authorization", headers)
        # max_tokens is REQUIRED by the messages API
        self.assertEqual(payload["max_tokens"], 300)
        # system is a TOP-LEVEL field, never a message
        self.assertEqual(payload["system"], "sys text")
        self.assertEqual(payload["messages"],
                         [{"role": "user", "content": "hello"},
                          {"role": "assistant", "content": "prev"},
                          {"role": "user", "content": "again"}])

    def test_claude_omits_system_when_absent(self):
        client = ua_llm.CloudClient("claude", "claude-x", SECRET)
        _, payload, _ = client.build_request([{"role": "user", "content": "u"}], 100)
        self.assertNotIn("system", payload)


class TestResponseParsing(UaTestCase):
    def test_compat_content_and_total_tokens(self):
        client = ua_llm.CloudClient("openai", "m", SECRET)
        out = client.parse_response(
            {"choices": [{"message": {"content": "answer"}}],
             "usage": {"total_tokens": 42}})
        self.assertEqual(out, ("answer", 42))

    def test_compat_token_fallback_sum_and_zero(self):
        client = ua_llm.CloudClient("qwen", "m", SECRET)
        self.assertEqual(client.parse_response(
            {"choices": [{"message": {"content": "x"}}],
             "usage": {"prompt_tokens": 3, "completion_tokens": 4}}), ("x", 7))
        self.assertEqual(client.parse_response(
            {"choices": [{"message": {"content": "x"}}]}), ("x", 0))

    def test_compat_missing_choices_or_empty_content_raise(self):
        client = ua_llm.CloudClient("deepseek", "m", SECRET)
        with self.assertRaises(ua_llm.CloudError):
            client.parse_response({"choices": []})
        with self.assertRaises(ua_llm.CloudError):
            client.parse_response({"choices": [{"message": {"content": "  "}}]})

    def test_compat_text_block_array_is_flattened(self):
        client = ua_llm.CloudClient("muse", "m", SECRET)
        self.assertEqual(client.parse_response(
            {"choices": [{"message": {"content": [
                {"type": "output_text", "text": "a"},
                {"type": "image_url", "image_url": {"url": "ignored"}},
                {"type": "text", "text": "b"},
            ]}}]}), ("ab", 0))

    def test_claude_text_blocks_and_token_sum(self):
        client = ua_llm.CloudClient("claude", "m", SECRET)
        out = client.parse_response(
            {"content": [{"type": "text", "text": "a"},
                         {"type": "thinking", "text": "hidden"},
                         {"type": "text", "text": "b"}],
             "usage": {"input_tokens": 3, "output_tokens": 4}})
        self.assertEqual(out, ("ab", 7))

    def test_claude_without_content_array_raises(self):
        client = ua_llm.CloudClient("claude", "m", SECRET)
        with self.assertRaises(ua_llm.CloudError):
            client.parse_response({"content": "not-an-array"})

    def test_non_object_body_raises(self):
        client = ua_llm.CloudClient("qwen", "m", SECRET)
        with self.assertRaises(ua_llm.CloudError):
            client.parse_response([1, 2])


class TestChatOverHttp(UaTestCase):
    def test_chat_posts_and_parses(self):
        self.write_cloud_config(provider="qwen", model="qwen3.5-plus")
        client = ua_llm.load_client()
        capture = []
        payload = {"choices": [{"message": {"content": '{"purpose": "p"}'}}],
                   "usage": {"total_tokens": 11}}
        with patch.object(ua_llm.urllib.request, "urlopen",
                          self.fake_urlopen(payload, capture=capture)):
            content, tokens = client.chat([{"role": "user", "content": "analyze"}])
        self.assertEqual((content, tokens), ('{"purpose": "p"}', 11))
        req = capture[0]
        self.assertEqual(req.full_url,
                         "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        self.assertEqual(req.get_method(), "POST")
        body = json.loads(req.data.decode())
        self.assertEqual(body["model"], "qwen3.5-plus")
        self.assertEqual(body["messages"], [{"role": "user", "content": "analyze"}])
        self.assertEqual(req.get_header("Authorization"), f"Bearer {SECRET}")

    def test_http_500_raises_cloud_error_without_key(self):
        self.write_cloud_config(provider="openai")
        client = ua_llm.load_client()
        with patch.object(ua_llm.urllib.request, "urlopen",
                          self.fake_urlopen(error=self.http_500())):
            with self.assertRaises(ua_llm.CloudError) as ctx:
                client.chat([{"role": "user", "content": "x"}])
        self.assertIn("HTTP 500", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_http_error_redacts_key_if_provider_echoes_it(self):
        self.write_cloud_config(provider="grok")
        client = ua_llm.load_client()
        err = urllib.error.HTTPError(
            "https://api.x.ai/v1/chat/completions", 400, "Bad Request", {},
            io.BytesIO(("provider echoed " + SECRET).encode()))
        with patch.object(ua_llm.urllib.request, "urlopen",
                          self.fake_urlopen(error=err)):
            with self.assertRaises(ua_llm.CloudError) as ctx:
                client.chat([{"role": "user", "content": "x"}])
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_transport_error_raises_cloud_error(self):
        self.write_cloud_config(provider="deepseek")
        client = ua_llm.load_client()
        err = urllib.error.URLError("connection refused")
        with patch.object(ua_llm.urllib.request, "urlopen", self.fake_urlopen(error=err)):
            with self.assertRaises(ua_llm.CloudError):
                client.chat([{"role": "user", "content": "x"}])

    def test_claude_chat_posts_native_shape(self):
        self.write_cloud_config(provider="claude", model="claude-x")
        client = ua_llm.load_client()
        capture = []
        payload = {"content": [{"type": "text", "text": "hi"}],
                   "usage": {"input_tokens": 2, "output_tokens": 3}}
        with patch.object(ua_llm.urllib.request, "urlopen",
                          self.fake_urlopen(payload, capture=capture)):
            content, tokens = client.chat([{"role": "system", "content": "s"},
                                           {"role": "user", "content": "u"}],
                                          max_tokens=256)
        self.assertEqual((content, tokens), ("hi", 5))
        req = capture[0]
        self.assertEqual(req.full_url, "https://api.anthropic.com/v1/messages")
        body = json.loads(req.data.decode())
        self.assertEqual(body["system"], "s")
        self.assertEqual(body["max_tokens"], 256)
        self.assertEqual(body["messages"], [{"role": "user", "content": "u"}])
        self.assertEqual(req.get_header("X-api-key"), SECRET)
        self.assertEqual(req.get_header("Anthropic-version"), "2023-06-01")


class TestCloudBreaker(UaTestCase):
    def test_trips_at_threshold_and_latches(self):
        breaker = ua_llm.CloudBreaker()
        for _ in range(ua_llm.BREAKER_THRESHOLD - 1):
            self.assertFalse(breaker.fail())
            self.assertFalse(breaker.tripped)
        self.assertTrue(breaker.fail())   # the tripping failure reports True once
        self.assertTrue(breaker.tripped)
        self.assertFalse(breaker.fail())  # latched: later failures do not re-report

    def test_success_resets_streak_before_trip(self):
        breaker = ua_llm.CloudBreaker()
        for _ in range(ua_llm.BREAKER_THRESHOLD - 1):
            breaker.fail()
        breaker.ok()
        self.assertEqual(breaker.failures, 0)
        self.assertFalse(breaker.tripped)


class CloudIndexCase(UaTestCase):
    """Runs index_project.main() end-to-end with a stubbed connector and a
    stubbed cloud HTTP layer (same pattern as test_ua_cache)."""

    def run_cloud_index(self, n_files, urlopen_fake):
        root = self.root / f"run-{n_files}-{id(urlopen_fake)}"
        root.mkdir()
        token = root / "token"
        token.write_text("t", encoding="utf-8")
        files = [{"relpath": f"f{i}.py", "size": 200, "mtime": 100.0 + i, "kind": "file"}
                 for i in range(1, n_files + 1)]
        body = "def f():\n    return 1\n" + "# pad\n" * 40

        def fake_api(host, tok, path, binary=False, timeout=90, retries=5):
            if path.startswith("/manifest"):
                return {"root_name": "demo", "total": len(files),
                        "has_more": False, "files": files}
            q = urllib.parse.parse_qs(path.split("?", 1)[1])
            offset = int(q.get("offset", ["0"])[0])
            length = int(q["length"][0])
            return body.encode()[offset:offset + length]

        self.write_cloud_config(provider="qwen", model="qwen3.5-plus")
        argv = ["index_project.py", "--host", "http://connector",
                "--token-file", str(token), "--grant", "g_test", "--limit", "0"]
        env = {"UYP_KEYFILE": "off", "UYP_ENRICH_WORKERS": "1",
               ua_llm.CONFIG_ENV: str(self.cfg_path)}
        state, out = root / "state", root / "out"
        with patch.object(sys, "argv", argv), \
             patch.dict(os.environ, env), \
             patch.object(index_project, "api", fake_api), \
             patch.object(index_project, "STATE", str(state)), \
             patch.object(index_project, "OUT", str(out)), \
             patch.object(index_project, "INTERACTIVE_LOCK", str(root / "no.lock")), \
             patch.object(index_project, "laya_decide",
                          lambda head, mid="": ("deep-analysis", 0.9)), \
             patch.object(index_project, "qwen_enrich",
                          side_effect=AssertionError("local ollama path must not run in cloud mode")), \
             patch.object(ua_llm.urllib.request, "urlopen", urlopen_fake):
            index_project.main()
        items = {p.name: json.loads(p.read_text(encoding="utf-8"))
                 for p in (out / "demo").glob("*.knowledge.json")}
        run_state = json.loads((state / "demo.json").read_text(encoding="utf-8"))
        return items, run_state, state


class TestIndexProjectCloud(CloudIndexCase):
    def test_cloud_success_writes_parsed_enrichment(self):
        payload = {"choices": [{"message": {"content":
                   '{"purpose": "p", "key_points": ["k"], "components": [], "depends_on": []}'}}],
                   "usage": {"total_tokens": 11}}
        capture = []
        items, run_state, _state = self.run_cloud_index(1, self.fake_urlopen(payload, capture=capture))
        item = items["f1.py.knowledge.json"]
        self.assertEqual(item["verdict"], "deep-analysis")
        self.assertEqual(item["derived"]["purpose"], "p")
        self.assertEqual(item["eval_tokens"], 11)
        self.assertNotIn("enrich_warning", item)
        self.assertEqual(run_state["ua_mode"], "cloud")
        self.assertNotIn("cloud_enrich_broken", run_state)
        self.assertTrue(capture[0].full_url.startswith(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"))

    def test_cloud_500_degrades_file_to_structure_only_with_warning(self):
        items, run_state, _state = self.run_cloud_index(1, self.fake_urlopen(error=self.http_500()))
        item = items["f1.py.knowledge.json"]
        self.assertEqual(item["verdict"], "structure-only")
        self.assertEqual(item["derived"]["kind"], "structure-only")
        self.assertEqual(item["enrich_warning"], "cloud_enrich_failed")
        # one failure does not trip the breaker
        self.assertEqual(run_state["ua_mode"], "cloud")
        self.assertNotIn("cloud_enrich_broken", run_state)

    def test_consecutive_failures_trip_breaker_and_mark_run_state(self):
        calls = []

        def always_500(req, timeout=None):
            calls.append(req)
            raise self.http_500()

        items, run_state, state = self.run_cloud_index(6, always_500)
        # breaker trips on the 5th consecutive failure: exactly 5 cloud calls
        self.assertEqual(len(calls), ua_llm.BREAKER_THRESHOLD)
        for i in range(1, 6):
            item = items[f"f{i}.py.knowledge.json"]
            self.assertEqual(item["verdict"], "structure-only", item["file"])
            self.assertEqual(item["derived"]["kind"], "structure-only", item["file"])
        for i in range(1, ua_llm.BREAKER_THRESHOLD + 1):
            self.assertEqual(items[f"f{i}.py.knowledge.json"]["enrich_warning"],
                             "cloud_enrich_failed")
        # the 6th file never reached the provider: breaker skip
        self.assertEqual(items["f6.py.knowledge.json"]["enrich_warning"],
                         "cloud_enrich_broken")
        self.assertEqual(run_state["ua_mode"], "cloud")
        self.assertIs(run_state["cloud_enrich_broken"], True)
        # ... and ua_bridge surfaces exactly these flags on the job uaSummary
        flags = ua_bridge._indexer_run_flags(state, "demo")
        self.assertEqual(flags, {"ua_mode": "cloud", "cloud_enrich_broken": True})


class TestAnchoredEnrichCloud(UaTestCase):
    def test_qwen_cloud_path_returns_content_without_curl(self):
        self.write_cloud_config(provider="gemini", model="g-1")
        payload = {"choices": [{"message": {"content": "P: x"}}],
                   "usage": {"total_tokens": 5}}
        with patch.object(ua_llm.urllib.request, "urlopen",
                          self.fake_urlopen(payload)), \
             patch.object(ae.subprocess, "run",
                          side_effect=AssertionError("local curl path must not run in cloud mode")):
            self.assertEqual(ae.qwen("prompt"), ("P: x", 5))

    def test_qwen_cloud_failure_raises_runtime_error_like_local(self):
        self.write_cloud_config(provider="qwen")
        with patch.object(ua_llm.urllib.request, "urlopen",
                          self.fake_urlopen(error=self.http_500())):
            with self.assertRaises(RuntimeError) as ctx:
                ae.qwen("prompt")
        self.assertIn("cloud enrich", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))


class TestProjectDigestCloud(UaTestCase):
    def test_ollama_chat_cloud_returns_content(self):
        self.write_cloud_config(provider="deepseek", model="d-1")
        payload = {"choices": [{"message": {"content": "  sourced answer  "}}],
                   "usage": {"total_tokens": 9}}
        with patch.object(ua_llm.urllib.request, "urlopen", self.fake_urlopen(payload)):
            self.assertEqual(project_digest.ollama_chat("question?"), "sourced answer")

    def test_ollama_chat_cloud_failure_returns_none(self):
        self.write_cloud_config(provider="qwen")
        with patch.object(ua_llm.urllib.request, "urlopen",
                          self.fake_urlopen(error=self.http_500())):
            self.assertIsNone(project_digest.ollama_chat("question?"))

    def test_broken_cloud_config_falls_back_to_local(self):
        # mode=cloud but the key file is missing: honest config error inside
        # load_client, and ollama_chat falls back to the local path (which
        # here is unavailable -> None, the existing honest contract).
        self.write_cloud_config(provider="qwen")
        cfg = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        os.unlink(cfg["api_key_file"])
        with patch.object(project_digest, "_post_json", side_effect=OSError("no local ollama")):
            self.assertIsNone(project_digest.ollama_chat("question?"))


class TestUaBridgeRunFlags(UaTestCase):
    def test_missing_state_file_yields_no_flags(self):
        self.assertEqual(ua_bridge._indexer_run_flags(self.root, "demo"), {})

    def test_malformed_state_file_yields_no_flags(self):
        (self.root / "demo.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(ua_bridge._indexer_run_flags(self.root, "demo"), {})

    def test_local_mode_state_surfaces_mode_only(self):
        (self.root / "demo.json").write_text(json.dumps(
            {"grant": "g", "root": "demo", "stats": {}, "ua_mode": "local"}), encoding="utf-8")
        self.assertEqual(ua_bridge._indexer_run_flags(self.root, "demo"),
                         {"ua_mode": "local"})

    def test_broken_cloud_state_surfaces_both_flags(self):
        (self.root / "demo.json").write_text(json.dumps(
            {"grant": "g", "root": "demo", "stats": {},
             "ua_mode": "cloud", "cloud_enrich_broken": True}), encoding="utf-8")
        self.assertEqual(ua_bridge._indexer_run_flags(self.root, "demo"),
                         {"ua_mode": "cloud", "cloud_enrich_broken": True})


if __name__ == "__main__":
    unittest.main()
