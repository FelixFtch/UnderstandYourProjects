#!/usr/bin/env python3
"""Durable, HomeHub-gated IndexJob worker.

The indexer used to be a one-shot CLI.  This module adds the P4 state machine
around that CLI without introducing a second identity or policy authority:

    DISCOVERED -> AUTHORIZED -> QUEUED -> RUNNING -> STAGED -> PUBLISHED
                                      -> BLOCKED / RETRY_WAIT / OFFLINE / REVOKED / FAILED

Each job record and event is stored below ``state_root``.  A run uses a job
specific staging directory for both the KnowledgeItems and the Understand
Anything graph.  Publishing swaps complete project directories and retains a
rollback copy, so a failed candidate cannot replace the previous stable
version.  Source bytes are still obtained by ``index_project.py`` and
``ua_bridge.py`` through the Connector; this worker never reads a source path.

Retryable failures (worker crash, missing manifest, transport errors) do not
end a job: the failure is still recorded under its canonical phase, then the
job moves into ``retry_wait`` with a bounded retry budget (``MAX_RETRIES``)
and an exponential backoff (``nextAttemptAt``).  ``run_pending`` requeues
retryable terminal jobs and resumes due ``retry_wait`` jobs, reusing the
previous attempt's staged output: ``index_project.py`` skips items whose
recorded version already matches the manifest, so a job that dies near the
end resumes where it stopped instead of restarting from zero.  Non-retryable
failures (revocation, grant epoch mismatch, scope denial, publish failure)
stay terminal.

HomeHub must supply the AccessContext projection.  The worker validates it but
never mints grants, extends expiry, changes policy, or writes audit decisions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from connector_registry import upsert_connector, update_health

from homehub_adapter import AccessContextError, load_context, validate_context


PHASES = (
    "discovered",
    "authorized",
    "queued",
    "running",
    "staged",
    "published",
    "blocked",
    "retry_wait",
    "offline",
    "revoked",
    "failed",
)

# ``failed``/``offline`` stay in TERMINAL: run_pending never executes them
# directly, it first reclassifies the retryable ones into ``retry_wait``.
TERMINAL = {"published", "blocked", "offline", "revoked", "failed"}

# Reasons the durable worker may retry.  Authorization answers (revocation,
# grant epoch mismatch, scope denial) and publish failures stay terminal:
# retrying them would only repeat the same denial, and a publish that already
# failed must not get another shot at replacing a stable knowledge version.
RETRYABLE_REASONS = {
    "worker_command_failed",         # worker/LLM crash, incl. transport HTTP codes
    "connector_manifest_not_found",  # connector answered 404 for the grant
    "connector_unavailable",         # transport error reaching the connector
}
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 60

# Events that are logged for observability but never move the durable phase.
INFORMATIONAL_PHASES = {"resumed"}

# NOTE: transitions TO ``discovered`` are NOT enumerated per phase below.
# ``IndexJobStore.event`` admits ``discovered`` from ANY non-terminal phase
# (the escape hatch); the table only governs forward progress and failure
# recording.
ALLOWED_TRANSITIONS = {
    # The manifest fetch happens before the authorized transition, so every
    # non-terminal phase must be able to record a connector/transport failure
    # (``offline`` was previously missing here, which crashed the scheduler
    # pass instead of recording the outage).
    "discovered": {"authorized", "retry_wait", "blocked", "revoked", "failed", "offline"},
    "authorized": {"queued", "blocked", "revoked", "failed", "offline"},
    "queued": {"running", "offline", "retry_wait", "revoked", "failed"},
    # -> discovered is always legal from running via the escape hatch: a
    # worker that dies mid-run leaves the job stranded here, and the recovery
    # sweep pushes it back to discovered for a clean re-entry (field
    # evidence: three running->authorized transition errors in one night,
    # each previously needing a manual kick script).
    "running": {"staged", "offline", "retry_wait", "revoked", "failed"},
    "staged": {"published", "failed", "revoked", "offline"},
    # ``blocked`` is reachable from retry_wait because a resumed job can find
    # its scope narrowed between attempts; it must block, not crash.
    "retry_wait": {"authorized", "queued", "running", "blocked", "offline", "revoked", "failed"},
    "offline": {"authorized", "queued", "retry_wait", "revoked", "failed"},
    "blocked": {"authorized", "revoked", "failed"},
    "revoked": set(),
    # ``retry_wait`` is reachable from failed so a retryable failure can be
    # requeued (immediately after it is recorded, or by the recovery pass in
    # run_pending for jobs that crashed before retry accounting existed).
    "failed": {"authorized", "queued", "retry_wait", "revoked"},
    "published": {"authorized", "queued", "revoked"},
}


class JobError(RuntimeError):
    """A durable job transition failed for a user-visible reason."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _retry_backoff_seconds(retry_count: int) -> int:
    """Exponential backoff for the Nth retry: 60s, 120s, 240s."""
    return RETRY_BACKOFF_BASE_SECONDS * (2 ** (max(int(retry_count), 1) - 1))


def safe_component(value: str, label: str = "component") -> str:
    value = str(value or "")
    if not value or value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"unsafe {label}: {value!r}")
    return value


def context_is_valid(context: dict[str, Any] | None) -> bool:
    try:
        validate_context(context or {})
    except (AccessContextError, TypeError, ValueError):
        return False
    return True


def scope_allows(context: dict[str, Any], job: dict[str, Any]) -> bool:
    project = str(job.get("projectId", ""))
    source = str(job.get("sourceId", ""))
    projects = {str(item) for item in context.get("projectScopes", [])}
    sources = {str(item) for item in context.get("sourceScopes", [])}
    project_ok = "*" in projects or project in projects or f"project:{project}" in projects
    source_ok = "*" in sources or source in sources or f"connector:{project}" in sources
    return project_ok and source_ok


def connector_grant_id(job: dict[str, Any]) -> str:
    """Resolve the Connector capability without confusing it with HomeHub policy."""
    value = job.get("connectorGrantId") or job.get("grantId")
    if not isinstance(value, str) or not value.strip():
        raise JobError("IndexJob is missing connectorGrantId")
    return value.strip()


def derive_source_epoch(manifest: dict[str, Any]) -> str | None:
    """Derive a deterministic source epoch from the observed manifest page.

    The Connector protocol does not yet carry an explicit epoch for a grant,
    so authorization pins the manifest observation itself: a digest over the
    page's (relpath, size, mtime) entries plus the connector's total.  A listed
    file changing, appearing, or disappearing moves the epoch, which is the
    drift ``sourceEpoch`` exists to detect on the next run.  A malformed or
    empty manifest yields ``None`` rather than an invented epoch; entries are
    hashed in relpath order so connector-side ordering cannot shift the value.
    """
    if not isinstance(manifest, dict):
        return None
    files = manifest.get("files")
    if not isinstance(files, list):
        return None
    entries = [entry for entry in files if isinstance(entry, dict) and str(entry.get("relpath", ""))]
    if not entries:
        return None
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: str(item.get("relpath", ""))):
        line = f"{entry.get('relpath')}\x1f{entry.get('size')}\x1f{entry.get('mtime')}"
        digest.update(line.encode("utf-8", "surrogatepass"))
        digest.update(b"\x1e")
    digest.update(f"total={manifest.get('total')}".encode("utf-8"))
    return digest.hexdigest()[:32]


def _registry_connector_id(source_id: str) -> str:
    """Map a capability id to a stable registry id without persisting paths."""
    raw = str(source_id)
    # Keep the canonical connector capability spelling used by Studio when it
    # is already safe; this lets the durable observation merge with the
    # project snapshot's connector projection instead of duplicating it.
    if raw.startswith("connector:") and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", raw):
        return raw
    slug = re.sub(r"[^A-Za-z0-9_.:-]+", "-", raw).strip("-")[:140]
    return f"connector:{slug or 'pending'}"


def _observe_connector(store: "IndexJobStore", job: dict[str, Any], context: dict[str, Any], manifest: dict[str, Any], connector_host: str, source_epoch: Any = None) -> None:
    """Persist connector health/manifest metadata after a scoped read.

    This is a status projection only.  The grant id, token, file entries, and
    HomeHub context are deliberately excluded; HomeHub remains authoritative.
    Registry I/O cannot make an otherwise successful IndexJob fail.
    """
    source_id = str(job.get("sourceId", ""))
    connector_id = _registry_connector_id(source_id)
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    kind = metadata.get("connectorKind", "local")
    label = metadata.get("connectorLabel", "Authorized connector")
    transport = os.environ.get("UYP_AGENT_TRANSPORT", "unknown")
    total = manifest.get("total") if isinstance(manifest.get("total"), int) else None
    has_more = bool(manifest.get("has_more"))
    if source_epoch is None:
        source_epoch = manifest.get("source_epoch")
    record = {
        "connectorId": connector_id,
        "nodeId": str(context.get("jarvisNodeId", "node:pending")),
        "kind": kind,
        "label": label,
        "transport": transport,
        "endpoint": connector_host,
        "state": "current",
        "manifestState": "pending" if has_more else "ready",
        "sourceIds": [source_id],
        "sourceEpoch": str(source_epoch) if source_epoch is not None else None,
        "lastSeen": now_iso(),
        "lastSyncAt": now_iso(),
        "manifest": {
            "state": "pending" if has_more else "ready",
            "sourceEpoch": str(source_epoch) if source_epoch is not None else None,
            "generatedAt": manifest.get("generated_at"),
            "total": total,
            "fileCount": total,
        },
    }
    try:
        upsert_connector(record, store.root / "connectors" / "registry.json")
    except (OSError, ValueError, TypeError):
        return


def _observe_connector_health(store: "IndexJobStore", job: dict[str, Any], *, state: str, detail: str) -> None:
    """Best-effort health update for a connector already in the registry."""
    try:
        update_health(
            _registry_connector_id(str(job.get("sourceId", ""))),
            state=state,
            detail=detail,
            path=store.root / "connectors" / "registry.json",
        )
    except (KeyError, OSError, ValueError, TypeError):
        return


def _record_failure(store: "IndexJobStore", job_id: str, job: dict[str, Any], *,
                    phase: str, reason: str, error: str | None = None) -> dict[str, Any]:
    """Record a failure, scheduling a bounded retry when the reason allows it.

    The failure itself is always recorded under its canonical phase (``failed``
    or ``offline``, or ``revoked`` for policy answers) so the event log keeps
    the real outcome.  A retryable reason then moves the job into
    ``retry_wait`` with the retry budget and backoff that ``run_pending`` needs
    to resume it; a non-retryable reason, or an exhausted budget, leaves the
    recorded phase terminal.  Returns the job record after the transition.
    """
    details: dict[str, Any] = {"reason": reason}
    if error is not None:
        details["error"] = error
    retries_used = int(job.get("retryCount") or 0)
    if reason not in RETRYABLE_REASONS or retries_used >= MAX_RETRIES:
        if reason in RETRYABLE_REASONS:
            details["retryCount"] = retries_used
            details["retriesExhausted"] = True
        store.event(job_id, phase, details)
        return store.get(job_id)
    retry_count = retries_used + 1
    store.event(job_id, phase, details)
    store.event(job_id, "retry_wait", {
        **details,
        "retryCount": retry_count,
        "nextAttemptAt": _timestamp_after(_retry_backoff_seconds(retry_count)),
    })
    return store.get(job_id)


class IndexJobStore:
    """Atomic JSON records and append-only transition events under state_root."""

    def __init__(self, state_root: str | os.PathLike[str]):
        self.root = Path(os.path.expanduser(str(state_root))).resolve()
        self.jobs = self.root / "index-jobs"
        self.jobs.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.jobs / f"{safe_component(job_id, 'job id')}.json"

    def _event_path(self, job_id: str) -> Path:
        return self.jobs / f"{safe_component(job_id, 'job id')}.events.jsonl"

    @staticmethod
    def _write_atomic(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(raw, path)
        finally:
            try:
                os.unlink(raw)
            except FileNotFoundError:
                pass

    def create(self, *, project_id: str, source_id: str, grant_id: str | None = None,
               connector_grant_id: str | None = None,
               source_epoch: str | None = None, grant_epoch: str | None = None,
               job_id: str | None = None, total: int | None = None,
               metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        safe_component(project_id, "project id")
        # A source id is a capability identifier, not a filesystem component;
        # GitHub-style ids may legitimately contain a slash (for example
        # ``github:org/repository``).  It is still bounded against NUL and
        # emptiness before being persisted.
        if not str(source_id) or "\x00" in str(source_id):
            raise ValueError(f"unsafe source id: {source_id!r}")
        if connector_grant_id and grant_id and connector_grant_id != grant_id:
            raise ValueError("grant_id and connector_grant_id must match when both are supplied")
        connector_grant_id = connector_grant_id or grant_id
        safe_component(connector_grant_id or "", "connector grant id")
        job_id = safe_component(job_id or f"job-{uuid.uuid4().hex}", "job id")
        if self._path(job_id).exists():
            raise JobError(f"job already exists: {job_id}")
        stamp = now_iso()
        record: dict[str, Any] = {
            "schemaVersion": "1.0",
            "jobId": job_id,
            "projectId": project_id,
            "sourceId": source_id,
            # This is the Connector's read capability. HomeHub's project
            # grant is represented by the AccessContext and its epoch; it is
            # deliberately a separate authorization namespace.
            "connectorGrantId": connector_grant_id,
            "sourceEpoch": source_epoch,
            "grantEpoch": grant_epoch,
            "phase": "discovered",
            "progress": {"processed": 0, "total": total},
            "createdAt": stamp,
            "updatedAt": stamp,
            "events": 0,
        }
        if metadata:
            record["metadata"] = metadata
        self._write_atomic(self._path(job_id), record)
        self.event(job_id, "discovered", {"reason": "job_created"})
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        try:
            return json.loads(self._path(job_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JobError(f"job not found: {job_id}") from exc

    def list(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.jobs.glob("*.json")):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return records

    def event(self, job_id: str, phase: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        """Record a phase transition, or an informational event that keeps the phase.

        Phases in ``INFORMATIONAL_PHASES`` (for example ``resumed``) are
        appended to the durable event log without moving the record's phase,
        so timeline readers can see retry pickups that are not state-machine
        transitions.
        """
        record = self.get(job_id)
        if phase not in PHASES and phase not in INFORMATIONAL_PHASES:
            raise JobError(f"unknown IndexJob phase: {phase}")
        current = str(record.get("phase"))
        informational = phase in INFORMATIONAL_PHASES
        if not informational:
            # Escape hatch (root-cause fix, 2026-10-10): ``discovered`` is
            # admissible from ANY non-terminal phase.  ``discovered`` is
            # always safe because run_job re-validates everything from
            # scratch before doing work -- manifest fetch, HomeHub context,
            # scope, grant epoch, source epoch -- so a reset can never skip
            # policy; the worst it can do is repeat a validation.  Without
            # this edge, any bug or crash that left a job in a non-terminal
            # phase stranded it forever (field evidence: three
            # running->authorized transition errors in one night, each
            # needing a manual "kick" script).  This rule is what makes
            # manual recovery unnecessary: the state machine can never
            # strand a job that has not reached a recorded answer.
            # Terminal phases stay excluded: published/revoked/blocked/
            # offline/failed are answers, not stranded work, and
            # failed/offline requeue only through _recover_failed_jobs so
            # the bounded retry budget is honored.
            allowed = ALLOWED_TRANSITIONS.get(current, set())
            if phase != current and phase not in allowed and not (
                    phase == "discovered" and current not in TERMINAL):
                raise JobError(f"invalid IndexJob transition: {current} -> {phase}")
        stamp = now_iso()
        if not informational:
            record["phase"] = phase
        record["updatedAt"] = stamp
        if details:
            for key, value in details.items():
                if key not in {"phase", "events"}:
                    record[key] = value
        record["events"] = int(record.get("events", 0)) + 1
        self._write_atomic(self._path(job_id), record)
        event = {"at": stamp, "phase": phase, "details": details or {}}
        with self._event_path(job_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def update(self, job_id: str, **fields: Any) -> dict[str, Any]:
        record = self.get(job_id)
        record.update(fields)
        record["updatedAt"] = now_iso()
        self._write_atomic(self._path(job_id), record)
        return record


def connector_call(host: str, token: str, path: str, *, binary: bool = False,
                    timeout: int = 90, retries: int = 5):
    """Connector fetch with the same transport hardening as index_project.api:

    percent-encoded request lines (CJK source paths) and retry-with-backoff
    on transport failures (launchd tunnel blips raise IncompleteRead /
    HTTPException mid-body). Policy answers (HTTPError) stay final.
    """
    import http.client
    safe_path = urllib.parse.quote(path, safe="/?=&")
    last: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(
            host.rstrip("/") + safe_path,
            headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
            return body if binary else json.loads(body)
        except urllib.error.HTTPError:
            raise
        except (OSError, urllib.error.URLError, json.JSONDecodeError,
                http.client.IncompleteRead, http.client.HTTPException) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt * 5, 60))
    raise last


def _run_command(command: list[str], env: dict[str, str]) -> None:
    subprocess.run(command, check=True, env=env)


def _copy_tree_atomic(staged: Path, target: Path, backup: Path) -> None:
    """Replace a project directory as one filesystem rename, with rollback."""
    if not staged.exists():
        raise JobError(f"staged artifact missing: {staged}")
    target.parent.mkdir(parents=True, exist_ok=True)
    backup.parent.mkdir(parents=True, exist_ok=True)
    replacement = target.parent / f".{target.name}.publish-{uuid.uuid4().hex}"
    shutil.copytree(staged, replacement)
    old_moved = False
    try:
        if target.exists():
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(target, backup)
            old_moved = True
        os.replace(replacement, target)
    except Exception:
        if replacement.exists():
            shutil.rmtree(replacement)
        if old_moved and not target.exists() and backup.exists():
            os.replace(backup, target)
        raise


def publish_staged(job: dict[str, Any], *, stage_root: Path, output_root: Path, state_root: Path) -> dict[str, Any]:
    """Publish staged KnowledgeItems and UA graph, preserving rollback copies."""
    project = safe_component(str(job["projectId"]), "project id")
    staged_output = stage_root / "output" / project
    staged_state = stage_root / "state" / project / "ua"
    target_output = output_root / project
    target_state = state_root / project / "ua"
    backup_root = state_root / "index-jobs" / safe_component(str(job["jobId"]), "job id") / "rollback"
    published: list[str] = []
    try:
        _copy_tree_atomic(staged_output, target_output, backup_root / "output")
        published.append("knowledge-items")
        _copy_tree_atomic(staged_state, target_state, backup_root / "ua")
        published.append("ua-graph")
    except Exception:
        # If the first half was published and the second half failed, restore
        # the previous copy when one exists.  The job remains failed and the
        # previous stable artifacts remain queryable.
        if "knowledge-items" in published:
            backup = backup_root / "output"
            if target_output.exists():
                shutil.rmtree(target_output)
            if backup.exists():
                os.replace(backup, target_output)
        raise
    return {
        "publishedAt": now_iso(),
        "knowledgeVersion": str(job.get("sourceEpoch") or job.get("updatedAt") or now_iso()),
        "sourceEpoch": job.get("sourceEpoch"),
        "publishedArtifacts": published,
        "outputPath": str(target_output),
        "graphPath": str(target_state / "knowledge-graph.json"),
    }


def _merge_incremental_baseline(*, stage_root: Path, output_root: Path, project: str) -> int:
    """Fill an incremental job's staging with the currently published items.

    Returns the number of baseline items copied (0 when the project was never
    published - a first publish has nothing to merge). Staged (changed) items
    are never overwritten; only files the wave did not touch ride along."""
    staged_dir = stage_root / "output" / safe_component(project, "project id")
    current = output_root / safe_component(project, "project id")
    if not current.is_dir():
        return 0
    staged_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for item in current.glob("*.knowledge.json"):
        target = staged_dir / item.name
        if not target.exists():
            shutil.copy2(item, target)
            copied += 1
    return copied


def _count_staged_items(stage_root: Path, project_id: str) -> int:
    """Count KnowledgeItems a previous attempt already staged for the project."""
    try:
        project_output = stage_root / "output" / safe_component(project_id, "project id")
        return sum(1 for item in project_output.glob("*.knowledge.json") if item.is_file())
    except (OSError, ValueError):
        return 0


def _preserve_staged_progress(store: "IndexJobStore", job_id: str, job: dict[str, Any],
                              stage_root: Path, manifest: dict[str, Any]) -> None:
    """After a worker crash, keep durable progress truthful about survivors.

    The worker writes staged output incrementally, so items completed before
    the crash must show up in the job record immediately -- not only when a
    later retry recounts them.
    """
    staged_items = _count_staged_items(stage_root, str(job["projectId"]))
    if staged_items:
        store.update(job_id, progress={"processed": staged_items, "total": manifest.get("total")})


def _enqueue_gbrain_mirror(store: "IndexJobStore", job_id: str,
                           job: dict[str, Any], publication: dict[str, Any]) -> dict[str, Any]:
    """Best-effort queueing of a post-publish gBrain mirror.

    The queue write is deliberately after the atomic local UYP/UA swap and
    performs no network I/O. A missing queue directory or malformed metadata
    is surfaced as an ``unavailable`` projection while the IndexJob remains
    ``published``: local project knowledge is the primary product and the
    optional gBrain mirror can be retried by its own worker.
    """
    try:
        from gbrain_publisher import enqueue_mirror, mirror_projection
        record = enqueue_mirror(
            state_root=store.root,
            index_job_id=job_id,
            project_id=str(job["projectId"]),
            knowledge_root=str(publication["outputPath"]),
            version=str(publication["knowledgeVersion"]),
            source_epoch=publication.get("sourceEpoch"),
            grant_epoch=job.get("grantEpoch"),
            published_at=publication.get("publishedAt"),
        )
        return mirror_projection(record)
    except Exception as exc:  # queueing must never turn a local publish into failure
        return {
            "phase": "unavailable",
            "lastError": f"{type(exc).__name__}: {exc}"[:300],
        }


def run_job(
    store: IndexJobStore,
    job_id: str,
    *,
    context: dict[str, Any] | None,
    connector_host: str,
    token_file: str,
    ua_root: str,
    output_root: str,
    runner: Callable[[list[str], dict[str, str]], None] = _run_command,
    python_executable: str | None = None,
    index_script: str | None = None,
    ua_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Authorize and execute one durable IndexJob.

    ``runner`` is injectable for tests.  Production uses subprocess for the
    existing index CLI and calls ``ua_bridge.run`` in-process after indexing.
    """
    job = store.get(job_id)
    if str(job.get("phase")) == "retry_wait":
        # A retry attempt is being picked up (by run_pending or a manual run).
        # ``resumed`` is informational: the durable phase keeps its retry_wait
        # value and moves on with the next real transition.
        resumed_details: dict[str, Any] = {"retryCount": int(job.get("retryCount") or 0)}
        reason = job.get("reason")
        if isinstance(reason, str) and reason:
            resumed_details["reason"] = reason
        store.event(job_id, "resumed", resumed_details)
    if not context_is_valid(context):
        revoked = isinstance(context, dict) and (
            context.get("revoked") is True
            or context.get("validation") in {"revoked", "expired"}
        )
        if isinstance(context, dict) and not revoked:
            try:
                revoked = datetime.fromisoformat(str(context.get("expiresAt", "")).replace("Z", "+00:00")) <= datetime.now(timezone.utc)
            except (TypeError, ValueError):
                pass
        store.event(job_id, "revoked" if revoked else "blocked", {
            "reason": "homehub_context_revoked" if revoked else "homehub_access_context_unavailable"
        })
        return store.get(job_id)
    assert context is not None
    if not scope_allows(context, job):
        store.event(job_id, "blocked", {"reason": "homehub_scope_denied", "auditId": context.get("auditId")})
        return store.get(job_id)
    if job.get("grantEpoch") and str(job["grantEpoch"]) != str(context.get("grantEpoch")):
        store.event(job_id, "revoked", {"reason": "grant_epoch_mismatch", "auditId": context.get("auditId")})
        return store.get(job_id)

    token_path = Path(os.path.expanduser(token_file))
    try:
        token = token_path.read_text(encoding="utf-8").strip()
        connector_grant = connector_grant_id(job)
        manifest = connector_call(
            connector_host,
            token,
            "/manifest?grant=" + urllib.parse.quote(connector_grant, safe=""),
        )
    except urllib.error.HTTPError as exc:
        phase = "revoked" if exc.code in {401, 403} else "failed" if exc.code == 404 else "offline"
        _observe_connector_health(store, job, state="revoked" if phase == "revoked" else "offline", detail=f"HTTPError:{exc.code}")
        reason = "connector_revoked" if phase == "revoked" else "connector_manifest_not_found" if phase == "failed" else "connector_unavailable"
        return _record_failure(store, job_id, job, phase=phase, reason=reason, error=f"HTTPError:{exc.code}")
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        _observe_connector_health(store, job, state="offline", detail=type(exc).__name__)
        return _record_failure(store, job_id, job, phase="offline", reason="connector_unavailable", error=type(exc).__name__)
    if str(manifest.get("root_name", "")) != str(job["projectId"]):
        _observe_connector_health(store, job, state="failed", detail="manifest_project_mismatch")
        return _record_failure(store, job_id, job, phase="failed", reason="manifest_project_mismatch")
    manifest_epoch = manifest.get("source_epoch") or derive_source_epoch(manifest)
    if job.get("sourceEpoch") and str(job["sourceEpoch"]) != str(manifest_epoch or ""):
        # The source changed between attempts (live-repo reality: agents keep
        # editing the Mac tree, so drift is perpetual - 2026-10-10 field
        # livelock: every resume saw drift -> retry_wait -> drift...).
        # Full-pass semantics: ACCEPT the new epoch and continue - the full
        # scan is a snapshot-at-acceptance; per-file changes flow through the
        # incremental wave (P8) which exists precisely for this. The new
        # epoch is pinned in the authorized event below, so the next drift
        # comparison uses the accepted lineage.
        store.event(job_id, "resumed", {"reason": "source_epoch_rebased",
                                        "oldEpoch": job.get("sourceEpoch"),
                                        "manifestEpoch": manifest_epoch})
        job["sourceEpoch"] = manifest_epoch
        store.update(job_id, sourceEpoch=manifest_epoch)

    _observe_connector(store, job, context, manifest, connector_host, source_epoch=manifest_epoch)

    # Pin the observed epoch in the durable record at authorization time so
    # publish metadata and the next run's drift check share one lineage value.
    store.event(job_id, "authorized", {"auditId": context.get("auditId"), "grantEpoch": context.get("grantEpoch"), "sourceEpoch": manifest_epoch})
    store.event(job_id, "queued", {"queue": "background-index"})
    stage_root = Path(store.root) / "index-jobs" / safe_component(job_id, "job id") / "staged"
    # Reuse a previous attempt's staging directory instead of wiping it.  The
    # index worker is idempotent against its own output -- index_project.py
    # skips items whose recorded version matches the manifest -- so a job that
    # dies at file 2900 of 3000 resumes at file 2901, not at file 1.  The
    # publish step still swaps complete directories atomically with a rollback
    # copy, so a reused candidate cannot replace the previous stable version.
    staged_items = _count_staged_items(stage_root, str(job["projectId"]))
    (stage_root / "output").mkdir(parents=True, exist_ok=True)
    (stage_root / "state").mkdir(parents=True, exist_ok=True)
    if staged_items:
        # Keep the durable progress truthful while the retry is running, so a
        # job that dies again still reports how much work survived.
        store.update(job_id, progress={"processed": staged_items, "total": manifest.get("total")})
    env = dict(os.environ)
    env.update({
        "UYP_OUTPUT_ROOT": str(stage_root / "output"),
        "UYP_STATE_ROOT": str(stage_root / "state"),
        "UYP_ACCESS_CONTEXT_FILE": "",  # index_project itself never authorizes
    })
    store.event(job_id, "running", {"stageRoot": str(stage_root), "auditId": context.get("auditId"), "resumedFromStagedItems": staged_items})
    py = python_executable or sys.executable
    script = index_script or str(Path(__file__).with_name("index_project.py"))
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    limit = int(metadata.get("limit", 0))
    command = [py, script, "--host", connector_host, "--token-file", str(token_path), "--grant", connector_grant_id(job)]
    # Pass the value explicitly: 0 means full pending project for the durable
    # worker, while the standalone CLI retains its 20-file default.
    command.extend(["--limit", str(limit)])
    changed_files = metadata.get("changed_files")
    # A deletion cannot be represented by --changes-file: index_project would
    # never visit the missing relpath and the stale KnowledgeItem would be
    # copied into the next published version.  Incremental reconciliation
    # marks such waves as full_reconcile, so the candidate is rebuilt from the
    # current Connector manifest and the atomic publish drops absent files.
    if (not metadata.get("full_reconcile")) and isinstance(changed_files, list) and changed_files:
        # P8 incremental reconcile pinned the exact relpaths that changed.
        # The list travels as a file inside the job's staging root rather
        # than argv: hundreds of relpaths do not belong on a command line,
        # and a resumed attempt re-reads it without any reconcile state.
        changes_path = stage_root / "changed_files.json"
        changes_path.write_text(
            json.dumps(sorted({str(item) for item in changed_files}), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        command.extend(["--changes-file", str(changes_path)])
    try:
        runner(command, env)
        if metadata.get("incremental") and not metadata.get("full_reconcile"):
            # Incremental workers stage only the wave's changed files; a
            # whole-tree publish of that staging replaces the project with a
            # sliver (2026-10-14 field incident: jarvis-homehub collapsed
            # 3179 -> 3 files when a one-file wave published). Fill the
            # staging with the CURRENT published items first so the candidate
            # is complete by construction; staged items overwrite stale ones.
            baseline = _merge_incremental_baseline(
                stage_root=stage_root,
                output_root=Path(os.path.expanduser(output_root)).resolve(),
                project=str(job["projectId"]),
            )
            if baseline:
                store.event(job_id, "running", {"baselineItems": baseline,
                                                "note": "incremental staging merged over the published baseline"})
        if ua_runner is None:
            from ua_bridge import run as ua_runner  # local import keeps CLI lightweight
        ua_summary = ua_runner(
            host=connector_host,
            token_file=str(token_path),
            grant=connector_grant_id(job),
            ua_root=ua_root,
            state_root=str(stage_root / "state"),
            limit=limit,
            project_name=str(job["projectId"]),
            knowledge_root=str(stage_root / "output" / str(job["projectId"])),
        )
        store.update(job_id, progress={"processed": int(ua_summary.get("stagedFiles", 0)), "total": manifest.get("total")}, uaSummary=ua_summary)
        store.event(job_id, "staged", {"uaSummary": ua_summary})
    except urllib.error.HTTPError as exc:
        _preserve_staged_progress(store, job_id, job, stage_root, manifest)
        phase = "revoked" if exc.code in {401, 403} else "offline" if exc.code in {408, 502, 503, 504} else "failed"
        return _record_failure(store, job_id, job, phase=phase, reason="worker_command_failed", error=f"HTTPError:{exc.code}")
    except (OSError, subprocess.CalledProcessError, ValueError, RuntimeError) as exc:
        _preserve_staged_progress(store, job_id, job, stage_root, manifest)
        return _record_failure(store, job_id, job, phase="failed", reason="worker_command_failed", error=type(exc).__name__)

    try:
        publication = publish_staged(
            store.get(job_id),
            stage_root=stage_root,
            output_root=Path(os.path.expanduser(output_root)).resolve(),
            state_root=store.root,
        )
    except (OSError, shutil.Error, JobError) as exc:
        return _record_failure(store, job_id, job, phase="failed", reason="publish_failed", error=type(exc).__name__)
    # The local UYP publication is complete before this hook runs. Queueing a
    # gBrain mirror is metadata-only and never blocks/fails the IndexJob; a
    # separate mirror worker can process/retry the durable record later.
    mirror = _enqueue_gbrain_mirror(store, job_id, store.get(job_id), publication)
    store.event(job_id, "published", {
        **publication,
        "auditId": context.get("auditId"),
        "gbrainMirror": mirror,
    })
    return store.get(job_id)


def _retry_attempt_due(job: dict[str, Any], stamp: datetime) -> bool:
    """A retry_wait job becomes due once ``nextAttemptAt`` has passed.

    Records without ``nextAttemptAt`` (the source-epoch-drift requeue and jobs
    written before retry accounting existed) stay immediately eligible, which
    preserves the previous run_pending behavior for them.  A malformed
    timestamp also counts as due: an early retry is recoverable, a job stuck
    behind an unparseable timestamp is not.
    """
    if str(job.get("phase")) != "retry_wait":
        return True
    raw = str(job.get("nextAttemptAt") or "")
    if not raw:
        return True
    try:
        due = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return due <= stamp



def _recover_failed_jobs(store: IndexJobStore) -> int:
    """Requeue terminal jobs whose failure reason is retryable.

    Jobs that crashed before retry accounting existed sit permanently in
    ``failed``/``offline`` even though their reason (worker crash, missing
    manifest, transport blip) is exactly what retries exist for.  Each
    recovery consumes one unit of the same bounded budget and gets the same
    backoff, so an exhausted or non-retryable job stays terminal.  Returns how
    many jobs were requeued.
    """
    recovered = 0
    for job in store.list():
        # running 也算孤儿: run_pending 是同步的, 它在跑说明上一个已死
        # (field evidence: 三次 running->authorized 转换错误)
        if str(job.get("phase")) not in {"failed", "offline", "running"}:
            continue
        reason = str(job.get("reason") or "")
        if str(job.get("phase")) == "running":
            reason = "worker_command_failed"  # 孤儿running 按可重试处理, 不吃预算
        if reason not in RETRYABLE_REASONS:
            continue
        retries_used = int(job.get("retryCount") or 0)
        if retries_used >= MAX_RETRIES:
            continue
        retry_count = retries_used + 1
        try:
            store.event(str(job["jobId"]), "retry_wait", {
                "reason": reason,
                "retryCount": retry_count,
                "nextAttemptAt": _timestamp_after(_retry_backoff_seconds(retry_count)),
            })
        except (JobError, KeyError):
            continue  # a concurrent actor moved the job first; leave it alone
        recovered += 1
    return recovered


def run_pending(
    store: IndexJobStore,
    *,
    context: dict[str, Any] | None,
    connector_host: str,
    token_file: str,
    ua_root: str,
    output_root: str,
    max_jobs: int = 1,
    runner: Callable[[list[str], dict[str, str]], None] = _run_command,
    ua_runner: Callable[..., dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run queued durable jobs once, without turning missing access into a grant.

    This is the scheduler entry point.  A systemd timer, launchd job, or
    deployment controller can invoke it repeatedly.  When HomeHub has not
    supplied a valid context the queue is left untouched so a restart does not
    convert a temporarily disconnected policy plane into permanent blocks.

    Before selecting jobs, terminal ``failed``/``offline`` jobs with a
    retryable reason and budget left are requeued into ``retry_wait``.
    ``retry_wait`` jobs are selected only once their ``nextAttemptAt`` backoff
    has elapsed, so a crashing job is retried with increasing delay instead of
    being hammered on every timer tick.  ``now`` is injectable so schedulers
    and tests can decide eligibility against a controlled clock.
    """
    stamp = now or datetime.now(timezone.utc)
    jobs = [job for job in store.list() if str(job.get("phase")) not in TERMINAL]
    if context is None or not context_is_valid(context):
        return {"ok": True, "scheduled": 0, "skipped": len(jobs), "recovered": 0, "reason": "homehub_access_context_unavailable", "jobs": []}
    recovered = _recover_failed_jobs(store)
    if recovered:
        jobs = [job for job in store.list() if str(job.get("phase")) not in TERMINAL]
    due = [job for job in jobs if _retry_attempt_due(job, stamp)]
    selected = due[: max(0, int(max_jobs))]
    results: list[dict[str, Any]] = []
    for job in selected:
        results.append(run_job(
            store,
            str(job["jobId"]),
            context=context,
            connector_host=connector_host,
            token_file=token_file,
            ua_root=ua_root,
            output_root=output_root,
            runner=runner,
            ua_runner=ua_runner,
        ))
    return {"ok": True, "scheduled": len(results), "skipped": max(0, len(jobs) - len(results)), "recovered": recovered, "jobs": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="HomeHub-gated durable UYP IndexJob worker")
    parser.add_argument("--state-root", default=os.environ.get("UYP_STATE_ROOT", "~/dev/uyp/state"))
    parser.add_argument("--output-root", default=os.environ.get("UYP_OUTPUT_ROOT", "~/dev/uyp/output"))
    parser.add_argument("--access-context", default=os.environ.get("UYP_ACCESS_CONTEXT_FILE"))
    parser.add_argument("--connector-host", default=os.environ.get("UYP_CONNECTOR_HOST", "http://127.0.0.1:7121"))
    parser.add_argument("--token-file", default=os.environ.get("UYP_CONNECTOR_TOKEN_FILE", "~/.config/uyp/token"))
    parser.add_argument("--ua-root", required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create")
    create.add_argument("--project-id", required=True)
    create.add_argument("--source-id", required=True)
    create.add_argument("--connector-grant-id")
    # Backward-compatible spelling for existing local scripts. It always
    # means the Connector capability, never the HomeHub project grant.
    create.add_argument("--grant-id")
    create.add_argument("--source-epoch")
    create.add_argument("--grant-epoch")
    create.add_argument("--job-id")
    create.add_argument("--total", type=int)
    create.add_argument("--limit", type=int, default=0)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("job_id")
    pending = sub.add_parser("run-pending", help="run the next queued jobs once; safe to call from a timer")
    pending.add_argument("--max-jobs", type=int, default=1)
    sub.add_parser("recover-stranded",
                    help="Push stranded running jobs (dead worker) back to discovered")
    sub.add_parser("list")
    args = parser.parse_args()
    store = IndexJobStore(args.state_root)
    if args.action == "create":
        connector_grant = args.connector_grant_id or args.grant_id
        if args.connector_grant_id and args.grant_id and args.connector_grant_id != args.grant_id:
            parser.error("--connector-grant-id and --grant-id must match when both are supplied")
        if not connector_grant:
            parser.error("create requires --connector-grant-id")
        result = store.create(
            project_id=args.project_id,
            source_id=args.source_id,
            connector_grant_id=connector_grant,
            source_epoch=args.source_epoch,
            grant_epoch=args.grant_epoch,
            job_id=args.job_id,
            total=args.total,
            metadata={"limit": args.limit},
        )
    elif args.action == "recover-stranded":
        # Dead-worker sweep: run_pending is synchronous, so a job still in
        # ``running`` means its worker is gone.  The escape hatch in event()
        # makes running->discovered legal; discovered re-validates manifest,
        # grant and epoch from scratch on the next pass.
        count = 0
        for job in store.list():
            if str(job.get("phase")) != "running":
                continue
            try:
                store.event(str(job["jobId"]), "discovered",
                            {"reason": "stranded_running_recovered"})
            except (JobError, KeyError):
                continue  # a concurrent actor moved the job first
            count += 1
        result = {"recovered": count}
    elif args.action == "list":
        result = store.list()
    elif args.action == "run-pending":
        context = load_context(args.access_context)
        # P8 pre-step: turn Connector change events into targeted jobs before
        # the scheduler picks work.  Guarded by the HomeHub context exactly
        # like the scheduler itself: no context means no reconcile, silently.
        # A failed reconcile never blocks the pass - its cursors are only
        # advanced on success, so the events retry on the next tick.
        reconcile_summary = None
        if context is not None and context_is_valid(context):
            try:
                from incremental import reconcile_and_enqueue  # local: avoids an import cycle
                reconcile_summary = reconcile_and_enqueue(
                    store, connector_host=args.connector_host, token_file=args.token_file)
            except Exception as exc:  # the scheduler pass must still run
                reconcile_summary = {"ok": False, "error": type(exc).__name__}
        result = run_pending(
            store,
            context=context,
            connector_host=args.connector_host,
            token_file=args.token_file,
            ua_root=args.ua_root,
            output_root=args.output_root,
            max_jobs=args.max_jobs,
        )
        if reconcile_summary is not None:
            result["reconcile"] = reconcile_summary
    else:
        result = run_job(
            store,
            args.job_id,
            context=load_context(args.access_context),
            connector_host=args.connector_host,
            token_file=args.token_file,
            ua_root=args.ua_root,
            output_root=args.output_root,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
