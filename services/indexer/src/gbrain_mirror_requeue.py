#!/usr/bin/env python3
"""Operator tool for the gbrain mirror FAILED queue (2026-10-19).

Classify - do not blindly retry.  The failed lane of
``<state_root>/gbrain-mirrors`` is triaged against LIVE state before
anything is requeued:

  retryable           transport-class failure (timeout / connection /
                      HTTP / serve rejection incl. queue_capacity) on a
                      job that is still CURRENT (source + knowledge
                      version + grant epoch), not superseded, not a
                      duplicate, and never operator-requeued before
  superseded          a newer knowledge version exists for the project,
                      the same version+epoch already succeeded, another
                      live job already covers it, or an older duplicate
                      in this batch
  terminal_expired    the job's grant epoch is no longer the project's
                      active epoch (ADR: grant-epoch rotation noise;
                      never re-enqueued)
  policy_blocked      the project has no active grant, the source fell
                      out of the grant's source scope, or the access
                      context denies the project - revoked/narrowed
                      content must never flow back
  configuration_error a publisher precondition failed (bad creds,
                      missing endpoint) - fix provisioning, do not retry
  permanent_failed    anything else, or a job that already used its one
                      operator requeue (bounded: capacity failures must
                      not retry forever)

Safety rails: dry-run by default; ``--execute`` writes; ``--rollback``
restores the last executed batch (only jobs still in the phase the
execute left them in); one operator requeue per job lifetime; a global
``--max-requeue`` cap per execution; every decision keeps the record's
``lastError`` and bumps the ``events`` counter (audit is append-only).

The worker re-validates epoch and scope at run time, so even a requeued
job can never resurrect revoked content (``run_pending_mirrors`` moves
mismatches straight back to terminal_expired).

Usage (on the jetson, same env as uyp-gbrain-mirror.service):

    python3 gbrain_mirror_requeue.py --state-root ~/dev/uyp/state            # dry-run
    python3 gbrain_mirror_requeue.py --state-root ~/dev/uyp/state --execute
    python3 gbrain_mirror_requeue.py --state-root ~/dev/uyp/state --rollback
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gbrain_publisher import MirrorJobStore  # noqa: E402

HUB = os.environ.get("UYP_HUB_BASE_URL", "http://127.0.0.1:5120")
TOKEN_FILE = os.environ.get("UYP_HOMEHUB_TOKEN_FILE",
                            "/home/jetson/.config/uyp/homehub.token")

CLASSES = ("retryable", "superseded", "terminal_expired", "policy_blocked",
           "configuration_error", "permanent_failed")

# One operator requeue per job lifetime: the worker budget is 3 attempts
# per enqueue, so a job's absolute ceiling is 7 attempts (3 + 1 + 3).
# Capacity-class failures must never loop forever.
MAX_OPERATOR_REQUEUES = 1

REQUEUE_DIRNAME = "gbrain-mirror-requeue"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── live state authorities ─────────────────────────────────────────

def active_ledger_grants(timeout: float = 5.0) -> dict[str, dict[str, Any]]:
    """Active HomeHub uyp_grants rows, keyed by project.

    Reads the same sanctioned HTTP surface the renewal timer uses
    (GET /api/uyp/grants + the service bearer).  Returns
    ``{project: {"epoch": str, "sources": set[str], "expires_at": str}}``
    for non-revoked, unexpired rows only; any transport or parse failure
    raises (fail closed - the operator fixes HomeHub, not the queue)."""
    token = open(os.path.expanduser(TOKEN_FILE), encoding="utf-8").read().strip()
    req = urllib.request.Request(
        HUB + "/api/uyp/grants",
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read() or b"{}")
    out: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for row in payload.get("grants", []):
        if row.get("revoked"):
            continue
        project = str(row.get("projectId") or "").strip()
        # the API speaks "grantEpoch" (the ledger column is "epoch");
        # accept either so the tool survives a rename in either place
        epoch = str(row.get("grantEpoch") or row.get("epoch") or "").strip()
        if not project or not epoch:
            continue
        try:
            exp = datetime.fromisoformat(
                str(row.get("expiresAt") or "").replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= now:
                continue
        except (TypeError, ValueError):
            continue
        entry = out.setdefault(project, {"epoch": epoch,
                                         "sources": set(), "expires_at": ""})
        entry["sources"].update(str(s) for s in (row.get("sourceIds") or [])
                                if str(s or "").strip())
        if str(row.get("expiresAt") or "") > entry["expires_at"]:
            entry["expires_at"] = str(row.get("expiresAt"))
    return out


def load_access_context(path: str | None) -> dict[str, Any] | None:
    from homehub_adapter import load_context
    return load_context(path)


# ── classification (pure; the testable core) ───────────────────────

def _error_class(last_error: str) -> str:
    text = str(last_error or "")
    if "GbrainPublishError" in text:
        return "configuration_error"
    if ("TimeoutError" in text or "URLError" in text
            or "HTTPError" in text or "GbrainRejectedError" in text):
        return "transport"
    if not text:
        return "unknown"
    return "unknown"


def classify_failed_jobs(records: list[dict[str, Any]],
                         ledger: dict[str, dict[str, Any]],
                         context: dict[str, Any] | None,
                         ) -> list[dict[str, Any]]:
    """Every failed mirror record -> a decision row (no writes here).

    A row is ``{"record", "mirrorJobId", "klass", "reason"}``; klass is
    retryable only when every live gate passes.  The epoch gate mirrors
    the worker's own ``_mirror_access_denial`` exactly - the record's
    grantEpoch must equal the LIVE access context's grantEpoch (the
    global epoch the worker will compare against at run time), not a
    per-project value: anything else would be re-terminal_expired on the
    next timer tick."""
    # knowledgeVersion is a content digest - unordered.  "Current" means
    # the version on the project's most recently UPDATED record (any
    # phase): every newer publish enqueues a fresh mirror, so an older
    # failed job can only ever write stale pages.
    newest_version: dict[str, str] = {}
    newest_stamp: dict[str, str] = {}
    done_keys: set[tuple] = set()
    live_keys: set[tuple] = set()
    for rec in records:
        project = str(rec.get("projectId") or "")
        version = str(rec.get("knowledgeVersion") or "")
        epoch = str(rec.get("grantEpoch") or "")
        source = str(rec.get("sourceId") or "")
        phase = str(rec.get("phase") or "")
        stamp = str(rec.get("updatedAt") or "")
        key = (project, source, version, epoch)
        if phase == "succeeded":
            done_keys.add(key)
        if phase in ("queued", "retry_wait", "running"):
            live_keys.add(key)
        if stamp > newest_stamp.get(project, ""):
            newest_stamp[project] = stamp
            newest_version[project] = version

    ctx_epoch = str((context or {}).get("grantEpoch") or "").strip()
    ctx_projects = {str(v) for v in (context or {}).get("projectScopes", [])}
    ctx_sources = {str(v) for v in (context or {}).get("sourceScopes", [])}

    rows: list[dict[str, Any]] = []
    batch_seen: set[tuple] = {}
    ordered = sorted(records, key=lambda r: str(r.get("updatedAt") or ""),
                     reverse=True)
    for rec in ordered:
        if str(rec.get("phase")) != "failed":
            continue
        mid = str(rec.get("mirrorJobId") or "")
        project = str(rec.get("projectId") or "")
        version = str(rec.get("knowledgeVersion") or "")
        epoch = str(rec.get("grantEpoch") or "")
        source = str(rec.get("sourceId") or "")
        key = (project, source, version, epoch)
        row = {"record": rec, "mirrorJobId": mid, "klass": "", "reason": ""}

        def _project_in_ctx() -> bool:
            return (project in ctx_projects
                    or "project:%s" % project in ctx_projects
                    or "*" in ctx_projects)

        def _source_in_ctx() -> bool:
            return (source in ctx_sources
                    or "connector:%s" % source in ctx_sources
                    or "*" in ctx_sources)

        if int(rec.get("operatorRequeues") or 0) >= MAX_OPERATOR_REQUEUES:
            row["klass"] = "permanent_failed"
            row["reason"] = "operator requeue budget already used"
        elif not ctx_epoch:
            row["klass"] = "policy_blocked"
            row["reason"] = "access context carries no grant epoch"
        elif epoch != ctx_epoch:
            row["klass"] = "terminal_expired"
            row["reason"] = ("grant epoch %s is not the live context "
                             "epoch %s" % (epoch or "-", ctx_epoch))
        elif not _project_in_ctx():
            row["klass"] = "policy_blocked"
            row["reason"] = "project not in the live access context"
        elif project not in ledger:
            row["klass"] = "policy_blocked"
            row["reason"] = "no active grant row for this project"
        elif not source:
            row["klass"] = "policy_blocked"
            row["reason"] = "record predates source pinning; needs a fresh job"
        elif not _source_in_ctx():
            row["klass"] = "policy_blocked"
            row["reason"] = "source fell out of the context source scope"
        elif source not in ledger[project]["sources"]:
            row["klass"] = "policy_blocked"
            row["reason"] = "source fell out of the grant's source scope"
        elif version != newest_version.get(project, ""):
            row["klass"] = "superseded"
            row["reason"] = "a newer knowledge version exists for the project"
        elif key in done_keys:
            row["klass"] = "superseded"
            row["reason"] = "same version+epoch already mirrored successfully"
        elif key in live_keys:
            row["klass"] = "superseded"
            row["reason"] = "a live job already covers this version+epoch"
        elif key in batch_seen:
            row["klass"] = "superseded"
            row["reason"] = "duplicate of a newer failed job in this batch"
        else:
            err_class = _error_class(rec.get("lastError"))
            if err_class == "transport":
                row["klass"] = "retryable"
                row["reason"] = "transport-class failure on current state"
            elif err_class == "configuration_error":
                row["klass"] = "configuration_error"
                row["reason"] = "publisher precondition failed; fix provisioning"
            else:
                row["klass"] = "permanent_failed"
                row["reason"] = "unclassifiable lastError; manual review"
        batch_seen.setdefault(key, mid)
        rows.append(row)
    return rows


# ── execute / rollback ─────────────────────────────────────────────

def _requeue_dir(state_root: str) -> Path:
    return Path(os.path.expanduser(str(state_root))) / REQUEUE_DIRNAME


def _snapshot(rec: dict[str, Any]) -> dict[str, Any]:
    return {k: rec.get(k) for k in ("mirrorJobId", "phase", "attempts",
                                    "nextAttemptAt", "lastError",
                                    "updatedAt")}


def execute(state_root: str, rows: list[dict[str, Any]], *, max_requeue: int,
            store: MirrorJobStore | None = None) -> dict[str, Any]:
    store = store or MirrorJobStore(state_root)
    picked = [r for r in rows if r["klass"] == "retryable"][:max(0, max_requeue)]
    manifest = {"executedAt": now_iso(), "stateRoot": str(state_root),
                "maxRequeue": max_requeue, "jobs": []}
    for row in picked:
        rec = row["record"]
        prior = _snapshot(rec)
        prior_requeues = int(rec.get("operatorRequeues") or 0)
        store.event(row["mirrorJobId"], "queued", {
            "attempts": 0,
            "nextAttemptAt": None,
            "requeueReason": row["reason"],
            "requeuedBy": "operator",
            "requeuedAt": now_iso(),
            "operatorRequeues": prior_requeues + 1,
        })
        manifest["jobs"].append({"prior": prior,
                                 "klass": row["klass"],
                                 "reason": row["reason"]})
    out_dir = _requeue_dir(state_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = out_dir / ("requeue-%s.json" % stamp)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")
    latest = out_dir / "LATEST"
    latest.write_text(str(manifest_path) + "\n", encoding="utf-8")
    manifest["manifestPath"] = str(manifest_path)
    return manifest


def rollback(state_root: str, manifest_path: str | None = None,
             store: MirrorJobStore | None = None) -> dict[str, Any]:
    """Undo the last execute: restore prior phase/attempts for jobs that
    are STILL in the phase the execute left them in.  Jobs the worker
    already ran (succeeded/failed again/...) are reported as skipped -
    rollback never rewrites history the worker already extended."""
    store = store or MirrorJobStore(state_root)
    if manifest_path is None:
        latest = _requeue_dir(state_root) / "LATEST"
        if not latest.exists():
            return {"error": "no requeue manifest to roll back"}
        manifest_path = latest.read_text(encoding="utf-8").strip()
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    restored, skipped = [], []
    for job in manifest.get("jobs", []):
        prior = job.get("prior") or {}
        mid = str(prior.get("mirrorJobId") or "")
        if not mid:
            continue
        try:
            current = store.get(mid)
        except Exception:
            skipped.append({"mirrorJobId": mid, "why": "record unreadable"})
            continue
        if str(current.get("phase")) != "queued" or \
                int(current.get("operatorRequeues") or 0) < 1:
            skipped.append({"mirrorJobId": mid,
                            "why": "worker already acted on this job "
                                   "(phase=%s)" % current.get("phase")})
            continue
        store.event(mid, str(prior.get("phase") or "failed"), {
            "attempts": prior.get("attempts"),
            "nextAttemptAt": prior.get("nextAttemptAt"),
            "rollbackOf": manifest.get("executedAt"),
            "rolledBackAt": now_iso(),
        })
        restored.append(mid)
    return {"manifest": manifest_path, "restored": restored,
            "skipped": skipped}


# ── CLI ────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify (and optionally requeue) FAILED gbrain "
                    "mirror jobs.  Dry-run unless --execute.")
    parser.add_argument("--state-root", default=os.environ.get(
        "UYP_STATE_ROOT", os.path.expanduser("~/dev/uyp/state")))
    parser.add_argument("--access-context", default=(
        os.environ.get("UYP_ACCESS_CONTEXT_FILE")
        or ("/home/jetson/.config/uyp/access-context.json"
            if os.path.exists("/home/jetson/.config/uyp/access-context.json")
            else None)))
    parser.add_argument("--execute", action="store_true",
                        help="actually requeue retryable jobs "
                             "(default is dry-run)")
    parser.add_argument("--rollback", action="store_true",
                        help="restore the last --execute batch")
    parser.add_argument("--rollback-manifest",
                        help="specific manifest to roll back "
                             "(default: the LATEST pointer)")
    parser.add_argument("--max-requeue", type=int, default=50,
                        help="hard cap of jobs requeued per execution")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output")
    args = parser.parse_args(argv)

    if args.rollback:
        result = rollback(args.state_root, args.rollback_manifest)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("rollback manifest:", result.get("manifest"))
            print("restored:", len(result.get("restored", [])))
            for mid in result.get("restored", []):
                print("  restored", mid)
            for skip in result.get("skipped", []):
                print("  skipped", skip.get("mirrorJobId"), "-", skip.get("why"))
            if result.get("error"):
                print("error:", result["error"])
                return 1
        return 0

    context = load_access_context(args.access_context)
    if context is None:
        print("ERROR: no valid HomeHub access context - refusing to "
              "classify against stale state (fail closed).", file=sys.stderr)
        return 2
    try:
        ledger = active_ledger_grants()
    except Exception as exc:
        print("ERROR: cannot read the live grant ledger: %s" % exc,
              file=sys.stderr)
        return 2

    store = MirrorJobStore(args.state_root)
    records = store.list()
    rows = classify_failed_jobs(records, ledger, context)

    counts: dict[str, int] = {k: 0 for k in CLASSES}
    for row in rows:
        counts[row["klass"]] += 1
    total = len(rows)
    if args.json:
        slim = [{"mirrorJobId": r["mirrorJobId"], "projectId":
                 r["record"].get("projectId"), "klass": r["klass"],
                 "reason": r["reason"],
                 "lastError": str(r["record"].get("lastError") or "")[:120]}
                for r in rows]
        print(json.dumps({"stateRoot": args.state_root,
                          "principal": context.get("principalId"),
                          "failedJobs": total, "counts": counts,
                          "jobs": slim}, indent=2))
    else:
        print("gbrain mirror failed-queue triage (dry-run)"
              + ("  [EXECUTE]" if args.execute else ""))
        print("  state root : %s" % args.state_root)
        print("  principal  : %s" % context.get("principalId"))
        print("  active epochs:",
              {p: v["epoch"] for p, v in sorted(ledger.items())})
        print("  failed jobs: %d" % total)
        for klass in CLASSES:
            print("    %-20s %d" % (klass, counts[klass]))
        for row in rows:
            if row["klass"] in ("retryable", "policy_blocked",
                                "configuration_error", "permanent_failed"):
                print("    %-6s %s %s@%s :: %s"
                      % (row["klass"][:6], row["mirrorJobId"][:24],
                         row["record"].get("projectId"),
                         row["record"].get("grantEpoch"), row["reason"]))

    if not args.execute:
        print("dry-run: nothing written (pass --execute to requeue the "
              "retryable class)")
        return 0

    manifest = execute(args.state_root, rows, max_requeue=args.max_requeue,
                       store=store)
    print("executed: requeued %d job(s); manifest %s"
          % (len(manifest["jobs"]), manifest.get("manifestPath")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
