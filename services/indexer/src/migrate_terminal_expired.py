#!/usr/bin/env python3
"""One-time (idempotent) migration: blocked epoch-mismatch -> terminal_expired.

ADR docs/ADR_MIRROR_EPOCH.md (adopted 2026-10-19): the ~930 mirror
records blocked with ``homehub_grant_epoch_mismatch`` are grant-epoch
ROTATION noise, not policy denials.  They become ``terminal_expired``:
the record file, events count, and lastError wording are preserved as
the audit chain; an ``expiredBy: grant_epoch_rotation`` marker is added
and one event is appended.  Records blocked for any OTHER reason
(scope denied, missing epoch, configuration) are left untouched, and a
second run is a no-op by construction (already-terminal records no
longer match the filter).

Usage (against the production state root):

    python3 migrate_terminal_expired.py --state-root ~/dev/uyp/state --dry-run
    python3 migrate_terminal_expired.py --state-root ~/dev/uyp/state --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gbrain_publisher import (  # noqa: E402
    MISMATCH_DENIAL,
    MirrorJobStore,
    now_iso,
)


def candidates(store: MirrorJobStore) -> list[dict]:
    return [record for record in store.list()
            if str(record.get("phase")) == "blocked"
            and str(record.get("lastError")) == MISMATCH_DENIAL]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-root", required=True,
                        help="UYP state root containing gbrain-mirrors/")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would migrate; change nothing")
    parser.add_argument("--apply", action="store_true",
                        help="perform the migration (idempotent)")
    args = parser.parse_args(argv)
    if not args.dry_run and not args.apply:
        parser.error("choose --dry-run or --apply")

    store = MirrorJobStore(os.path.expanduser(args.state_root))
    matches = candidates(store)
    counts = Counter(str(record.get("phase")) for record in store.list())
    print("queue before:", dict(counts))
    print("epoch-mismatch blocked records:", len(matches))
    by_project = Counter(str(record.get("projectId")) for record in matches)
    for project, n in sorted(by_project.items()):
        print("  %s: %d" % (project, n))
    if args.dry_run:
        print("dry run: no changes written")
        return 0

    migrated = 0
    for record in matches:
        mirror_id = str(record.get("mirrorJobId"))
        updated = store.event(
            mirror_id, "terminal_expired",
            {"lastError": MISMATCH_DENIAL,
             "blockedBy": "homehub",
             "expiredBy": "grant_epoch_rotation",
             "migratedAt": now_iso()})
        if str(updated.get("phase")) == "terminal_expired":
            migrated += 1
    after = Counter(str(record.get("phase")) for record in store.list())
    print("migrated:", migrated)
    print("queue after:", dict(after))
    remaining = sum(1 for record in store.list()
                    if str(record.get("phase")) == "blocked"
                    and str(record.get("lastError")) == MISMATCH_DENIAL)
    print("epoch-mismatch still blocked (must be 0):", remaining)
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
