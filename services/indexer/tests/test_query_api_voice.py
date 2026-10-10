"""Voice handshake contract for the query API (2026-10-10).

The box's agent-runtime voice chain calls ``POST /api/knowledge/search``
on loopback with ``X-Agent-Member`` identity headers and no Bearer - it
must never hold this service's credentials.  The service therefore acts
as the box for those calls (``UYP_HOMEHUB_ACCESS_CONTEXT_URL`` +
``UYP_HOMEHUB_TOKEN_FILE``, exactly like the indexer worker), while a
caller-presented Bearer resolves that caller's own projection, and a
credential-less, header-less request keeps failing closed (503).

All servers here are loopback; the HomeHub side is a fake loopback
stand-in and the search synthesis is faked at the query_api seam - no
Ollama, no real knowledge store beyond one fixture item.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import query_api  # noqa: E402


def box_context() -> dict:
    return {
        "principalId": "jetson-box",
        "sessionId": "voice-session",
        "jarvisNodeId": "jetson-1",
        "projectScopes": ["demo-project"],
        "sourceScopes": ["connector:demo-project"],
        "grantEpoch": "epoch-1",
        "policyDigest": "sha256:policy",
        "expiresAt": "2099-01-01T00:00:00Z",
        "auditId": "audit-voice",
    }


class _FakeHomeHubHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.server.seen_authorization.append(self.headers.get("Authorization"))
        body = json.dumps(
            {"status": "ok", "accessContext": self.server.payload}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        return


class FakeHomeHub(ThreadingHTTPServer):
    """Loopback stand-in for HomeHub's /api/uyp/access-context route."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _FakeHomeHubHandler)
        self.payload = box_context()
        self.seen_authorization: list = []


class QueryApiVoiceHandshakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        output = root / "output" / "demo-project"
        output.mkdir(parents=True)
        (output / "src__main.py.knowledge.json").write_text(json.dumps({
            "file": "src/main.py",
            "version": {"mtime": "2026-10-09T12:00:00Z"},
            "verdict": "quick-summary",
            "analyzed_at": "2026-10-09T12:00:00Z",
            "derived": {"purpose": "Entry point"},
        }), encoding="utf-8")
        self.env_old = {key: os.environ.get(key) for key in (
            "UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_ACCESS_CONTEXT_FILE",
            "UYP_HOMEHUB_ACCESS_CONTEXT_URL", "UYP_HOMEHUB_TOKEN_FILE")}
        os.environ["UYP_OUTPUT_ROOT"] = str(root / "output")
        os.environ["UYP_STATE_ROOT"] = str(root / "state")
        os.environ.pop("UYP_ACCESS_CONTEXT_FILE", None)
        os.environ.pop("UYP_HOMEHUB_ACCESS_CONTEXT_URL", None)
        os.environ.pop("UYP_HOMEHUB_TOKEN_FILE", None)
        # Fake search synthesis at the query_api seam: no Ollama, and the
        # scoped items it receives are recorded so tests can assert the
        # resolved context actually filtered the store.
        self.search_calls: list = []

        def fake_search_answer(question, items):
            self.search_calls.append({"question": question, "items": list(items)})
            return {
                "answer": "委托签名在 demo-project 的 src/main.py 附近实现。",
                "sources": [{"file": item["file"], "match": 4.0} for item in items[:2]],
                "confidence": "high",
            }

        patcher = patch.object(query_api, "search_answer", fake_search_answer)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Real query API on an ephemeral loopback port with the
        # loopback-voice guard ON (mirrors main()'s loopback bind).
        self.api = ThreadingHTTPServer(("127.0.0.1", 0), query_api.QueryHandler)
        self.api.loopback_voice = True
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.addCleanup(self.api.server_close)
        self.addCleanup(self.api.shutdown)

    def tearDown(self):
        for key, value in self.env_old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def _post_search(self, body, headers=None):
        request = urllib.request.Request(
            "http://127.0.0.1:%d/api/knowledge/search" % self.api.server_address[1],
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def _start_homehub(self) -> FakeHomeHub:
        homehub = FakeHomeHub()
        threading.Thread(target=homehub.serve_forever, daemon=True).start()
        self.addCleanup(homehub.server_close)
        self.addCleanup(homehub.shutdown)
        os.environ["UYP_HOMEHUB_ACCESS_CONTEXT_URL"] = (
            "http://127.0.0.1:%d/api/uyp/access-context" % homehub.server_address[1])
        return homehub

    def test_voice_member_header_without_bearer_serves_box_context(self):
        homehub = self._start_homehub()
        token_file = Path(self.tmp.name) / "homehub.token"
        token_file.write_text("box-token\n", encoding="utf-8")
        os.environ["UYP_HOMEHUB_TOKEN_FILE"] = str(token_file)
        status, body = self._post_search(
            {"query": "哪里实现了委托签名"}, headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("answer", body)
        self.assertEqual(body["sources"][0]["file"], "src/main.py")
        self.assertEqual(body["access"]["grantEpoch"], "epoch-1")
        # The SERVICE acted as the box: HomeHub saw the box-token bearer,
        # and the box context's projectScopes scoped the searched items.
        self.assertEqual(homehub.seen_authorization, ["Bearer box-token"])
        self.assertEqual(len(self.search_calls), 1)
        self.assertEqual(self.search_calls[0]["question"], "哪里实现了委托签名")
        self.assertEqual(len(self.search_calls[0]["items"]), 1)

    def test_no_bearer_no_header_fails_closed_503(self):
        # No Bearer, no member header, nothing configured: today's
        # fail-closed 503, unchanged.
        status, body = self._post_search({"query": "哪里实现了委托签名"})
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "access_context_unavailable")
        self.assertEqual(self.search_calls, [])

    def test_bearer_request_resolves_callers_own_context(self):
        homehub = self._start_homehub()
        # No token file configured: the CALLER's bearer must reach HomeHub.
        status, body = self._post_search(
            {"query": "where is signing implemented"},
            headers={"Authorization": "Bearer caller-session-token"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(homehub.seen_authorization, ["Bearer caller-session-token"])
        self.assertEqual(len(self.search_calls[0]["items"]), 1)

    def test_bearer_failure_never_falls_back_to_box_context(self):
        # A caller presented credentials and HomeHub is unreachable: fail
        # closed - never silently serve the box context instead.
        os.environ["UYP_HOMEHUB_ACCESS_CONTEXT_URL"] = "http://127.0.0.1:9/unreachable"
        token_file = Path(self.tmp.name) / "homehub.token"
        token_file.write_text("box-token\n", encoding="utf-8")
        os.environ["UYP_HOMEHUB_TOKEN_FILE"] = str(token_file)
        status, body = self._post_search(
            {"query": "where is signing implemented"},
            headers={"Authorization": "Bearer expired-token"})
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "access_context_unavailable")
        self.assertEqual(self.search_calls, [])


class RequestContextResolutionTests(unittest.TestCase):
    """Unit pins on the resolution order with mocked loads: which tier a
    request takes, including the loopback-bind guard."""

    def test_bearer_takes_the_caller_token_tier(self):
        with patch.object(query_api, "load_homehub_context_for_token",
                          return_value={"ctx": "caller"}) as caller_tier, \
             patch.object(query_api, "load_homehub_context",
                          return_value={"ctx": "box"}) as box_tier, \
             patch.object(query_api, "load_access_context",
                          return_value={"ctx": "env"}) as env_tier:
            resolved = query_api.load_request_context(
                {"Authorization": "Bearer tok"}, loopback_voice=True)
            self.assertEqual(resolved, {"ctx": "caller"})
            caller_tier.assert_called_once_with("tok")
            box_tier.assert_not_called()
            env_tier.assert_not_called()

    def test_member_header_takes_box_tier_only_on_loopback(self):
        with patch.object(query_api, "load_homehub_context_for_token",
                          return_value=None) as caller_tier, \
             patch.object(query_api, "load_homehub_context",
                          return_value={"ctx": "box"}) as box_tier, \
             patch.object(query_api, "load_access_context",
                          return_value={"ctx": "env"}) as env_tier:
            resolved = query_api.load_request_context(
                {"X-Agent-Member": "felix"}, loopback_voice=True)
            self.assertEqual(resolved, {"ctx": "box"})
            box_tier.assert_called_once()
            # Guard off (a --lan bind): the voice tier is NOT admitted;
            # the request keeps today's service-level path.
            resolved = query_api.load_request_context(
                {"X-Agent-Member": "felix"}, loopback_voice=False)
            self.assertEqual(resolved, {"ctx": "env"})
            env_tier.assert_called_once()
            caller_tier.assert_not_called()

    def test_plain_request_keeps_today_service_path(self):
        with patch.object(query_api, "load_homehub_context_for_token",
                          return_value=None) as caller_tier, \
             patch.object(query_api, "load_homehub_context",
                          return_value={"ctx": "box"}) as box_tier, \
             patch.object(query_api, "load_access_context",
                          return_value={"ctx": "env"}) as env_tier:
            resolved = query_api.load_request_context({}, loopback_voice=True)
            self.assertEqual(resolved, {"ctx": "env"})
            env_tier.assert_called_once()
            box_tier.assert_not_called()
            caller_tier.assert_not_called()


if __name__ == "__main__":
    unittest.main()
