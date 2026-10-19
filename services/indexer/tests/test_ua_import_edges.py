"""Imports-edge pipeline tests: the extract-import-map stage the bridge owns.

ua_bridge runs vendored node stages in this order:

    scan-project.mjs -> extract-import-map.mjs -> compute-batches.mjs
        -> extract-structure.mjs (per batch) -> ua_graph_builder.mjs

scan-project deliberately emits no importMap (the interactive skill's scanner
agent merges Step C itself), while compute-batches reads ``scan.importMap`` to
build ``batchImportData`` and to run Louvain.  Without the bridge-side
extract-import-map stage, batchImportData is all-empty, ua_graph_builder's
``importsByPath`` is all-empty, and the built graph has zero imports edges.

Two layers are pinned here, all against a 6-file Python fixture whose edges
are known by construction:

    app.py -> gateway.py, calendar.py
    gateway.py -> policy.py
    policy.py -> broker.py
    broker.py -> device.py
    calendar.py imports nothing (negative case: no calendar->device edge)

1. Real node scripts (skipped when node is absent): the full offline chain
   from fixture to knowledge-graph.json, plus incremental (analysisPaths) and
   deleted-file behaviour.  Each test seeds its own state so alphabetical
   execution order carries no hidden dependencies.
2. Faked node: run() invocation order, and that compute-batches receives a
   scan-result.json that already carries importMap.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import ua_bridge  # noqa: E402

INDEXER = Path(__file__).parents[1]
# Deployment layouts differ: the repo vendors UA under indexer/vendor, while
# jetson keeps it beside the indexer at ~/dev/uyp/understand-anything-src-*.
# UYP_UA_ROOT (the same variable production passes as --ua-root) wins.
UA_ROOT = Path(os.environ.get("UYP_UA_ROOT") or (INDEXER / "vendor" / "understand-anything"))
SKILLS = UA_ROOT / "skills" / "understand"
# repo layout nests under src/, the jetson deployment is flat
GRAPH_BUILDER = next(p for p in (INDEXER / "src" / "ua_graph_builder.mjs",
                                 INDEXER / "ua_graph_builder.mjs") if p.is_file())

# The five known edges, as (source locator, target locator) in the built graph.
KNOWN_EDGES = {
    ("file:app.py", "file:gateway.py"),
    ("file:app.py", "file:calendar.py"),
    ("file:gateway.py", "file:policy.py"),
    ("file:policy.py", "file:broker.py"),
    ("file:broker.py", "file:device.py"),
}

FIXTURE_FILES = {
    "app.py": (
        "from gateway import Gateway\n"
        "from calendar import Calendar\n"
        "\n"
        "\n"
        "def main() -> int:\n"
        "    gw = Gateway()\n"
        "    cal = Calendar()\n"
        "    return gw.handle(cal.today())\n"
    ),
    "gateway.py": (
        "from policy import Policy\n"
        "\n"
        "\n"
        "class Gateway:\n"
        "    def handle(self, request: str) -> int:\n"
        "        return Policy().check(request)\n"
    ),
    "policy.py": (
        "from broker import Broker\n"
        "\n"
        "\n"
        "class Policy:\n"
        "    def check(self, request: str) -> int:\n"
        "        return Broker().publish(request)\n"
    ),
    "broker.py": (
        "from device import Device\n"
        "\n"
        "\n"
        "class Broker:\n"
        "    def publish(self, message: str) -> int:\n"
        "        return Device().send(message)\n"
    ),
    "device.py": (
        "class Device:\n"
        "    def send(self, message: str) -> int:\n"
        "        return len(message)\n"
    ),
    "calendar.py": (
        "class Calendar:\n"
        "    def today(self) -> str:\n"
        "        return '2026-10-18'\n"
    ),
}


def _node_and_skills_available() -> bool:
    return bool(shutil.which("node")) and (SKILLS / "scan-project.mjs").is_file()


@unittest.skipUnless(_node_and_skills_available(), "node + vendored UA skills required")
class ImportPipelineFixtureTests(unittest.TestCase):
    """Real vendored node scripts against a temp fixture: the chain the bridge
    drives, reproducing its exact stage sequence (offline, no connector)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "fixture"
        self.work = Path(self.tmp.name) / "work"
        self.project.mkdir()
        self.work.mkdir()
        for name, content in FIXTURE_FILES.items():
            (self.project / name).write_text(content, encoding="utf-8")
        self.env = {"PATH": os.environ.get("PATH", ""), "UYP_UA_ROOT": str(UA_ROOT)}

    def run_node(self, *args):
        subprocess.run(["node", *args], check=True, env=self.env,
                       capture_output=True, text=True, cwd=str(self.tmp.name))

    def scan(self, name="scan-result.json") -> Path:
        path = self.work / name
        self.run_node(str(SKILLS / "scan-project.mjs"), str(self.project), str(path),
                      "--exclude-analysis-data")
        return path

    def merge_import_map(self, scan_path: Path, analysis_paths=None) -> dict:
        """Run extract-import-map over a scan-result and merge it in place —
        the same contract ua_bridge performs between its scan and batch
        stages. Returns the extractor's full result."""
        scan = json.loads(scan_path.read_text(encoding="utf-8"))
        payload = {"projectRoot": str(self.project), "files": scan.get("files", [])}
        if analysis_paths is not None:
            payload["analysisPaths"] = analysis_paths
        input_path = scan_path.with_name(scan_path.stem + "-import-input.json")
        output_path = scan_path.with_name(scan_path.stem + "-import-map.json")
        input_path.write_text(json.dumps(payload), encoding="utf-8")
        self.run_node(str(SKILLS / "extract-import-map.mjs"), str(input_path), str(output_path))
        result = json.loads(output_path.read_text(encoding="utf-8"))
        # full-scan replaces; analysisPaths mode emits only the re-analyzed
        # files' entries, so a consumer merges them into the previous map
        if analysis_paths is None:
            scan["importMap"] = result.get("importMap", {})
        else:
            scan.setdefault("importMap", {}).update(result.get("importMap", {}))
        scan_path.write_text(json.dumps(scan), encoding="utf-8")
        return result

    def merged_scan(self, name="scan-result.json") -> Path:
        path = self.scan(name)
        self.merge_import_map(path)
        return path

    def batches_from(self, scan_path: Path) -> dict:
        batches_path = scan_path.with_name("batches-" + scan_path.stem + ".json")
        self.run_node(str(SKILLS / "compute-batches.mjs"), str(self.project),
                      f"--scan-result={scan_path}", f"--output={batches_path}")
        return json.loads(batches_path.read_text(encoding="utf-8"))

    def test_1_extract_import_map_invocation_and_output_shape(self):
        # argv: <input.json> <output.json>; input {projectRoot, files};
        # output {scriptCompleted, stats, failures, importMap}. The merged
        # importMap resolves exactly the five known edges.
        scan_path = self.merged_scan()
        result = json.loads(scan_path.with_name("scan-result-import-map.json")
                            .read_text(encoding="utf-8"))
        self.assertTrue(result["scriptCompleted"])
        self.assertEqual(result["stats"],
                         {"filesScanned": 6, "filesWithImports": 4, "totalEdges": 5})
        imap = result["importMap"]
        self.assertEqual(imap["app.py"], ["calendar.py", "gateway.py"])
        self.assertEqual(imap["gateway.py"], ["policy.py"])
        self.assertEqual(imap["policy.py"], ["broker.py"])
        self.assertEqual(imap["broker.py"], ["device.py"])
        # negative case: calendar imports nothing, device imports nothing
        self.assertEqual(imap["calendar.py"], [])
        self.assertEqual(imap["device.py"], [])
        # merged into the scan-result compute-batches will read
        scan = json.loads(scan_path.read_text(encoding="utf-8"))
        self.assertEqual(scan["importMap"], imap)

    def test_2_scan_result_alone_has_no_import_map(self):
        # Pins WHY the bridge stage exists: scan-project never emits one.
        scan = json.loads(self.scan().read_text(encoding="utf-8"))
        self.assertNotIn("importMap", scan)
        self.assertEqual(len(scan["files"]), 6)
        self.assertTrue(all(f["fileCategory"] == "code" for f in scan["files"]))

    def test_3_compute_batches_populates_batch_import_data(self):
        batches = self.batches_from(self.merged_scan())
        self.assertEqual(batches["algorithm"], "louvain")
        merged = {}
        for batch in batches["batches"]:
            merged.update(batch["batchImportData"])
        self.assertEqual(set(merged), set(FIXTURE_FILES))
        self.assertEqual(merged["app.py"], ["calendar.py", "gateway.py"])
        self.assertEqual(merged["broker.py"], ["device.py"])

    def test_4_graph_has_exactly_the_known_imports_edges(self):
        scan_path = self.merged_scan()
        batches = self.batches_from(scan_path)
        all_results = []
        imports_by_path = {}
        for batch in batches["batches"]:
            index = batch["batchIndex"]
            input_path = self.work / f"extract-input-{index}.json"
            output_path = self.work / f"extract-result-{index}.json"
            input_path.write_text(json.dumps({
                "projectRoot": str(self.project),
                "batchFiles": batch["files"],
                "batchImportData": batch.get("batchImportData", {}),
            }), encoding="utf-8")
            self.run_node(str(SKILLS / "extract-structure.mjs"),
                          str(input_path), str(output_path))
            extracted = json.loads(output_path.read_text(encoding="utf-8"))
            all_results.extend(extracted.get("results", []))
            imports_by_path.update(batch.get("batchImportData", {}))
        graph_input = self.work / "graph-input.json"
        graph_path = self.work / "knowledge-graph.json"
        graph_input.write_text(json.dumps({
            "projectName": "fixture",
            "contentDigest": "fixture-digest",
            "results": all_results,
            "importsByPath": imports_by_path,
            "semanticByPath": {},
        }), encoding="utf-8")
        self.run_node(str(GRAPH_BUILDER), str(graph_input), str(graph_path))
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        imports = {(e["source"], e["target"]) for e in graph["edges"] if e["type"] == "imports"}
        self.assertEqual(imports, KNOWN_EDGES)
        # negative case: no calendar -> device edge anywhere
        self.assertNotIn(("file:calendar.py", "file:device.py"), imports)
        # every locator resolves to a real file node in the same graph
        node_ids = {n["id"] for n in graph["nodes"]}
        for source, target in imports:
            self.assertIn(source, node_ids)
            self.assertIn(target, node_ids)

    def test_5_incremental_analysis_paths_touches_only_the_changed_file(self):
        base = self.merged_scan()
        before = json.loads(base.read_text(encoding="utf-8"))["importMap"]
        (self.project / "app.py").write_text(
            FIXTURE_FILES["app.py"] + "\nfrom device import Device\n", encoding="utf-8")
        # incremental handoff: a private scan copy plus analysisPaths
        incremental = base.with_name("scan-incremental.json")
        incremental.write_text(base.read_text(encoding="utf-8"), encoding="utf-8")
        result = self.merge_import_map(incremental, analysis_paths=["app.py"])
        self.assertEqual(result["stats"]["filesScanned"], 1)
        self.assertEqual(set(result["importMap"]), {"app.py"})
        merged = json.loads(incremental.read_text(encoding="utf-8"))["importMap"]
        # merged map: app.py gained the new edge, every other entry unchanged
        self.assertEqual(merged["app.py"], ["calendar.py", "device.py", "gateway.py"])
        for path, targets in before.items():
            if path != "app.py":
                self.assertEqual(merged[path], targets)

    def test_6_deleted_file_leaves_no_stale_edges(self):
        base = self.merged_scan()
        (self.project / "calendar.py").unlink()
        scan_path = self.scan("scan-after-delete.json")
        self.merge_import_map(scan_path)
        scan = json.loads(scan_path.read_text(encoding="utf-8"))
        self.assertEqual(len(scan["files"]), 5)
        self.assertNotIn("calendar.py", scan["importMap"])
        for targets in scan["importMap"].values():
            self.assertNotIn("calendar.py", targets)
        # app.py's import of the deleted module silently drops; the rest hold
        self.assertEqual(scan["importMap"]["app.py"], ["gateway.py"])
        self.assertEqual(scan["importMap"]["broker.py"], ["device.py"])
        self.assertNotEqual(scan["importMap"], json.loads(base.read_text(encoding="utf-8"))["importMap"])


class BridgeWiringTests(unittest.TestCase):
    """run() against a faked connector and faked node: extract-import-map is
    invoked between scan-project and compute-batches, and the scan-result on
    disk already carries importMap when compute-batches reads it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.token_file = self.root / "token"
        self.token_file.write_text("connector-token", encoding="utf-8")

    def fake_api(self, host, token, path, *, binary=False, timeout=90):
        if path.startswith("/manifest"):
            return {"root_name": "demo", "total": 1, "files": [
                {"relpath": "src/main.py", "kind": "file", "size": 20, "mtime": 1.0}]}
        query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
        return f"content-of-{query['relpath'][0]}".encode()

    def test_extract_import_map_runs_between_scan_and_batches_with_merged_scan_result(self):
        commands = []
        scan_results_at_batch_time = []
        graph_inputs = []

        def checked(command, *, env):
            commands.append(list(command))
            name = Path(command[1]).name
            if name == "scan-project.mjs":
                Path(command[3]).write_text(json.dumps({
                    "contentDigest": "d1",
                    "files": [{"path": "src/main.py", "language": "python",
                               "sizeLines": 1, "fileCategory": "code"}],
                }), encoding="utf-8")
            elif name == "extract-import-map.mjs":
                payload = json.loads(Path(command[2]).read_text(encoding="utf-8"))
                # the stage sees the staging tree and the scan inventory
                self.assertTrue(payload["projectRoot"].endswith("ua-cache/files"))
                self.assertEqual(payload["files"][0]["path"], "src/main.py")
                Path(command[3]).write_text(json.dumps({
                    "scriptCompleted": True,
                    "stats": {"filesScanned": 1, "filesWithImports": 1, "totalEdges": 1},
                    "importMap": {"src/main.py": ["src/util.py"]},
                }), encoding="utf-8")
            elif name == "compute-batches.mjs":
                scan_arg = [a for a in command if a.startswith("--scan-result=")][0]
                scan_results_at_batch_time.append(
                    json.loads(Path(scan_arg.split("=", 1)[1]).read_text(encoding="utf-8")))
                out_arg = [a for a in command if a.startswith("--output=")][0]
                Path(out_arg.split("=", 1)[1]).write_text(json.dumps({
                    "batches": [{"batchIndex": 1, "files": ["src/main.py"],
                                 "batchImportData": {"src/main.py": ["src/util.py"]}}]}),
                    encoding="utf-8")
            elif name == "extract-structure.mjs":
                Path(command[3]).write_text(json.dumps({"results": []}), encoding="utf-8")
            elif name == "ua_graph_builder.mjs":
                graph_inputs.append(json.loads(Path(command[2]).read_text(encoding="utf-8")))
                Path(command[3]).write_text(json.dumps({
                    "nodes": [], "edges": [], "project": {"languages": []}}),
                    encoding="utf-8")

        with patch.object(ua_bridge, "api", side_effect=self.fake_api), \
                patch.object(ua_bridge, "run_checked", side_effect=checked):
            summary = ua_bridge.run(host="http://connector",
                                    token_file=str(self.token_file),
                                    grant="g1",
                                    ua_root=str(self.root / "ua"),
                                    state_root=str(self.root / "state"))
        names = [Path(c[1]).name for c in commands]
        self.assertIn("extract-import-map.mjs", names)
        self.assertLess(names.index("scan-project.mjs"), names.index("extract-import-map.mjs"))
        self.assertLess(names.index("extract-import-map.mjs"), names.index("compute-batches.mjs"))
        # compute-batches read a scan-result that already carried importMap
        self.assertEqual(scan_results_at_batch_time[0]["importMap"],
                         {"src/main.py": ["src/util.py"]})
        # the graph builder receives importsByPath derived from the importMap
        # stage output (via batchImportData)
        self.assertEqual(graph_inputs[0]["importsByPath"], {"src/main.py": ["src/util.py"]})
        self.assertEqual(summary["importEdges"], 0)  # empty graph in this fake


if __name__ == "__main__":
    unittest.main()
