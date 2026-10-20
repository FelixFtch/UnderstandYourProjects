"""Voice-priority yield for the mirror pass (owner rule 语音>查询>索引).

The mirror/gBrain embedding lane had no yield (field evidence
2026-10-19: it was the box's top CPU feeder during satellite turns,
starving ASR). A fresh interactive lock now skips the pass cleanly -
same 30-second window and clean no-op contract as the IndexJob worker.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import gbrain_mirror_worker as worker  # noqa: E402


class YieldTests(unittest.TestCase):
    def test_fresh_lock_skips_the_pass(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".lock",
                                         delete=False) as fh:
            fh.write(str(time.time()))
            lock = fh.name
        self.addCleanup(Path(lock).unlink, missing_ok=True)
        original = worker.INTERACTIVE_LOCK
        worker.INTERACTIVE_LOCK = lock
        self.addCleanup(setattr, worker, "INTERACTIVE_LOCK", original)
        self.assertTrue(worker.voice_active())
        out = io.StringIO()
        with redirect_stdout(out):
            code = worker.main([
                "--state-root", "/nonexistent", "--url",
                "http://127.0.0.1:1", "--creds", "/nonexistent",
                "--access-context", "/nonexistent"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["yielded"])

    def test_stale_or_missing_lock_does_not_yield(self) -> None:
        self.assertFalse(worker.voice_active("/nonexistent/lock"))
        with tempfile.NamedTemporaryFile("w", suffix=".lock",
                                         delete=False) as fh:
            fh.write(str(time.time() - worker.INTERACTIVE_HOLD_S - 5))
            lock = fh.name
        self.addCleanup(Path(lock).unlink, missing_ok=True)
        self.assertFalse(worker.voice_active(lock))

    def test_future_or_negative_stamp_is_ignored(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".lock",
                                         delete=False) as fh:
            fh.write("-1")
            lock = fh.name
        self.addCleanup(Path(lock).unlink, missing_ok=True)
        self.assertFalse(worker.voice_active(lock, now=100.0))


if __name__ == "__main__":
    unittest.main()
