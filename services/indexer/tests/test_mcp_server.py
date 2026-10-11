"""MCP server contracts (P6 Coding Agent surface, 2026-10).

Pins the stdio MCP server (mcp_server.py) the way the existing query API
tests pin the HTTP surface:

* framing — the JSON-RPC 2.0 / MCP initialize handshake, id echo, tools
  list, notification silence, and the JSON-RPC error shape (-32700,
  -32600, -32601, -32602, pre-initialize -32002);
* surface — exactly the six read-only P6 tools, nothing that mutates;
* per-member scoping — the same fail-closed tiers as the HTTP API
  handshake: a member resolves to her own grant scopes (the voice
  handshake function), a member HomeHub cannot resolve is denied in her
  name, and no principal at all means every tool is denied;
* read-only — a battery of calls over a real temp store leaves every
  output/state byte untouched and creates no registry file.

Search synthesis is faked at the same query_api seam the groups tests
use (no Ollama); scope filtering, graph loading, and job projection run
real.  The HTTP-mode class runs the real query API on an ephemeral
loopback port with the voice guard on, exactly like test_query_api_groups.
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import mcp_server  # noqa: E402
import query_api  # noqa: E402

REPO_ROOT = Path(__file__).parents[3]

SIX_TOOLS = ["index.status", "project.get", "project.related",
             "project.search", "source.locate", "source.read_evidence"]


def member_context(member: str, projects, sources) -> dict:
    return {
        "principalId": member,
        "sessionId": f"session-{member}",
        "jarvisNodeId": "jetson-1",
        "projectScopes": list(projects),
        "sourceScopes": list(sources),
        "grantEpoch": f"epoch-{member}",
        "policyDigest": "sha256:policy",
        "expiresAt": "2099-01-01T00:00:00Z",
        "auditId": f"audit-{member}",
    }


class McpFramingTests(unittest.TestCase):
    """Protocol-level contracts; no store, no principal (calls deny)."""

    def setUp(self):
        self.runner = mcp_server.ToolRunner(principal={"tier": None, "subject": None})
        self.server = mcp_server.McpStdioServer(self.runner)

    def request(self, method, params=None, request_id=1):
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        return self.server.handle_message(message)

    def test_initialize_handshake_and_id_echo(self):
        for request_id in (7, "agent-call-1"):
            response = self.request("initialize", {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "claude-code", "version": "1"},
            }, request_id)
            self.assertEqual(response["jsonrpc"], "2.0")
            self.assertEqual(response["id"], request_id)
            result = response["result"]
            self.assertEqual(result["protocolVersion"], "2025-06-18")
            self.assertIn("tools", result["capabilities"])
            self.assertEqual(result["serverInfo"]["name"], "uyp-mcp")
            # Initialized flag flipped: subsequent requests are admitted.
        self.assertTrue(self.server.initialized)

    def test_initialize_answers_unsupported_version_with_server_default(self):
        response = self.request("initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(response["result"]["protocolVersion"], mcp_server.PROTOCOL_VERSION)

    def test_request_before_initialize_is_rejected(self):
        server = mcp_server.McpStdioServer(self.runner)
        response = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(response["error"]["code"], -32002)

    def test_tools_list_returns_exactly_the_six(self):
        self.request("initialize")
        response = self.request("tools/list")
        names = sorted(tool["name"] for tool in response["result"]["tools"])
        self.assertEqual(names, sorted(SIX_TOOLS))
        for tool in response["result"]["tools"]:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertTrue(tool["description"])

    def test_unknown_method_is_method_not_found(self):
        self.request("initialize")
        response = self.request("resources/list")
        self.assertEqual(response["error"]["code"], -32601)

    def test_unknown_tool_is_invalid_params(self):
        self.request("initialize")
        response = self.request("tools/call", {"name": "shell.exec", "arguments": {}})
        self.assertEqual(response["error"]["code"], -32602)

    def test_notifications_produce_no_response(self):
        self.assertIsNone(self.server.handle_message(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertIsNone(self.server.handle_message(
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}}))

    def test_serve_framing_parse_error_and_batch_rejection(self):
        stream_in = io.StringIO("not json\n"
                                '[{"jsonrpc": "2.0", "id": 1, "method": "ping"}]\n'
                                ' {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}}\n'
                                '\n')
        stream_out = io.StringIO()
        self.server.serve(stream_in, stream_out)
        lines = stream_out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 3)
        parse_error = json.loads(lines[0])
        self.assertIsNone(parse_error["id"])
        self.assertEqual(parse_error["error"]["code"], -32700)
        batch_error = json.loads(lines[1])
        self.assertEqual(batch_error["error"]["code"], -32600)
        initialized = json.loads(lines[2])
        self.assertEqual(initialized["id"], 2)
        self.assertIn("result", initialized)

    def test_ping_and_non_object_message(self):
        self.request("initialize")
        self.assertEqual(self.request("ping", request_id="p1"), {"jsonrpc": "2.0", "id": "p1", "result": {}})
        response = self.server.handle_message([1, 2, 3])
        self.assertEqual(response["error"]["code"], -32600)
        response = self.server.handle_message({"jsonrpc": "2.0", "id": 5})
        self.assertEqual(response["error"]["code"], -32600)


def write_store(root: Path) -> None:
    """Two projects: demo-project (in ly's scope) and other-project (not)."""
    items = {
        ("demo-project", "lib/signing.py"): {
            "file": "lib/signing.py",
            "version": {"mtime": "2026-10-09T12:00:00Z", "size": 1200},
            "verdict": "quick-summary",
            "analyzed_at": "2026-10-09T12:00:00Z",
            "source": "mac-connector",
            "derived": {
                "purpose": "sign_request signs delegation payloads with HMAC.",
                "key_points": ["fact signs the payload header (L5-L20)",
                               "fact verifies the signature (L21-L30)"],
                "components": ["sign_request (L5-L20)", "Signing (L1-L30)"],
            },
            "anchor_top": "sign_request L5-L20",
        },
        ("demo-project", "src/main.py"): {
            "file": "src/main.py",
            "version": {"mtime": "2026-10-09T12:01:00Z", "size": 800},
            "verdict": "quick-summary",
            "analyzed_at": "2026-10-09T12:01:00Z",
            "source": "mac-connector",
            "derived": {
                "purpose": "Entry point wiring the signing chain.",
                "key_points": ["fact main parses argv (L10-L42)"],
                "components": ["main (L10-L42)"],
            },
            "anchor_top": "main L10-L42",
        },
        ("other-project", "lib/other.py"): {
            "file": "lib/other.py",
            "version": {"mtime": "2026-10-09T12:02:00Z", "size": 900},
            "verdict": "quick-summary",
            "analyzed_at": "2026-10-09T12:02:00Z",
            "source": "mac-connector",
            "derived": {
                "purpose": "Memory store with signing helpers.",
                "key_points": ["fact other_fn signs entries (L1-L9)"],
                "components": ["signing (L1-L9)", "other_fn (L1-L9)"],
            },
            "anchor_top": "other_fn L1-L9",
        },
    }
    for (project, relpath), item in items.items():
        project_dir = root / "output" / project
        project_dir.mkdir(parents=True, exist_ok=True)
        stem = relpath.replace("/", "__")
        (project_dir / f"{stem}.knowledge.json").write_text(json.dumps(item), encoding="utf-8")
    graphs = {
        "demo-project": {
            "version": "1.0.0",
            "project": {"name": "demo-project", "languages": ["python"], "frameworks": []},
            "nodes": [
                {"id": "file:lib/signing.py", "type": "file", "filePath": "lib/signing.py"},
                {"id": "file:src/main.py", "type": "file", "filePath": "src/main.py"},
                {"id": "class:lib/signing.py:SigningClass", "type": "class",
                 "filePath": "lib/signing.py", "name": "SigningClass", "lineRange": [1, 30]},
                {"id": "function:lib/signing.py:sign_request", "type": "function",
                 "filePath": "lib/signing.py", "name": "sign_request", "lineRange": [5, 20]},
                {"id": "function:src/main.py:main", "type": "function",
                 "filePath": "src/main.py", "name": "main", "lineRange": [10, 42]},
            ],
            "edges": [
                {"source": "file:src/main.py", "target": "file:lib/signing.py", "type": "import"},
                {"source": "file:lib/signing.py", "target": "function:lib/signing.py:sign_request", "type": "contains"},
            ],
            "layers": [], "tour": [],
        },
        "other-project": {
            "version": "1.0.0",
            "project": {"name": "other-project", "languages": ["python"], "frameworks": []},
            "nodes": [
                {"id": "function:lib/other.py:other_fn", "type": "function",
                 "filePath": "lib/other.py", "name": "other_fn", "lineRange": [1, 9]},
            ],
            "edges": [], "layers": [], "tour": [],
        },
    }
    for project, graph in graphs.items():
        graph_dir = root / "state" / project / "ua"
        graph_dir.mkdir(parents=True, exist_ok=True)
        (graph_dir / "knowledge-graph.json").write_text(json.dumps(graph), encoding="utf-8")
    jobs = root / "state" / "index-jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    (jobs / "job-1.json").write_text(json.dumps({
        "jobId": "job-1", "projectId": "demo-project", "sourceId": "connector:demo-project",
        "phase": "published", "progress": {"processed": 2, "total": 2},
        "updatedAt": "2026-10-09T12:05:00Z",
    }), encoding="utf-8")
    (jobs / "job-2.json").write_text(json.dumps({
        "jobId": "job-2", "projectId": "other-project", "sourceId": "connector:other-project",
        "phase": "running", "progress": {"processed": 0, "total": 1},
        "updatedAt": "2026-10-09T12:06:00Z",
    }), encoding="utf-8")


class McpDirectModeTests(unittest.TestCase):
    """The six tools over the shared query_api functions (no HTTP hop)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_store(self.root)
        self.contexts = {
            "ly": member_context("ly", ["demo-project"], ["connector:demo-project"]),
            "boss": member_context("boss", ["*"], ["*"]),
        }
        self.env_old = {key: os.environ.get(key) for key in (
            "UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_GROUPS_FILE",
            "UYP_ACCESS_CONTEXT_FILE", "UYP_HOMEHUB_ACCESS_CONTEXT_URL",
            "UYP_HOMEHUB_TOKEN_FILE", "UYP_MCP_PRINCIPAL", "UYP_MCP_TOKEN_FILE",
            "UYP_CONNECTOR_HOST")}
        os.environ["UYP_OUTPUT_ROOT"] = str(self.root / "output")
        os.environ["UYP_STATE_ROOT"] = str(self.root / "state")
        os.environ["UYP_GROUPS_FILE"] = str(self.root / "state" / "groups.json")
        os.environ.pop("UYP_ACCESS_CONTEXT_FILE", None)
        os.environ.pop("UYP_HOMEHUB_ACCESS_CONTEXT_URL", None)
        os.environ.pop("UYP_HOMEHUB_TOKEN_FILE", None)
        os.environ.pop("UYP_MCP_PRINCIPAL", None)
        os.environ.pop("UYP_MCP_TOKEN_FILE", None)
        os.environ.pop("UYP_CONNECTOR_HOST", None)
        # Member tier at the mcp_server seam: the same function the voice
        # handshake uses, faked to the HomeHub answers these members get.
        patcher = patch.object(mcp_server, "load_context_for_member",
                               lambda member: self.contexts.get(member))
        patcher.start()
        self.addCleanup(patcher.stop)
        # Search synthesis faked at the query_api seam (records the scoped set).
        self.search_calls: list = []

        def fake_search_answer(question, items):
            self.search_calls.append({"question": question, "items": list(items)})
            if not items:
                return {"answer": query_api.MISS_SENTENCE, "sources": [], "confidence": "none"}
            return {"answer": f"{question} 在 {items[0]['file']} 附近。",
                    "sources": [{"file": item["file"], "match": 4.0} for item in items[:2]],
                    "confidence": "high"}

        search_patcher = patch.object(query_api, "search_answer", fake_search_answer)
        search_patcher.start()
        self.addCleanup(search_patcher.stop)
        self.server = mcp_server.McpStdioServer(self.runner_for("ly"))

    def tearDown(self):
        for key, value in self.env_old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def runner_for(self, member: str) -> mcp_server.ToolRunner:
        return mcp_server.ToolRunner(principal={"tier": "member", "subject": member})

    def call(self, name, arguments, member="ly"):
        """tools/call through the server; returns (payload, isError)."""
        server = self.server if member == "ly" else mcp_server.McpStdioServer(self.runner_for(member))
        if not server.initialized:
            server.handle_message({"jsonrpc": "2.0", "id": 40, "method": "initialize", "params": {}})
        response = server.handle_message({"jsonrpc": "2.0", "id": 41, "method": "tools/call",
                                          "params": {"name": name, "arguments": arguments}})
        self.assertIn("result", response)
        return json.loads(response["result"]["content"][0]["text"]), response["result"]["isError"]

    # ---- project.search: per-member enforcement ---------------------------

    def test_search_scopes_to_member_grants(self):
        payload, is_error = self.call("project.search", {"query": "哪里实现了委托签名"})
        self.assertFalse(is_error)
        self.assertTrue(payload["ok"])
        # Only demo-project reached synthesis: ly's grants, not the box's.
        self.assertEqual(sorted(item["file"] for item in self.search_calls[0]["items"]),
                         ["lib/signing.py", "src/main.py"])
        for citation in payload["citations"]:
            self.assertEqual(citation["projectId"], "project:demo-project")
            self.assertEqual(citation["producingJarvis"], "jetson-1")
            self.assertFalse(citation["allowedToShare"])
        self.assertEqual(payload["access"]["grantEpoch"], "epoch-ly")

    def test_search_denied_for_member_homehub_cannot_resolve(self):
        payload, is_error = self.call("project.search", {"query": "anything"}, member="stranger")
        self.assertTrue(is_error)
        self.assertEqual(payload["error"], "member_access_denied")
        self.assertEqual(self.search_calls, [])  # synthesis never ran

    def test_every_tool_denied_without_principal(self):
        runner = mcp_server.ToolRunner(principal={"tier": None, "subject": None})
        server = mcp_server.McpStdioServer(runner)
        server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        for name, args in (("project.search", {"query": "x"}),
                           ("project.get", {"project_id": "demo-project"}),
                           ("project.related", {"project_id": "demo-project"}),
                           ("source.locate", {"symbol": "main"}),
                           ("source.read_evidence", {"item_id": "knowledge:demo-project:0"}),
                           ("index.status", {})):
            response = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                              "params": {"name": name, "arguments": args}})
            body = json.loads(response["result"]["content"][0]["text"])
            self.assertTrue(response["result"]["isError"], name)
            self.assertEqual(body["error"], "principal_required", name)

    def test_bearer_token_tier_resolves_its_own_principal(self):
        token_file = self.root / "agent.token"
        token_file.write_text("companion-bearer-1", encoding="utf-8")
        os.environ["UYP_MCP_TOKEN_FILE"] = str(token_file)
        runner = mcp_server.ToolRunner()  # env-derived: bearer tier
        self.assertEqual(runner.principal["tier"], "bearer")
        with patch.object(mcp_server, "load_context_for_token",
                          lambda token: self.contexts["ly"] if token == "companion-bearer-1" else None):
            server = mcp_server.McpStdioServer(runner)
            server.handle_message({"jsonrpc": "2.0", "id": 8, "method": "initialize", "params": {}})
            response = server.handle_message(
                {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                 "params": {"name": "project.search", "arguments": {"query": "签名"}}})
        body = json.loads(response["result"]["content"][0]["text"])
        self.assertFalse(response["result"]["isError"])
        self.assertTrue(body["ok"])
        # An unreadable token file is a denial, not a fallback.
        os.environ["UYP_MCP_TOKEN_FILE"] = str(self.root / "missing.token")
        with patch.object(mcp_server, "load_context_for_token", lambda token: None):
            denial_server = mcp_server.McpStdioServer(mcp_server.ToolRunner())
            denial_server.handle_message({"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": {}})
            response = denial_server.handle_message(
                {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                 "params": {"name": "index.status", "arguments": {}}})
        body = json.loads(response["result"]["content"][0]["text"])
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(body["error"], "principal_required")

    # ---- project.get --------------------------------------------------------

    def test_get_returns_summary_and_scoped_jobs(self):
        payload, is_error = self.call("project.get", {"project_id": "demo-project"})
        self.assertFalse(is_error)
        project = payload["project"]
        self.assertEqual(project["projectId"], "project:demo-project")
        self.assertEqual(project["counts"]["files"], 2)
        self.assertEqual(project["freshness"], "partial")  # connector unconfigured
        self.assertEqual([job["jobId"] for job in payload["jobs"]], ["job-1"])
        self.assertEqual(payload["evidenceCount"], 2)

    def test_get_out_of_scope_project_shares_nothing(self):
        # other-project exists on disk but is outside ly's grants: the reply
        # is the same generic denial as for a nonexistent id, with no echo.
        payload, is_error = self.call("project.get", {"project_id": "other-project"})
        self.assertTrue(is_error)
        self.assertEqual(payload["error"], "project_not_in_scope")
        self.assertNotIn("other-project", json.dumps(payload))

    def test_index_status_scopes_counts_and_jobs_like_health(self):
        ly_payload, _ = self.call("index.status", {})
        boss_payload, _ = self.call("index.status", {}, member="boss")
        self.assertEqual(ly_payload["knowledgeItems"], 2)
        self.assertEqual(boss_payload["knowledgeItems"], 3)
        self.assertEqual([job["jobId"] for job in ly_payload["jobs"]], ["job-1"])
        self.assertEqual(sorted(job["jobId"] for job in boss_payload["jobs"]), ["job-1", "job-2"])
        self.assertTrue(ly_payload["readOnly"])

    # ---- project.related ------------------------------------------------------

    def test_related_uses_graph_and_tags_within_scope(self):
        payload, is_error = self.call("project.related", {"project_id": "demo-project"}, member="boss")
        self.assertFalse(is_error)
        related = payload["related"]
        self.assertEqual(related["files"][0]["file"], "src/main.py")
        self.assertEqual(related["files"][0]["imports"], ["lib/signing.py"])
        self.assertEqual(related["hubs"][0], {"file": "lib/signing.py", "importedBy": 1})
        self.assertIn("signing", related["tags"])
        # other-project shares the "signing" component tag with demo-project.
        self.assertEqual(related["projects"][0]["projectId"], "project:other-project")
        self.assertIn("signing", related["projects"][0]["sharedTags"])

    def test_related_never_proposes_out_of_scope_projects(self):
        payload, is_error = self.call("project.related", {"project_id": "demo-project"})  # ly
        self.assertFalse(is_error)
        self.assertEqual(payload["related"]["projects"], [])

    def test_related_query_mode_uses_search_ranking(self):
        payload, is_error = self.call("project.related", {"query": "哪里实现了委托签名"})
        self.assertFalse(is_error)
        self.assertTrue(payload["match"])
        self.assertEqual(payload["projectId"], "project:demo-project")
        miss_payload, _ = self.call("project.related", {"query": "zzz unmatched topic"})
        self.assertFalse(miss_payload["match"])
        self.assertEqual(miss_payload["answer"], query_api.MISS_SENTENCE)

    def test_related_out_of_scope_denied(self):
        payload, is_error = self.call("project.related", {"project_id": "other-project"})
        self.assertTrue(is_error)
        self.assertEqual(payload["error"], "project_not_in_scope")

    # ---- source.locate -----------------------------------------------------

    def test_locate_symbols_from_anchored_tables(self):
        payload, is_error = self.call("source.locate", {"symbol": "sign"})
        self.assertFalse(is_error)
        rows = payload["matches"]
        self.assertEqual({row["symbol"] for row in rows}, {"sign_request", "SigningClass"})
        for row in rows:
            self.assertEqual(row["projectId"], "project:demo-project")
        by_name = {row["symbol"]: row for row in rows}
        self.assertEqual(by_name["sign_request"]["lineRange"], [5, 20])
        self.assertEqual(by_name["sign_request"]["kind"], "function")

    def test_locate_hides_out_of_scope_symbols(self):
        # other_fn exists in the other-project symbol table but ly cannot see it.
        payload, _ = self.call("source.locate", {"symbol": "other_fn"})
        self.assertEqual(payload["matches"], [])
        payload, is_error = self.call("source.locate", {"symbol": "other_fn", "project_id": "other-project"})
        self.assertTrue(is_error)
        self.assertEqual(payload["error"], "project_not_in_scope")
        # The wildcard member finds it, proving the table is read, just scoped.
        payload, _ = self.call("source.locate", {"symbol": "other_fn"}, member="boss")
        self.assertEqual(payload["matches"][0]["file"], "lib/other.py")

    def test_locate_file_pattern_and_argument_errors(self):
        payload, _ = self.call("source.locate", {"file_pattern": "src/*.py"})
        self.assertEqual([row["file"] for row in payload["matches"]], ["src/main.py"])
        server = mcp_server.McpStdioServer(self.runner_for("ly"))
        server.handle_message({"jsonrpc": "2.0", "id": 4, "method": "initialize", "params": {}})
        response = server.handle_message(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "source.locate", "arguments": {}}})
        self.assertEqual(response["error"]["code"], -32602)  # MCP invalid arguments

    # ---- source.read_evidence -------------------------------------------------

    def test_read_evidence_by_snapshot_item_id(self):
        payload, is_error = self.call("source.read_evidence", {"item_id": "knowledge:demo-project:0"})
        self.assertFalse(is_error)
        evidence = payload["evidence"]
        # Sorted-by-file order matches project_snapshot: lib/signing.py is index 0.
        self.assertEqual(evidence["file"], "lib/signing.py")
        self.assertEqual(evidence["projectId"], "project:demo-project")
        self.assertEqual(evidence["anchorTop"], "sign_request L5-L20")
        self.assertEqual(evidence["keyPoints"][0]["evidenceLevel"], "fact")
        self.assertIn("(L5-L20)", evidence["keyPoints"][0]["point"])
        get_payload, _ = self.call("project.get", {"project_id": "demo-project"})
        self.assertEqual(get_payload["evidence"][0]["evidenceId"], "knowledge:demo-project:0")

    def test_read_evidence_by_path_with_line_window(self):
        payload, _ = self.call("source.read_evidence",
                               {"path": "src/main.py", "lines": [10, 50]})
        key_points = payload["evidence"]["keyPoints"]
        self.assertEqual(len(key_points), 1)  # (L10-L42) intersects [10, 50]
        payload, _ = self.call("source.read_evidence",
                               {"path": "src/main.py", "lines": [100, 200]})
        self.assertEqual(payload["evidence"]["keyPoints"], [])

    def test_read_evidence_raw_head_only_without_line_filter(self):
        item_path = self.root / "output" / "demo-project" / "src__main.py.knowledge.json"
        item = json.loads(item_path.read_text(encoding="utf-8"))
        item["derived"] = {"raw_head": "import hmac\n"}
        item_path.write_text(json.dumps(item), encoding="utf-8")
        payload, _ = self.call("source.read_evidence", {"path": "src/main.py"})
        self.assertEqual(payload["evidence"]["rawHead"], "import hmac\n")
        payload, _ = self.call("source.read_evidence", {"path": "src/main.py", "lines": [1, 40]})
        self.assertIsNone(payload["evidence"]["rawHead"])

    def test_read_evidence_out_of_scope_path_is_honest_miss(self):
        payload, is_error = self.call("source.read_evidence", {"path": "lib/other.py"})
        self.assertTrue(is_error)
        self.assertEqual(payload["error"], "evidence_not_found")
        self.assertNotIn("other", json.dumps(payload))

    def test_read_evidence_argument_errors(self):
        server = mcp_server.McpStdioServer(self.runner_for("ly"))
        server.handle_message({"jsonrpc": "2.0", "id": 5, "method": "initialize", "params": {}})
        for arguments in ({"item_id": "x", "path": "y"}, {}):
            response = server.handle_message(
                {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                 "params": {"name": "source.read_evidence", "arguments": arguments}})
            self.assertEqual(response["error"]["code"], -32602)

    # ---- read-only invariant ------------------------------------------------

    def _tree_digest(self) -> dict:
        digest = {}
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                digest[str(path.relative_to(self.root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest

    def test_tools_never_mutate_the_store(self):
        before = self._tree_digest()
        for member in ("ly", "boss"):
            for name, args in (
                ("project.search", {"query": "签名"}),
                ("project.get", {"project_id": "demo-project"}),
                ("project.related", {"project_id": "demo-project"}),
                ("source.locate", {"symbol": "sign"}),
                ("source.read_evidence", {"item_id": "knowledge:demo-project:0"}),
                ("index.status", {}),
            ):
                self.call(name, args, member=member)
            # Denials must not mutate either.
            self.call("project.get", {"project_id": "other-project"}, member=member)
            self.call("source.read_evidence", {"path": "lib/other.py"}, member=member)
        self.assertEqual(self._tree_digest(), before)
        # No groups registry (or any other state) was created by the MCP tools.
        self.assertFalse((self.root / "state" / "groups.json").exists())


class McpHttpModeTests(unittest.TestCase):
    """--api mode against the real loopback query API (voice guard on)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_store(self.root)
        # The API's service-level context (tier c) for snapshot/health routes.
        service_context = self.root / "access.json"
        service_context.write_text(json.dumps(member_context("box", ["*"], ["*"])), encoding="utf-8")
        self.env_old = {key: os.environ.get(key) for key in (
            "UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_GROUPS_FILE",
            "UYP_ACCESS_CONTEXT_FILE", "UYP_HOMEHUB_ACCESS_CONTEXT_URL",
            "UYP_HOMEHUB_TOKEN_FILE", "UYP_MCP_PRINCIPAL", "UYP_MCP_TOKEN_FILE",
            "UYP_CONNECTOR_HOST")}
        os.environ["UYP_OUTPUT_ROOT"] = str(self.root / "output")
        os.environ["UYP_STATE_ROOT"] = str(self.root / "state")
        os.environ["UYP_GROUPS_FILE"] = str(self.root / "state" / "groups.json")
        os.environ["UYP_ACCESS_CONTEXT_FILE"] = str(service_context)
        os.environ.pop("UYP_HOMEHUB_ACCESS_CONTEXT_URL", None)
        os.environ.pop("UYP_HOMEHUB_TOKEN_FILE", None)
        os.environ.pop("UYP_MCP_PRINCIPAL", None)
        os.environ.pop("UYP_MCP_TOKEN_FILE", None)
        os.environ.pop("UYP_CONNECTOR_HOST", None)
        self.contexts = {
            "ly": member_context("ly", ["demo-project"], ["connector:demo-project"]),
        }
        # API-side member tier (the voice handshake seam inside query_api)
        # and the MCP server's own local resolution for unbound tools.
        api_patcher = patch.object(query_api, "load_homehub_context_for_member",
                                   lambda member: self.contexts.get(member))
        api_patcher.start()
        self.addCleanup(api_patcher.stop)
        local_patcher = patch.object(mcp_server, "load_context_for_member",
                                     lambda member: self.contexts.get(member))
        local_patcher.start()
        self.addCleanup(local_patcher.stop)
        self.search_calls: list = []

        def fake_search_answer(question, items):
            self.search_calls.append({"question": question, "items": list(items)})
            if not items:
                return {"answer": query_api.MISS_SENTENCE, "sources": [], "confidence": "none"}
            return {"answer": f"{question} 在 {items[0]['file']} 附近。",
                    "sources": [{"file": item["file"], "match": 4.0} for item in items[:2]],
                    "confidence": "high"}

        search_patcher = patch.object(query_api, "search_answer", fake_search_answer)
        search_patcher.start()
        self.addCleanup(search_patcher.stop)
        self.api = ThreadingHTTPServer(("127.0.0.1", 0), query_api.QueryHandler)
        self.api.loopback_voice = True
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.addCleanup(self.api.server_close)
        self.addCleanup(self.api.shutdown)
        self.runner = mcp_server.ToolRunner(
            api_url=f"http://127.0.0.1:{self.api.server_address[1]}",
            principal={"tier": "member", "subject": "ly"})
        self.server = mcp_server.McpStdioServer(self.runner)

    def tearDown(self):
        for key, value in self.env_old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def call(self, name, arguments, runner=None):
        server = mcp_server.McpStdioServer(runner) if runner else self.server
        if not server.initialized:
            server.handle_message({"jsonrpc": "2.0", "id": 6, "method": "initialize", "params": {}})
        response = server.handle_message({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                          "params": {"name": name, "arguments": arguments}})
        return json.loads(response["result"]["content"][0]["text"]), response["result"]["isError"]

    def test_http_search_carries_the_voice_member_header(self):
        # The member tier rides X-Agent-Member exactly like the voice chain;
        # the API resolves ly's own grants and scopes the synthesis input.
        payload, is_error = self.call("project.search", {"query": "哪里实现了委托签名"})
        self.assertFalse(is_error)
        self.assertEqual(payload["backend"], "http")
        self.assertEqual(sorted(item["file"] for item in self.search_calls[0]["items"]),
                         ["lib/signing.py", "src/main.py"])

    def test_http_search_member_denial_is_forwarded(self):
        runner = mcp_server.ToolRunner(
            api_url=f"http://127.0.0.1:{self.api.server_address[1]}",
            principal={"tier": "member", "subject": "stranger"})
        payload, is_error = self.call("project.search", {"query": "x"}, runner=runner)
        self.assertTrue(is_error)
        self.assertEqual(payload["error"], "member_access_denied")
        self.assertEqual(self.search_calls, [])

    def test_http_get_uses_the_snapshot_route(self):
        payload, is_error = self.call("project.get", {"project_id": "demo-project"})
        self.assertFalse(is_error)
        self.assertEqual(payload["project"]["name"], "demo-project")
        self.assertEqual([job["jobId"] for job in payload["jobs"]], ["job-1"])
        payload, is_error = self.call("project.get", {"project_id": "ghost-project"})
        self.assertTrue(is_error)
        self.assertEqual(payload["error"], "project_not_in_scope")

    def test_http_index_status_reports_the_api_health(self):
        payload, is_error = self.call("index.status", {})
        self.assertFalse(is_error)
        self.assertEqual(payload["backend"], "http")
        self.assertEqual(payload["service"], "uyp-query-api")
        self.assertEqual(payload["principal"], {"tier": "member", "subject": "ly"})

    def test_http_local_tools_still_enforce_the_principal_locally(self):
        # related/locate have no route: they enforce with the same shared
        # functions locally, against the same member resolution.
        payload, is_error = self.call("source.locate", {"symbol": "other_fn"})
        self.assertFalse(is_error)
        self.assertEqual(payload["matches"], [])

    def test_unreachable_api_fails_closed(self):
        runner = mcp_server.ToolRunner(api_url="http://127.0.0.1:9",
                                       principal={"tier": "member", "subject": "ly"})
        payload, is_error = self.call("project.search", {"query": "x"}, runner=runner)
        self.assertTrue(is_error)
        self.assertEqual(payload["error"], "query_api_unreachable")

    def test_http_mode_without_principal_never_reaches_the_api(self):
        # The API's service-level context (tier c) would happily answer an
        # unauthenticated loopback request; the MCP gate must refuse before
        # any HTTP hop so the agent can never ride the ambient box context.
        runner = mcp_server.ToolRunner(
            api_url=f"http://127.0.0.1:{self.api.server_address[1]}",
            principal={"tier": None, "subject": None})
        for name, args in (("project.search", {"query": "x"}),
                           ("project.get", {"project_id": "demo-project"}),
                           ("index.status", {})):
            payload, is_error = self.call(name, args, runner=runner)
            self.assertTrue(is_error, name)
            self.assertEqual(payload["error"], "principal_required", name)
        self.assertEqual(self.search_calls, [])


class McpSubprocessTests(unittest.TestCase):
    """End-to-end stdio smoke over the real process (arg parsing + framing)."""

    def test_stdio_exchange_without_principal(self):
        lines = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "test", "version": "0"}}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "project.search", "arguments": {"query": "签名"}}}),
        ]) + "\n"
        env = {key: value for key, value in os.environ.items() if not key.startswith("UYP_")}
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "services" / "indexer" / "src" / "mcp_server.py")],
            input=lines, capture_output=True, text=True, timeout=30, env=env, cwd=str(REPO_ROOT))
        self.assertEqual(result.returncode, 0)
        out = [json.loads(line) for line in result.stdout.strip().splitlines()]
        self.assertEqual(len(out), 3)  # the notification produced no line
        self.assertEqual(out[0]["id"], 1)
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "uyp-mcp")
        self.assertEqual(sorted(tool["name"] for tool in out[1]["result"]["tools"]), sorted(SIX_TOOLS))
        self.assertTrue(out[2]["result"]["isError"])
        self.assertEqual(json.loads(out[2]["result"]["content"][0]["text"])["error"],
                         "principal_required")
        # The warning is diagnostics on stderr, never on the protocol channel.
        self.assertIn("no principal configured", result.stderr)


if __name__ == "__main__":
    unittest.main()
