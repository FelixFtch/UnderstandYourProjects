"""Voice handshake contract for the query API (2026-10-10, per-member pass).

The box's agent-runtime voice chain calls ``POST /api/knowledge/search``
on loopback with ``X-Agent-Member`` identity headers and no Bearer - it
must never hold this service's credentials.  The service therefore acts
as the box for those calls (``UYP_HOMEHUB_ACCESS_CONTEXT_URL`` +
``UYP_HOMEHUB_TOKEN_FILE``, exactly like the indexer worker) and asks
HomeHub to resolve the SPEAKING MEMBER's own grant scopes: a member with
a grant is served under her scopes, a member without one is honestly
denied (403), and the box context is never a fallback.  A
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
from urllib.parse import parse_qs, urlparse

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


def member_context(member: str, projects=("demo-project",)) -> dict:
    """A HomeHub member-scoped projection: principalId IS the member."""
    return {
        "principalId": member,
        "sessionId": f"session-{member}",
        "jarvisNodeId": "jetson-1",
        "projectScopes": list(projects),
        "sourceScopes": [f"connector:{project}" for project in projects],
        "grantEpoch": f"epoch-{member}",
        "policyDigest": f"sha256:policy-{member}",
        "expiresAt": "2099-01-01T00:00:00Z",
        "auditId": f"audit-{member}",
    }


class _FakeHomeHubHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.server.seen_requests.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
        })
        member = (parse_qs(urlparse(self.path).query).get("member") or [None])[0]
        payload = self.server.context_for(member)
        body = json.dumps(
            {"status": "ok", "accessContext": payload}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        return


class FakeHomeHub(ThreadingHTTPServer):
    """Loopback stand-in for HomeHub's /api/uyp/access-context route.

    Mirrors the HomeHub contract: a ``member`` query parameter resolves
    THAT member's projection; without one the caller (the box service
    bearer) gets its own context.
    """

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _FakeHomeHubHandler)
        self.box_payload = box_context()
        self.member_payloads: dict = {}
        self.seen_requests: list = []

    def context_for(self, member):
        if member is None:
            return self.box_payload
        return self.member_payloads.get(member, member_context(member))


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

    def _configure_box_token(self) -> None:
        token_file = Path(self.tmp.name) / "homehub.token"
        token_file.write_text("box-token\n", encoding="utf-8")
        os.environ["UYP_HOMEHUB_TOKEN_FILE"] = str(token_file)

    def test_voice_member_header_resolves_member_scoped_context(self):
        homehub = self._start_homehub()
        self._configure_box_token()
        status, body = self._post_search(
            {"query": "哪里实现了委托签名"}, headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("answer", body)
        self.assertEqual(body["sources"][0]["file"], "src/main.py")
        self.assertEqual(body["access"]["grantEpoch"], "epoch-felix")
        # The SERVICE acted as the box (its own bearer) but selected the
        # SPEAKING MEMBER: HomeHub saw the box bearer plus member=felix,
        # and felix's member context scoped the searched items.
        self.assertEqual(len(homehub.seen_requests), 1)
        self.assertIn("member=felix", homehub.seen_requests[0]["path"])
        self.assertEqual(homehub.seen_requests[0]["authorization"], "Bearer box-token")
        self.assertEqual(len(self.search_calls), 1)
        self.assertEqual(self.search_calls[0]["question"], "哪里实现了委托签名")
        self.assertEqual(len(self.search_calls[0]["items"]), 1)

    def test_voice_member_scoping_hides_projects_the_member_lacks(self):
        homehub = self._start_homehub()
        homehub.member_payloads["ly"] = member_context("ly", projects=("other-project",))
        self._configure_box_token()
        status, body = self._post_search(
            {"query": "哪里实现了委托签名"}, headers={"X-Agent-Member": "ly"})
        # ly is authorized - for a project this box does not hold.  Her
        # scopes filter the store to nothing; the box's demo-project
        # context must NOT widen the search back.
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["sources"], [])
        self.assertEqual(self.search_calls[0]["items"], [])

    def test_voice_member_without_grants_is_honestly_denied(self):
        homehub = self._start_homehub()
        homehub.member_payloads["ly"] = member_context("ly", projects=())
        self._configure_box_token()
        status, body = self._post_search(
            {"query": "哪里实现了委托签名"}, headers={"X-Agent-Member": "ly"})
        # HomeHub answered with a valid EMPTY context: that is this
        # member's honest denial, never a fallback to the box scopes.
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "member_access_denied")
        self.assertEqual(self.search_calls, [])
        self.assertIn("member=ly", homehub.seen_requests[0]["path"])

    def test_voice_member_projection_for_another_principal_is_denied(self):
        # The bug class this pass closes: HomeHub answering a member
        # request with the BOX's own context (any principal other than the
        # requested member) must deny, never serve the box scopes.
        homehub = self._start_homehub()
        homehub.member_payloads["ly"] = box_context()
        self._configure_box_token()
        status, body = self._post_search(
            {"query": "哪里实现了委托签名"}, headers={"X-Agent-Member": "ly"})
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "member_access_denied")
        self.assertEqual(self.search_calls, [])

    def test_no_member_header_keeps_today_box_service_path(self):
        homehub = self._start_homehub()
        self._configure_box_token()
        status, body = self._post_search({"query": "哪里实现了委托签名"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["sources"][0]["file"], "src/main.py")
        self.assertEqual(body["access"]["grantEpoch"], "epoch-1")
        self.assertEqual(len(self.search_calls[0]["items"]), 1)
        # No member header: HomeHub saw the plain box request, no selector.
        self.assertEqual(len(homehub.seen_requests), 1)
        self.assertNotIn("member=", homehub.seen_requests[0]["path"])
        self.assertEqual(homehub.seen_requests[0]["authorization"], "Bearer box-token")

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
        self.assertEqual(homehub.seen_requests[0]["authorization"], "Bearer caller-session-token")
        self.assertNotIn("member=", homehub.seen_requests[0]["path"])
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

    # ---- slow-answer hint: headers precede the synthesis body -------------

    def _raw_search_request(self, question):
        import socket
        body = json.dumps({"query": question}).encode("utf-8")
        sock = socket.create_connection(self.api.server_address, timeout=5)
        sock.sendall(
            b"POST /api/knowledge/search HTTP/1.0\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"\r\n" + body)
        return sock

    @staticmethod
    def _recv_headers(sock):
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk:
                break
            head += chunk
        return head

    def test_slow_search_sends_hint_headers_before_the_body(self):
        # Root-cause fix (2026-10-10): a retrieval HIT means qwen synthesis
        # (5-15s + queue wait).  The response HEADERS - including
        # X-UYP-Slow-Hint - must be flushed BEFORE the synthesis runs, so a
        # streaming voice caller can speak a filler while the answer is
        # computed.  The synthesis is held on an event to prove the ordering.
        self._start_homehub()
        self._configure_box_token()
        release = threading.Event()
        synthesis_started = threading.Event()

        def blocking_answer(question, items):
            synthesis_started.set()
            release.wait(timeout=10)
            return {"answer": "slow but grounded", "sources": [], "confidence": "high"}

        with patch.object(query_api, "search_will_synthesize",
                          return_value=True), \
             patch.object(query_api, "search_answer", blocking_answer):
            sock = self._raw_search_request("哪里实现了委托签名")
            head = self._recv_headers(sock)
        self.assertIn(b"X-UYP-Slow-Hint: true", head)
        # headers arrived while the synthesis was still blocked, and no
        # Content-Length frames the body: it ends at connection close
        self.assertTrue(synthesis_started.is_set())
        self.assertNotIn(b"Content-Length", head)
        release.set()
        body = b""
        sock.settimeout(5)
        while True:
            try:
                chunk = sock.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            body += chunk
        sock.close()
        payload = json.loads(body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["answer"], "slow but grounded")

    def test_instant_miss_keeps_normal_framing_without_hint(self):
        # A miss is answered with the canonical sentence instantly: no
        # X-UYP-Slow-Hint, and the body stays framed by Content-Length.
        self._start_homehub()
        self._configure_box_token()
        with patch.object(query_api, "search_will_synthesize",
                          return_value=False):
            request = urllib.request.Request(
                "http://127.0.0.1:%d/api/knowledge/search" % self.api.server_address[1],
                data=json.dumps({"query": "量子退火算法在哪里实现"}).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read())
                self.assertIsNone(response.headers.get("X-UYP-Slow-Hint"))
                self.assertEqual(
                    response.headers.get("Content-Length"),
                    str(len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))))
        self.assertTrue(payload["ok"])


class RequestContextResolutionTests(unittest.TestCase):
    """Unit pins on the resolution order with mocked loads: which tier a
    request takes, including the loopback-bind guard, the member denial
    signal, and the structural no-fallback guarantee."""

    def test_bearer_takes_the_caller_token_tier(self):
        with patch.object(query_api, "load_homehub_context_for_token",
                          return_value={"ctx": "caller"}) as caller_tier, \
             patch.object(query_api, "load_homehub_context",
                          return_value={"ctx": "box"}) as box_tier, \
             patch.object(query_api, "load_homehub_context_for_member",
                          return_value={"ctx": "member"}) as member_tier, \
             patch.object(query_api, "load_access_context",
                          return_value={"ctx": "env"}) as env_tier:
            resolved = query_api.load_request_context(
                {"Authorization": "Bearer tok"}, loopback_voice=True)
        self.assertEqual(resolved, ({"ctx": "caller"}, None))
        caller_tier.assert_called_once_with("tok")
        box_tier.assert_not_called()
        member_tier.assert_not_called()
        env_tier.assert_not_called()

    def test_member_header_takes_member_tier_only_on_loopback(self):
        with patch.object(query_api, "load_homehub_context_for_token",
                          return_value=None) as caller_tier, \
             patch.object(query_api, "load_homehub_context",
                          return_value={"ctx": "box"}) as box_tier, \
             patch.object(query_api, "load_homehub_context_for_member",
                          return_value={"ctx": "member"}) as member_tier, \
             patch.object(query_api, "load_access_context",
                          return_value={"ctx": "env"}) as env_tier:
            resolved = query_api.load_request_context(
                {"X-Agent-Member": "felix"}, loopback_voice=True)
            self.assertEqual(resolved, ({"ctx": "member"}, None))
            member_tier.assert_called_once_with("felix")
            # The box tier is never consulted on the member path: there is
            # no fallback if the member resolution fails.
            box_tier.assert_not_called()
            # Guard off (a --lan bind): the voice tier is NOT admitted;
            # the request keeps today's service-level path.
            resolved = query_api.load_request_context(
                {"X-Agent-Member": "felix"}, loopback_voice=False)
            self.assertEqual(resolved, ({"ctx": "env"}, None))
            env_tier.assert_called_once()
            caller_tier.assert_not_called()

    def test_member_denial_is_reported_not_swallowed(self):
        # The member tier failed: the denial names the member so the
        # caller answers 403 honestly, and the box context stays untouched.
        with patch.object(query_api, "load_homehub_context_for_member",
                          return_value=None) as member_tier, \
             patch.object(query_api, "load_homehub_context",
                          return_value={"ctx": "box"}) as box_tier:
            resolved = query_api.load_request_context(
                {"X-Agent-Member": "ly"}, loopback_voice=True)
        self.assertEqual(resolved, (None, "ly"))
        member_tier.assert_called_once_with("ly")
        box_tier.assert_not_called()

    def test_plain_request_keeps_today_service_path(self):
        with patch.object(query_api, "load_homehub_context_for_token",
                          return_value=None) as caller_tier, \
             patch.object(query_api, "load_homehub_context",
                          return_value={"ctx": "box"}) as box_tier, \
             patch.object(query_api, "load_homehub_context_for_member",
                          return_value={"ctx": "member"}) as member_tier, \
             patch.object(query_api, "load_access_context",
                          return_value={"ctx": "env"}) as env_tier:
            resolved = query_api.load_request_context({}, loopback_voice=True)
        self.assertEqual(resolved, ({"ctx": "env"}, None))
        env_tier.assert_called_once()
        box_tier.assert_not_called()
        member_tier.assert_not_called()
        caller_tier.assert_not_called()


if __name__ == "__main__":
    unittest.main()
