"""HTTP contract for /api/projects* and the group member_id binding fix.

Real query API on an ephemeral loopback port; HomeHub is a fake loopback
server answering /api/uyp/access-context (per bearer, or per ?member= for
the box's service token) and /api/members (roles).  No credential, an
unresolvable bearer, or a member without grants fails closed.
"""

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import projects  # noqa: E402
import query_api  # noqa: E402
from test_projects import ConnectorMixin, FixtureMixin, RecordingLauncher  # noqa: E402

MEMBERS = [{"member_id": "robin", "role": "owner"}, {"member_id": "ly", "role": "member"}]


def access_context(principal, projects_=("commontasks",)):
    return {
        "principalId": principal, "sessionId": f"s-{principal}", "jarvisNodeId": "hub-1",
        "projectScopes": list(projects_), "sourceScopes": [f"connector:{p}" for p in projects_],
        "grantEpoch": "7", "policyDigest": "sha256:x", "expiresAt": "2099-01-01T00:00:00Z",
        "auditId": f"audit-{principal}",
    }


class _HomeHubHandler(BaseHTTPRequestHandler):
    def _json(self, value, status=200):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        server = self.server
        auth = self.headers.get("Authorization") or ""
        token = auth[7:] if auth.startswith("Bearer ") else ""
        server.seen.append((self.path, token))
        caller = server.tokens.get(token)
        if caller is None:
            return self._json({"detail": "Invalid or revoked token"}, 401)
        url = urlparse(self.path)
        if url.path == "/api/members":
            return self._json(MEMBERS)
        if url.path == "/api/uyp/access-context":
            member = (parse_qs(url.query).get("member") or [None])[0]
            principal = member or caller
            return self._json({"status": "ok", "accessContext": server.contexts.get(principal, access_context(principal, ()))})
        return self._json({"detail": "not found"}, 404)

    def log_message(self, *_args):
        return


class FakeHomeHub(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _HomeHubHandler)
        self.tokens = {"tok-robin": "robin", "tok-ly": "ly", "box-token": "robin"}
        self.contexts = {"robin": access_context("robin"), "ly": access_context("ly", ())}
        self.seen = []


class ProjectsApiTests(FixtureMixin, ConnectorMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._env_extra = {k: os.environ.get(k) for k in (
            "UYP_HOMEHUB_ACCESS_CONTEXT_URL", "UYP_HOMEHUB_TOKEN_FILE", "UYP_ACCESS_CONTEXT_FILE",
            "UYP_OWNER_MEMBER", "UYP_HOMEHUB_MEMBERS_URL")}
        for key in self._env_extra:
            os.environ.pop(key, None)
        self.commontasks()
        self.homehub = FakeHomeHub()
        threading.Thread(target=self.homehub.serve_forever, daemon=True).start()
        self.addCleanup(self.homehub.server_close)
        self.addCleanup(self.homehub.shutdown)
        os.environ["UYP_HOMEHUB_ACCESS_CONTEXT_URL"] = "http://127.0.0.1:%d/api/uyp/access-context" % self.homehub.server_address[1]
        token_file = self.root / "homehub.token"
        token_file.write_text("box-token\n", encoding="utf-8")
        os.environ["UYP_HOMEHUB_TOKEN_FILE"] = str(token_file)
        query_api._ROLE_CACHE.clear()
        self.api = ThreadingHTTPServer(("127.0.0.1", 0), query_api.QueryHandler)
        self.api.loopback_voice = True
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.addCleanup(self.api.server_close)
        self.addCleanup(self.api.shutdown)

    def tearDown(self):
        for key, value in self._env_extra.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        super().tearDown()

    def request(self, method, path, body=None, headers=None, token="tok-robin"):
        all_headers = {"Content-Type": "application/json", **(headers or {})}
        if token:
            all_headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.api.server_address[1], path),
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=all_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    # ---- context resolution ------------------------------------------------

    def test_bearer_lists_only_granted_projects(self):
        status, body = self.request("GET", "/api/projects")
        self.assertEqual(status, 200)
        self.assertEqual([p["project_id"] for p in body["projects"]], ["commontasks"])
        self.assertEqual(body["tree"], [{"project_id": "commontasks", "children": []}])
        self.assertIn(("/api/uyp/access-context", "tok-robin"), self.homehub.seen)
        # ly has no grant for it: empty listing, not an error.
        status, body = self.request("GET", "/api/projects", token="tok-ly")
        self.assertEqual((status, body), (200, {"projects": [], "tree": [], "folder_tree": []}))

    def test_fail_closed_without_or_with_bad_credentials(self):
        status, body = self.request("GET", "/api/projects", token=None)
        self.assertEqual((status, body["error"]), (401, "credentials_required"))
        status, body = self.request("GET", "/api/projects", token="forged")
        self.assertEqual((status, body["error"]), (401, "invalid_credentials"))
        # A service-level context file must NOT open the projects surface.
        context_file = self.root / "box.json"
        context_file.write_text(json.dumps(access_context("robin")), encoding="utf-8")
        os.environ["UYP_ACCESS_CONTEXT_FILE"] = str(context_file)
        status, body = self.request("GET", "/api/projects/commontasks", token=None)
        self.assertEqual(status, 401)
        os.environ.pop("UYP_HOMEHUB_ACCESS_CONTEXT_URL")
        status, body = self.request("GET", "/api/projects")
        self.assertEqual((status, body["error"]), (503, "access_context_unavailable"))

    def test_loopback_member_tier(self):
        status, body = self.request("GET", "/api/projects", token=None, headers={"X-Agent-Member": "robin"})
        self.assertEqual(status, 200)
        self.assertEqual([p["project_id"] for p in body["projects"]], ["commontasks"])
        self.assertIn(("/api/uyp/access-context?member=robin", "box-token"), self.homehub.seen)
        # A member with no grants is honestly denied.
        status, body = self.request("GET", "/api/projects", token=None, headers={"X-Agent-Member": "ly"})
        self.assertEqual((status, body["error"]), (403, "member_access_denied"))
        # Never admitted on a non-loopback bind.
        self.api.loopback_voice = False
        status, body = self.request("GET", "/api/projects", token=None, headers={"X-Agent-Member": "robin"})
        self.assertEqual((status, body["error"]), (401, "credentials_required"))

    # ---- read endpoints ------------------------------------------------------

    def test_digest_activity_and_scope(self):
        status, body = self.request("GET", "/api/projects/commontasks")
        self.assertEqual(status, 200)
        self.assertEqual(body["project"]["project_id"], "commontasks")
        self.assertTrue(body["overview"])
        self.assertEqual(body["activity"]["window"], "7d")
        status, body = self.request("GET", "/api/projects/commontasks/activity?since=2000-01-01T00:00:00Z")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["changed"]), 7)
        self.assertEqual(set(body), {"changed"})
        status, body = self.request("GET", "/api/projects/commontasks/activity?since=nonsense")
        self.assertEqual((status, body["error"]), (400, "invalid_window"))
        status, body = self.request("GET", "/api/projects/commontasks", token="tok-ly")
        self.assertEqual((status, body["error"]), (404, "project_not_found"))
        status, body = self.request("GET", "/api/projects/ghost")
        self.assertEqual(status, 404)

    def test_studio_projection_uses_request_bearer_and_never_process_context(self):
        status, body = self.request("GET", "/api/studio/snapshot")
        self.assertEqual(status, 200)
        self.assertEqual(body["project"]["name"], "commontasks")
        status, body = self.request("GET", "/api/studio/snapshot", token="tok-ly")
        self.assertEqual(status, 200)
        self.assertEqual(body["project"]["name"], "Project scope unavailable")
        self.assertNotIn("graph", body)

        # Even if a stale process-level projection exists, browser Studio
        # calls without a caller bearer cannot read it.
        context_file = self.root / "box.json"
        context_file.write_text(json.dumps(access_context("robin")), encoding="utf-8")
        os.environ["UYP_ACCESS_CONTEXT_FILE"] = str(context_file)
        status, body = self.request("GET", "/api/studio/snapshot", token=None)
        self.assertEqual((status, body["error"]), (401, "credentials_required"))
        status, body = self.request("GET", "/api/sources", token=None)
        self.assertEqual((status, body["error"]), (401, "credentials_required"))

    def test_graph_is_caller_scoped_bounded_and_source_redacted(self):
        graph_path = self.root / "state" / "commontasks" / "ua" / "knowledge-graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        graph["nodes"].append({
            "id": "article:notes", "type": "article", "name": "notes",
            "filePath": "docs/notes.md", "knowledgeMeta": {"content": "private source bytes"},
            "summary": "A generated note", "tags": [], "complexity": "simple",
        })
        graph["nodes"].extend({
            "id": f"file:generated/{index}.py", "type": "file", "name": f"generated-{index}",
            "filePath": f"generated/{index}.py",
        } for index in range(505))
        graph["edges"].extend({
            "source": "file:src/app.py", "target": f"file:generated/{index}.py", "type": "imports",
        } for index in range(1005))
        graph_path.write_text(json.dumps(graph), encoding="utf-8")

        status, body = self.request("GET", "/api/projects/commontasks/graph")
        self.assertEqual(status, 200)
        self.assertEqual(body["projectId"], "commontasks")
        self.assertEqual(body["counts"]["nodes"], 510)
        self.assertEqual(body["counts"]["edges"], 1008)
        self.assertEqual(len(body["nodes"]), query_api.MAX_GRAPH_NODES)
        self.assertEqual(len(body["edges"]), query_api.MAX_GRAPH_EDGES)
        self.assertTrue(body["truncated"]["nodes"] and body["truncated"]["edges"])
        article = next(node for node in body["nodes"] if node["id"] == "article:notes")
        self.assertNotIn("content", article.get("knowledgeMeta", {}))
        self.assertEqual(set(body), {"projectId", "version", "kind", "project", "nodes", "edges",
                                     "layers", "tour", "counts", "truncated"})

        # HomeHub's per-member context is the authorization boundary; a member
        # without this project sees an opaque 404, just like the digest route.
        status, body = self.request("GET", "/api/projects/commontasks/graph", token="tok-ly")
        self.assertEqual((status, body["error"]), (404, "project_not_found"))

    def test_ask_endpoint(self):
        calls = []

        def fake_ask(context, project_id, question, *, member=None, role=None):
            calls.append((context["principalId"], project_id, question, member, role))
            return {"answer": "In src/db.py.", "sources": [{"file": "src/db.py"}], "confidence": "high"}

        with patch.object(query_api.project_digest, "ask", fake_ask):
            status, body = self.request("POST", "/api/projects/commontasks/ask", {"question": "where is sqlite?"})
            self.assertEqual(status, 200)
            self.assertEqual(body["answer"], "In src/db.py.")
            self.assertEqual(calls, [("robin", "commontasks", "where is sqlite?", "robin", "owner")])
            status, body = self.request("POST", "/api/projects/commontasks/ask", {"question": " "})
            self.assertEqual((status, body["error"]), (400, "question_required"))

    def test_ask_out_of_scope_is_404(self):
        status, body = self.request("POST", "/api/projects/commontasks/ask", {"question": "sqlite"}, token="tok-ly")
        self.assertEqual(status, 404)

    # ---- analyze / jobs ------------------------------------------------------

    def test_analyze_is_owner_only_and_returns_202(self):
        self.start_connector()
        launcher = RecordingLauncher()
        real = query_api.project_jobs.create_analyze_job

        def create(path, device_id=None, **kwargs):
            return real(path, device_id, launcher=launcher, **kwargs)

        with patch.object(query_api.project_jobs, "create_analyze_job", create):
            status, body = self.request("POST", "/api/projects/analyze", {"path": "~/code/newproj"}, token="tok-ly")
            self.assertEqual((status, body["error"]), (403, "owner_session_required"))
            status, body = self.request("POST", "/api/projects/analyze", {"path": "~/code/newproj", "device_id": "d_mac"})
            self.assertEqual(status, 202)
            self.assertEqual(body["project_id"], "newproj")
            self.assertEqual(body["status"], "queued")
            self.assertEqual(body["relation"], {"parent_id": None, "children": []})
            self.assertEqual(launcher.calls[0][0]["actor"], "robin")
            status, err = self.request("POST", "/api/projects/analyze", {"path": "../x"})
            self.assertEqual((status, err["error"]), (400, "invalid_path"))
        # The owner sees the job even before a grant for the new project exists.
        status, job = self.request("GET", f"/api/projects/jobs/{body['job_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(set(job), {"job_id", "project_id", "status", "phase", "progress", "log_tail"})
        self.assertEqual(job["status"], "queued")
        # A member without a grant for that project cannot read it.
        status, _ = self.request("GET", f"/api/projects/jobs/{body['job_id']}", token="tok-ly")
        self.assertEqual(status, 404)
        status, _ = self.request("GET", "/api/projects/jobs/job_000000000000")
        self.assertEqual(status, 404)

    def test_owner_pin_counts_as_owner_without_members_lookup(self):
        os.environ["UYP_OWNER_MEMBER"] = "ly"
        status, body = self.request("GET", "/api/projects/ids", token="tok-ly")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"project_ids": ["commontasks"]})
        self.assertNotIn("/api/members", [path for path, _ in self.homehub.seen])

    def test_ids_lists_every_registered_project_for_owner_only(self):
        status, body = self.request("GET", "/api/projects/ids")
        self.assertEqual((status, body), (200, {"project_ids": ["commontasks"]}))
        self.assertIn(("/api/members", "tok-robin"), self.homehub.seen)
        status, body = self.request("GET", "/api/projects/ids", token="tok-ly")
        self.assertEqual((status, body["error"]), (403, "owner_session_required"))


class GroupMemberBindingTests(unittest.TestCase):
    """member_id in a group body/query is bound to the caller's credential."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        project = root / "output" / "demo-project"
        project.mkdir(parents=True)
        (project / "src__main.py.knowledge.json").write_text(json.dumps({
            "file": "src/main.py", "version": {"mtime": 1}, "verdict": "quick-summary",
            "derived": {"purpose": "Entry point"}}), encoding="utf-8")
        self._env = {k: os.environ.get(k) for k in (
            "UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_GROUPS_FILE", "UYP_ACCESS_CONTEXT_FILE",
            "UYP_HOMEHUB_ACCESS_CONTEXT_URL", "UYP_HOMEHUB_TOKEN_FILE", "UYP_OWNER_MEMBER")}
        for key in self._env:
            os.environ.pop(key, None)
        os.environ["UYP_OUTPUT_ROOT"] = str(root / "output")
        os.environ["UYP_STATE_ROOT"] = str(root / "state")
        os.environ["UYP_GROUPS_FILE"] = str(root / "state" / "groups.json")
        self.homehub = FakeHomeHub()
        self.homehub.contexts["ly"] = access_context("ly", ("demo-project",))
        threading.Thread(target=self.homehub.serve_forever, daemon=True).start()
        self.addCleanup(self.homehub.server_close)
        self.addCleanup(self.homehub.shutdown)
        os.environ["UYP_HOMEHUB_ACCESS_CONTEXT_URL"] = "http://127.0.0.1:%d/api/uyp/access-context" % self.homehub.server_address[1]
        context_file = root / "box.json"
        context_file.write_text(json.dumps(access_context("felix", ("*",))), encoding="utf-8")
        self.box_context_file = str(context_file)
        query_api.group_registry().upsert({
            "group_id": "group:demo", "name": "Demo", "owner_member": "robin", "member_members": ["robin", "ly"],
            "knowledge_view": {"project_ids": ["demo-project"], "source_ids": ["connector:demo-project"]}})
        self.searches = []

        def fake_answer(question, items):
            self.searches.append(list(items))
            return {"answer": "ok", "sources": [], "confidence": "high"}

        patcher = patch.object(query_api, "search_answer", fake_answer)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.api = ThreadingHTTPServer(("127.0.0.1", 0), query_api.QueryHandler)
        self.api.loopback_voice = True
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.addCleanup(self.api.server_close)
        self.addCleanup(self.api.shutdown)

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        with __import__("contextlib").suppress(OSError):
            os.remove(query_api.INTERACTIVE_LOCK)
        self.tmp.cleanup()

    def search(self, body, headers=None):
        request = urllib.request.Request(
            "http://127.0.0.1:%d/api/groups/group:demo/search" % self.api.server_address[1],
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def messages(self, query, headers=None):
        request = urllib.request.Request(
            "http://127.0.0.1:%d/api/groups/group:demo/messages?%s" % (self.api.server_address[1], query),
            headers=headers or {}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def test_bearer_cannot_impersonate_another_member(self):
        status, body = self.search({"query": "entry", "member_id": "robin"}, {"Authorization": "Bearer tok-ly"})
        self.assertEqual((status, body["error"]), (403, "member_mismatch"))
        self.assertEqual(self.searches, [])
        status, body = self.messages("member_id=robin", {"Authorization": "Bearer tok-ly"})
        self.assertEqual((status, body["error"]), (403, "member_mismatch"))

    def test_bearer_resolves_its_own_member(self):
        status, body = self.search({"query": "entry"}, {"Authorization": "Bearer tok-ly"})
        self.assertEqual(status, 200)
        self.assertEqual(body["memberId"], "ly")
        status, body = self.search({"query": "entry", "member_id": "member:ly"}, {"Authorization": "Bearer tok-ly"})
        self.assertEqual((status, body["memberId"]), (200, "ly"))

    def test_unresolvable_bearer_never_falls_back_to_body_member(self):
        status, body = self.search({"query": "entry", "member_id": "robin"}, {"Authorization": "Bearer forged"})
        self.assertEqual((status, body["error"]), (401, "invalid_credentials"))
        self.assertEqual(self.searches, [])

    def test_voice_member_header_must_agree_with_body(self):
        status, body = self.search({"query": "entry", "member_id": "robin"}, {"X-Agent-Member": "ly"})
        self.assertEqual((status, body["error"]), (403, "member_mismatch"))

    def test_browser_origin_cannot_assert_a_member_without_credentials(self):
        os.environ["UYP_ACCESS_CONTEXT_FILE"] = self.box_context_file
        status, body = self.search({"query": "entry", "member_id": "robin"}, {"Origin": "http://evil.example"})
        self.assertEqual((status, body["error"]), (403, "member_assertion_refused"))
        self.assertEqual(self.searches, [])
        # Same assertion from a loopback machine caller (no Origin) keeps working.
        status, body = self.search({"query": "entry", "member_id": "ly"})
        self.assertEqual((status, body["memberId"]), (200, "ly"))

    def test_non_loopback_bind_requires_principal_match(self):
        # Service tier: the box's own projection file (no HomeHub URL).
        os.environ.pop("UYP_HOMEHUB_ACCESS_CONTEXT_URL")
        os.environ["UYP_ACCESS_CONTEXT_FILE"] = self.box_context_file
        self.api.loopback_voice = False
        status, body = self.search({"query": "entry", "member_id": "ly"})
        self.assertEqual((status, body["error"]), (403, "member_assertion_refused"))
        status, body = self.search({"query": "entry", "member_id": "felix"})
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
