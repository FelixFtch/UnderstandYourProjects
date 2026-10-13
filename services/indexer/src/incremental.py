#!/usr/bin/env python3
"""Jetson-side incremental reconcile: Connector events -> targeted IndexJobs.

Fetches ``GET /events?since=<id>`` from the Connector, keeps one cursor per
grant under ``state_root`` (``incremental-cursor.json``), and enqueues a
durable IndexJob with ``metadata.changed_files`` pinned for each changed
grant, so the worker re-processes only what actually changed instead of
rescanning the project.

Fail-closed properties:
- a failed events or grants fetch aborts the pass and leaves every cursor
  untouched: events are simply re-fetched on the next tick, nothing is lost
  and nothing is invented;
- events for a grant the Connector no longer lists (revoked), or a grant with
  no prior IndexJob (unknown project), are dropped by advancing only that
  grant's cursor;
- a grant with a non-terminal job is deferred: its cursor stays put, so the
  same changes are retried once the pending job resolves;
- job ids are deterministic (``incr-<sha256(grant:lastEventId)>``): a crash
  between job creation and the cursor save replays into the SAME job instead
  of duplicating it.

Deletes trigger a durable full-reconcile job. A deleted file is absent from
the next manifest, so a targeted changed-file pass cannot remove its prior
KnowledgeItem safely. The full-reconcile candidate is published atomically
only after the current manifest has been indexed; stale KnowledgeItems are
therefore removed without writing tombstones into a source project.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
from pathlib import Path
from typing import Any, Callable

from index_job import TERMINAL, JobError, connector_call

CURSOR_FILENAME = "incremental-cursor.json"


def parse_event_id(value: Any) -> int:
    """'e_42' or '42' -> 42; anything unparseable -> 0 (refetch all).

    Refetching from zero is the fail-closed direction: the deterministic job
    ids and changed-file dedupe make a replay harmless, while guessing a
    higher cursor could silently skip real changes.
    """
    raw = str(value if value is not None else "").strip()
    if raw.startswith("e_"):
        raw = raw[2:]
    return int(raw) if raw.isdigit() else 0


def fetch_events(host: str, token: str, since_id: int = 0, *, timeout: int = 30) -> dict:
    """Fetch the Connector's event log beyond ``since_id``."""
    return connector_call(host, token, f"/events?since={int(since_id)}", timeout=timeout)


def fetch_grants(host: str, token: str, *, timeout: int = 30) -> list:
    """Fetch the Connector's active grant list."""
    payload = connector_call(host, token, "/grants", timeout=timeout)
    grants = payload.get("grants") if isinstance(payload, dict) else None
    return grants if isinstance(grants, list) else []


def load_cursors(state_root: str | os.PathLike[str]) -> dict[str, str]:
    path = Path(state_root) / CURSOR_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if str(v)}


def save_cursors(state_root: str | os.PathLike[str], cursors: dict[str, str]) -> None:
    path = Path(state_root) / CURSOR_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(cursors, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    os.replace(tmp, path)


def group_changes(events: list, cursors: dict[str, str]) -> dict[str, dict]:
    """Fold log events into one per-grant bucket beyond each grant's cursor.

    Per relpath the LAST event in the batch wins: a file modified then deleted
    is a delete, not a change to re-analyze. Returns
    ``{grant: {lastEventId, changed (sorted), deleted_files (sorted),
    deleted (count)}}``.
    """
    last_kind: dict[str, dict[str, str]] = {}
    buckets: dict[str, dict] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        grant = str(event.get("grant") or "")
        relpath = str(event.get("relpath") or "")
        kind = str(event.get("kind") or "")
        if not grant or not relpath:
            continue
        event_id = parse_event_id(event.get("id"))
        if event_id <= parse_event_id(cursors.get(grant)):
            continue
        bucket = buckets.setdefault(grant, {
            "lastEventId": 0,
            "changed": [],
            "deleted_files": [],
            "deleted": 0,
        })
        bucket["lastEventId"] = max(bucket["lastEventId"], event_id)
        last_kind.setdefault(grant, {})[relpath] = kind
    for grant, kinds in last_kind.items():
        bucket = buckets[grant]
        bucket["changed"] = sorted(rel for rel, kind in kinds.items()
                                   if kind in {"created", "modified"})
        bucket["deleted_files"] = sorted(rel for rel, kind in kinds.items()
                                          if kind == "deleted")
        bucket["deleted"] = len(bucket["deleted_files"])
    return buckets


def latest_job_for_grant(store, grant_id: str) -> dict | None:
    """The most recent job for a connector grant, if the project is known."""
    jobs = [job for job in store.list()
            if str(job.get("connectorGrantId") or "") == grant_id]
    if not jobs:
        return None
    return max(jobs, key=lambda job: str(job.get("updatedAt") or ""))


def pending_job_for_grant(store, grant_id: str) -> dict | None:
    for job in store.list():
        if str(job.get("connectorGrantId") or "") == grant_id and str(job.get("phase")) not in TERMINAL:
            return job
    return None


def incremental_job_id(grant_id: str, last_event_id: int) -> str:
    digest = hashlib.sha256(f"{grant_id}:{int(last_event_id)}".encode("utf-8")).hexdigest()[:12]
    return f"incr-{digest}"


def reconcile_and_enqueue(
    store,
    *,
    connector_host: str,
    token_file: str,
    events_fetcher: Callable[[int], dict] | None = None,
    grants_fetcher: Callable[[], list] | None = None,
) -> dict:
    """One reconcile pass: fetch events, enqueue targeted jobs, save cursors.

    ``events_fetcher``/``grants_fetcher`` are injectable for tests; the
    production defaults read the Connector with the device bearer. Returns a
    summary dict; ``ok`` is False only when the pass could not observe the
    Connector (cursors then stay untouched, so the next pass retries).
    """
    summary: dict[str, Any] = {"ok": True, "fetched": 0, "changed": {},
                               "enqueued": [], "deferred": [], "dropped": [], "error": None}
    cursors = load_cursors(store.root)

    def default_events(since_id: int) -> dict:
        token = Path(os.path.expanduser(token_file)).read_text(encoding="utf-8").strip()
        return fetch_events(connector_host, token, since_id)

    def default_grants() -> list:
        token = Path(os.path.expanduser(token_file)).read_text(encoding="utf-8").strip()
        return fetch_grants(connector_host, token)

    fetch_events_now = events_fetcher or default_events
    fetch_grants_now = grants_fetcher or default_grants

    try:
        batch = fetch_events_now(min((parse_event_id(v) for v in cursors.values()), default=0))
        grants = fetch_grants_now()
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        # fail closed: no cursor moves, no job is created from a partial view
        return {**summary, "ok": False, "error": type(exc).__name__}

    events = batch.get("events") if isinstance(batch, dict) else None
    if not isinstance(events, list):
        return {**summary, "ok": False, "error": "bad_events_response"}
    if not isinstance(grants, list):
        return {**summary, "ok": False, "error": "bad_grants_response"}
    summary["fetched"] = len(events)
    if not events:
        return summary

    active = {str(g.get("id") or "") for g in grants if isinstance(g, dict)}
    for grant_id, bucket in sorted(group_changes(events, cursors).items()):
        last_id = f"e_{bucket['lastEventId']}"
        summary["changed"][grant_id] = {"changed": len(bucket["changed"]),
                                        "deleted": bucket["deleted"]}
        if grant_id not in active:
            cursors[grant_id] = last_id
            summary["dropped"].append({"grant": grant_id, "reason": "grant_not_active"})
            continue
        prior = latest_job_for_grant(store, grant_id)
        if prior is None:
            # unknown project: first-scan onboarding is a full manifest job,
            # not an incremental one driven by the event log
            cursors[grant_id] = last_id
            summary["dropped"].append({"grant": grant_id, "reason": "unknown_project"})
            continue
        if pending_job_for_grant(store, grant_id) is not None:
            summary["deferred"].append({"grant": grant_id})
            continue  # cursor stays: retried once the pending job resolves
        if not bucket["changed"] and not bucket["deleted_files"]:
            # Events with an unknown kind cannot be represented by the
            # targeted worker. Consume them once the Connector has confirmed
            # the grant is active; no source bytes or permissions are guessed.
            cursors[grant_id] = last_id
            summary["dropped"].append({"grant": grant_id, "reason": "no_supported_changes"})
            continue
        job_id = incremental_job_id(grant_id, bucket["lastEventId"])
        try:
            store.create(
                project_id=str(prior["projectId"]),
                source_id=str(prior["sourceId"]),
                connector_grant_id=grant_id,
                job_id=job_id,
                metadata={
                    "limit": 0,
                    "incremental": True,
                    "changed_files": bucket["changed"],
                    "changedCount": len(bucket["changed"]),
                    # A delete cannot be handled by a changed-file-only
                    # candidate: the old item would otherwise survive the
                    # atomic publish. IndexJob treats this as a full
                    # manifest reconciliation, while retaining the paths for
                    # audit/debugging in the durable record.
                    "full_reconcile": bool(bucket["deleted_files"]),
                    "deleted_files": bucket["deleted_files"],
                    "deletedCount": bucket["deleted"],
                    "lastEventId": last_id,
                },
            )
        except JobError:
            # deterministic id: a previous pass already created this exact job
            # (crash between create and cursor save) - consume, don't duplicate
            cursors[grant_id] = last_id
            summary["enqueued"].append({"jobId": job_id, "grant": grant_id,
                                        "changed": len(bucket["changed"]), "replayed": True})
            continue
        except ValueError:
            # defensive: persisted jobs already carry validated ids, so this
            # is unreachable in practice - but the event stream is external
            # input, and an unsafe id must never advance the cursor
            summary["deferred"].append({"grant": grant_id, "reason": "unsafe_identifier"})
            continue
        cursors[grant_id] = last_id
        summary["enqueued"].append({"jobId": job_id, "grant": grant_id,
                                    "changed": len(bucket["changed"]),
                                    "deleted": bucket["deleted"]})

    save_cursors(store.root, cursors)
    return summary
