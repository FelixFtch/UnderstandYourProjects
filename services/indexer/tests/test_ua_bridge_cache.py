"""UA staging cache tests: manifest entries -> persistent files/+meta/ tree.

The connector api is faked (no network) and node phases are faked where a test
crosses run() end to end.  What stays real is the cache layout itself, so
these tests pin the shared contract the enrichment worker (index_project.py)
also writes against.
"""
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import ua_bridge  # noqa: E402


MANIFEST_FILES = [
    {"relpath": "src/main.py", "kind": "file", "size": 11, "mtime": 1000.5},
    {"relpath": "src/util/empty.txt", "kind": "file", "size": 0, "mtime": "2026-10-11T10:00:00Z"},
    {"relpath": "README.md", "kind": "file", "size": 6, "mtime": 1000.5},
]


def fake_api(host, token, path, *, binary=False, timeout=90):
    # Deterministic bytes derived from the requested relpath, like a connector
    # /read would return them.
    query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    return f"content-of-{query['relpath'][0]}".encode()


def http_error_413(host, token, path, *, binary=False, timeout=90):
    import urllib.error
    raise urllib.error.HTTPError(path, 413, "Payload Too Large", None, None)


class StageManifestFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache_root = Path(self.tmp.name) / "demo" / "ua-cache"

    def stage(self, files=None):
        return ua_bridge.stage_manifest_files(
            files if files is not None else MANIFEST_FILES,
            cache_root=self.cache_root,
            host="http://connector",
            token="t",
            grant="g1",
        )

    def meta(self, rel):
        return json.loads((self.cache_root / "meta" / (rel + ".json")).read_text(encoding="utf-8"))

    def test_first_pass_downloads_and_writes_files_and_meta(self):
        with patch.object(ua_bridge, "api", side_effect=fake_api) as api_mock:
            files_root, staged, reused, skipped = self.stage()
        self.assertEqual((staged, reused, skipped), (3, 0, []))
        self.assertEqual(files_root, self.cache_root / "files")
        # one /read per non-empty file; empty files are touched, not fetched
        self.assertEqual(api_mock.call_count, 3 - 1)
        for entry in MANIFEST_FILES:
            target = self.cache_root / "files" / entry["relpath"]
            self.assertTrue(target.is_file(), entry["relpath"])
            self.assertEqual(self.meta(entry["relpath"]),
                             {"size": entry["size"], "mtime": entry["mtime"]})
        self.assertEqual((self.cache_root / "files" / "src" / "main.py").read_bytes(),
                         b"content-of-src/main.py")
        self.assertEqual((self.cache_root / "files" / "src" / "util" / "empty.txt").read_bytes(),
                         b"")
        # the sidecar tree is a sibling, never inside the scanned files tree
        self.assertFalse((self.cache_root / "files" / "meta").exists())
        self.assertFalse(list((self.cache_root / "files").rglob("*.json")))

    def test_second_pass_reuses_everything_without_calling_api(self):
        with patch.object(ua_bridge, "api", side_effect=fake_api):
            self.stage()
        with patch.object(ua_bridge, "api") as api_mock:
            _, staged, reused, skipped = self.stage()
        api_mock.assert_not_called()
        self.assertEqual((staged, reused, skipped), (0, 3, []))

    def test_size_change_forces_redownload_of_only_that_entry(self):
        with patch.object(ua_bridge, "api", side_effect=fake_api):
            self.stage()
        changed = [dict(MANIFEST_FILES[0], size=99), *MANIFEST_FILES[1:]]
        with patch.object(ua_bridge, "api", side_effect=fake_api) as api_mock:
            _, staged, reused, skipped = self.stage(changed)
        self.assertEqual((staged, reused, skipped), (1, 2, []))
        self.assertEqual(api_mock.call_count, 1)
        self.assertIn("relpath=src/main.py", api_mock.call_args_list[0].args[2])
        self.assertEqual(self.meta("src/main.py")["size"], 99)

    def test_mtime_change_invalidates_but_float_noise_does_not(self):
        with patch.object(ua_bridge, "api", side_effect=fake_api):
            self.stage()
        noise = [dict(MANIFEST_FILES[0], mtime=1000.5 + 1e-9), *MANIFEST_FILES[1:]]
        with patch.object(ua_bridge, "api") as api_mock:
            _, staged, reused, _ = self.stage(noise)
        api_mock.assert_not_called()  # sub-epsilon drift is the same version
        self.assertEqual((staged, reused), (0, 3))

        moved = [dict(MANIFEST_FILES[0], mtime=1000.6), *MANIFEST_FILES[1:]]
        with patch.object(ua_bridge, "api", side_effect=fake_api) as api_mock:
            _, staged, reused, _ = self.stage(moved)
        self.assertEqual((staged, reused), (1, 2))
        self.assertEqual(self.meta("src/main.py")["mtime"], 1000.6)

    def test_bytes_missing_with_valid_sidecar_redownloads(self):
        with patch.object(ua_bridge, "api", side_effect=fake_api):
            self.stage()
        # crash-shaped state: sidecar survived, data did not
        (self.cache_root / "files" / "src" / "main.py").unlink()
        with patch.object(ua_bridge, "api", side_effect=fake_api) as api_mock:
            _, staged, reused, _ = self.stage()
        self.assertEqual((staged, reused), (1, 2))
        self.assertEqual(api_mock.call_count, 1)
        self.assertEqual((self.cache_root / "files" / "src" / "main.py").read_bytes(),
                         b"content-of-src/main.py")

    def test_oversized_and_413_files_stay_skipped_and_uncached(self):
        entries = [dict(MANIFEST_FILES[0], size=17)]  # size 17 > max 16
        with patch.object(ua_bridge, "api") as api_mock:
            files_root, staged, reused, skipped = ua_bridge.stage_manifest_files(
                entries, cache_root=self.cache_root, host="http://connector",
                token="t", grant="g1", max_file_bytes=16)
        api_mock.assert_not_called()  # too-large entries never reach /read
        self.assertEqual((staged, reused), (0, 0))
        self.assertEqual(skipped, ["src/main.py"])
        self.assertFalse((self.cache_root / "files" / "src" / "main.py").exists())

        # a 413 from the connector is a skip too, and leaves no sidecar behind
        # so a later run retries the read instead of caching the gap; the
        # zero-size entry still stages locally (it never reads the connector)
        with patch.object(ua_bridge, "api", side_effect=http_error_413):
            _, staged, reused, skipped = ua_bridge.stage_manifest_files(
                MANIFEST_FILES, cache_root=self.cache_root, host="http://connector",
                token="t", grant="g1")
        self.assertEqual((staged, reused), (1, 0))
        self.assertEqual(sorted(skipped), ["README.md", "src/main.py"])
        self.assertFalse((self.cache_root / "meta" / "README.md.json").exists())
        self.assertTrue((self.cache_root / "files" / "src" / "util" / "empty.txt").exists())


class RunEndToEndTests(unittest.TestCase):
    """run() against a faked connector and faked node: cache layout, node
    arguments, and summary counters."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.token_file = self.root / "token"
        self.token_file.write_text("connector-token", encoding="utf-8")
        self.state_root = self.root / "state"
        self.ua_root = self.root / "ua"

    def manifest_api(self, files):
        def call(host, token, path, *, binary=False, timeout=90):
            if path.startswith("/manifest"):
                return {"root_name": "demo", "total": len(files), "files": files}
            return fake_api(host, token, path, binary=binary, timeout=timeout)
        return call

    def fake_run_checked(self, command, *, env):
        name = Path(command[1]).name
        if name == "scan-project.mjs":
            Path(command[3]).write_text(json.dumps({"contentDigest": "d1"}), encoding="utf-8")
        elif name == "compute-batches.mjs":
            for arg in command:
                if arg.startswith("--output="):
                    Path(arg.split("=", 1)[1]).write_text(json.dumps({
                        "batches": [{"batchIndex": 0, "files": ["src/main.py"],
                                     "batchImportData": {"src/main.py": []}}]}),
                        encoding="utf-8")
        elif name == "extract-structure.mjs":
            Path(command[3]).write_text(json.dumps({"results": []}), encoding="utf-8")
        elif name == "ua_graph_builder.mjs":
            Path(command[3]).write_text(json.dumps({"nodes": [], "edges": [],
                                                    "project": {"languages": []}}),
                                        encoding="utf-8")

    def run_bridge(self, files):
        commands = []

        def checked(command, *, env):
            commands.append(list(command))
            self.fake_run_checked(command, env=env)

        with patch.object(ua_bridge, "api", side_effect=self.manifest_api(files)) as api_mock, \
                patch.object(ua_bridge, "run_checked", side_effect=checked):
            summary = ua_bridge.run(host="http://connector",
                                    token_file=str(self.token_file),
                                    grant="g1",
                                    ua_root=str(self.ua_root),
                                    state_root=str(self.state_root))
        return summary, commands, api_mock

    def test_node_phases_scan_the_cache_files_tree_and_second_run_is_all_reuse(self):
        summary, commands, api_mock = self.run_bridge(MANIFEST_FILES)
        cache_files = self.state_root.resolve() / "demo" / "ua-cache" / "files"
        by_script = {Path(command[1]).name: command for command in commands}
        self.assertEqual(by_script["scan-project.mjs"][2], str(cache_files))
        self.assertEqual(by_script["compute-batches.mjs"][2], str(cache_files))
        extract_input = json.loads((self.state_root / "demo" / "ua" / "intermediate"
                                    / "extract-input-0.json").read_text(encoding="utf-8"))
        self.assertEqual(extract_input["projectRoot"], str(cache_files))
        self.assertEqual(summary["stagedFiles"], 3)
        self.assertEqual(summary["cache_reused"], 0)
        # sidecars live next to (not inside) the tree the graph builder sees
        self.assertFalse((cache_files / "meta").exists())

        second, commands2, api_mock2 = self.run_bridge(MANIFEST_FILES)
        self.assertEqual(second["stagedFiles"], 0)
        self.assertEqual(second["cache_reused"], 3)
        # only the manifest page was fetched; not a single /read re-downloaded
        reads = [call for call in api_mock2.call_args_list if "/read?" in call.args[2]]
        self.assertEqual(reads, [])
        self.assertEqual(len(commands2), len(commands))  # full node pipeline still ran


if __name__ == "__main__":
    unittest.main()
