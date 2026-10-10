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

HomeHub must supply the AccessContext projection.  The worker validates it but
never mints grants, extends expiry, changes policy, or writes audit decisions.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from homehub_adapter import AccessContextError, validate_context


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

TERMINAL = {"published", "blocked", "offline", "revoked", "failed"}

ALLOWED_TRANSITIONS = {
    "discovered": {"authorized", "retry_wait", "blocked", "revoked", "failed"},
    "authorized": {"queued", "blocked", "revoked", "failed"},
    "queued": {"running", "offline", "retry_wait", "revoked", "failed"},
    "running": {"staged", "offline", "retry_wait", "revoked", "failed"},
    "staged": {"published", "failed", "revoked"},
    "retry_wait": {"authorized", "queued", "running", "offline", "revoked", "failed"},
    "offline": {"authorized", "queued", "retry_wait", "revoked", "failed"},
    "blocked": {"authorized", "revoked", "failed"},
    "revoked": set(),
    "failed": {"authorized", "queued", "revoked"},
    "published": {"authorized", "queued", "revoked"},
}


class JobError(RuntimeError):
    """A durable job transition failed for a user-visible reason."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def load_context(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        value = json.loads(Path(os.path.expanduser(path)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return validate_context(value)
    except (AccessContextError, TypeError, ValueError):
        return None


def scope_allows(context: dict[str, Any], job: dict[str, Any]) -> bool:
    project = str(job.get("projectId", ""))
    source = str(job.get("sourceId", ""))
    projects = {str(item) for item in context.get("projectScopes", [])}
    sources = {str(item) for item in context.get("sourceScopes", [])}
    project_ok = "*" in projects or project in projects or f"project:{project}" in projects
    source_ok = "*" in sources or source in sources or f"connector:{project}" in sources
    return project_ok and source_ok


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

    def create(self, *, project_id: str, source_id: str, grant_id: str,
               source_epoch: str | None = None, grant_epoch: str | None = None,
               job_id: str | None = None, total: int | None = None,
               metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        safe_component(project_id, "project id")
        safe_component(source_id, "source id")
        safe_component(grant_id, "grant id")
        job_id = safe_component(job_id or f"job-{uuid.uuid4().hex}", "job id")
        if self._path(job_id).exists():
            raise JobError(f"job already exists: {job_id}")
        stamp = now_iso()
        record: dict[str, Any] = {
            "schemaVersion": "1.0",
            "jobId": job_id,
            "projectId": project_id,
            "sourceId": source_id,
            "grantId": grant_id,
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
        record = self.get(job_id)
        if phase not in PHASES:
            raise JobError(f"unknown IndexJob phase: {phase}")
        current = str(record.get("phase"))
        if phase != current and phase not in ALLOWED_TRANSITIONS.get(current, set()):
            raise JobError(f"invalid IndexJob transition: {current} -> {phase}")
        stamp = now_iso()
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


def connector_call(host: str, token: str, path: str, *, binary: bool = False, timeout: int = 90):
    request = urllib.request.Request(host.rstrip("/") + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return body if binary else json.loads(body)


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
        "publishedArtifacts": published,
        "outputPath": str(target_output),
        "graphPath": str(target_state / "knowledge-graph.json"),
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
        manifest = connector_call(
            connector_host,
            token,
            "/manifest?grant=" + urllib.parse.quote(str(job["grantId"]), safe=""),
        )
    except urllib.error.HTTPError as exc:
        phase = "revoked" if exc.code in {401, 403} else "offline"
        store.event(job_id, phase, {"reason": "connector_revoked" if phase == "revoked" else "connector_unavailable", "error": f"HTTPError:{exc.code}"})
        return store.get(job_id)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        store.event(job_id, "offline", {"reason": "connector_unavailable", "error": type(exc).__name__})
        return store.get(job_id)
    if str(manifest.get("root_name", "")) != str(job["projectId"]):
        store.event(job_id, "failed", {"reason": "manifest_project_mismatch"})
        return store.get(job_id)
    manifest_epoch = manifest.get("source_epoch")
    if job.get("sourceEpoch") and str(job["sourceEpoch"]) != str(manifest_epoch or ""):
        # The source changed between discovery and authorization.  Requeueing
        # requires a fresh manifest and is safer than indexing a stale grant.
        store.event(job_id, "retry_wait", {"reason": "source_epoch_changed", "manifestEpoch": manifest_epoch})
        return store.get(job_id)

    store.event(job_id, "authorized", {"auditId": context.get("auditId"), "grantEpoch": context.get("grantEpoch")})
    store.event(job_id, "queued", {"queue": "background-index"})
    stage_root = Path(store.root) / "index-jobs" / safe_component(job_id, "job id") / "staged"
    if stage_root.exists():
        # A resume starts from a fresh candidate; the previous candidate stays
        # in the job directory as a diagnostic/rollback artifact.
        archive = stage_root.with_name(f"staged-previous-{uuid.uuid4().hex}")
        os.replace(stage_root, archive)
    (stage_root / "output").mkdir(parents=True, exist_ok=True)
    (stage_root / "state").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "UYP_OUTPUT_ROOT": str(stage_root / "output"),
        "UYP_STATE_ROOT": str(stage_root / "state"),
        "UYP_ACCESS_CONTEXT_FILE": "",  # index_project itself never authorizes
    })
    store.event(job_id, "running", {"stageRoot": str(stage_root), "auditId": context.get("auditId")})
    py = python_executable or sys.executable
    script = index_script or str(Path(__file__).with_name("index_project.py"))
    limit = int((job.get("metadata") or {}).get("limit", 0))
    command = [py, script, "--host", connector_host, "--token-file", str(token_path), "--grant", str(job["grantId"])]
    # Pass the value explicitly: 0 means full pending project for the durable
    # worker, while the standalone CLI retains its 20-file default.
    command.extend(["--limit", str(limit)])
    try:
        runner(command, env)
        if ua_runner is None:
            from ua_bridge import run as ua_runner  # local import keeps CLI lightweight
        ua_summary = ua_runner(
            host=connector_host,
            token_file=str(token_path),
            grant=str(job["grantId"]),
            ua_root=ua_root,
            state_root=str(stage_root / "state"),
            limit=limit,
            project_name=str(job["projectId"]),
            knowledge_root=str(stage_root / "output" / str(job["projectId"])),
        )
        store.update(job_id, progress={"processed": int(ua_summary.get("stagedFiles", 0)), "total": manifest.get("total")}, uaSummary=ua_summary)
        store.event(job_id, "staged", {"uaSummary": ua_summary})
    except urllib.error.HTTPError as exc:
        phase = "revoked" if exc.code in {401, 403} else "offline" if exc.code in {408, 502, 503, 504} else "failed"
        store.event(job_id, phase, {"reason": "worker_command_failed", "error": f"HTTPError:{exc.code}"})
        return store.get(job_id)
    except (OSError, subprocess.CalledProcessError, ValueError, RuntimeError) as exc:
        store.event(job_id, "failed", {"reason": "worker_command_failed", "error": type(exc).__name__})
        return store.get(job_id)

    try:
        publication = publish_staged(
            store.get(job_id),
            stage_root=stage_root,
            output_root=Path(os.path.expanduser(output_root)).resolve(),
            state_root=store.root,
        )
    except (OSError, shutil.Error, JobError) as exc:
        store.event(job_id, "failed", {"reason": "publish_failed", "error": type(exc).__name__})
        return store.get(job_id)
    store.event(job_id, "published", {**publication, "auditId": context.get("auditId")})
    return store.get(job_id)


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
) -> dict[str, Any]:
    """Run queued durable jobs once, without turning missing access into a grant.

    This is the scheduler entry point.  A systemd timer, launchd job, or
    deployment controller can invoke it repeatedly.  When HomeHub has not
    supplied a valid context the queue is left untouched so a restart does not
    convert a temporarily disconnected policy plane into permanent blocks.
    """
    jobs = [job for job in store.list() if str(job.get("phase")) not in TERMINAL]
    if context is None or not context_is_valid(context):
        return {"ok": True, "scheduled": 0, "skipped": len(jobs), "reason": "homehub_access_context_unavailable", "jobs": []}
    selected = jobs[: max(0, int(max_jobs))]
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
    return {"ok": True, "scheduled": len(results), "skipped": max(0, len(jobs) - len(results)), "jobs": results}


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
    create.add_argument("--grant-id", required=True)
    create.add_argument("--source-epoch")
    create.add_argument("--grant-epoch")
    create.add_argument("--job-id")
    create.add_argument("--total", type=int)
    create.add_argument("--limit", type=int, default=0)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("job_id")
    pending = sub.add_parser("run-pending", help="run the next queued jobs once; safe to call from a timer")
    pending.add_argument("--max-jobs", type=int, default=1)
    sub.add_parser("list")
    args = parser.parse_args()
    store = IndexJobStore(args.state_root)
    if args.action == "create":
        result = store.create(
            project_id=args.project_id,
            source_id=args.source_id,
            grant_id=args.grant_id,
            source_epoch=args.source_epoch,
            grant_epoch=args.grant_epoch,
            job_id=args.job_id,
            total=args.total,
            metadata={"limit": args.limit},
        )
    elif args.action == "list":
        result = store.list()
    elif args.action == "run-pending":
        result = run_pending(
            store,
            context=load_context(args.access_context),
            connector_host=args.connector_host,
            token_file=args.token_file,
            ua_root=args.ua_root,
            output_root=args.output_root,
            max_jobs=args.max_jobs,
        )
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
