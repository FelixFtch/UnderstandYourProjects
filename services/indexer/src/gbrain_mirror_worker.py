#!/usr/bin/env python3
"""One-shot worker for the durable UYP -> gBrain mirror queue.

The IndexJob worker writes local KnowledgeItems and UA output first, then
queues a metadata-only mirror record.  This process is the separate, optional
second lane that performs the gBrain write.  It is intentionally a one-shot
command so systemd, launchd, or a deployment scheduler can run it on a timer;
there is no resident loop and no gBrain call in the local IndexJob path.

Before a live write the worker requires a fresh HomeHub AccessContext.  A
missing or invalid context leaves queued records untouched so a temporary
HomeHub outage does not turn into a permanent revoke.  A valid context with
another grant epoch or without the project scope moves the record to
``blocked`` and prevents publishing stale data after revocation.  HomeHub
remains the only issuer and revocation authority; this module only validates
the projection it receives.

No secret is stored in the mirror queue.  The gBrain URL and writer credential
path are supplied as environment variables or command-line arguments at run
time.  The worker never writes those values into a Studio projection.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from gbrain_publisher import MirrorJobStore, mirror_projection, run_pending_mirrors
from homehub_adapter import load_context


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run due durable UYP gBrain mirror jobs once (HomeHub-gated)")
    parser.add_argument("--state-root", default=os.environ.get("UYP_STATE_ROOT", "~/dev/uyp/state"),
                        help="UYP state root containing gbrain-mirrors/")
    parser.add_argument("--url", default=os.environ.get("UYP_GBRAIN_URL"),
                        help="project-knowledge gBrain serve URL (no default endpoint)")
    parser.add_argument("--creds", default=os.environ.get("UYP_GBRAIN_CREDS"),
                        help="writer OAuth credentials JSON path")
    parser.add_argument("--access-context",
                        default=os.environ.get("UYP_ACCESS_CONTEXT_FILE"),
                        help="HomeHub AccessContext projection; URL transport remains authoritative when configured")
    parser.add_argument("--max-jobs", type=int, default=1,
                        help="maximum due jobs to attempt in this pass (default: 1)")
    parser.add_argument("--status", action="store_true",
                        help="print safe queue projections without attempting work")
    return parser


def queue_status(state_root: str | os.PathLike[str]) -> dict[str, Any]:
    """Return only public-safe queue fields (no local knowledge roots)."""
    store = MirrorJobStore(state_root)
    jobs = [mirror_projection(record) for record in store.list()]
    counts: dict[str, int] = {}
    for job in jobs:
        phase = str(job.get("phase") or "unknown")
        counts[phase] = counts.get(phase, 0) + 1
    return {"ok": True, "jobs": jobs, "counts": counts}


def run_once(*, state_root: str | os.PathLike[str], base_url: str | None,
             creds: Any, access_context: str | None, max_jobs: int = 1) -> dict[str, Any]:
    """Run one fail-closed timer pass.

    ``load_context`` intentionally prefers the configured HomeHub URL over a
    local file.  Therefore passing a file path here does not bypass a live
    HomeHub adapter when one is configured.
    """
    context = load_context(access_context)
    return run_pending_mirrors(
        state_root,
        max_jobs=max_jobs,
        base_url=base_url,
        creds=creds,
        access_context=context,
        enforce_access_context=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.status:
        print(json.dumps(queue_status(args.state_root), ensure_ascii=False, indent=2))
        return 0
    result = run_once(
        state_root=args.state_root,
        base_url=args.url,
        creds=args.creds,
        access_context=args.access_context,
        max_jobs=max(0, args.max_jobs),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # A policy-plane outage is a clean no-op for timer purposes; systemd can
    # invoke the next tick rather than retrying in a hot loop.  A job failure
    # is still visible in its durable state and is returned as non-zero so a
    # supervising deployment can alert on it.
    phases = {str(job.get("phase")) for job in result.get("jobs", [])}
    return 1 if "failed" in phases else 0


if __name__ == "__main__":
    raise SystemExit(main())
