"""Studio v2 project registry, digest, ask and analyze jobs (docs/STUDIO_V2.md §6.2).

Offline: temp output/state roots, a fake loopback Mac connector, a fake job
launcher, and fake LLM / gbrain callables.  One test executes a generated
run.sh end-to-end with a shim interpreter standing in for the indexer.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import project_digest  # noqa: E402
import project_jobs  # noqa: E402
import projects  # noqa: E402

ENV_KEYS = (
    "UYP_OUTPUT_ROOT", "UYP_STATE_ROOT", "UYP_CONNECTOR_HOST", "UYP_CONNECTOR_TOKEN_FILE",
    "UYP_CONNECTOR_DEVICE_ID", "UYP_PROJECT_STALE_DAYS", "UYP_ASK_YIELD_MAX_S", "UYP_UA_ROOT",
    "UYP_ANALYZE_LAYA_UNIT", "UYP_ANALYZE_PYTHON", "UYP_ANALYZE_LAUNCHER", "UYP_PROJECT_LIVE_ACTIVITY",
)
NOW = time.time()


class FixtureMixin:
    """Temp roots + helpers to write KnowledgeItems / graphs like the indexer does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "output"
        self.state = self.root / "state"
        self.out.mkdir()
        self.state.mkdir()
        self._env = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["UYP_OUTPUT_ROOT"] = str(self.out)
        os.environ["UYP_STATE_ROOT"] = str(self.state)
        os.environ["UYP_ASK_YIELD_MAX_S"] = "0"
        os.environ["UYP_UA_ROOT"] = str(self.root / "no-ua")
        projects.reset_caches()
        project_digest._MANIFEST_CACHE.clear()

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        projects.reset_caches()
        self.tmp.cleanup()

    def item(self, project, rel, purpose=None, tier=None, rank=None, embedded=None, mtime=None, key_points=None):
        directory = self.out / project
        directory.mkdir(parents=True, exist_ok=True)
        value = {
            "file": rel, "version": {"mtime": int(mtime if mtime is not None else NOW - 3600), "size": 100},
            "verdict": "quick-summary" if purpose else "structure-only",
            "analyzed_at": "2026-10-10T10:00:00",
            "derived": ({"purpose": purpose, "key_points": key_points or [f"{rel} point"], "components": []}
                        if purpose else {"kind": "structure-only", "lines": 3}),
        }
        if tier:
            value["keyfile"] = {"tier": tier, "score": 0.5, "rank": rank, "gate": None, "embedded": embedded}
        (directory / (rel.replace("/", "__") + ".knowledge.json")).write_text(json.dumps(value), encoding="utf-8")

    def graph(self, project, nodes, edges, layers):
        directory = self.state / project / "ua"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "knowledge-graph.json").write_text(json.dumps({
            "project": {"languages": ["python", "typescript"]}, "nodes": nodes, "edges": edges, "layers": layers,
        }), encoding="utf-8")

    def commontasks(self):
        """The real-world shape: README, tiered code, an embedded upstream repo, a graph."""
        self.item("commontasks", "README.md", "Shared clinic task tracker with a voice assistant.", "A", 3)
        self.item("commontasks", "src/app.py", "Flask entry point wiring routes and the scheduler.", "A", 1)
        self.item("commontasks", "src/db.py", "SQLite persistence layer for tasks.", "B", 7, mtime=NOW - 10 * 86400)
        self.item("commontasks", "web/main.ts", "Browser client that renders the task board.", "A", 2, mtime=NOW - 2 * 86400)
        self.item("commontasks", "docs/notes.txt", None, "C", 20)
        self.item("commontasks", "vendor/ua/README.md", "Upstream Understand Anything readme.", "B", 40, embedded="vendor/ua")
        self.item("commontasks", "vendor/ua/core.ts", None, "C", 41, embedded="vendor/ua")
        (self.state / "commontasks.json").write_text(json.dumps({"grant": "g_ct", "root": "commontasks"}), encoding="utf-8")
        self.graph("commontasks",
                   [{"id": "file:src/app.py", "type": "file", "name": "app.py", "filePath": "src/app.py"},
                    {"id": "file:src/db.py", "type": "file", "name": "db.py", "filePath": "src/db.py"},
                    {"id": "fn:src/app.py:main", "type": "function", "name": "main", "filePath": "src/app.py"},
                    {"id": "concept:tasks", "type": "concept", "name": "tasks"}],
                   [{"source": "file:src/app.py", "target": "file:src/db.py", "type": "imports"},
                    {"source": "file:src/app.py", "target": "fn:src/app.py:main", "type": "contains"},
                    {"source": "file:src/app.py", "target": "concept:tasks", "type": "related"}],
                   [{"id": "core", "name": "Core", "nodeIds": ["file:src/app.py", "file:src/db.py"]},
                    {"id": "web", "name": "UI", "nodeIds": ["file:web/main.ts"]}])


def context_for(*project_ids, principal="robin"):
    return {"principalId": principal, "projectScopes": list(project_ids),
            "sourceScopes": [f"connector:{pid}" for pid in project_ids]}


# ------------------------------------------------------------------ fakes --
class _ConnectorHandler(BaseHTTPRequestHandler):
    def _json(self, value, status=200):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        server = self.server
        server.calls.append(("GET", self.path, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer conn-token":
            return self._json({"ok": False, "error": "unauthorized"}, 401)
        url = urlparse(self.path)
        if url.path == "/grants":
            return self._json({"grants": server.grants})
        if url.path == "/manifest":
            grant = (parse_qs(url.query).get("grant") or [""])[0]
            files = server.manifests.get(grant, [])
            return self._json({"grant": grant, "root_name": "x", "files": files, "has_more": False,
                               "next_cursor": None, "total": len(files)})
        return self._json({"ok": False, "error": "not_found"}, 404)

    def do_POST(self):
        server = self.server
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        server.calls.append(("POST", self.path, body))
        if self.headers.get("Authorization") != "Bearer conn-token":
            return self._json({"ok": False, "error": "unauthorized"}, 401)
        path = str(body.get("path") or "")
        if path.startswith("~/"):
            path = "/Users/robin" + path[1:]
        if not path.startswith("/Users/robin/") or path in server.missing:
            return self._json({"ok": False, "error": "path_not_grantable"}, 400)
        if "secret" in path:
            return self._json({"ok": False, "error": "denied_pattern"}, 403)
        grant = {"id": f"g_{len(server.grants) + 1:03d}", "path": path, "mode": "ro"}
        server.grants.append(grant)
        return self._json({"ok": True, "id": grant["id"], "path": path})

    def log_message(self, *_args):
        return


class FakeConnector(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _ConnectorHandler)
        self.grants = []
        self.manifests = {}
        self.missing = set()
        self.calls = []


class ConnectorMixin:
    def start_connector(self):
        connector = FakeConnector()
        threading.Thread(target=connector.serve_forever, daemon=True).start()
        self.addCleanup(connector.server_close)
        self.addCleanup(connector.shutdown)
        token = self.root / "conn.token"
        token.write_text("conn-token\n", encoding="utf-8")
        os.environ["UYP_CONNECTOR_HOST"] = "http://127.0.0.1:%d" % connector.server_address[1]
        os.environ["UYP_CONNECTOR_TOKEN_FILE"] = str(token)
        return connector


class RecordingLauncher:
    def __init__(self):
        self.calls = []

    def __call__(self, job, script):
        self.calls.append((job, script))
        return {"launcher": "fake", "unit": None}


# ------------------------------------------------------------------ tests --
class RegistryImportTests(FixtureMixin, unittest.TestCase):
    def test_imports_existing_outputs_with_connector_path_and_stats(self):
        self.commontasks()
        doc = projects.sync_registry(grants=[{"id": "g_ct", "path": "/Users/robin/code/commontasks"}])
        self.assertEqual([r["project_id"] for r in doc["projects"]], ["commontasks"])
        record = doc["projects"][0]
        self.assertEqual(record["path"], "/Users/robin/code/commontasks")
        self.assertEqual(record["grant_id"], "g_ct")
        self.assertEqual(record["device_id"], "d_mac")
        self.assertEqual(record["status"], "analyzed")
        self.assertEqual(record["stats"]["files"], 7)
        self.assertEqual(record["stats"]["summarized"], 5)
        self.assertEqual(record["stats"]["nodes"], 4)
        self.assertEqual(record["stats"]["edges"], 3)
        self.assertEqual(record["stats"]["languages"], ["python", "typescript"])
        self.assertEqual(record["tiers"], {"A": 3, "B": 2, "C": 2, "gate": 0})
        self.assertEqual(record["embedded_roots"], ["vendor/ua"])
        self.assertTrue(record["analyzed_at"].endswith("Z"))
        # Durable, atomic registry document on disk.
        on_disk = json.loads((self.state / "projects" / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["schema_version"], "uyp.projects.v1")
        self.assertEqual(on_disk["projects"][0]["project_id"], "commontasks")
        self.assertEqual([p.name for p in (self.state / "projects").iterdir() if p.name.startswith(".tmp-")], [])

    def test_import_without_connector_leaves_path_empty_then_backfills(self):
        self.commontasks()
        doc = projects.sync_registry(grants=None, use_connector=False)
        self.assertIsNone(doc["projects"][0]["path"])
        listing = projects.public_record(doc, doc["projects"][0], {"commontasks"})
        self.assertEqual(listing["path"], "")
        doc = projects.sync_registry(grants=[{"id": "g_ct", "path": "/Users/robin/code/commontasks"}])
        self.assertEqual(doc["projects"][0]["path"], "/Users/robin/code/commontasks")
        self.assertEqual(len(doc["projects"]), 1)  # never imported twice

    def test_device_id_follows_connector_env(self):
        os.environ["UYP_CONNECTOR_DEVICE_ID"] = "d_robins_mbp"
        self.commontasks()
        doc = projects.sync_registry(grants=[])
        self.assertEqual(doc["projects"][0]["device_id"], "d_robins_mbp")

    def test_status_is_stale_after_threshold_and_failed_after_failed_job(self):
        self.commontasks()
        doc = projects.sync_registry(grants=[])
        record = doc["projects"][0]
        self.assertEqual(projects.derive_status(record, None, now=NOW), "analyzed")
        os.environ["UYP_PROJECT_STALE_DAYS"] = "1"
        later = projects.parse_time(record["analyzed_at"]) + 3 * 86400
        self.assertEqual(projects.derive_status(record, None, now=later), "stale")
        self.assertEqual(projects.derive_status(record, {"status": "running"}), "analyzing")
        self.assertEqual(projects.derive_status(record, {"status": "queued"}), "queued")
        self.assertEqual(projects.derive_status(record, {"status": "failed", "finished_at": "2099-01-01T00:00:00Z"}), "failed")
        empty = projects.new_record("fresh", root_name="fresh", path="/Users/robin/fresh", device_id=None,
                                    output_dir="fresh", grant_id=None, origin="analyze")
        self.assertEqual(projects.derive_status(empty, None), "not_analyzed")
        self.assertEqual(projects.derive_status(empty, {"status": "failed"}), "failed")

    def test_unsafe_legacy_directory_gets_opaque_id_but_keeps_output_dir(self):
        self.item("My Notes", "a.md", "Personal notes.", "A", 1)
        doc = projects.sync_registry(grants=[{"id": "g_n", "path": "/Users/robin/My Notes"}])
        record = doc["projects"][0]
        self.assertRegex(record["project_id"], r"^My-Notes-[0-9a-f]{6}$")
        self.assertEqual(record["output_dir"], "My Notes")
        self.assertEqual(record["root_name"], "My Notes")
        self.assertEqual(record["stats"]["files"], 1)


class HierarchyTests(FixtureMixin, unittest.TestCase):
    def _doc(self, *entries):
        doc = {"schema_version": projects.SCHEMA, "projects": []}
        for project_id, path, device in entries:
            doc["projects"].append(projects.new_record(project_id, root_name=project_id, path=path, device_id=device,
                                                       output_dir=project_id, grant_id=None, origin="analyze"))
        projects.relink(doc)
        return {r["project_id"]: r for r in doc["projects"]}

    def test_deepest_ancestor_is_parent_and_siblings_share_it(self):
        by_id = self._doc(
            ("code", "/Users/robin/code", None),
            ("commontasks", "/Users/robin/code/commontasks", None),
            ("web", "/Users/robin/code/commontasks/web", None),
            ("other", "/Users/robin/code/other", None),
            ("codex", "/Users/robin/codex", None),  # prefix of the string, not of the path
        )
        self.assertIsNone(by_id["code"]["parent_id"])
        self.assertEqual(by_id["code"]["children"], ["commontasks", "other"])
        self.assertEqual(by_id["commontasks"]["parent_id"], "code")
        self.assertEqual(by_id["web"]["parent_id"], "commontasks")  # grandchild links to the deepest ancestor
        self.assertEqual(by_id["commontasks"]["children"], ["web"])
        self.assertIsNone(by_id["codex"]["parent_id"])
        tree = projects.build_tree([projects.public_record({}, r, set(by_id)) for r in by_id.values()])
        self.assertEqual([n["project_id"] for n in tree], ["code", "codex"])
        self.assertEqual([n["project_id"] for n in tree[0]["children"]], ["commontasks", "other"])
        self.assertEqual(tree[0]["children"][0]["children"][0]["project_id"], "web")

    def test_folder_tree_exposes_registered_nested_folder_metadata(self):
        by_id = self._doc(
            ("code", "/Users/robin/code", "d_mac"),
            ("commontasks", "/Users/robin/code/commontasks", "d_mac"),
            ("web", "/Users/robin/code/commontasks/web", "d_mac"),
        )
        records = [projects.public_record({}, record, set(by_id)) for record in by_id.values()]
        tree = projects.build_folder_tree(records)
        self.assertEqual(tree[0]["folder_id"], "folder:code")
        self.assertEqual(tree[0]["path"], "/Users/robin/code")
        self.assertEqual(tree[0]["parent_folder_id"], None)
        child = tree[0]["children"][0]
        self.assertEqual(child["folder_id"], "folder:commontasks")
        self.assertEqual(child["parent_folder_id"], "folder:code")
        self.assertEqual(child["children"][0]["folder_id"], "folder:web")
        self.assertEqual(child["children"][0]["parent_folder_id"], "folder:commontasks")

    def test_folder_tree_updates_for_added_moved_and_removed_folder(self):
        by_id = self._doc(("code", "/Users/robin/code", "d_mac"))
        added = projects.new_record("docs", root_name="docs", path="/Users/robin/code/docs",
                                    device_id="d_mac", output_dir="docs", grant_id=None, origin="analyze")
        by_id["docs"] = added
        doc = {"schema_version": projects.SCHEMA, "projects": [
            next(record for record in by_id.values() if record["project_id"] == "code"), added,
        ]}
        projects.relink(doc)
        public = [projects.public_record(doc, record, {"code", "docs"}) for record in doc["projects"]]
        tree = projects.build_folder_tree(public)
        self.assertEqual([node["project_id"] for node in tree[0]["children"]], ["docs"])

        # Moving a registered folder turns it into a sibling/root after relink.
        added["path"] = "/Users/robin/docs"
        projects.relink(doc)
        public = [projects.public_record(doc, record, {"code", "docs"}) for record in doc["projects"]]
        tree = projects.build_folder_tree(public)
        self.assertEqual([node["project_id"] for node in tree], ["code", "docs"])
        self.assertIsNone(next(node for node in tree if node["project_id"] == "docs")["parent_folder_id"])

        # Removing the child removes the folder node and cannot leave a stale
        # child pointer on its former parent.
        doc["projects"] = [record for record in doc["projects"] if record["project_id"] != "docs"]
        projects.relink(doc)
        public = [projects.public_record(doc, record, {"code"}) for record in doc["projects"]]
        tree = projects.build_folder_tree(public)
        self.assertEqual(tree, [{
            "folder_id": "folder:code", "project_id": "code", "name": "code",
            "path": "/Users/robin/code", "device_id": "d_mac", "status": "not_analyzed",
            "parent_folder_id": None, "children": [],
        }])

    def test_relations_only_on_the_same_device(self):
        by_id = self._doc(("code", "/Users/robin/code", "d_mac"),
                          ("nas-copy", "/Users/robin/code/commontasks", "d_nas"))
        self.assertIsNone(by_id["nas-copy"]["parent_id"])
        self.assertEqual(by_id["code"]["children"], [])

    def test_public_record_hides_invisible_relations(self):
        by_id = self._doc(("code", "/Users/robin/code", None), ("commontasks", "/Users/robin/code/commontasks", None))
        public = projects.public_record({}, by_id["commontasks"], {"commontasks"})
        self.assertIsNone(public["parent_id"])
        self.assertEqual(projects.public_record({}, by_id["code"], {"code"})["children"], [])
        visible = [projects.public_record({}, by_id["commontasks"], {"commontasks"})]
        self.assertEqual(projects.build_folder_tree(visible)[0]["parent_folder_id"], None)

    def test_unique_ids_for_same_folder_name(self):
        doc = {"projects": []}
        first = projects.allocate_project_id(doc, "commontasks", "d_mac", "/Users/robin/code/commontasks")
        self.assertEqual(first, "commontasks")
        doc["projects"].append(projects.new_record(first, root_name="commontasks", path="/Users/robin/code/commontasks",
                                                   device_id="d_mac", output_dir=first, grant_id=None, origin="analyze"))
        second = projects.allocate_project_id(doc, "commontasks", "d_nas", "/Volumes/nas/commontasks")
        self.assertRegex(second, r"^commontasks-[0-9a-f]{6}$")
        doc["projects"].append(projects.new_record(second, root_name="commontasks", path="/Volumes/nas/commontasks",
                                                   device_id="d_nas", output_dir=second, grant_id=None, origin="analyze"))
        third = projects.allocate_project_id(doc, "commontasks", "d_mac", "/Users/robin/archive/commontasks")
        self.assertNotIn(third, {first, second})
        self.assertRegex(projects.allocate_project_id(doc, "我的 项目", "d_mac", "/Users/robin/x"), r"^project-[0-9a-f]{6}$")
        # Route words under /api/projects/ are never used as a plain id.
        self.assertRegex(projects.allocate_project_id(doc, "ids", "d_mac", "/Users/robin/ids"), r"^ids-[0-9a-f]{6}$")

    def test_path_validation(self):
        self.assertEqual(projects.normalize_folder_path("/Users/robin/code/x/"), "/Users/robin/code/x")
        self.assertEqual(projects.normalize_folder_path("~/code//x"), "~/code/x")
        for bad in ("relative/x", "/Users/robin/../root", "/", "~", "", "/Users/\x00x", 5, "~/a/../b"):
            with self.assertRaises(projects.PathError):
                projects.normalize_folder_path(bad)
        grants = [{"id": "g1", "path": "/Users/robin/code/x"}]
        self.assertEqual(projects.match_grant(grants, "~/code/x")["id"], "g1")
        self.assertIsNone(projects.match_grant(grants, "~/x"))


class DigestTests(FixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.commontasks()
        projects.sync_registry(grants=[{"id": "g_ct", "path": "/Users/robin/code/commontasks"}])
        self.ctx = context_for("commontasks")

    def test_list_filters_by_project_and_source_scopes(self):
        self.assertEqual(project_digest.list_projects(self.ctx)["projects"][0]["project_id"], "commontasks")
        self.assertEqual(project_digest.list_projects(context_for("other")), {"projects": [], "tree": [], "folder_tree": []})
        no_source = {"projectScopes": ["commontasks"], "sourceScopes": ["connector:other"]}
        self.assertEqual(project_digest.list_projects(no_source)["projects"], [])
        wildcard = {"projectScopes": ["*"], "sourceScopes": ["*"]}
        listing = project_digest.list_projects(wildcard)
        self.assertEqual(listing["tree"], [{"project_id": "commontasks", "children": []}])
        self.assertEqual(listing["folder_tree"][0]["folder_id"], "folder:commontasks")
        self.assertEqual(listing["folder_tree"][0]["children"], [])
        self.assertEqual(set(listing["projects"][0]), {
            "project_id", "device_id", "root_name", "path", "parent_id", "children", "status",
            "analyzed_at", "stats", "tiers", "embedded_roots"})

    def test_digest_sections(self):
        result = project_digest.digest(self.ctx, "commontasks", now=NOW)
        self.assertEqual(set(result), {"project", "overview", "key_files", "areas", "activity", "graph", "related", "generated_at"})
        self.assertTrue(result["overview"].startswith("Shared clinic task tracker with a voice assistant."))
        self.assertIn("src (2 files)", result["overview"])
        self.assertNotIn("vendor", result["overview"])
        # Key files: tier A/B with purposes, ordered by tier then classifier rank; embedded excluded.
        self.assertEqual([k["file"] for k in result["key_files"]], ["src/app.py", "web/main.ts", "README.md", "src/db.py"])
        self.assertEqual(result["key_files"][0], {"file": "src/app.py", "tier": "A",
                                                  "purpose": "Flask entry point wiring routes and the scheduler.",
                                                  "key_points": ["src/app.py point"]})
        areas = {a["folder"]: a for a in result["areas"]}
        self.assertEqual(areas["src"]["files"], 2)
        self.assertEqual(areas["src"]["summary"], "Flask entry point wiring routes and the scheduler; SQLite persistence layer for tasks")
        self.assertEqual(areas["docs"]["summary"], "1 file, structure only (no summaries yet).")
        self.assertTrue(areas["vendor/ua"]["embedded"])
        self.assertEqual(areas["vendor/ua"]["files"], 2)
        self.assertEqual(result["areas"][-1]["folder"], "vendor/ua")  # the separate embedded line comes last
        self.assertNotIn("vendor", [a["folder"] for a in result["areas"]])
        # Graph summary.
        self.assertEqual(result["graph"]["layers"], [{"name": "Core", "files": 2}, {"name": "UI", "files": 1}])
        self.assertEqual(result["graph"]["top_nodes"][0], {"name": "app.py", "type": "file", "file": "src/app.py"})
        self.assertEqual(result["related"], {"parent": None, "children": [], "siblings": []})

    def test_activity_window_and_by_day(self):
        result = project_digest.digest(self.ctx, "commontasks", now=NOW)["activity"]
        self.assertEqual(result["window"], "7d")
        files = [c["file"] for c in result["changed"]]
        self.assertNotIn("src/db.py", files)  # 10 days old
        self.assertIn("web/main.ts", files)
        self.assertEqual(files[-1], "web/main.ts")  # newest first; this one is 2 days old
        self.assertEqual(len(result["by_day"]), 7)
        self.assertEqual(sum(d["count"] for d in result["by_day"]), len(files))
        main = next(c for c in result["changed"] if c["file"] == "web/main.ts")
        self.assertEqual(main["purpose"], "Browser client that renders the task board.")
        window = project_digest.activity(self.ctx, "commontasks", NOW - 12 * 86400, NOW - 5 * 86400)
        self.assertEqual([c["file"] for c in window["changed"]], ["src/db.py"])
        self.assertIsNone(project_digest.activity(context_for("other"), "commontasks", 0, NOW))

    def test_activity_prefers_live_connector_manifest(self):
        connector = ConnectorMixin.start_connector(self)
        connector.manifests["g_ct"] = [
            {"relpath": "src/db.py", "mtime": int(NOW - 60), "size": 1, "kind": "file"},
            {"relpath": "src/new.py", "mtime": int(NOW - 120), "size": 1, "kind": "file"},
            {"relpath": "web/main.ts", "mtime": int(NOW - 30 * 86400), "size": 1, "kind": "file"},
        ]
        result = project_digest.activity(self.ctx, "commontasks", NOW - 86400, NOW)
        self.assertEqual([c["file"] for c in result["changed"]], ["src/db.py", "src/new.py"])
        self.assertEqual(result["changed"][0]["purpose"], "SQLite persistence layer for tasks.")
        self.assertEqual(result["changed"][1]["purpose"], "")

    def test_activity_offline_connector_is_stale_with_as_of(self):
        # Freshness audit 2026-10-18: an unreachable connector must degrade
        # to stale-with-as-of, never to a bare "no changes" body.
        connector = ConnectorMixin.start_connector(self)
        connector.manifests["g_ct"] = [
            {"relpath": "src/db.py", "mtime": int(NOW - 3600), "size": 1, "kind": "file"}]
        online = project_digest.activity(self.ctx, "commontasks", NOW - 86400, NOW)
        self.assertEqual(set(online), {"changed"})  # online body stays minimal
        connector.shutdown()  # the source goes dark
        project_digest._MANIFEST_CACHE.clear()
        degraded = project_digest.activity(self.ctx, "commontasks", NOW - 86400, NOW)
        self.assertEqual(set(degraded), {"changed", "freshness"})
        self.assertEqual(degraded["freshness"]["state"], "stale")
        self.assertTrue(degraded["freshness"]["asOf"])  # index time, always present here
        self.assertIn("connector_unavailable", degraded["freshness"]["detail"])
        # The listed files are the INDEX's view again (README.md etc.), not
        # the manifest's src/db.py - that is exactly why the as-of matters.
        degraded_files = [c["file"] for c in degraded["changed"]]
        self.assertIn("README.md", degraded_files)
        self.assertNotIn("src/db.py", degraded_files)
        # The digest's activity section carries the same honesty block.
        section = project_digest.digest(self.ctx, "commontasks", now=NOW)["activity"]
        self.assertEqual(section["freshness"]["state"], "stale")
        self.assertEqual(section["freshness"]["asOf"], degraded["freshness"]["asOf"])

    def test_digest_is_absent_outside_scope(self):
        self.assertIsNone(project_digest.digest(context_for("other"), "commontasks"))
        self.assertIsNone(project_digest.digest(self.ctx, "../etc"))

    def test_related_parent_children_siblings(self):
        registry = projects.ProjectRegistry()
        with registry.edit() as doc:
            for pid, path in (("code", "/Users/robin/code"), ("other", "/Users/robin/code/other")):
                doc["projects"].append(projects.new_record(pid, root_name=pid, path=path, device_id=None,
                                                           output_dir=pid, grant_id=None, origin="analyze"))
        ctx = context_for("commontasks", "code", "other")
        result = project_digest.digest(ctx, "commontasks", now=NOW)
        self.assertEqual(result["related"]["parent"]["project_id"], "code")
        self.assertEqual([s["project_id"] for s in result["related"]["siblings"]], ["other"])
        self.assertEqual(result["project"]["parent_id"], "code")
        # Without a grant for the parent, the relation is not revealed.
        hidden = project_digest.digest(context_for("commontasks", "other"), "commontasks", now=NOW)
        self.assertIsNone(hidden["related"]["parent"])
        self.assertEqual(hidden["related"]["siblings"], [])
        tree = project_digest.list_projects(ctx)["tree"]
        self.assertEqual(tree[0]["project_id"], "code")
        self.assertEqual([c["project_id"] for c in tree[0]["children"]], ["commontasks", "other"])


class AskTests(FixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.commontasks()
        projects.sync_registry(grants=[])
        self.ctx = context_for("commontasks")
        self.prompts = []

    def llm(self, reply):
        def fake(prompt):
            self.prompts.append(prompt)
            return reply
        return fake

    def test_hit_synthesizes_with_sources(self):
        result = project_digest.ask(self.ctx, "commontasks", "Where is the SQLite persistence?",
                                    member="robin", role="owner", llm=self.llm("Tasks persist in src/db.py."),
                                    gbrain=lambda q, m, r: [])
        self.assertEqual(result["answer"], "Tasks persist in src/db.py.")
        self.assertEqual(result["sources"][0], {"file": "src/db.py"})
        self.assertIn(result["confidence"], {"high", "medium"})
        self.assertIn("FILE: src/db.py", self.prompts[0])
        self.assertIn("OVERVIEW: Shared clinic task tracker", self.prompts[0])
        self.assertIn("NOT_ENOUGH_INFO", self.prompts[0])

    def test_nothing_matches_is_an_honest_miss_without_llm(self):
        result = project_digest.ask(self.ctx, "commontasks", "quantum chromodynamics lattice",
                                    member="robin", role="owner", llm=self.llm("made up"), gbrain=lambda q, m, r: [])
        self.assertEqual(result["confidence"], "none")
        self.assertEqual(result["sources"], [])
        self.assertIn("enough information", result["answer"])
        self.assertEqual(self.prompts, [])

    def test_model_says_not_enough(self):
        result = project_digest.ask(self.ctx, "commontasks", "scheduler retry policy?", member="robin", role="owner",
                                    llm=self.llm("NOT_ENOUGH_INFO"), gbrain=lambda q, m, r: [])
        self.assertEqual(result["confidence"], "none")
        self.assertEqual(result["sources"], [])

    def test_overview_question_uses_key_files(self):
        result = project_digest.ask(self.ctx, "commontasks", "Give me an overview", member="robin", role="owner",
                                    llm=self.llm("A clinic task tracker."), gbrain=lambda q, m, r: [])
        self.assertEqual(result["answer"], "A clinic task tracker.")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(result["sources"][0], {"file": "src/app.py"})

    def test_relevant_gbrain_blocks_join_context_and_irrelevant_are_dropped(self):
        seen = []

        def gbrain(question, member, role):
            seen.append((member, role))
            return [{"brain": "robin", "score": "0.9", "text": "Decided commontasks deploys to the Jetson on Fridays."},
                    {"brain": "family", "score": "0.8", "text": "Groceries: milk and eggs."}]

        result = project_digest.ask(self.ctx, "commontasks", "When do deploys happen?", member="robin", role="owner",
                                    llm=self.llm("Fridays, on the Jetson."), gbrain=gbrain)
        self.assertEqual(seen, [("robin", "owner")])
        self.assertEqual(result["answer"], "Fridays, on the Jetson.")
        self.assertIn("MEMORY (robin): Decided commontasks deploys", self.prompts[0])
        self.assertNotIn("Groceries", self.prompts[0])

    def test_gbrain_skipped_without_resolved_role(self):
        called = []
        project_digest.ask(self.ctx, "commontasks", "sqlite persistence", member="robin", role=None,
                           llm=self.llm("ok"), gbrain=lambda *a: called.append(a) or [])
        self.assertEqual(called, [])

    def test_model_unavailable(self):
        result = project_digest.ask(self.ctx, "commontasks", "sqlite persistence", member="robin", role="owner",
                                    llm=self.llm(None), gbrain=lambda q, m, r: [])
        self.assertEqual(result["confidence"], "unavailable")
        self.assertEqual(result["sources"][0], {"file": "src/db.py"})

    def test_out_of_scope_project(self):
        self.assertIsNone(project_digest.ask(context_for("other"), "commontasks", "sqlite", llm=self.llm("x")))
        self.assertEqual(self.prompts, [])

    # ── ranking vs embedded third-party folders (2026-10-11) ───────────────
    def _bundled_upstream(self):
        """Embedded files that match a question much better than the owner's code."""
        self.item("commontasks", "vendor/ua/scheduler.ts",
                  "Scheduler scheduler scheduler: upstream job scheduler with retry scheduler queue.", "B", 42,
                  embedded="vendor/ua")
        self.item("commontasks", "vendor/ua/sched2.ts", "Second upstream scheduler helper.", "B", 43, embedded="vendor/ua")
        self.item("commontasks", "vendor/ua/sched3.ts", "Third upstream scheduler module.", "B", 44, embedded="vendor/ua")
        projects.sync_registry(grants=[])

    def test_owner_code_outranks_embedded_upstream(self):
        self._bundled_upstream()
        result = project_digest.ask(self.ctx, "commontasks", "How does the scheduler work?",
                                    member="robin", role="owner", llm=self.llm("ok"), gbrain=lambda q, m, r: [])
        files = [s["file"] for s in result["sources"]]
        self.assertEqual(files[0], "src/app.py")  # "wiring routes and the scheduler", tier A
        self.assertLessEqual(sum(f.startswith("vendor/ua/") for f in files), project_digest.EMBEDDED_MAX_HITS)
        self.assertIn("bundled third-party folder vendor/ua/", self.prompts[0])

    def test_naming_the_embedded_folder_lifts_the_penalty(self):
        self._bundled_upstream()
        result = project_digest.ask(self.ctx, "commontasks", "How does the ua scheduler work?",
                                    member="robin", role="owner", llm=self.llm("ok"), gbrain=lambda q, m, r: [])
        files = [s["file"] for s in result["sources"]]
        self.assertEqual(files[0], "vendor/ua/scheduler.ts")
        self.assertGreater(sum(f.startswith("vendor/ua/") for f in files), project_digest.EMBEDDED_MAX_HITS)

    def test_project_name_is_not_evidence_and_overview_cites_own_key_files(self):
        self.item("commontasks", "vendor/ua/UPSTREAM.md",
                  "How commontasks vendors this upstream copy of commontasks tooling.", "B", 45, embedded="vendor/ua")
        projects.sync_registry(grants=[])
        result = project_digest.ask(self.ctx, "commontasks", "What is commontasks about and what are its key files?",
                                    member="robin", role="owner", llm=self.llm("A clinic task tracker."),
                                    gbrain=lambda q, m, r: [])
        files = [s["file"] for s in result["sources"]]
        self.assertEqual(files[:3], ["src/app.py", "web/main.ts", "README.md"])  # own tier-A key files first
        self.assertNotIn("vendor/ua/UPSTREAM.md", files)
        self.assertIn("KEY FILE (A): src/app.py", self.prompts[0])

    def test_specific_question_naming_the_project_leads_with_matching_files(self):
        result = project_digest.ask(self.ctx, "commontasks", "How does commontasks persist tasks in SQLite?",
                                    member="robin", role="owner", llm=self.llm("In src/db.py."),
                                    gbrain=lambda q, m, r: [])
        self.assertEqual(result["sources"][0], {"file": "src/db.py"})  # the answering file, not key files
        self.assertNotIn("KEY FILE", self.prompts[0])
        # with nothing specific to match, naming the project still gives the overview
        project_digest.ask(self.ctx, "commontasks", "Tell me commontasks", member="robin", role="owner",
                           llm=self.llm("ok"), gbrain=lambda q, m, r: [])
        self.assertIn("KEY FILE (A): src/app.py", self.prompts[-1])


class AnalyzeJobTests(FixtureMixin, ConnectorMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.connector = self.start_connector()
        self.launcher = RecordingLauncher()

    def analyze(self, path, **kwargs):
        return project_jobs.create_analyze_job(path, launcher=self.launcher, **kwargs)

    def test_new_folder_creates_grant_registers_and_launches(self):
        result = self.analyze("~/code/commontasks")
        self.assertRegex(result["job_id"], r"^job_[0-9a-f]{12}$")
        self.assertEqual(result, {"job_id": result["job_id"], "project_id": "commontasks",
                                  "relation": {"parent_id": None, "children": []}, "status": "queued"})
        self.assertEqual([c[0] for c in self.connector.calls], ["GET", "POST"])
        self.assertEqual(self.connector.calls[1][2], {"path": "~/code/commontasks"})
        record = projects.ProjectRegistry().get("commontasks")
        self.assertEqual(record["path"], "/Users/robin/code/commontasks")
        self.assertEqual(record["grant_id"], "g_001")
        self.assertEqual(record["device_id"], "d_mac")
        self.assertEqual(record["last_job_id"], result["job_id"])
        job, script = self.launcher.calls[0]
        text = Path(script).read_text(encoding="utf-8")
        self.assertIn("index_project.py --host", text)
        self.assertIn("--grant g_001 --limit 0", text)
        self.assertIn("ua_bridge.py", text)
        self.assertIn("--project-name commontasks", text)
        self.assertIn("flock", text)
        self.assertNotIn("conn-token", text)  # the token is read from its file, never embedded
        self.assertEqual(oct(os.stat(script).st_mode & 0o777), "0o700")
        state = project_jobs.job_state(result["job_id"])
        self.assertEqual(state["status"], "queued")
        self.assertEqual(state["progress"], {"done": 0, "total": 0})

    def test_existing_grant_is_reused(self):
        self.connector.grants.append({"id": "g_ct", "path": "/Users/robin/code/commontasks"})
        self.analyze("/Users/robin/code/commontasks/")
        self.assertEqual([c[0] for c in self.connector.calls], ["GET"])
        self.assertEqual(projects.ProjectRegistry().get("commontasks")["grant_id"], "g_ct")

    def test_rejections(self):
        cases = [("relative/path", "invalid_path", 400), ("/Users/robin/missing", "path_not_grantable", 400),
                 ("/Users/robin/secret-stuff", "path_denied", 403)]
        self.connector.missing.add("/Users/robin/missing")
        for path, code, status in cases:
            with self.assertRaises(project_jobs.AnalyzeError) as caught:
                self.analyze(path)
            self.assertEqual((caught.exception.code, caught.exception.status), (code, status))
        with self.assertRaises(project_jobs.AnalyzeError) as caught:
            self.analyze("/Users/robin/code/x", device_id="d_jetson")
        self.assertEqual(caught.exception.code, "unsupported_device")
        with self.assertRaises(project_jobs.AnalyzeError) as caught:
            self.analyze("/Users/robin/code/x", device_id="bad id!")
        self.assertEqual(caught.exception.code, "invalid_device_id")
        os.environ.pop("UYP_CONNECTOR_HOST")
        with self.assertRaises(project_jobs.AnalyzeError) as caught:
            self.analyze("/Users/robin/code/x")
        self.assertEqual((caught.exception.code, caught.exception.status), ("connector_unconfigured", 503))
        self.assertEqual(self.launcher.calls, [])

    def test_active_job_is_returned_instead_of_a_second_run(self):
        first = self.analyze("/Users/robin/code/commontasks")
        (self.state / "project-jobs" / first["job_id"] / "pid").write_text(str(os.getpid()), encoding="utf-8")
        second = self.analyze("/Users/robin/code/commontasks")
        self.assertEqual(second["job_id"], first["job_id"])
        self.assertEqual(len(self.launcher.calls), 1)

    def test_ancestor_links_children_and_reuses_their_outputs(self):
        self.commontasks()
        self.connector.grants.append({"id": "g_ct", "path": "/Users/robin/code/commontasks"})
        projects.sync_registry()
        result = self.analyze("/Users/robin/code")
        self.assertEqual(result["project_id"], "code")
        self.assertEqual(result["relation"], {"parent_id": None, "children": ["commontasks"]})
        self.assertEqual(projects.ProjectRegistry().get("commontasks")["parent_id"], "code")
        job, _ = self.launcher.calls[0]
        self.assertEqual(job["seeds"], [{"mode": "ancestor", "from": "commontasks", "project_id": "commontasks",
                                         "prefix": "commontasks"}])
        self.assertEqual(projects.ProjectRegistry().get("code")["linked_children"], ["commontasks"])
        report = project_jobs.seed(job)
        self.assertEqual(report["reused"], 7)
        seeded = json.loads((self.out / "code" / "commontasks__src__app.py.knowledge.json").read_text(encoding="utf-8"))
        self.assertEqual(seeded["file"], "commontasks/src/app.py")
        self.assertEqual(seeded["reused_from"], "commontasks")
        original = json.loads((self.out / "commontasks" / "src__app.py.knowledge.json").read_text(encoding="utf-8"))
        self.assertEqual(seeded["version"], original["version"])  # same version -> the indexer's resume skips it
        self.assertEqual(project_jobs.seed(job)["reused"], 0)  # idempotent

    def test_descendant_gets_parent_context_and_enriched_items(self):
        self.commontasks()
        self.connector.grants.append({"id": "g_ct", "path": "/Users/robin/code/commontasks"})
        projects.sync_registry()
        result = self.analyze("/Users/robin/code/commontasks/src")
        self.assertEqual(result["relation"], {"parent_id": "commontasks", "children": []})
        job, script = self.launcher.calls[0]
        context = Path(job["context_file"]).read_text(encoding="utf-8")
        self.assertIn("part of the larger project 'commontasks'", context)
        self.assertIn("Shared clinic task tracker", context)
        self.assertIn("--context-file", Path(script).read_text(encoding="utf-8"))
        self.assertEqual(projects.ProjectRegistry().get("src")["context"]["parent_id"], "commontasks")
        report = project_jobs.seed(job)
        self.assertEqual(report["reused"], 2)  # src/app.py and src/db.py (both enriched)
        self.assertTrue((self.out / "src" / "app.py.knowledge.json").exists())

    def test_pathless_import_is_adopted_not_duplicated(self):
        self.commontasks()
        projects.sync_registry(grants=None, use_connector=False)  # connector offline at import
        result = self.analyze("/Users/robin/code/commontasks")
        self.assertEqual(result["project_id"], "commontasks")
        records = projects.ProjectRegistry().records()
        self.assertEqual([r["project_id"] for r in records], ["commontasks"])
        self.assertEqual(records[0]["path"], "/Users/robin/code/commontasks")

    def test_name_collision_redirects_index_output(self):
        self.commontasks()
        self.connector.grants.append({"id": "g_ct", "path": "/Users/robin/code/commontasks"})
        projects.sync_registry()
        result = self.analyze("/Users/robin/archive/commontasks")
        self.assertRegex(result["project_id"], r"^commontasks-[0-9a-f]{6}$")
        job, script = self.launcher.calls[0]
        link = Path(job["dir"]) / "out" / "commontasks"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.path.realpath(link), os.path.realpath(self.out / result["project_id"]))
        text = Path(script).read_text(encoding="utf-8")
        self.assertIn(f"--project-name {result['project_id']}", text)
        self.assertIn(f"export UYP_OUTPUT_ROOT={job['dir']}/out", text)

    def test_job_state_parsing(self):
        result = self.analyze("/Users/robin/code/commontasks")
        directory = self.state / "project-jobs" / result["job_id"]
        (directory / "pid").write_text(str(os.getpid()), encoding="utf-8")
        log = directory / "job.log"
        log.write_text("PHASE waiting 2026\n", encoding="utf-8")
        self.assertEqual(project_jobs.job_state(result["job_id"])["phase"], "waiting")
        log.write_text("PHASE waiting x\nPHASE start x\nPHASE seed\nPHASE index\nindexing commontasks: 4 files (of 10)\n"
                       "key-file classifier: {\"A\": 1} in 0.1s\n  quick-summary         src/app.py\n"
                       "  structure-only        docs/a.txt\n", encoding="utf-8")
        state = project_jobs.job_state(result["job_id"])
        self.assertEqual((state["status"], state["phase"], state["progress"]), ("running", "enrich", {"done": 2, "total": 4}))
        self.assertEqual(state["log_tail"][-1], "  structure-only        docs/a.txt")
        self.assertEqual(set(project_jobs.public_job(state)), {"job_id", "project_id", "status", "phase", "progress", "log_tail"})
        with open(log, "a", encoding="utf-8") as fh:
            fh.write("DONE in 5s | {}\nindex_project exit=0\nPHASE graph\nua_bridge exit=0\nPHASE finalize\n")
        (directory / "exit_code").write_text("0", encoding="utf-8")
        state = project_jobs.job_state(result["job_id"])
        self.assertEqual((state["status"], state["phase"], state["progress"]), ("done", "done", {"done": 4, "total": 4}))
        (directory / "exit_code").write_text("1", encoding="utf-8")
        self.assertEqual(project_jobs.job_state(result["job_id"])["status"], "failed")
        self.assertEqual(project_jobs.jobs_by_project()["commontasks"]["status"], "failed")
        self.assertIsNone(project_jobs.job_state("job_../../etc"))

    def test_dead_process_without_exit_code_is_failed(self):
        result = self.analyze("/Users/robin/code/commontasks")
        directory = self.state / "project-jobs" / result["job_id"]
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        (directory / "pid").write_text(str(proc.pid), encoding="utf-8")
        (directory / "job.log").write_text("PHASE start\nPHASE index\n", encoding="utf-8")
        state = project_jobs.job_state(result["job_id"])
        self.assertEqual((state["status"], state["phase"]), ("failed", "interrupted"))

    @unittest.skipUnless(shutil.which("bash"), "bash required")
    def test_generated_script_runs_end_to_end_with_shim_indexer(self):
        shim = self.root / "pyshim"
        shim.write_text(f"""#!/bin/sh
case "$1" in
  project_jobs.py) exec {sys.executable} "$@" ;;
  index_project.py) echo "indexing commontasks: 2 files (of 2)"; echo 'key-file classifier: {{"A": 2}} in 0.0s';
                    echo "  quick-summary         a.py"; echo "  quick-summary         b.py"; echo "DONE in 1s | {{}}"; exit 0 ;;
  ua_bridge.py) echo "graph ok"; exit 0 ;;
esac
exit 9
""", encoding="utf-8")
        shim.chmod(0o755)
        ua = self.root / "ua"
        ua.mkdir()
        os.environ.update({"UYP_ANALYZE_PYTHON": str(shim), "UYP_ANALYZE_LAYA_UNIT": "", "UYP_UA_ROOT": str(ua)})
        self.item("commontasks", "a.py", "Module a.", "A", 1)
        result = self.analyze("/Users/robin/code/commontasks")
        _, script = self.launcher.calls[0]
        completed = subprocess.run(["bash", script], timeout=60)
        self.assertEqual(completed.returncode, 0)
        state = project_jobs.job_state(result["job_id"])
        self.assertEqual((state["status"], state["phase"], state["progress"]), ("done", "done", {"done": 2, "total": 2}))
        log = "\n".join(state["log_tail"])
        self.assertIn("ua_bridge exit=0", log)
        self.assertIn("finalize: registry refreshed for commontasks", log)
        self.assertEqual(projects.ProjectRegistry().get("commontasks")["stats"]["files"], 1)


if __name__ == "__main__":
    unittest.main()
