import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import index_project  # noqa: E402


def paged_api(pages):
    calls = []

    def api(host, token, path):
        calls.append(path)
        idx = 0
        if "cursor=" in path:
            idx = int(path.rsplit("cursor=", 1)[1].replace("c", ""))
        return pages[idx]
    return api, calls


class TestFullManifest(unittest.TestCase):
    def test_follows_cursor_to_the_end(self):
        pages = [
            {"root_name": "p", "total": 5, "has_more": True, "next_cursor": "c1",
             "files": [{"relpath": "a"}, {"relpath": "b"}]},
            {"root_name": "p", "total": 5, "has_more": True, "next_cursor": "c2",
             "files": [{"relpath": "gbrain/x"}, {"relpath": "gbrain/y"}]},
            {"root_name": "p", "total": 5, "has_more": False, "next_cursor": None,
             "files": [{"relpath": "secretagent/agent.py"}]},
        ]
        api, calls = paged_api(pages)
        man = index_project.fetch_full_manifest("h", "t", "g_1", api_fn=api)
        self.assertEqual([f["relpath"] for f in man["files"]],
                         ["a", "b", "gbrain/x", "gbrain/y", "secretagent/agent.py"])
        self.assertFalse(man["has_more"])
        self.assertEqual(len(calls), 3)

    def test_single_page_unchanged(self):
        api, calls = paged_api([{"root_name": "p", "total": 1, "has_more": False,
                                 "files": [{"relpath": "a"}]}])
        man = index_project.fetch_full_manifest("h", "t", "g_1", api_fn=api)
        self.assertEqual(len(man["files"]), 1)
        self.assertEqual(len(calls), 1)

    def test_stuck_cursor_raises(self):
        page = {"root_name": "p", "has_more": True, "next_cursor": "c1", "files": []}
        api, _ = paged_api([page, page])
        with self.assertRaises(RuntimeError):
            index_project.fetch_full_manifest("h", "t", "g_1", api_fn=api)


if __name__ == "__main__":
    unittest.main()
