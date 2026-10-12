import json
import os
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import index_project  # noqa: E402


def filler(size: int, seed: bytes = b"# ua-cache fixture line\n") -> bytes:
    # Deterministic payload of an exact byte length: the cache contract is
    # byte identity, so assertions compare against the full constructed body.
    return (seed * (size // len(seed) + 1))[:size]


class TestUaCacheWrite(unittest.TestCase):
    """Direct checks of the shared cache layout consumed by ua_bridge.py:

      <state_root>/<root>/ua-cache/files/<relpath>          complete bytes
      <state_root>/<root>/ua-cache/meta/<relpath>.json      {"size", "mtime"}
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = tmp.name

    def test_complete_read_writes_bytes_and_meta(self):
        payload = b"port = 8123\n" * 40
        index_project._ua_cache_write(self.state, "demo", "src/pkg/mod.py",
                                      payload, len(payload), 1728360000.5)
        base = Path(self.state) / "demo" / "ua-cache"
        self.assertEqual(
            (base / "files" / "src" / "pkg" / "mod.py").read_bytes(), payload)
        self.assertEqual(
            json.loads((base / "meta" / "src" / "pkg" / "mod.py.json").read_text()),
            {"size": len(payload), "mtime": 1728360000.5})

    def test_no_entry_for_unset_root_partial_payload_or_empty_file(self):
        payload = b"x" * 100
        # unset/empty state root (standalone CLI) -> skip entirely
        index_project._ua_cache_write(None, "demo", "a.py", payload, 100, 1.0)
        index_project._ua_cache_write("", "demo", "a.py", payload, 100, 1.0)
        # missing mtime -> no validity record possible -> no entry
        index_project._ua_cache_write(self.state, "demo", "a.py", payload, 100, None)
        # partial payload (the capped 256 KiB fetch of a larger file) and
        # size-0 files: the cache must never hold incomplete bytes
        index_project._ua_cache_write(self.state, "demo", "big.py", payload, 300000, 1.0)
        index_project._ua_cache_write(self.state, "demo", "empty.py", b"", 0, 1.0)
        self.assertEqual(os.listdir(self.state), [])

    def test_escaping_relpaths_are_rejected_without_writing(self):
        for bad in ("../evil.py", "/abs.py", "a/../../b.py", "..", ""):
            index_project._ua_cache_write(self.state, "demo", bad, b"data", 4, 1.0)
        self.assertFalse(os.path.exists(os.path.join(self.state, "demo")))

    def test_unwritable_state_root_is_silent_not_fatal(self):
        # state_root inside a regular file: every makedirs/open fails, but a
        # cache problem must never surface to the analysis run.
        blocker = Path(self.state) / "blocker"
        blocker.write_bytes(b"not a dir")
        index_project._ua_cache_write(str(blocker), "demo", "a.py", b"data", 4, 1.0)
        self.assertTrue(blocker.is_file())


class TestIndexRunWritesUaCache(unittest.TestCase):
    """End-to-end through main(): only full-content reads (the safe_read
    path) may populate the cache.  2 KiB head reads, offset mid reads,
    >READ_CAP files and reads capped short of the manifest size must not -
    and the cache stays off when UYP_STATE_ROOT is unset."""

    def _run_index(self, env):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        token = root / "token"
        token.write_text("t", encoding="utf-8")

        # app.py -> deep (full read cached); conf.yaml -> structure-only
        # (full read cached); bundle.min.js -> rule skip (head read only);
        # big.yaml -> structure-only but fetched capped at 256 KiB (partial);
        # huge.py -> over READ_CAP (safe_read never hits the transport).
        files = [
            {"relpath": "app.py", "size": 5000, "mtime": 111.5, "kind": "file"},
            {"relpath": "conf.yaml", "size": 1200, "mtime": 222.25, "kind": "file"},
            {"relpath": "vendor/bundle.min.js", "size": 90000, "mtime": 333.0, "kind": "file"},
            {"relpath": "big.yaml", "size": 300000, "mtime": 444.0, "kind": "file"},
            {"relpath": "huge.py", "size": 17 * 1024 * 1024, "mtime": 555.0, "kind": "file"},
        ]
        content = {f["relpath"]: filler(f["size"]) for f in files}
        calls = []

        def fake_api(host, tok, path, binary=False, timeout=90, retries=5):
            if path.startswith("/manifest"):
                return {"root_name": "demo", "total": len(files),
                        "has_more": False, "files": files}
            q = urllib.parse.parse_qs(path.split("?", 1)[1])
            rel = q["relpath"][0]
            offset = int(q.get("offset", ["0"])[0])
            length = int(q["length"][0])
            calls.append((rel, offset, length))
            return content[rel][offset:offset + length]

        argv = ["index_project.py", "--host", "http://connector",
                "--token-file", str(token), "--grant", "g_test", "--limit", "0"]
        run_env = {"UYP_KEYFILE": "off", "UYP_ENRICH_WORKERS": "1"}
        run_env.update(env)
        with patch.object(sys, "argv", argv), \
             patch.dict(os.environ, run_env), \
             patch.object(index_project, "api", fake_api), \
             patch.object(index_project, "STATE", str(root / "state")), \
             patch.object(index_project, "OUT", str(root / "out")), \
             patch.object(index_project, "INTERACTIVE_LOCK",
                          str(root / "no-such.lock")), \
             patch.object(index_project, "laya_decide",
                          lambda head, mid="": ("deep-analysis", 0.9)), \
             patch.object(index_project, "qwen_enrich",
                          lambda content, think: ('{"purpose": "p"}', 3)):
            index_project.main()
        return root, content, calls

    def test_full_reads_cache_head_mid_and_capped_reads_do_not(self):
        cache = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(cache, ignore_errors=True))
        root, content, calls = self._run_index({"UYP_STATE_ROOT": str(cache)})

        base = cache / "demo" / "ua-cache"
        self.assertEqual((base / "files" / "app.py").read_bytes(),
                         content["app.py"])
        self.assertEqual(json.loads((base / "meta" / "app.py.json").read_text()),
                         {"size": 5000, "mtime": 111.5})
        self.assertEqual((base / "files" / "conf.yaml").read_bytes(),
                         content["conf.yaml"])
        self.assertEqual(json.loads((base / "meta" / "conf.yaml.json").read_text()),
                         {"size": 1200, "mtime": 222.25})
        cached = sorted(str(p.relative_to(base / "files"))
                        for p in (base / "files").rglob("*") if p.is_file())
        self.assertEqual(cached, ["app.py", "conf.yaml"])

        # the transport really made the reads that must NOT cache: a head
        # read for the rule-skipped bundle, an offset mid read for app.py,
        # a 256 KiB-capped fetch for big.yaml, and nothing beyond the 2 KiB
        # windows for the over-cap huge.py.
        self.assertIn(("vendor/bundle.min.js", 0, 2048), calls)
        self.assertTrue(any(rel == "app.py" and offset == 2500
                            for rel, offset, length in calls))
        self.assertTrue(any(rel == "big.yaml" and length == 262144
                            for rel, offset, length in calls))
        self.assertFalse(any(rel == "huge.py" and length > 2048
                             for rel, offset, length in calls))
        # the analysis itself still completed for every file
        out = root / "out" / "demo"
        self.assertEqual(len(list(out.glob("*.knowledge.json"))), 5)

    def test_no_cache_dirs_when_state_root_unset(self):
        # "" exercises the same skip as a truly unset variable (the reader
        # treats falsy as off) and shields the test from an ambient
        # UYP_STATE_ROOT on an operator machine.
        root, _, _ = self._run_index({"UYP_STATE_ROOT": ""})
        self.assertEqual(list(root.rglob("ua-cache")), [])


if __name__ == "__main__":
    unittest.main()
