"""POST /api/ua/query — the unified UA graph query door (2026-10-19).

Contract under test (owner plan, iron rules):

- the same caller tiers as /api/projects (loopback X-Agent-Member voice
  tier here; no credential -> 401, invisible project -> 404);
- ``operation`` is optional: the deterministic keyword inference fills
  it from the question;
- targets are resolved by CODE against the project's UA graph — the
  ambiguous case answers the structured clarify payload (candidates),
  the zero-candidate case answers an honest not_found, and neither ever
  fabricates evidence;
- every success path returns contract KnowledgeEvidence records (six
  frozen fields + permission_checked=true) with source ua-graph:<pid>.

Offline: fake HomeHub stand-in, fixture graph in the state root, fixture
knowledge items in the output store. No Ollama.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import query_api  # noqa: E402


def member_context(member: str, projects=("demo-project",)) -> dict:
    return {
        "principalId": member,
        "sessionId": f"session-{member}",
        "jarvisNodeId": "jetson-1",
        "projectScopes": list(projects),
        "sourceScopes": [f"connector:{p}" for p in projects],
        "grantEpoch": f"epoch-{member}",
        "policyDigest": f"sha256:policy-{member}",
        "expiresAt": "2099-01-01T00:00:00Z",
        "auditId": f"audit-{member}",
    }


class _FakeHomeHubHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        member = (parse_qs(urlparse(self.path).query).get("member") or [None])[0]
        payload = self.server.context_for(member)
        body = json.dumps({"status": "ok", "accessContext": payload}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        return


class FakeHomeHub(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _FakeHomeHubHandler)
        self.member_payloads: dict = {}

    def context_for(self, member):
        if member is None:
            return {"principalId": "jetson-box", "projectScopes": ["*"],
                    "sourceScopes": ["*"], "grantEpoch": "e",
                    "expiresAt": "2099-01-01T00:00:00Z"}
        return self.member_payloads.get(member, member_context(member))


def fixture_graph() -> dict:
    return {
        "version": "g-test-1",
        "project": {"name": "demo-project", "languages": ["python"],
                    "analyzedAt": "2026-10-19T10:00:00.000Z"},
        "nodes": [
            {"id": "file:src/sig_helper.py", "type": "file", "name": "sig_helper.py",
             "filePath": "src/sig_helper.py",
             "summary": "Manages trust-root keys for HMAC signing delegation operations.",
             "tags": ["python"]},
            {"id": "file:src/client.py", "type": "file", "name": "client.py",
             "filePath": "src/client.py",
             "summary": "Signs requests with the delegation key before sending.",
             "tags": []},
            {"id": "file:src/util/format.py", "type": "file", "name": "format.py",
             "filePath": "src/util/format.py", "summary": "String helpers.", "tags": []},
            {"id": "file:src/legacy/format.py", "type": "file", "name": "format.py",
             "filePath": "src/legacy/format.py", "summary": "Legacy string helpers.", "tags": []},
            {"id": "function:src/sig_helper.py:load_key", "type": "function",
             "name": "load_key", "filePath": "src/sig_helper.py",
             "lineRange": [10, 42], "summary": "load_key in src/sig_helper.py", "tags": []},
        ],
        "edges": [
            {"source": "file:src/sig_helper.py",
             "target": "function:src/sig_helper.py:load_key", "type": "contains"},
            {"source": "file:src/client.py", "target": "file:src/sig_helper.py",
             "type": "imports"},
            {"source": "file:src/util/format.py", "target": "file:src/sig_helper.py",
             "type": "imports"},
        ],
    }


class UaQueryEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        output = root / "output" / "demo-project"
        output.mkdir(parents=True)
        now = time.time()
        for name, purpose, age_days in (
            ("src__sig_helper.py", "Manages trust-root keys for HMAC signing.", 0.2),
            ("src__client.py", "Signs requests before sending.", 1.5),
        ):
            (output / (name + ".knowledge.json")).write_text(json.dumps({
                "file": name.replace("__", "/").rsplit(".", 1)[0] + ".py",
                "version": {"mtime": now - age_days * 86400},
                "verdict": "quick-summary",
                "analyzed_at": "2026-10-18T00:00:00Z",
                "derived": {"purpose": purpose},
            }), encoding="utf-8")
        ua_dir = root / "state" / "demo-project" / "ua"
        ua_dir.mkdir(parents=True)
        (ua_dir / "knowledge-graph.json").write_text(
            json.dumps(fixture_graph()), encoding="utf-8")
        self.env_old = {key: os.environ.get(key) for key in (
            "UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_ACCESS_CONTEXT_FILE",
            "UYP_HOMEHUB_ACCESS_CONTEXT_URL", "UYP_HOMEHUB_TOKEN_FILE")}
        os.environ["UYP_OUTPUT_ROOT"] = str(root / "output")
        os.environ["UYP_STATE_ROOT"] = str(root / "state")
        os.environ.pop("UYP_ACCESS_CONTEXT_FILE", None)
        os.environ.pop("UYP_HOMEHUB_ACCESS_CONTEXT_URL", None)
        os.environ.pop("UYP_HOMEHUB_TOKEN_FILE", None)
        # Fresh caches per test (the module-level graph/registry caches
        # key on mtime/size, but an empty state root must not inherit a
        # previous test's parsed graph object).
        query_api._ua_graph_cache.clear()
        homehub = FakeHomeHub()
        threading.Thread(target=homehub.serve_forever, daemon=True).start()
        self.addCleanup(homehub.server_close)
        self.addCleanup(homehub.shutdown)
        os.environ["UYP_HOMEHUB_ACCESS_CONTEXT_URL"] = (
            "http://127.0.0.1:%d/api/uyp/access-context" % homehub.server_address[1])
        token_file = root / "homehub.token"
        token_file.write_text("box-token\n", encoding="utf-8")
        os.environ["UYP_HOMEHUB_TOKEN_FILE"] = str(token_file)
        self.homehub = homehub
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

    def _post(self, body, headers=None):
        request = urllib.request.Request(
            "http://127.0.0.1:%d/api/ua/query" % self.api.server_address[1],
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    # ---- credential model ------------------------------------------------

    def test_no_credential_fails_closed(self):
        status, body = self._post({"operation": "summary"})
        self.assertEqual(status, 401)
        self.assertFalse(body["ok"])

    def test_member_without_grant_is_denied(self):
        self.homehub.member_payloads["ly"] = None  # HomeHub denies ly
        status, body = self._post(
            {"operation": "summary", "project": "demo-project"},
            headers={"X-Agent-Member": "ly"})
        self.assertEqual(status, 403)

    def test_invisible_project_is_404(self):
        status, body = self._post(
            {"operation": "summary", "project": "secret-project"},
            headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "project_not_found")

    # ---- operations ------------------------------------------------------

    def test_summary_named_project(self):
        status, body = self._post(
            {"operation": "summary", "project": "demo-project"},
            headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["evidence"])
        record = body["evidence"][0]
        for key in ("source_id", "source_version", "locator", "content",
                    "permission_checked", "retrieved_at"):
            self.assertIn(key, record)
        self.assertTrue(record["permission_checked"])
        self.assertEqual(record["source_id"], "ua-graph:demo-project")

    def test_recent_changes_inferred_from_question(self):
        status, body = self._post(
            {"question": "what did I add to the demo-project project?"},
            headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 200)
        self.assertEqual(body["operation"], "recent_changes")
        self.assertEqual(body["status"], "ok")
        files = [record["locator"] for record in body["evidence"]]
        self.assertIn("src/sig_helper.py", files)
        self.assertIn("indexJob", body)

    def test_dependents_returns_importers_with_edges(self):
        status, body = self._post(
            {"question": "which files import sig_helper?",
             "project": "demo-project"},
            headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 200)
        self.assertEqual(body["operation"], "dependents")
        joined = " ".join(r["content"] for r in body["evidence"])
        self.assertIn("client.py imports src/sig_helper.py", joined)
        edge_ids = [e for r in body["evidence"] for e in r.get("edge_ids", [])]
        self.assertTrue(any("[imports]" in e for e in edge_ids))

    def test_explain_with_active_node_session_context(self):
        status, body = self._post(
            {"operation": "explain", "project": "demo-project",
             "question": "explain this file",
             "activeNodeId": "file:src/sig_helper.py"},
            headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["resolution"]["nodeId"], "file:src/sig_helper.py")
        self.assertEqual(body["resolution"]["resolution"], "session_active")
        joined = " ".join(r["content"] for r in body["evidence"])
        self.assertIn("HMAC signing delegation", joined)

    def test_ambiguous_filename_is_structured_clarify(self):
        status, body = self._post(
            {"operation": "dependents", "project": "demo-project",
             "target": {"query": "format.py"}},
            headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ambiguous")
        self.assertEqual(len(body["resolution"]["candidates"]), 2)
        self.assertEqual(body["evidence"], [])

    def test_not_found_is_honest_empty(self):
        status, body = self._post(
            {"operation": "explain", "project": "demo-project",
             "target": {"query": "quantum flux capacitor"}},
            headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "not_found")
        self.assertEqual(body["evidence"], [])

    def test_no_context_deictic_ask_clarifies(self):
        status, body = self._post(
            {"operation": "explain", "project": "demo-project",
             "target": {"query": "this file"}},
            headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "no_context")
        self.assertEqual(body["evidence"], [])

    def test_unnamed_project_autoselects_single_visible(self):
        status, body = self._post(
            {"operation": "locate", "target": {"query": "load_key"}},
            headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 200)
        self.assertEqual(body["projectId"], "demo-project")
        self.assertEqual(body["status"], "ok")
        self.assertIn("L10-L42", body["evidence"][0]["locator"])

    def test_bad_operation_rejected(self):
        status, body = self._post(
            {"operation": "speculate", "project": "demo-project"},
            headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_operation")

    def test_missing_question_and_operation_rejected(self):
        status, body = self._post(
            {"project": "demo-project"}, headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "question_or_operation_required")

    def test_last_target_id_session_continuation(self):
        status, body = self._post(
            {"operation": "explain", "project": "demo-project",
             "target": {"query": "it"},
             "lastTargetId": "file:src/sig_helper.py"},
            headers={"X-Agent-Member": "felix"})
        self.assertEqual(status, 200)
        self.assertEqual(body["resolution"]["resolution"], "session_last")
        self.assertEqual(body["status"], "ok")


if __name__ == "__main__":
    unittest.main()
