"""gbrain_publisher tests.

The live-path tests run against an in-thread http.server double of a gbrain
serve: it implements the two endpoints the production writer path uses
(POST /token with OAuth client_credentials, POST /mcp with JSON-RPC
tools/call), answers with plain JSON or SSE, and reproduces the two
rejection shapes observed on the Jetson -- HTTP 200 + result.isError with
the error payload nested in result.content[].text (the 2026-09-27 family
quota failure), and permission_denied for tools outside the writer's
surface.  Nothing here touches the real :8790/:3141 services.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import gbrain_publisher as gp  # noqa: E402


class _FakeServeHandler(BaseHTTPRequestHandler):
    """Records every call; dispatch decisions live on the server object."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        state = self.server.state
        if self.path == "/token":
            form = urllib.parse.parse_qs(body.decode())
            state.token_requests.append(form)
            if form.get("client_id") != ["writer"] or form.get("client_secret") != ["secret"]:
                self._respond(401, {"error": "invalid_client"})
                return
            self._respond(200, {"access_token": "tok-1", "expires_in": 3600})
            return
        if self.path == "/mcp":
            if self.headers.get("Authorization") != "Bearer tok-1":
                self._respond(401, {"error": "unauthorized"})
                return
            rpc = json.loads(body)
            result = state.dispatch(rpc["params"]["name"], rpc["params"]["arguments"])
            if state.sse:
                payload = ("event: message\ndata: " + json.dumps(result) + "\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self._respond(200, result)
            return
        self._respond(404, {"error": "not found"})

    def _respond(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class FakeGbrainServe:
    """In-thread stand-in for one gbrain serve (token + MCP tools/call)."""

    def __init__(self, *, reject_slugs=(), reject_deletes=False, sse=False):
        self.calls = []          # (tool, arguments) in arrival order
        self.pages = {}          # slug -> content
        self.token_requests = []
        self.reject_slugs = set(reject_slugs)
        self.reject_deletes = reject_deletes
        self.sse = sse
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FakeServeHandler)
        self._httpd.state = self
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self._httpd.server_address[1]

    @staticmethod
    def creds():
        return {"client_id": "writer", "client_secret": "secret"}

    def close(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def dispatch(self, tool, arguments):
        slug = str(arguments.get("slug", ""))
        self.calls.append((tool, dict(arguments)))
        if tool == "put_page":
            if slug in self.reject_slugs:
                return self._envelope({
                    "isError": True,
                    "content": [{"type": "text",
                                 "text": json.dumps({"error": "Write capacity exhausted"})}],
                })
            self.pages[slug] = arguments.get("content", "")
            return self._ok({"slug": slug, "written": True})
        if tool == "delete_page":
            if self.reject_deletes:
                return self._envelope({
                    "isError": True,
                    "content": [{"type": "text",
                                 "text": json.dumps({"error": "permission_denied"})}],
                })
            self.pages.pop(slug, None)
            return self._ok({"slug": slug, "deleted": True})
        return self._envelope({
            "isError": True,
            "content": [{"type": "text", "text": json.dumps({"error": "unknown tool"})}],
        })

    @staticmethod
    def _ok(result):
        return {"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text", "text": json.dumps(result)}]}}

    @staticmethod
    def _envelope(result):
        return {"jsonrpc": "2.0", "id": 1, "result": result}


def quick_item(relpath, purpose="Entry point"):
    return {"file": relpath, "version": {"mtime": 1728000000, "size": 120},
            "verdict": "quick-summary", "think_gate": 0.0,
            "source": "mac-connector", "analyzed_at": "2026-10-10T00:00:00",
            "derived": {"purpose": purpose, "key_points": ["parses CLI"],
                        "components": ["main"], "depends_on": ["argparse"]}}


def structure_item(relpath):
    return {"file": relpath, "version": {"mtime": 1728000001, "size": 40},
            "verdict": "structure-only", "think_gate": 0.0,
            "source": "mac-connector", "analyzed_at": "2026-10-10T00:00:00",
            "derived": {"kind": "structure-only", "lines": 12, "py_defs": 2, "imports": 3}}


def make_knowledge_root(root: Path, project="demo"):
    out = root / "output" / project
    out.mkdir(parents=True)
    for item in (quick_item("src/main.py"), structure_item("src/utils/helpers.py")):
        safe = item["file"].replace("/", "__") + ".knowledge.json"
        (out / safe).write_text(json.dumps(item), encoding="utf-8")
    return out


class GbrainPublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Keep UYP_GBRAIN_* env out of the tests: a live publish must fail
        # closed unless the test itself supplies an endpoint.
        patcher = patch.dict("os.environ")
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("UYP_GBRAIN_URL", None)
        os.environ.pop("UYP_GBRAIN_CREDS", None)

    def serve(self, **kwargs):
        server = FakeGbrainServe(**kwargs)
        self.addCleanup(server.close)
        return server

    def client(self, server):
        return gp.McpServeClient(server.url, server.creds())

    # ── slug + page construction ──

    def test_entry_slug_binds_namespace_project_and_epoch(self):
        self.assertEqual(gp.entry_slug("demo", "g1", "src/main.py"),
                         "project_knowledge/demo/g1/src/main.py")
        # A different grant epoch is a different subtree: a re-grant can
        # never alias onto an older grant's pages, and revoke targets one
        # epoch exactly.
        self.assertNotEqual(gp.entry_slug("demo", "g1", "src/main.py"),
                            gp.entry_slug("demo", "g2", "src/main.py"))
        # Unsafe characters are sanitized deterministically on every level.
        self.assertEqual(gp.entry_slug("my proj", "g:1", "docs/a b.md"),
                         "project_knowledge/my_proj/g_1/docs/a_b.md")
        with self.assertRaises(gp.GbrainPublishError):
            gp.entry_slug("demo", "g1", "x/" + "y" * gp.SLUG_MAX)

    def test_page_carries_revocation_and_version_metadata(self):
        page = gp.build_page(quick_item("src/main.py"), project_id="demo",
                             version="v9", grant_epoch="g1", published_at="2026-10-10T00:00:00Z")
        self.assertTrue(page["content"].startswith("---\n"))
        for expected in ('uyp_namespace: "project_knowledge"', 'uyp_grant_epoch: "g1"',
                         'uyp_version: "v9"', 'uyp_relpath: "src/main.py"',
                         "uyp_revoked: false"):
            self.assertIn(expected, page["content"])
        self.assertIn("- Purpose: Entry point", page["content"])
        structure = gp.build_page(structure_item("src/utils/helpers.py"),
                                  project_id="demo", version="v9", grant_epoch="g1")
        self.assertIn("- Structure: 12 lines, 2 py defs, 3 imports", structure["content"])

    def test_manifest_lists_every_entry_slug(self):
        entries = [gp.build_page(quick_item("src/main.py"), project_id="demo",
                                 version="v1", grant_epoch="g1")]
        manifest = gp.build_manifest("demo", "g1", version="v1", entries=entries)
        self.assertEqual(manifest["slug"], "project_knowledge/demo/g1/__manifest__")
        self.assertIn(entries[0]["slug"], manifest["content"])
        self.assertIn("uyp_revoked: false", manifest["content"])

    def test_sanitized_slug_collision_fails_closed(self):
        out = make_knowledge_root(self.root)
        (out / "collide.knowledge.json").write_text(json.dumps(quick_item("a b.py")), encoding="utf-8")
        (out / "collide2.knowledge.json").write_text(json.dumps(quick_item("a_b.py")), encoding="utf-8")
        with self.assertRaises(gp.GbrainPublishError) as caught:
            gp.publish(out, "demo", "v1", "g1", dry_run=True, log=lambda line: None)
        self.assertIn("collision", str(caught.exception))

    # ── dry run (default): plan only, zero network ──

    def test_dry_run_prints_plan_without_network(self):
        server = self.serve()
        out = make_knowledge_root(self.root)
        lines = []
        summary = gp.publish(out, "demo", "v1", "g1", log=lines.append)
        self.assertEqual(server.calls, [])
        self.assertEqual(server.token_requests, [])
        self.assertTrue(summary["dryRun"])
        self.assertEqual(summary["entries"], 2)
        self.assertFalse(summary["manifestWritten"])
        self.assertIn("DRY RUN", lines[0])
        self.assertIn("PUT project_knowledge/demo/g1/src/main.py", "\n".join(lines))
        self.assertIn("PUT project_knowledge/demo/g1/__manifest__", "\n".join(lines))
        self.assertIsNone(summary["endpoint"])

    def test_dry_run_is_the_default(self):
        server = self.serve()
        out = make_knowledge_root(self.root)
        # No dry_run argument at all, and a fully configured client: the
        # default must still not touch the network.
        summary = gp.publish(out, "demo", "v1", "g1", client=self.client(server),
                             log=lambda line: None)
        self.assertTrue(summary["dryRun"])
        self.assertEqual(server.calls, [])

    # ── live publish against the fake serve ──

    def test_publish_writes_manifest_last_with_stable_request_ids(self):
        server = self.serve()
        out = make_knowledge_root(self.root)
        client = self.client(server)
        first = gp.publish(out, "demo", "v1", "g1", dry_run=False,
                           client=client, log=lambda line: None,
                           published_at="2026-10-10T00:00:00Z")
        self.assertFalse(first["dryRun"])
        self.assertEqual(first["ok"], 2)
        self.assertTrue(first["manifestWritten"])
        puts = [arguments for tool, arguments in server.calls if tool == "put_page"]
        self.assertEqual(len(puts), 3)
        self.assertEqual(puts[-1]["slug"], "project_knowledge/demo/g1/__manifest__")
        self.assertTrue(all(arguments["force"] for arguments in puts))
        # The same version replayed with the same stamp is byte-identical,
        # so the derived request_id (and the serve-side receipt) repeats.
        second = gp.publish(out, "demo", "v1", "g1", dry_run=False,
                            client=client, log=lambda line: None,
                            published_at="2026-10-10T00:00:00Z")
        self.assertTrue(second["manifestWritten"])
        replay = [arguments for tool, arguments in server.calls if tool == "put_page"][3:]
        self.assertEqual([call["request_id"] for call in puts],
                         [call["request_id"] for call in replay])
        self.assertEqual(len(server.token_requests), 1)  # bearer cached across calls

    def test_rejected_put_aborts_before_manifest(self):
        out = make_knowledge_root(self.root)
        server = self.serve(reject_slugs={"project_knowledge/demo/g1/src/main.py"})
        summary = gp.publish(out, "demo", "v1", "g1", dry_run=False,
                             client=self.client(server), log=lambda line: None)
        self.assertEqual(summary["ok"], 0)
        self.assertEqual(summary["failed"]["slug"], "project_knowledge/demo/g1/src/main.py")
        self.assertIn("Write capacity exhausted", summary["failed"]["reason"])
        self.assertEqual(summary["notAttempted"], 2)  # second item + manifest
        self.assertFalse(summary["manifestWritten"])
        slugs = [arguments["slug"] for tool, arguments in server.calls]
        self.assertNotIn("project_knowledge/demo/g1/__manifest__", slugs)

    def test_sse_encoded_responses_are_unwrapped(self):
        server = self.serve(sse=True)
        out = make_knowledge_root(self.root)
        summary = gp.publish(out, "demo", "v1", "g1", dry_run=False,
                             client=self.client(server), log=lambda line: None)
        self.assertTrue(summary["manifestWritten"])
        self.assertEqual(len(server.calls), 3)

    def test_live_publish_requires_explicit_endpoint(self):
        out = make_knowledge_root(self.root)
        with self.assertRaises(gp.GbrainPublishError) as caught:
            gp.publish(out, "demo", "v1", "g1", dry_run=False, log=lambda line: None)
        self.assertIn("no default endpoint", str(caught.exception))

    # ── revocation ──

    def test_revoke_deletes_epoch_pages_and_tombstones_manifest(self):
        server = self.serve()
        out = make_knowledge_root(self.root)
        client = self.client(server)
        gp.publish(out, "demo", "v1", "g1", dry_run=False, client=client, log=lambda line: None)
        server.calls.clear()
        summary = gp.revoke("demo", "g1", knowledge_root=out, dry_run=False, client=client,
                            log=lambda line: None)
        deletes = [arguments["slug"] for tool, arguments in server.calls if tool == "delete_page"]
        self.assertEqual(sorted(deletes), sorted([
            "project_knowledge/demo/g1/src/main.py",
            "project_knowledge/demo/g1/src/utils/helpers.py",
        ]))
        self.assertEqual(summary["deleted"], deletes)
        self.assertEqual(summary["deleteUnsupported"], [])
        # The manifest page is never deleted; it is overwritten as the
        # tombstone so even a reader that ignores soft-deletes sees stale.
        last_tool, last_args = server.calls[-1]
        self.assertEqual(last_tool, "put_page")
        self.assertEqual(last_args["slug"], "project_knowledge/demo/g1/__manifest__")
        self.assertIn("uyp_revoked: true", last_args["content"])
        self.assertTrue(summary["tombstoneWritten"])
        # Deleted pages are gone from the serve's page set.
        self.assertNotIn("project_knowledge/demo/g1/src/main.py", server.pages)

    def test_revoke_reports_gap_when_delete_is_unavailable(self):
        server = self.serve(reject_deletes=True)
        out = make_knowledge_root(self.root)
        summary = gp.revoke("demo", "g1", knowledge_root=out, dry_run=False,
                            client=self.client(server), log=lambda line: None)
        self.assertEqual(summary["deleted"], [])
        self.assertEqual(len(summary["deleteUnsupported"]), 2)
        self.assertIn("permission_denied", summary["deleteUnsupported"][0]["reason"])
        # The tombstone still lands: the epoch is marked stale even though
        # per-page deletion needs a surface grant on the serve.
        self.assertTrue(summary["tombstoneWritten"])
        self.assertIn("project_knowledge/demo/g1/__manifest__", server.pages)

    def test_revoke_dry_run_plans_deletes_without_network(self):
        server = self.serve()
        out = make_knowledge_root(self.root)
        lines = []
        summary = gp.revoke("demo", "g1", knowledge_root=out, log=lines.append)
        self.assertTrue(summary["dryRun"])
        self.assertEqual(server.calls, [])
        self.assertEqual(len(summary["targets"]), 2)
        printed = "\n".join(lines)
        self.assertIn("DELETE project_knowledge/demo/g1/src/main.py", printed)
        self.assertIn("uyp_revoked: true", printed)

    def test_revoke_needs_local_targets(self):
        # The MCP surface cannot enumerate a slug prefix remotely, so a
        # revoke without a local source of slugs must fail closed.
        with self.assertRaises(gp.GbrainPublishError):
            gp.revoke("demo", "g1", log=lambda line: None)

    def test_new_epoch_does_not_alias_revoked_pages(self):
        server = self.serve()
        out = make_knowledge_root(self.root)
        client = self.client(server)
        gp.publish(out, "demo", "v1", "g1", dry_run=False, client=client, log=lambda line: None)
        gp.revoke("demo", "g1", knowledge_root=out, dry_run=False, client=client, log=lambda line: None)
        gp.publish(out, "demo", "v2", "g2", dry_run=False, client=client, log=lambda line: None)
        # g1's pages are deleted, g2's live under a different subtree, and
        # each epoch has its own manifest.
        self.assertNotIn("project_knowledge/demo/g1/src/main.py", server.pages)
        self.assertIn("project_knowledge/demo/g2/src/main.py", server.pages)
        self.assertIn("project_knowledge/demo/g1/__manifest__", server.pages)
        self.assertIn("project_knowledge/demo/g2/__manifest__", server.pages)


if __name__ == "__main__":
    unittest.main()
