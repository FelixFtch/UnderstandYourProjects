#!/usr/bin/env python3
"""Read-only Jetson query service for UnderstandYourProjects.

This is the bridge between the Studio and the existing index/search proof of
concept. It deliberately does not mint identity, grants, or pairing tokens.
When a HomeHub AccessContext projection is unavailable, search returns an
explicit access error instead of searching the whole output directory.

Run on the Agent Box:
    UYP_ACCESS_CONTEXT_FILE=/path/context.json python3 query_api.py

The service binds to loopback by default. ``--lan`` is an explicit deployment
choice; put it behind the approved transport and HomeHub adapter before using
it outside the Jetson.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import glob
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from knowledge_search import (
    INTERACTIVE_LOCK,
    MISS_SENTENCE,
    answer as search_answer,
    load_items,
    will_synthesize as search_will_synthesize,
)
import knowledge_evidence
import knowledge_core
from knowledge_core import ua_query as ua_core
from connector_registry import load_registry, public_projection, registry_health
from groups import (
    GroupRegistry,
    GroupsError,
    group_allows_member,
    intersect_views,
    scoped_retrieval,
    source_overlap,
    validate_group_context,
)
from group_device_actions import GroupDeviceActionError, validate_group_device_action
from homehub_adapter import (
    load_context as load_homehub_context,
    load_context_for_member as load_homehub_context_for_member,
    load_context_for_token as load_homehub_context_for_token,
)
from nandatown_client import NandaTownClient
import project_digest
import project_jobs
import projects as project_registry


VERSION = "0.1.0"
DEFAULT_OUTPUT = "~/dev/uyp/output"
DEFAULT_STATE = "~/dev/uyp/state"
MAX_BODY = 64 * 1024
INDEX_JOB_PHASES = frozenset({
    "discovered", "authorized", "queued", "running", "staged", "published",
    "blocked", "retry_wait", "offline", "revoked", "failed",
})


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def configured_path(name: str, default: str) -> str:
    return os.path.realpath(os.path.expanduser(os.environ.get(name, default)))


def output_root() -> str:
    return configured_path("UYP_OUTPUT_ROOT", DEFAULT_OUTPUT)


def state_root() -> str:
    return configured_path("UYP_STATE_ROOT", DEFAULT_STATE)


def safe_state_project(project: str) -> str | None:
    """Return a state-root component, never an arbitrary filesystem path."""
    value = str(project or "")
    if not value or value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        return None
    return value


def load_ua_graph(project: str) -> dict | None:
    """Load only the bridge-published UA graph for an authorized project."""
    component = safe_state_project(project)
    if component is None:
        return None
    root = os.path.realpath(state_root())
    candidate = os.path.realpath(os.path.join(root, component, "ua", "knowledge-graph.json"))
    try:
        if os.path.commonpath([root, candidate]) != root:
            return None
        with open(candidate, encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) and isinstance(value.get("nodes"), list) else None
    except (OSError, json.JSONDecodeError):
        return None


_graph_index_lock = threading.Lock()
# root -> ((mtime, size), GraphIndex | None); the Jetson graph JSON is
# ~25 MB, so it is parsed once per edition, never once per request.
_graph_index_cache: dict[str, tuple[tuple[float, int], object]] = {}


def _graph_index_for(root: str):
    """Cached GraphIndex over a project's published UA graph.

    Graph refs on KnowledgeEvidence records are optional: any failure
    (missing graph, bad JSON, path escape) yields None and the query
    path continues without them.
    """
    component = safe_state_project(root)
    if component is None:
        return None
    try:
        base = os.path.realpath(state_root())
        candidate = os.path.realpath(os.path.join(base, component, "ua", "knowledge-graph.json"))
        if os.path.commonpath([base, candidate]) != base:
            return None
        stat = os.stat(candidate)
        key = (stat.st_mtime, stat.st_size)
    except OSError:
        return None
    with _graph_index_lock:
        cached = _graph_index_cache.get(component)
        if cached and cached[0] == key:
            return cached[1]
    index = knowledge_evidence.GraphIndex(load_ua_graph(component)) if component else None
    with _graph_index_lock:
        _graph_index_cache[component] = (key, index)
    return index


# ---- Unified UA query (2026-10-19): one graph query door for every entry --
#
# knowledge_core.ua_query owns the deterministic target resolver and the
# six operations; this adapter adds ONLY the credential model (the same
# /api/projects caller tiers), the graph cache (a ~25 MB JSON parses once
# per edition), the IndexJob/manifest-backed activity provider, and the
# caller-visible project list. No LLM runs here: operation inference is
# keyword-deterministic, answers/phrasing belong to the callers.

_ua_graph_cache: dict[str, tuple[tuple[float, int], object]] = {}


def _ua_graph_for(project: str):
    """Cached ua_query.UAGraph per project graph edition; None = absent."""
    component = safe_state_project(project)
    if component is None:
        return None
    try:
        base = os.path.realpath(state_root())
        candidate = os.path.realpath(os.path.join(base, component, "ua", "knowledge-graph.json"))
        if os.path.commonpath([base, candidate]) != base:
            return None
        stat = os.stat(candidate)
        key = (stat.st_mtime, stat.st_size)
    except OSError:
        return None
    with _graph_index_lock:
        cached = _ua_graph_cache.get(component)
        if cached and cached[0] == key:
            return cached[1]
    graph = ua_core.load_graph(component, root=state_root())
    with _graph_index_lock:
        _ua_graph_cache[component] = (key, graph)
    return graph


def _ua_project_ids(context: dict) -> list[str]:
    """Caller-visible projects that actually have a UA graph, sorted."""
    try:
        listing = project_digest.list_projects(context)
    except Exception:  # noqa: BLE001 - registry hiccups answer empty, honest
        return []
    ids = []
    for record in listing.get("projects") or []:
        project_id = str(record.get("project_id") or "")
        if project_id and _ua_graph_for(project_id) is not None:
            ids.append(project_id)
    return sorted(set(ids))


def _ua_activity(context: dict, project_id: str, since: float, until: float) -> list[dict]:
    """Changed-file rows via the visible-project activity path."""
    result = project_digest.activity(context, project_id, since, until)
    if not isinstance(result, dict):
        return []
    return [row for row in (result.get("changed") or [])
            if isinstance(row, dict) and row.get("file")]


_TIME_RANGE_ALIASES = {
    "day": "day", "today": "day",
    "week": "week", "this_week": "week", "recently": "week",
}


def _ua_request_from_payload(payload: dict) -> tuple[object, str | None]:
    """(UAQueryRequest, error). Operation defaults to the deterministic
    keyword inference over the question text; every enum is validated."""
    question = str(payload.get("question") or payload.get("query") or "").strip()
    operation = str(payload.get("operation") or "").strip().lower()
    if not operation:
        if not question:
            return None, "question_or_operation_required"
        operation = ua_core.infer_operation(question)
    if operation not in ua_core.OPERATIONS:
        return None, "invalid_operation"
    raw_range = str(payload.get("timeRange") or payload.get("time_range") or "").strip().lower()
    time_range = _TIME_RANGE_ALIASES.get(raw_range) if raw_range else None
    if raw_range and time_range is None:
        return None, "invalid_time_range"
    raw_target = payload.get("target")
    target = None
    if isinstance(raw_target, dict) and any(raw_target.get(k) for k in
                                            ("type", "query", "path", "nodeId", "node_id")):
        target = ua_core.UATarget(
            type=str(raw_target.get("type") or "") or None,
            query=str(raw_target.get("query") or "") or None,
            path=str(raw_target.get("path") or "") or None,
            node_id=str(raw_target.get("nodeId") or raw_target.get("node_id") or "") or None,
        )
    elif question:
        target = ua_core.UATarget(query=question)
    session_context = {
        "active_node_id": str(payload.get("activeNodeId")
                              or payload.get("active_node_id") or ""),
        "last_target_id": str(payload.get("lastTargetId")
                              or payload.get("last_target_id") or ""),
    }
    return ua_core.UAQueryRequest(
        operation=operation,
        project_id="",
        target=target,
        time_range=time_range,
        session_context={k: v for k, v in session_context.items() if v},
    ), None


def _ua_run(context: dict, req, project_id: str) -> dict:
    """Run one query against ONE visible project and frame the response."""
    graph = _ua_graph_for(project_id)
    request = ua_core.UAQueryRequest(
        operation=req.operation, project_id=project_id, target=req.target,
        time_range=req.time_range, session_context=req.session_context)
    result = ua_core.run_ua_query(
        request, graph=graph,
        activity=(lambda pid, since, until: _ua_activity(context, pid, since, until))
        if req.operation == "recent_changes" else None)
    body = {
        "ok": True,
        "operation": result.operation,
        "projectId": project_id,
        "status": result.status,
        "resolution": {
            "nodeId": result.target.node_id,
            "resolution": result.target.resolution,
            "confidence": result.target.confidence,
            "candidates": [dict(candidate, projectId=project_id)
                           for candidate in result.target.candidates],
        },
        "note": result.note,
        "evidence": result.evidence,
        "indexAsOf": result.index_as_of,
        "auditId": None,
    }
    if req.operation == "recent_changes":
        job = project_jobs.jobs_by_project().get(project_id) or {}
        body["indexJob"] = {
            "phase": job.get("phase"), "status": job.get("status"),
            "progress": job.get("progress"),
        } if job.get("phase") else None
    return body


def _ua_respond(handler, payload: dict, audit: str) -> None:
    """POST /api/ua/query: resolve + run one unified UA graph query.

    Project selection is deterministic and honest: a NAMED project must
    be caller-visible (404 otherwise, indistinguishable from absent);
    an UNNAMED project runs the target resolution across every visible
    graphed project - exactly one hit executes there, hits in several
    projects clarify once with the candidates, and project-scoped
    operations (summary / recent_changes) with several candidates
    clarify which project. Zero matches answer not_found / no_graph,
    never a chat downgrade (that rule belongs to the callers too).
    """
    caller = handler._project_caller(audit)
    if caller is None:
        return
    context = caller["context"]
    req, error = _ua_request_from_payload(payload)
    if error is not None:
        handler.json_response({"ok": False, "error": error}, 400, audit)
        return
    project = str(payload.get("project") or payload.get("projectId") or "").strip()
    if project:
        if project_digest._resolve(context, project) is None:
            handler._project_not_found(audit)
            return
        graph = _ua_graph_for(project)
        if graph is None:
            body = {
                "ok": True, "operation": req.operation, "projectId": project,
                "status": "no_graph",
                "resolution": {"nodeId": "", "resolution": "not_found",
                               "confidence": 0.0, "candidates": []},
                "note": f"No analyzed code graph for {project} yet.",
                "evidence": [], "indexAsOf": None, "auditId": audit,
            }
        else:
            body = _ua_run(context, req, project)
            body["auditId"] = audit
        handler.json_response(body, audit=audit)
        return
    candidates = _ua_project_ids(context)
    if not candidates:
        handler.json_response({
            "ok": True, "operation": req.operation, "projectId": None,
            "status": "no_graph",
            "resolution": {"nodeId": "", "resolution": "not_found",
                           "confidence": 0.0, "candidates": []},
            "note": "No analyzed code graphs are available to you yet.",
            "evidence": [], "indexAsOf": None, "auditId": audit,
        }, audit=audit)
        return
    if len(candidates) == 1:
        body = _ua_run(context, req, candidates[0])
        body["auditId"] = audit
        handler.json_response(body, audit=audit)
        return
    if req.operation in ("summary", "recent_changes"):
        # Project-scoped: several visible projects is a one-shot clarify.
        handler.json_response({
            "ok": True, "operation": req.operation, "projectId": None,
            "status": "ambiguous_project",
            "resolution": {"nodeId": "", "resolution": "ambiguous",
                           "confidence": 0.0, "candidates": [
                               {"node_id": "", "name": p, "type": "project",
                                "file": "", "projectId": p}
                               for p in candidates]},
            "note": "Several analyzed projects are available; ask which one.",
            "evidence": [], "indexAsOf": None, "auditId": audit,
        }, audit=audit)
        return
    # Target-based operations: resolve across every visible graph.
    resolved_projects: list[tuple[str, object]] = []
    ambiguous: list[dict] = []
    negative = ("not_found", 0.0, [])
    for project_id in candidates:
        graph = _ua_graph_for(project_id)
        if graph is None:
            continue
        verdict = ua_core.resolve_target(req.target, graph, req.session_context)
        if verdict.resolved:
            resolved_projects.append((project_id, graph))
        elif verdict.resolution == "ambiguous":
            ambiguous.extend(
                dict(candidate, projectId=project_id)
                for candidate in verdict.candidates)
        elif negative[0] != "no_context" and verdict.resolution == "no_context":
            negative = ("no_context", verdict.confidence, verdict.candidates)
    if len(resolved_projects) == 1:
        body = _ua_run(context, req, resolved_projects[0][0])
        body["auditId"] = audit
        handler.json_response(body, audit=audit)
        return
    if len(resolved_projects) > 1:
        handler.json_response({
            "ok": True, "operation": req.operation, "projectId": None,
            "status": "ambiguous_project",
            "resolution": {"nodeId": "", "resolution": "ambiguous",
                           "confidence": 0.0, "candidates": [
                               {"node_id": "", "name": p, "type": "project",
                                "file": "", "projectId": p}
                               for p, _g in resolved_projects]},
            "note": "That matches several analyzed projects; ask which one.",
            "evidence": [], "indexAsOf": None, "auditId": audit,
        }, audit=audit)
        return
    if ambiguous:
        handler.json_response({
            "ok": True, "operation": req.operation, "projectId": None,
            "status": "ambiguous",
            "resolution": {"nodeId": "", "resolution": "ambiguous",
                           "confidence": 0.0,
                           "candidates": ambiguous[:ua_core.MAX_CANDIDATES]},
            "note": "Several graph nodes match; ask which one.",
            "evidence": [], "indexAsOf": None, "auditId": audit,
        }, audit=audit)
        return
    note = ("Which file or symbol do you mean?" if negative[0] == "no_context"
            else "I could not find that in the analyzed code graphs.")
    handler.json_response({
        "ok": True, "operation": req.operation, "projectId": None,
        "status": negative[0],
        "resolution": {"nodeId": "", "resolution": negative[0],
                       "confidence": negative[1],
                       "candidates": negative[2]},
        "note": note, "evidence": [], "indexAsOf": None, "auditId": audit,
    }, audit=audit)


def load_access_context() -> dict | None:
    # A local file is only a transport projection from HomeHub.  Use the same
    # strict validator as IndexJob and federation code, and fail closed.
    return load_homehub_context()


def load_request_context(headers, *, loopback_voice: bool = False) -> tuple[dict | None, str | None]:
    """Per-request HomeHub context resolution (voice handshake, 2026-10-10).

    Returns ``(context, denied_member)``: ``context`` is the validated
    HomeHub projection or ``None``; ``denied_member`` names the loopback
    voice member whose per-member resolution was DENIED (only ever set by
    the member tier), so the caller can answer with an honest 403 in that
    member's name instead of a generic 503.

    Resolution order for ``POST /api/knowledge/search``:

    (a) ``Authorization: Bearer <token>`` - the caller presents its own
        HomeHub Companion bearer (a Studio session).  The service resolves
        THAT caller's projection over the same approved transport and
        strict validation as every other path (``homehub_adapter``).
        Fail closed: a request that presented credentials never falls
        back to the box context.
    (b) loopback-voice mode - no Bearer, but ``X-Agent-Member`` is present:
        the voice runtime (the box's agent-runtime) must never hold this
        service's credentials, so the SERVICE acts as the box - it
        presents its own service bearer through ``UYP_HOMEHUB_ACCESS_CONTEXT_URL``
        + ``UYP_HOMEHUB_TOKEN_FILE`` (standard env names, no new ones) and
        asks HomeHub to resolve the SPEAKING MEMBER's grant scopes
        (``load_homehub_context_for_member``).  Per-member enforcement:
        the member header selects whose grants scope the search.  A
        member with no grant, an unknown member, or a HomeHub projection
        that speaks for any other principal (including the box itself) is
        an honest denial - NEVER a fallback to the box context, which was
        the bug where the owner's grant served every member.
        ``loopback_voice`` is set ONLY by ``main()`` for a loopback bind:
        header-asserted voice identity must never be admitted on a
        ``--lan`` bind (this adds no network exposure).
    (c) no Bearer, no member header - today's service-level resolution
        (env/file), unchanged: ``None`` (and a 503) when nothing is
        configured.
    """
    auth = str(headers.get("Authorization") or "")
    if auth[:7].lower() == "bearer " and auth[7:].strip():
        return load_homehub_context_for_token(auth[7:]), None
    member = str(headers.get("X-Agent-Member") or "").strip()
    if member and loopback_voice:
        context = load_homehub_context_for_member(member)
        return context, (None if context is not None else member)
    return load_access_context(), None


def access_context_valid(context: dict) -> bool:
    if context.get("revoked") is True or context.get("validation") in {"revoked", "expired"}:
        return False
    try:
        expires = datetime.fromisoformat(str(context["expiresAt"]).replace("Z", "+00:00"))
        return expires > datetime.now(timezone.utc)
    except (KeyError, TypeError, ValueError):
        return False


def item_root(path: str) -> str:
    return knowledge_core.item_root(path)


def grouped_items() -> dict[str, list[dict]]:
    # Moved into the shared Knowledge Core so /api/knowledge/search and
    # /api/health cannot drift on how the output store is read.
    return knowledge_core.grouped_items()


def _scope_allows_job(context: dict, job: dict) -> bool:
    """Filter a persisted IndexJob by HomeHub capability scopes."""
    project = str(job.get("projectId", ""))
    source = str(job.get("sourceId", ""))
    projects = {str(value) for value in context.get("projectScopes", [])}
    sources = {str(value) for value in context.get("sourceScopes", [])}
    project_ok = "*" in projects or project in projects or f"project:{project}" in projects
    source_ok = "*" in sources or source in sources or f"connector:{project}" in sources
    return project_ok and source_ok


def _job_projection(raw: dict) -> dict | None:
    """Keep only the public IndexJob contract; drop grants and filesystem paths."""
    if not isinstance(raw, dict):
        return None
    job_id = str(raw.get("jobId", ""))
    project = str(raw.get("projectId", ""))
    source = str(raw.get("sourceId", ""))
    if not job_id or "/" in job_id or "\\" in job_id or not project or "/" in project or "\\" in project or not source:
        return None
    phase = str(raw.get("phase", ""))
    if phase not in INDEX_JOB_PHASES:
        return None
    progress = raw.get("progress") if isinstance(raw.get("progress"), dict) else {}
    processed = progress.get("processed", 0)
    total = progress.get("total")
    processed = processed if isinstance(processed, int) and 0 <= processed <= 100_000_000 else 0
    total = total if isinstance(total, int) and 0 <= total <= 100_000_000 else None
    result = {
        "jobId": job_id,
        "projectId": project if project.startswith("project:") else f"project:{project}",
        "sourceId": source,
        "phase": phase,
        "progress": {"processed": processed, "total": total},
    }
    # These are timestamps/versions only; connectorGrantId/grantId, outputPath, metadata and
    # event details are deliberately excluded from the Studio projection.
    for key in ("sourceEpoch", "knowledgeVersion", "createdAt", "updatedAt", "publishedAt", "finishedAt", "reason", "auditId"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip() and len(value) <= 256:
            result[key] = value.strip()
    # Optional asynchronous gBrain mirror status.  Keep this projection to
    # version/epoch/attempt metadata: local knowledge paths, endpoints, and
    # writer credentials never cross the Studio boundary.
    mirror = raw.get("gbrainMirror")
    if isinstance(mirror, dict):
        mirror_result = {}
        for key in ("mirrorJobId", "indexJobId", "projectId", "knowledgeVersion",
                    "sourceEpoch", "grantEpoch", "publishedAt", "phase",
                    "attempts", "maxAttempts", "nextAttemptAt", "lastError",
                    "createdAt", "updatedAt"):
            value = mirror.get(key)
            if isinstance(value, str) and len(value) <= 300:
                mirror_result[key] = value
            elif key in {"attempts", "maxAttempts"} and isinstance(value, int) and value >= 0:
                mirror_result[key] = value
        if mirror_result:
            result["gbrainMirror"] = mirror_result
    return result


def load_persisted_index_jobs(project_id: str | None = None, context: dict | None = None) -> list[dict]:
    """Read durable IndexJob records, fail-closed without HomeHub context."""
    if context is None:
        return []
    jobs_root = os.path.realpath(os.path.join(state_root(), "index-jobs"))
    if not os.path.isdir(jobs_root):
        return []
    requested = str(project_id or "").removeprefix("project:")
    result: list[dict] = []
    for path in sorted(glob.glob(os.path.join(jobs_root, "*.json"))):
        try:
            if os.path.commonpath([jobs_root, os.path.realpath(path)]) != jobs_root:
                continue
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        projected = _job_projection(raw)
        if projected is None or not _scope_allows_job(context, raw):
            continue
        raw_project = str(raw.get("projectId", "")).removeprefix("project:")
        if requested and raw_project != requested:
            continue
        result.append(projected)
    return result


def index_jobs_health(context: dict | None = None) -> dict:
    """Summarize durable job state without exposing unauthorized projects."""
    jobs = load_persisted_index_jobs(context=context)
    active = sum(1 for job in jobs if job["phase"] not in {"published", "blocked", "offline", "revoked", "failed"})
    latest = max((str(job.get("updatedAt", "")) for job in jobs), default=None)
    return {"state": "current" if jobs else "pending", "total": len(jobs), "active": active, "lastUpdatedAt": latest}


def configured_connector_status() -> dict:
    host = os.environ.get("UYP_CONNECTOR_HOST")
    token_file = os.environ.get("UYP_CONNECTOR_TOKEN_FILE", "~/.config/uyp/token")
    if not host:
        return {"state": "unsupported", "detail": "Connector host is not configured"}
    try:
        token = open(os.path.expanduser(token_file), encoding="utf-8").read().strip()
        req = urllib.request.Request(host.rstrip("/") + "/status", headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=3) as response:
            status = json.loads(response.read())
        if status.get("state") != "online":
            return {"state": "offline", "detail": f"Connector reported {status.get('state', 'unknown')}"}
        return {"state": "current", "detail": f"Connector {status.get('connector_version', 'unknown')} · {status.get('grants_active', 0)} active grants", "lastSyncAt": now_iso()}
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        return {"state": "offline", "detail": f"Connector unavailable: {type(exc).__name__}"}


def connector_registry_projection(context: dict | None = None) -> list[dict]:
    """Return connector metadata with HomeHub scope filtering.

    The registry is a durable status projection, not an ACL.  Without a
    HomeHub AccessContext we expose only opaque connector/node ids and health
    state; labels, source ids, and manifest scope stay hidden.  With a context,
    source identifiers are still filtered by the context's source scopes.
    """
    document = load_registry()
    records = document.get("connectors", [])
    if context is None:
        return public_projection({"connectors": records}, include_sources=False)
    scopes = {str(value) for value in context.get("sourceScopes", [])}
    all_sources = "*" in scopes
    allowed: list[dict] = []
    for record in records:
        source_ids = {str(value) for value in record.get("sourceIds", [])}
        connector_id = str(record.get("connectorId", ""))
        if not all_sources and not source_ids.intersection(scopes) and connector_id not in scopes:
            continue
        allowed.append(record)
    return public_projection({"connectors": allowed}, include_sources=True)


def registry_agent_nodes(context: dict | None = None) -> list[dict]:
    """Build read-only Agent Box projections from the durable registry."""
    connectors = connector_registry_projection(context)
    records = load_registry().get("connectors", [])
    by_node: dict[str, dict] = {}
    for record in records:
        node_id = str(record.get("nodeId", ""))
        if not node_id:
            continue
        # A connector that was filtered by source scope must not reveal its
        # source association through the node's connectorIds either.
        visible_ids = {item["connectorId"] for item in connectors if item["nodeId"] == node_id}
        if context is not None and not visible_ids:
            continue
        state = str(record.get("state", "pending"))
        pairing = "revoked" if state == "revoked" else "offline" if state in {"offline", "failed"} else "paired" if state == "current" else "pairing" if state == "pending" else "discovered"
        entry = by_node.setdefault(node_id, {
            "nodeId": node_id,
            "label": str(record.get("label")) if context is not None else "Agent Box metadata pending",
            "transport": str(record.get("transport", "unknown")),
            "pairing": pairing,
            "lastSeen": record.get("lastSeen"),
            "capabilities": list(record.get("capabilities", [])),
            "connectorIds": [],
        })
        for connector_id in sorted(visible_ids):
            if connector_id not in entry["connectorIds"]:
                entry["connectorIds"].append(connector_id)
    return list(by_node.values())


# Live NandaTown directory state: the coordinator is queried directly (join
# -> directory) so real Jarvis boxes surface each other in the Studio.  The
# projection - and the honest failure, when there is one - is cached briefly
# so a down town cannot stall every snapshot; the cache never turns a
# failure into data.  UYP_NANDATOWN_CACHE_TTL=0 disables it (tests do).
_NANDATOWN_CACHE_LOCK = threading.Lock()
_nandatown_cache: dict = {"expires": 0.0, "peers": [], "error": None}


def nandatown_peers_projection() -> tuple[list[dict], dict | None]:
    """Query the town coordinator for the live peer directory.

    Returns ``(peers, error)``: ``peers`` is the Studio PeerJarvisSummary
    projection of the run's participant directory (empty on any failure),
    and ``error`` is ``None`` on success or ``{"code", "message"}`` with
    the client's fail-closed diagnosis - unreachable, unauthorized,
    unconfigured, or unknown run.  Peers are directory metadata only,
    never a HomeHub grant or a source listing.
    """
    try:
        configured = os.environ.get("UYP_NANDATOWN_CACHE_TTL")
        ttl = max(0.0, float(configured)) if configured is not None else 30.0
    except ValueError:
        ttl = 30.0
    now = time.monotonic()
    with _NANDATOWN_CACHE_LOCK:
        # TTL=0 must be a HARD no-cache switch read at CHECK time too:
        # a poisoned entry stored under a longer TTL (e.g. a snapshot
        # call while the town env was absent) would otherwise keep
        # serving its error even after the operator disables caching.
        if ttl > 0 and now < _nandatown_cache["expires"]:
            return list(_nandatown_cache["peers"]), _nandatown_cache["error"]
    client = NandaTownClient()
    peers = client.list_peers()
    error = (None if client.error_code is None else
             {"code": client.error_code,
              "message": client.last_error or client.error_code})
    with _NANDATOWN_CACHE_LOCK:
        _nandatown_cache["expires"] = now + ttl
        _nandatown_cache["peers"] = list(peers)
        _nandatown_cache["error"] = error
    return peers, error


def load_nandatown_peers() -> list[dict]:
    """The public NandaTown peer directory; empty when town is unavailable.

    Fail-closed for the snapshot path: a town that cannot be reached or
    joined yields no peers rather than stale or fabricated entries; the
    dedicated /api/nandatown/peers endpoint additionally reports the
    honest error instead of pretending metadata-only success.
    """
    return nandatown_peers_projection()[0]


# ---- Group messaging over NandaTown (audit A2, P10/G9) --------------------
#
# The groups engine owns WHO may speak in a group; nandatown_client owns the
# transport.  This block wires the two to a local per-group message log and
# adds nothing to identity or scope:
#
# * send: POST /api/groups/{id}/messages - a member's message fans out to
#   the group's town peers (one message per recipient with its own
#   message_id; the town has no broadcast primitive).  The local echo is
#   persisted only when at least one copy was accepted (or the directory
#   was honestly empty) - a transport failure is an honest 503 carrying
#   the client's error_code, never a faked delivery.
# * receive: a background poll loop claims this participant's inbox once
#   per group and routes inbound messages into the group's local log.
#   The client re-offers foreign-group messages instead of consuming
#   them, so a message for a group this box does not know is never lost
#   to this poller.
# * history: GET /api/groups/{id}/messages - the member-scoped local log
#   a chat UI polls.  (The voice chain's group_knowledge tool needs only
#   search, which was already live.)
#
# Run mapping v1: a group's messages route to the town run named by its
# registry field ``town_run_id``, else the deployment default
# (``UYP_NANDATOWN_RUN_ID``).  With neither set the endpoints answer an
# honest 503 ``nandatown_run_unconfigured`` instead of silently guessing
# the client's hardcoded DEFAULT_RUN_ID - that constant stays a transport
# default for directory/health, never a group-routing decision.
# Per-group run CREATION automation (town admin API) is future work;
# this is mapping only.

DEFAULT_POLL_SECONDS = 15.0
MAX_MESSAGE_TEXT = 4000
MAX_MESSAGE_LOG_ROWS = 2000
MAX_MESSAGE_LOG_BYTES = 4 * 1024 * 1024

_GROUP_MESSAGE_LOCK = threading.Lock()


def group_town_run(record) -> str | None:
    """The town run a group's messages route to, or None when unmapped.

    ``town_run_id`` on the registry record wins; the deployment's
    ``UYP_NANDATOWN_RUN_ID`` is the default; nothing else is guessed.
    """
    explicit = str((record or {}).get("town_run_id") or "").strip()
    if explicit:
        return explicit
    configured = str(os.environ.get("UYP_NANDATOWN_RUN_ID") or "").strip()
    return configured or None


def town_transport_configured() -> bool:
    """Whether this process holds a town join token (the un-defaultable env).

    URL, run, and participant all have deployment defaults; a join token
    does not.  Without one no town call can succeed, so the poll loop
    stays disabled - fail-closed and quiet.
    """
    return bool(str(os.environ.get("UYP_NANDATOWN_JOIN_TOKEN") or "").strip())


def group_messages_path(group_id: str) -> str | None:
    """``<state-root>/groups/<id>/messages.jsonl``; None for an unsafe id."""
    component = safe_state_project(str(group_id or ""))
    if component is None:
        return None
    return os.path.join(state_root(), "groups", component, "messages.jsonl")


def load_group_messages(group_id: str) -> list[dict]:
    """The group's local message log (oldest first), fail-closed to [].

    Bounded: only the last ``MAX_MESSAGE_LOG_BYTES`` of the file and the
    last ``MAX_MESSAGE_LOG_ROWS`` rows are returned; malformed lines are
    skipped, never fatal.
    """
    path = group_messages_path(group_id)
    if path is None:
        return []
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            if size > MAX_MESSAGE_LOG_BYTES:
                fh.seek(max(0, size - MAX_MESSAGE_LOG_BYTES))
                fh.readline()  # drop the partial line the seek landed in
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows[-MAX_MESSAGE_LOG_ROWS:]


def append_group_message(group_id: str, row: dict) -> bool:
    """Append one row to a group's local log; False when it is a duplicate.

    Dedupe is on ``message_id`` (town delivery is at-least-once; a lease
    expiry can re-offer a message this log already holds).  A row without
    a message_id is always appended.
    """
    path = group_messages_path(group_id)
    if path is None or not isinstance(row, dict):
        return False
    with _GROUP_MESSAGE_LOCK:
        message_id = row.get("message_id")
        if message_id and any(existing.get("message_id") == message_id
                              for existing in load_group_messages(group_id)):
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            os.chmod(os.path.dirname(path), 0o700)
        except OSError:
            pass
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return True


def _message_epoch(value) -> float | None:
    """Parse an ISO-8601 sent_at; None when absent or malformed."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.timestamp()


def inbound_watermark(group_id: str) -> float:
    """The newest INBOUND sent_at this group's log already holds (0.0 if none).

    Restart safety for the poll loop's ``since_ts``: replays older than
    what the log recorded are filtered by the client.  Outbound echoes
    are deliberately excluded - a peer's skewed clock must never hide an
    inbound message behind this box's own later send.
    """
    latest = 0.0
    for row in load_group_messages(group_id):
        if row.get("direction") != "in":
            continue
        sent = _message_epoch(row.get("sent_at") or row.get("received_at"))
        if sent is not None and sent > latest:
            latest = sent
    return latest


def nandatown_poll_seconds() -> float:
    """Poll interval from ``UYP_NANDATOWN_POLL_SECONDS`` (default 15)."""
    raw = os.environ.get("UYP_NANDATOWN_POLL_SECONDS")
    if raw is None or not str(raw).strip():
        return DEFAULT_POLL_SECONDS
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_POLL_SECONDS


def poll_nandatown_groups() -> dict:
    """One bounded receive pass over every locally-mapped group.

    For each distinct town run the mapped groups resolve to, join as this
    process's configured participant and claim that group's pending
    messages (the client consumes same-group messages and re-offers
    foreign ones).  Inbound rows are deduped on ``message_id`` and
    appended to the group's local log.  Never raises; failures land in
    the returned report's ``error`` so callers (the loop, tests) can see
    the honest code without the loop ever dying to it.
    """
    report: dict = {"polled_runs": 0, "polled_groups": 0, "received": 0,
                    "stored": 0, "error": None, "finished_at": now_iso()}
    if not town_transport_configured():
        report["error"] = "nandatown_unconfigured"
        return report
    by_run: dict[str, list[dict]] = {}
    for record in group_registry().load()["groups"]:
        run = group_town_run(record)
        if run:
            by_run.setdefault(run, []).append(record)
    for run in sorted(by_run):
        client = NandaTownClient(run_id=run)
        report["polled_runs"] += 1
        for record in by_run[run]:
            group_id = record["group_id"]
            report["polled_groups"] += 1
            for message in client.poll_group_messages(
                    group_id, since_ts=inbound_watermark(group_id)):
                report["received"] += 1
                body = message.get("body") if isinstance(message.get("body"), dict) else {}
                text = body.get("text")
                if not isinstance(text, str):
                    text = json.dumps(body, ensure_ascii=False)[:MAX_MESSAGE_TEXT] if body else ""
                row = {
                    "message_id": message.get("message_id"),
                    "group_id": group_id,
                    "sender": str(message.get("from") or body.get("sender") or ""),
                    "sent_at": message.get("sent_at"),
                    "received_at": message.get("received_at") or now_iso(),
                    "text": text[:MAX_MESSAGE_TEXT],
                    "direction": "in",
                }
                if append_group_message(group_id, row):
                    report["stored"] += 1
        if client.error_code is not None and report["error"] is None:
            report["error"] = client.error_code
    return report


_nandatown_poll_lock = threading.Lock()
_nandatown_poll_thread: threading.Thread | None = None
_nandatown_poll_stop = threading.Event()
nandatown_poll_status: dict = {"started": False, "interval_seconds": None,
                               "last_report": None}


def _nandatown_poll_loop(interval: float) -> None:
    while not _nandatown_poll_stop.is_set():
        try:
            nandatown_poll_status["last_report"] = poll_nandatown_groups()
        except Exception as exc:  # noqa: BLE001 - the loop outlives any one pass
            nandatown_poll_status["last_report"] = {
                "error": "nandatown_poll_failed", "detail": str(exc),
                "finished_at": now_iso()}
        _nandatown_poll_stop.wait(interval)


def start_nandatown_poller() -> bool:
    """Start the inbound receive loop once per process.

    Disabled - quietly, fail-closed - when the town transport env is
    absent (no join token) or ``UYP_NANDATOWN_POLL_SECONDS`` is set to
    zero or below.  Never raises; returns whether a loop was started.
    """
    global _nandatown_poll_thread
    interval = nandatown_poll_seconds()
    if interval <= 0.0 or not town_transport_configured():
        return False
    with _nandatown_poll_lock:
        if _nandatown_poll_thread is not None and _nandatown_poll_thread.is_alive():
            return False
        _nandatown_poll_stop.clear()
        _nandatown_poll_thread = threading.Thread(
            target=_nandatown_poll_loop, args=(interval,),
            name="uyp-nandatown-poll", daemon=True)
        _nandatown_poll_thread.start()
    nandatown_poll_status.update({"started": True, "interval_seconds": interval})
    return True


def manifest_source_epoch(root: str, *, context: dict | None = None,
                          registry_connectors: list[dict] | None = None,
                          jobs: list[dict] | None = None) -> str | None:
    """The true manifest/source epoch (a content digest) for an authorized project.

    ``sourceEpoch`` in the Studio contracts is the Connector manifest epoch
    published by the index pipeline - NEVER a wall-clock timestamp (freshness
    audit 2026-10-18: project_snapshot used to copy max(analyzed_at) into it,
    which made two different notions share one name).  Origin preference:
    the durable connector-registry record for ``connector:{root}``, then the
    newest persisted index job that published one.  None when neither is
    known (deployments without a paired connector) - callers must then omit
    or null the field rather than substitute a timestamp.
    """
    source_id = f"connector:{root}"
    connectors = registry_connectors if registry_connectors is not None else connector_registry_projection(context)
    for record in connectors:
        if record.get("connectorId") != source_id:
            continue
        epoch = str(record.get("sourceEpoch") or "").strip()
        if epoch:
            return epoch
    job_list = jobs if jobs is not None else load_persisted_index_jobs(root, context)
    for job in sorted(job_list, key=lambda value: str(value.get("updatedAt", "")), reverse=True):
        epoch = str(job.get("sourceEpoch") or "").strip()
        if epoch:
            return epoch
    return None


def project_snapshot(project_id: str | None = None, *, context: dict | None = None) -> dict:
    """Build a snapshot from an already resolved HomeHub context.

    Direct callers that omit ``context`` retain the local CLI/test projection.
    HTTP Studio handlers resolve the caller first and pass the request-scoped
    context here, so a process-level fallback can never cross user sessions.
    """
    if context is None:
        context = load_access_context()
    all_groups = grouped_items()
    if context:
        visible: dict[str, list[dict]] = {}
        for name, values in all_groups.items():
            permitted = [item for item in values if scope_allows(context, item)]
            if permitted:
                visible[name] = permitted
        groups = visible
    else:
        # Do not reveal project names, paths, counts, or evidence before
        # HomeHub supplies an AccessContext projection.
        groups = {}
    requested_root = project_id.removeprefix("project:") if project_id else None
    if requested_root:
        # An explicit project selection must never silently fall back to a
        # different authorized project.  That would make a stale/forged UI
        # project id display another project's knowledge.
        root = requested_root if requested_root in groups else "No authorized project"
    else:
        root = next(iter(groups), "Access context pending" if context is None else "No authorized project")
    items = groups.get(root, [])
    connector = configured_connector_status()
    updated = max((str(item.get("analyzed_at", "")) for item in items), default=now_iso())
    visible_project = context is not None and root not in {"Access context pending", "No authorized project"}
    ua_graph = load_ua_graph(root) if visible_project else None
    graph_project = ua_graph.get("project", {}) if ua_graph else {}
    graph_nodes = ua_graph.get("nodes", []) if ua_graph else []
    graph_edges = ua_graph.get("edges", []) if ua_graph else []
    graph_layers = ua_graph.get("layers", []) if ua_graph else []
    graph_files = sum(1 for node in graph_nodes if node.get("type") == "file")
    source_id = f"connector:{root}" if visible_project else "source:pending"
    project_key = f"project:{root}" if visible_project else "project:unavailable"
    enriched = sum(1 for item in items if item.get("derived", {}).get("purpose"))
    layers = len(graph_layers) if ua_graph else (len({item.get("verdict", "unknown") for item in items}) if items else 0)
    # Studio evidence panel entries are now PROJECTED from the same
    # contract KnowledgeEvidence records the search API returns (one
    # producer, one truth); the v3.2 entry shape is preserved so the
    # Studio contract itself does not move.
    snapshot_items = sorted(items, key=lambda value: value.get("file", ""))[:200]
    # Reuse the graph already loaded for this snapshot instead of a
    # second 25 MB parse; fall back to the cached loader when absent.
    snapshot_graph = (knowledge_evidence.GraphIndex(ua_graph) if ua_graph
                      else (_graph_index_for(root) if visible_project else None))
    evidence_records = knowledge_evidence.build_evidence(
        [{"file": item.get("file")} for item in snapshot_items],
        snapshot_items,
        gate=lambda item: scope_allows(context, item) if context else False,
        default_root=root if visible_project else None,
        graph_provider=(lambda project_root, _index=snapshot_graph:
                        _index if _index and project_root == root else None),
    )
    anchor_by_file = {str(item.get("file") or ""): item.get("anchor_top") for item in snapshot_items}
    evidence = []
    for index, record in enumerate(evidence_records):
        record_path = str(record.get("locator") or "").split("#", 1)[0]
        evidence.append(knowledge_evidence.studio_entry_from_evidence(
            record,
            evidence_id=f"knowledge:{root}:{index}",
            project_key=project_key,
            # v3.2 anchored-enrichment primary actor; the Studio evidence badge
            # (studio-contracts.ts EvidenceRef.anchorTop) renders from this.
            anchor_top=anchor_by_file.get(record_path),
            producing_jarvis=context.get("jarvisNodeId") if context else None,
        ))
    state = "current" if items and connector["state"] == "current" else "partial" if items else "unsupported"
    reason = None if state == "current" else "Knowledge output exists, but connector freshness or HomeHub context is not attached."
    source = {"sourceId": source_id, "label": root if visible_project else "Authorized source pending", "kind": "local", "state": connector["state"] if context else "unsupported", "detail": connector["detail"] if context else "HomeHub AccessContext required before source metadata is published"}
    node_id = (context or {}).get("jarvisNodeId") or "agent-node-pending"
    node_pairing = "paired" if context else "discovered"
    node_transport = os.environ.get("UYP_AGENT_TRANSPORT", "unknown") if context else "unknown"
    connector_projection = {"connectorId": source_id, "nodeId": node_id, "kind": "local", "label": root if visible_project else "Connector metadata pending", "state": connector["state"], "manifestState": "ready" if items else "pending", "sourceIds": [source_id] if visible_project else []}
    registry_connectors = connector_registry_projection(context)
    connector_ids = {item["connectorId"] for item in registry_connectors}
    if connector_projection["connectorId"] not in connector_ids:
        registry_connectors.append(connector_projection)
    registry_nodes = registry_agent_nodes(context)
    persisted_jobs = load_persisted_index_jobs(root if visible_project else None, context)
    # sourceEpoch is the manifest content epoch (or null when unknown);
    # analyzedAt/updatedAt carry the timestamp semantics it used to borrow.
    source_epoch = (manifest_source_epoch(root, context=context,
                                          registry_connectors=registry_connectors, jobs=persisted_jobs)
                    if visible_project else None)
    snapshot = {
        "project": {
            "projectId": project_key, "sourceId": source_id, "name": root if visible_project else "Project scope unavailable",
            "description": f"{len(items)} authorized KnowledgeItems with a vendored UA structure graph." if visible_project and ua_graph else (f"{len(items)} authorized KnowledgeItems from the Agent Box output store." if visible_project else "HomeHub has not supplied a project scope to Studio."),
            "languages": graph_project.get("languages", []) if visible_project else [], "frameworks": graph_project.get("frameworks", []) if visible_project else [],
            "counts": {"files": graph_files or len(items), "nodes": len(graph_nodes) or len(items), "relations": len(graph_edges), "layers": layers},
            "entryPoints": [item.get("file") for item in items[:4] if item.get("file")] if visible_project else [],
            "knowledgeVersion": updated, "analyzedAt": updated, "sourceEpoch": source_epoch,
            "freshness": state, "updatedAt": updated,
            "schemaVersion": graph_project.get("graphVersion") or ua_graph.get("version") if ua_graph else None,
            "visibility": "private" if visible_project else None,
            "grantEpoch": context.get("grantEpoch") if context else None,
            "policyDigest": context.get("policyDigest") if context else None,
            "auditId": context.get("auditId") if context else None,
        },
        "health": {
            "state": state, "knowledgeVersion": updated, "sourceEpoch": source_epoch,
            "coverage": {"filesIndexed": len(items)}, "lastSuccessfulAt": updated,
            "connectorStatus": connector["state"], "reason": reason,
        },
        "evidence": evidence, "evidenceOrigin": "service" if items else "graph-fallback",
        "jobs": persisted_jobs,
        "sources": [source],
        "agentNodes": [{"nodeId": node_id, "label": os.environ.get("UYP_AGENT_LABEL", "Jetson Agent Box") if context else "Jetson Agent Box · identity pending", "transport": node_transport, "pairing": node_pairing, "lastSeen": updated if items else None, "capabilities": ["Incremental index", "Knowledge search", "Evidence citations"], "connectorIds": [source_id]}],
        "connectors": registry_connectors,
        "peers": load_nandatown_peers(),
    }
    # Keep the locally derived project node and durable registry nodes visible
    # as separate projections.  A registry record never overrides HomeHub's
    # node identity or creates an authorization decision.
    known_nodes = {entry["nodeId"] for entry in snapshot["agentNodes"]}
    for entry in registry_nodes:
        if entry["nodeId"] not in known_nodes:
            snapshot["agentNodes"].append(entry)
    if visible_project and ua_graph:
        snapshot["graph"] = {
            "version": ua_graph.get("version"),
            "project": graph_project,
            "nodes": graph_nodes[:500],
            "edges": graph_edges[:1000],
            "layers": graph_layers,
            "tour": ua_graph.get("tour", []),
        }
    if context:
        snapshot["access"] = context
    return snapshot


def context_scope(context: dict | None) -> knowledge_core.ResolvedScope:
    """A validated HomeHub projection -> the shared ResolvedScope.

    The scope PARSING lives in the shared Knowledge Core now (one
    implementation for :8787 and :8790); this helper only maps the
    context's already-validated fields onto it.
    """
    if context is None:
        return knowledge_core.scope_from_grants([], [], 0)
    return knowledge_core.scope_from_grants(
        [str(value) for value in context.get("projectScopes", [])],
        [str(value) for value in context.get("sourceScopes", [])],
        _grant_epoch_of(context),
    )


def _grant_epoch_of(context: dict) -> int:
    """The context's grantEpoch (a string) as an int; 0 when opaque."""
    try:
        return int(str(context.get("grantEpoch") or "").strip())
    except ValueError:
        return 0


def scope_allows(context: dict, item: dict) -> bool:
    # Scope parsing moved into the shared Knowledge Core; the semantics
    # (project/source capability sets, ``*`` widening one dimension) are
    # unchanged.  Source scopes stay capability identifiers, never
    # arbitrary paths - the Connector remains the only component allowed
    # to resolve a path.
    return knowledge_core.scope_allows_item(context_scope(context), item)


def scoped_items(context: dict | None, project_id: str | None = None) -> list[dict]:
    """Apply the search scope filter; fail closed without an AccessContext.

    ``/api/knowledge/search`` and ``/api/health`` must never disagree about
    how much knowledge is visible, so both go through this one helper
    (now the Knowledge Core's ``scoped_items_for_scope``).  A missing,
    revoked, or narrowed context yields the same empty set here that
    search would query (P7 acceptance finding 1).  When a caller supplies
    a project id, the result is narrowed to that project after HomeHub
    scope filtering.  The project id is a selector, never an
    authorization grant.
    """
    if context is None:
        return []
    return knowledge_core.scoped_items_for_scope(context_scope(context), project_id)


def search_citations(result_sources: list | None, scoped: list[dict], context: dict) -> list[dict]:
    """Project search sources into the stable AGENTFLOW section-5 shape.

    The HTTP Query API is the authority for browser and HTTP-MCP callers, so
    citation projection belongs here rather than only in the direct MCP
    adapter.  ``scoped`` has already passed the HomeHub project/source filter;
    this function only joins returned source paths back to those authorized
    items and never widens the result set.

    Since the KnowledgeEvidence producer landed, citations are DERIVED
    from the same contract records (never rebuilt ad hoc from items):
    the join happens once, in knowledge_evidence.build_evidence.
    """
    evidence = knowledge_evidence.build_evidence(
        result_sources, scoped, gate=lambda item: scope_allows(context, item))
    return knowledge_evidence.citations_from_evidence(evidence, context, result_sources)


def health_payload() -> dict:
    """Health card whose knowledge count is scope-filtered like search.

    No AccessContext means no counts: the payload reports zero items and
    ``accessContext: false`` instead of leaking the unscoped output total.
    """
    context = load_access_context()
    return {
        "ok": True,
        "service": "uyp-query-api",
        "version": VERSION,
        "knowledgeItems": len(scoped_items(context)),
        "accessContext": bool(context),
        "connector": configured_connector_status(),
        "connectorRegistry": registry_health(),
        "indexJobs": index_jobs_health(context),
    }


# ---- Groups (P10) HTTP surface -------------------------------------------
#
# The groups engine (groups.py) owns the group -> knowledge-view model; these
# helpers only adapt it to HTTP.  Authority stays where it was: HomeHub for
# identity/policy/revocation, the owner-authored registry for membership and
# views, and scoped_retrieval as the single fail-closed retrieval pipeline.
# HomeHub group-issuance is not deployed yet, so a group search without a
# HomeHub-issued projection builds one from the registry record plus the
# requesting member; scoped_retrieval still validates it and clamps it back
# to the registered view, so the local bridge can never widen access.

GROUP_CONTEXT_TTL = timedelta(minutes=10)
GROUP_LOCAL_POLICY_DIGEST = "sha256:uyp-local-registry"


def _touch_interactive_lock() -> None:
    """Voice-chain preemptive flag (语音>查询>索引, 2026-10-10).

    Group search sets the same /tmp/uyp_interactive.lock knowledge_search
    sets before synthesis, so an indexing worker holding the qwen slots
    yields to a group answer exactly like it yields to a knowledge search.

    The lock is a yield HINT, never a gate (2026-10-10 live incident: the
    satellite yield watcher runs as root and created the lock root-owned,
    so this open() raised PermissionError and killed the whole response
    with a bare connection close).  A failed touch degrades to a
    best-effort mtime bump and never takes the answer down with it.
    """
    try:
        with open(INTERACTIVE_LOCK, "w") as fh:
            fh.write(str(time.time()))
    except OSError:
        try:
            os.utime(INTERACTIVE_LOCK, None)
        except OSError:
            pass


def _member_key(value) -> str:
    """One canonical form for member ids: bare or ``member:``-prefixed."""
    text = str(value or "").strip()
    return text[len("member:"):] if text.startswith("member:") else text


def _same_member(one, other) -> bool:
    left, right = _member_key(one), _member_key(other)
    return bool(left) and left == right


def group_registry() -> GroupRegistry:
    """The durable registry (state/groups.json); path resolved per call."""
    return GroupRegistry()


def configured_owner_member() -> str:
    """The deployment's owner pin for the owner-sees-all group listing.

    Unset by default: without an explicit owner pin every caller sees only
    the groups they own or belong to - never the whole registry.
    """
    return str(os.environ.get("UYP_OWNER_MEMBER") or "").strip()


def caller_context(headers):
    """Resolve the calling principal for group management endpoints.

    Same tiers as search minus the loopback voice tier: a caller-presented
    Bearer resolves that caller, otherwise today's service-level env/file
    context.  Group membership itself is checked against the registry (or a
    HomeHub group context), never against the member AccessContext tier.
    """
    return load_request_context(headers, loopback_voice=False)[0]


def local_group_context(record: dict, member_id: str, jarvis_node_id=None) -> dict:
    """Construct the per-request group context from a registry record.

    The bridge for the pre-HomeHub-issuance era (docs/GROUPS_DESIGN.md
    "What waits"): the owner-authored record plus the requesting member are
    projected into the same shape HomeHub will issue, then handed to
    scoped_retrieval, which re-validates it, checks registry membership,
    and intersects it with the registered view.
    """
    return {
        "group_id": record["group_id"],
        "member_id": member_id,
        "jarvis_node_id": str(jarvis_node_id or "").strip() or "uyp-local",
        "project_ids": list(record["knowledge_view"]["project_ids"]),
        "source_ids": list(record["knowledge_view"]["source_ids"]),
        "grant_epoch": record["grant_epoch"],
        "policy_digest": GROUP_LOCAL_POLICY_DIGEST,
        "expires_at": (datetime.now(timezone.utc) + GROUP_CONTEXT_TTL).isoformat().replace("+00:00", "Z"),
        "audit_id": f"uyp-local-{uuid.uuid4().hex[:12]}",
    }


# ---- Projects / analyzed folders (Studio v2, docs/STUDIO_V2.md §6.2) -------
#
# The /api/projects* endpoints accept ONLY a caller credential: (a) the
# caller's HomeHub Companion bearer, or (b) on a loopback bind, the voice /
# agent-runtime tier's X-Agent-Member (resolved with this service's own
# HomeHub token).  There is no service-level fallback: no credential -> 401,
# unresolvable bearer -> 401, member without grants -> 403, HomeHub transport
# unconfigured -> 503.  Projects are then filtered by the context's project
# and source scopes; the owner gets grants from the companion proxy.

_ROLE_CACHE: dict = {}
_ROLE_CACHE_LOCK = threading.Lock()
MAX_QUESTION = 2000
# The Studio graph view is a navigational projection, not a source export.
# Keep the payload bounded even when a project has a very large UA graph.
MAX_GRAPH_NODES = 500
MAX_GRAPH_EDGES = 1000
MAX_GRAPH_LAYERS = 200
MAX_GRAPH_TOUR = 100


def _graph_public_value(value, *, content_allowed: bool = False):
    """Strip source-bearing fields from nested UA metadata.

    Understand Anything's knowledge nodes may carry ``knowledgeMeta.content``
    for article/document nodes.  That is source material, so the Studio graph
    endpoint only exposes the structural/semantic fields needed to draw and
    explain the graph.  This helper intentionally copies allow-listed fields
    instead of returning the graph object from disk verbatim.
    """
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == "content" and not content_allowed:
            continue
        if isinstance(item, dict):
            result[key] = _graph_public_value(item, content_allowed=content_allowed)
        elif isinstance(item, list):
            result[key] = [
                _graph_public_value(entry, content_allowed=content_allowed)
                if isinstance(entry, dict) else entry
                for entry in item
            ]
        else:
            result[key] = item
    return result


def public_project_graph(context: dict, project_id: str) -> dict | None:
    """Return a caller-scoped, bounded UA graph projection.

    The registry is derived metadata; authorization still comes from the
    caller's HomeHub AccessContext via ``project_digest._resolve``.  No source
    bytes are read here and the graph file is never returned verbatim.
    """
    resolved = project_digest._resolve(context, project_id)
    if resolved is None:
        return None
    _, record, _, _ = resolved
    output_dir = str(record.get("output_dir") or record.get("project_id") or "")
    graph = project_registry.load_graph(output_dir)
    if not isinstance(graph, dict):
        return None

    raw_nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    raw_edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    raw_layers = [layer for layer in graph.get("layers", []) if isinstance(layer, dict)]
    raw_tour = [step for step in graph.get("tour", []) if isinstance(step, dict)]

    node_keys = {
        "id", "type", "name", "filePath", "lineRange", "summary", "tags",
        "complexity", "languageNotes", "domainMeta", "knowledgeMeta", "figmaMeta",
    }
    edge_keys = {"source", "target", "type", "direction", "description", "weight"}
    layer_keys = {"id", "name", "description", "nodeIds"}
    tour_keys = {"order", "title", "description", "nodeIds", "languageLesson"}

    def project_meta(value):
        if not isinstance(value, dict):
            return {}
        return _graph_public_value({key: value[key] for key in (
            "name", "languages", "frameworks", "description", "analyzedAt", "gitCommitHash"
        ) if key in value})

    def pick(value, keys):
        return _graph_public_value({key: value[key] for key in keys if key in value})

    return {
        "projectId": project_id,
        "version": graph.get("version"),
        "kind": graph.get("kind"),
        "project": project_meta(graph.get("project")),
        "nodes": [pick(node, node_keys) for node in raw_nodes[:MAX_GRAPH_NODES]],
        "edges": [pick(edge, edge_keys) for edge in raw_edges[:MAX_GRAPH_EDGES]],
        "layers": [pick(layer, layer_keys) for layer in raw_layers[:MAX_GRAPH_LAYERS]],
        "tour": [pick(step, tour_keys) for step in raw_tour[:MAX_GRAPH_TOUR]],
        "counts": {"nodes": len(raw_nodes), "edges": len(raw_edges),
                   "layers": len(raw_layers), "tour": len(raw_tour)},
        "truncated": {"nodes": len(raw_nodes) > MAX_GRAPH_NODES,
                      "edges": len(raw_edges) > MAX_GRAPH_EDGES,
                      "layers": len(raw_layers) > MAX_GRAPH_LAYERS,
                      "tour": len(raw_tour) > MAX_GRAPH_TOUR},
    }


def resolve_project_caller(headers, *, loopback_voice: bool = False):
    """Return ``(caller, error)``; ``error`` is ``(status, code, message)``."""
    url = os.environ.get("UYP_HOMEHUB_ACCESS_CONTEXT_URL")
    auth = str(headers.get("Authorization") or "")
    if auth[:7].lower() == "bearer " and auth[7:].strip():
        if not url:
            return None, (503, "access_context_unavailable", "HomeHub access-context transport is not configured.")
        bearer = auth[7:].strip()
        context = load_homehub_context_for_token(bearer)
        if context is None:
            return None, (401, "invalid_credentials", "HomeHub did not accept the presented bearer.")
        return {"context": context, "principal": str(context["principalId"]), "bearer": bearer, "tier": "bearer"}, None
    member = str(headers.get("X-Agent-Member") or "").strip()
    if member:
        if not loopback_voice:
            return None, (401, "credentials_required", "X-Agent-Member is accepted only on a loopback bind.")
        if not url or not os.environ.get("UYP_HOMEHUB_TOKEN_FILE"):
            return None, (503, "access_context_unavailable", "HomeHub member resolution is not configured on this Agent Box.")
        context = load_homehub_context_for_member(member)
        if context is None:
            return None, (403, "member_access_denied", "HomeHub has no active project grant for this member.")
        return {"context": context, "principal": member, "bearer": None, "tier": "member"}, None
    return None, (401, "credentials_required", "A HomeHub bearer (or loopback X-Agent-Member) is required.")


def _homehub_members_url() -> str | None:
    explicit = os.environ.get("UYP_HOMEHUB_MEMBERS_URL")
    if explicit:
        return explicit
    base = os.environ.get("UYP_HOMEHUB_ACCESS_CONTEXT_URL")
    if not base:
        return None
    parts = urlparse(base)
    return f"{parts.scheme}://{parts.netloc}/api/members" if parts.scheme and parts.netloc else None


def resolve_member_role(caller: dict) -> str | None:
    """The caller's HomeHub role (owner/member/guest), or None if unknown.

    HomeHub is the authority: an explicit ``role`` on the projection wins,
    then the deployment owner pin (UYP_OWNER_MEMBER), then HomeHub's members
    list read with the caller's own bearer (or, for the loopback member
    tier, this service's HomeHub token).  Unknown -> None (fail closed).
    """
    context = caller.get("context") or {}
    if isinstance(context.get("role"), str) and context["role"].strip():
        return context["role"].strip()
    principal = _member_key(caller.get("principal"))
    if not principal:
        return None
    if _same_member(principal, configured_owner_member()):
        return "owner"
    url = _homehub_members_url()
    token = caller.get("bearer")
    if not token:
        token_file = os.environ.get("UYP_HOMEHUB_TOKEN_FILE")
        try:
            with open(os.path.expanduser(token_file or ""), encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError:
            token = None
    if not url or not token:
        return None
    key = (principal, hashlib.sha256(token.encode("utf-8")).hexdigest()[:16])
    now = time.monotonic()
    with _ROLE_CACHE_LOCK:
        cached = _ROLE_CACHE.get(key)
        if cached and now < cached[0]:
            return cached[1]
    role = None
    try:
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=3) as response:
            value = json.loads(response.read())
        rows = value.get("members") if isinstance(value, dict) else value
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and _same_member(row.get("member_id"), principal):
                role = str(row.get("role") or "").strip() or None
                break
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None
    with _ROLE_CACHE_LOCK:
        _ROLE_CACHE[key] = (now + 60.0, role)
    return role


def _parse_window_bound(value, default: float) -> float | None:
    if value is None or str(value).strip() == "":
        return default
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


class QueryHandler(BaseHTTPRequestHandler):
    def _headers(self, audit: str) -> None:
        allowed = [o.strip() for o in os.environ.get(
            "UYP_CORS_ORIGIN",
            "http://127.0.0.1:4173,http://localhost:4173").split(",") if o.strip()]
        origin = self.headers.get("Origin")
        # ACAO carries exactly ONE origin: echo the request's origin when it
        # is allowlisted. Sending a static first-of-list broke every page
        # opened as localhost:4173 (2026-10-11: Studio fell back to the demo
        # graph because every live fetch was CORS-blocked).
        self.send_header("Access-Control-Allow-Origin",
                         origin if origin in allowed else allowed[0])
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Agent-Member, X-Group-Context")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("X-UYP-Audit-Id", audit)

    def json_response(self, value: dict, status: int = 200, audit: str | None = None) -> None:
        audit = audit or str(uuid.uuid4())
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._headers(audit)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        audit = str(uuid.uuid4())
        self.send_response(204)
        self._headers(audit)
        self.end_headers()

    def do_GET(self) -> None:
        audit = str(uuid.uuid4())
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            self.json_response(health_payload(), audit=audit)
            return
        if parsed.path == "/api/studio/snapshot":
            caller = self._project_caller(audit)
            if caller is None:
                return
            self.json_response(project_snapshot((query.get("projectId") or [None])[0], context=caller["context"]), audit=audit)
            return
        if parsed.path == "/api/knowledge-graph":
            caller = self._project_caller(audit)
            if caller is None:
                return
            snapshot = project_snapshot((query.get("projectId") or [None])[0], context=caller["context"])
            graph = snapshot.get("graph")
            if graph is None:
                self.json_response({"ok": False, "error": "knowledge_graph_unavailable"}, 404, audit)
            else:
                self.json_response(graph, audit=audit)
            return
        if parsed.path == "/api/sources":
            caller = self._project_caller(audit)
            if caller is None:
                return
            self.json_response({"sources": project_snapshot((query.get("projectId") or [None])[0], context=caller["context"])["sources"]}, audit=audit)
            return
        if parsed.path == "/api/connectors":
            caller = self._project_caller(audit)
            if caller is None:
                return
            context = caller["context"]
            self.json_response({
                "connectors": connector_registry_projection(context),
                "registry": registry_health(),
                "accessContext": bool(context),
                "metadataOnly": context is None,
            }, audit=audit)
            return
        if parsed.path == "/api/nandatown/peers":
            peers, error = nandatown_peers_projection()
            if error is None:
                self.json_response({"peers": peers, "metadataOnly": False, "source": "town"}, audit=audit)
            else:
                # Honest refusal: the town directory could not be read, so no
                # peers are served and no metadata-only success is pretended.
                self.json_response({
                    "ok": False,
                    "error": error["code"],
                    "peers": [],
                    "metadataOnly": True,
                    "message": f"NandaTown directory unavailable: {error['message']}",
                }, 503, audit)
            return
        if parsed.path == "/api/groups":
            # Groups listing: the deployment's owner pin (UYP_OWNER_MEMBER)
            # sees the whole registry, every other caller sees only the
            # groups they own or belong to.  No context, no listing.
            context = caller_context(self.headers)
            if context is None:
                self.json_response({"ok": False, "error": "access_context_unavailable", "message": "HomeHub must provide an AccessContext before groups can be listed."}, 503, audit)
                return
            principal = str(context.get("principalId") or "")
            records = group_registry().load()["groups"]
            owner_view = _same_member(principal, configured_owner_member())
            if not owner_view:
                records = [record for record in records if group_allows_member(record, principal)]
            self.json_response({"ok": True, "groups": records, "ownerView": owner_view}, audit=audit)
            return
        parts = parsed.path.split("/")
        if (len(parts) == 5 and parts[0] == "" and parts[1] == "api"
                and parts[2] == "groups" and parts[3] and parts[4] == "messages"):
            self._get_group_messages(parts[3], query, audit)
            return
        if parsed.path == "/api/projects" or parsed.path.startswith("/api/projects/"):
            self._get_projects(parsed.path, query, audit)
            return
        if parsed.path == "/api/index/jobs":
            caller = self._project_caller(audit)
            if caller is None:
                return
            context = caller["context"]
            project = (query.get("projectId") or [None])[0]
            self.json_response({"jobs": load_persisted_index_jobs(project, context), "accessContext": bool(context)}, audit=audit)
            return
        if parsed.path.startswith("/api/knowledge/evidence/"):
            caller = self._project_caller(audit)
            if caller is None:
                return
            evidence_id = parsed.path.rsplit("/", 1)[-1]
            evidence = next((item for item in project_snapshot((query.get("projectId") or [None])[0], context=caller["context"])["evidence"] if item["evidenceId"] == evidence_id), None)
            if evidence is None:
                self.json_response({"ok": False, "error": "evidence_not_found"}, 404, audit)
            else:
                self.json_response(evidence, audit=audit)
            return
        self.json_response({"ok": False, "error": "not_found"}, 404, audit)

    def do_POST(self) -> None:
        audit = str(uuid.uuid4())
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("body_too_large")
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self.json_response({"ok": False, "error": "invalid_json"}, 400, audit)
            return
        if parsed.path == "/api/knowledge/search":
            self._post_knowledge_search(payload, audit)
            return
        if parsed.path == "/api/ua/query":
            _ua_respond(self, payload, audit)
            return
        if parsed.path == "/api/groups":
            self._post_group_create(payload, audit)
            return
        if parsed.path == "/api/projects" or parsed.path.startswith("/api/projects/"):
            self._post_projects(parsed.path, payload, audit)
            return
        parts = parsed.path.split("/")
        if (len(parts) == 5 and parts[0] == "" and parts[1] == "api"
                and parts[2] == "groups" and parts[3] and parts[4] == "search"):
            self._post_group_search(parts[3], payload, audit)
            return
        if (len(parts) == 5 and parts[0] == "" and parts[1] == "api"
                and parts[2] == "groups" and parts[3] and parts[4] == "messages"):
            self._post_group_message(parts[3], payload, audit)
            return
        if (len(parts) == 5 and parts[0] == "" and parts[1] == "api"
                and parts[2] == "groups" and parts[3] and parts[4] == "device-actions"):
            self._post_group_device_action(parts[3], payload, audit)
            return
        self.json_response({"ok": False, "error": "not_found"}, 404, audit)

    def _post_knowledge_search(self, payload: dict, audit: str) -> None:
        # Voice handshake (2026-10-10), per-member pass: per-request
        # resolution - caller Bearer, loopback X-Agent-Member voice mode,
        # or today's service-level env/file path.  The loopback guard flag
        # is set by main() only for a loopback bind (fail closed
        # otherwise).  A voice member whose member-scoped resolution was
        # denied gets an honest 403 in their name - never the box context,
        # never a generic 503 that hides WHO was denied.
        context, denied_member = load_request_context(
            self.headers,
            loopback_voice=getattr(self.server, "loopback_voice", False),
        )
        if context is None:
            if denied_member:
                self.json_response({
                    "ok": False,
                    "error": "member_access_denied",
                    "message": "HomeHub has no active project grant for this member; voice search is denied for them.",
                }, 403, audit)
                return
            self.json_response({"ok": False, "error": "access_context_unavailable", "message": "HomeHub must provide an AccessContext before project knowledge can be searched."}, 503, audit)
            return
        question = str(payload.get("query", "")).strip()
        if not question:
            self.json_response({"ok": False, "error": "query_required"}, 400, audit)
            return
        # Shared Knowledge Core (2026-10 extraction): this handler is now a
        # thin adapter - construct the request from the ALREADY VALIDATED
        # HomeHub projection, run the one authorized_search pipeline that
        # :8790 also runs, and project the result back into this API's
        # response shape.  The request-level project selector narrows the
        # already validated context inside the core (never a grant, never a
        # widening).  composer/will_synthesize are passed as late-bound
        # module references so the seam the tests patch keeps working.
        request = knowledge_core.KnowledgeQueryRequest(
            request_id=audit,
            session_id=str(context.get("sessionId") or ""),
            principal_id=str(context.get("principalId") or ""),
            auth_level=str(context.get("authLevel") or "second_factor_verified"),
            grants=[str(value) for value in context.get("projectScopes", [])],
            grant_epoch=_grant_epoch_of(context),
            source_scope=[str(value) for value in context.get("sourceScopes", [])],
            query=question,
            project=payload.get("projectId") if payload.get("projectId") else None,
        )
        # Slow-answer hint (root-cause fix, 2026-10-10): lexical retrieval is
        # instant, but a retrieval HIT means qwen synthesis - 5-15s plus
        # queue wait when the GPU is busy indexing.  For hinted-slow answers
        # the response HEADERS (X-UYP-Slow-Hint) are sent and flushed BEFORE
        # the synthesis runs (the core fires before_synthesis at exactly
        # that point), and the body is framed by connection close instead
        # of Content-Length, so a streaming voice caller can speak "Let me
        # look that up..." while the answer is still computed.  A miss
        # (instant canonical sentence) keeps the normal framing.
        streamed: list[bool] = []

        def _stream_slow_headers() -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._headers(audit)
            self.send_header("X-UYP-Slow-Hint", "true")
            self.end_headers()
            self.wfile.flush()
            streamed.append(True)

        result = knowledge_core.authorized_search(
            request,
            composer=lambda question_, items: search_answer(question_, items),
            will_synthesize=lambda question_, items: search_will_synthesize(question_, items),
            graph_provider=(_graph_index_for
                            if os.environ.get("UYP_EVIDENCE_GRAPH_REFS", "1") != "0"
                            else None),
            before_synthesis=_stream_slow_headers,
        )
        # KnowledgeEvidence producer (2026-10-18), now inside the core: the
        # retrieval join happens ONCE - legacy sources[], AGENTFLOW
        # citations[], and the contract evidence[] all derive from the same
        # records (single source of truth).
        sources = []
        for summary in result.sources:
            entry = {"file": summary.file}
            if summary.match is not None:
                entry["match"] = summary.match
            if summary.ts is not None:
                entry["ts"] = summary.ts
            sources.append(entry)
        body = {
            "answer": result.answer,
            "sources": sources,
            "confidence": result.extras.get("confidence"),
            "index_as_of": result.index_as_of,
            "freshness": result.freshness,
            "ok": True,
            "auditId": audit,
            "projectId": payload.get("projectId"),
            "access": {"grantEpoch": context.get("grantEpoch"), "expiresAt": context.get("expiresAt")},
            "citations": knowledge_evidence.citations_from_evidence(
                result.evidence, context, sources),
            "evidence": result.evidence,
        }
        if streamed:
            self.wfile.write(json.dumps(body, ensure_ascii=False).encode("utf-8"))
            self.wfile.flush()
            return
        self.json_response(body, audit=audit)

    # ---- Projects (Studio v2 §6.2) ------------------------------------------

    def _project_caller(self, audit: str):
        caller, error = resolve_project_caller(
            self.headers, loopback_voice=getattr(self.server, "loopback_voice", False))
        if error is not None:
            status, code, message = error
            self.json_response({"ok": False, "error": code, "message": message}, status, audit)
            return None
        return caller

    def _project_not_found(self, audit: str) -> None:
        # Absent and not-authorized are indistinguishable to the caller.
        self.json_response({"ok": False, "error": "project_not_found", "message": "No such project in your authorized scope."}, 404, audit)

    def _get_projects(self, path: str, query: dict, audit: str) -> None:
        caller = self._project_caller(audit)
        if caller is None:
            return
        context = caller["context"]
        parts = [unquote(part) for part in path.split("/")[3:] if part != ""]
        if not parts:
            self.json_response(project_digest.list_projects(context), audit=audit)
            return
        if parts == ["ids"]:
            if resolve_member_role(caller) != "owner":
                self.json_response({"ok": False, "error": "owner_session_required", "message": "Only the owner can list every registered project."}, 403, audit)
                return
            doc = project_registry.sync_registry(jobs_by_project=project_jobs.jobs_by_project())
            self.json_response({"project_ids": sorted(r["project_id"] for r in doc["projects"])}, audit=audit)
            return
        if len(parts) == 2 and parts[0] == "jobs":
            state = project_jobs.job_state(parts[1])
            record = project_registry.ProjectRegistry().get(state["project_id"]) if state else None
            allowed = record is not None and (project_registry.visible(context, record)
                                              or resolve_member_role(caller) == "owner")
            if state is None or not allowed:
                self.json_response({"ok": False, "error": "job_not_found"}, 404, audit)
                return
            self.json_response(project_jobs.public_job(state), audit=audit)
            return
        if len(parts) == 1:
            result = project_digest.digest(context, parts[0])
            if result is None:
                self._project_not_found(audit)
                return
            self.json_response(result, audit=audit)
            return
        if len(parts) == 2 and parts[1] == "graph":
            # Full UA graph projection is caller-scoped.  Do not reuse the
            # service-level /api/knowledge-graph route here: browser callers
            # must be resolved through their own HomeHub bearer/context.
            result = public_project_graph(context, parts[0])
            if result is None:
                self._project_not_found(audit)
                return
            self.json_response(result, audit=audit)
            return
        if len(parts) == 2 and parts[1] == "activity":
            now = time.time()
            until = _parse_window_bound((query.get("until") or [None])[0], now)
            since = _parse_window_bound((query.get("since") or [None])[0], (until or now) - 7 * 86400)
            if since is None or until is None or since > until:
                self.json_response({"ok": False, "error": "invalid_window", "message": "since/until must be ISO-8601 and since <= until."}, 400, audit)
                return
            result = project_digest.activity(context, parts[0], since, until)
            if result is None:
                self._project_not_found(audit)
                return
            self.json_response(result, audit=audit)
            return
        self.json_response({"ok": False, "error": "not_found"}, 404, audit)

    def _post_projects(self, path: str, payload: dict, audit: str) -> None:
        caller = self._project_caller(audit)
        if caller is None:
            return
        parts = [unquote(part) for part in path.split("/")[3:] if part != ""]
        if parts == ["analyze"]:
            if resolve_member_role(caller) != "owner":
                self.json_response({"ok": False, "error": "owner_session_required", "message": "Only the owner can start a folder analysis."}, 403, audit)
                return
            try:
                result = project_jobs.create_analyze_job(
                    payload.get("path"), payload.get("device_id"), actor=_member_key(caller["principal"]))
            except project_jobs.AnalyzeError as exc:
                self.json_response({"ok": False, "error": exc.code, "message": exc.message}, exc.status, audit)
                return
            result.pop("_existing", None)
            self.json_response(result, 202, audit)
            return
        if len(parts) == 2 and parts[1] == "ask":
            question = str(payload.get("question") or "").strip()
            if not question:
                self.json_response({"ok": False, "error": "question_required"}, 400, audit)
                return
            if len(question) > MAX_QUESTION:
                self.json_response({"ok": False, "error": "question_too_long", "message": f"Questions are bounded to {MAX_QUESTION} characters."}, 400, audit)
                return
            role = resolve_member_role(caller)
            result = project_digest.ask(caller["context"], parts[0], question,
                                        member=_member_key(caller["principal"]), role=role)
            if result is None:
                self._project_not_found(audit)
                return
            self.json_response(result, audit=audit)
            return
        self.json_response({"ok": False, "error": "not_found"}, 404, audit)

    # ---- Groups (P10) endpoints -------------------------------------------

    def _post_group_create(self, payload: dict, audit: str) -> None:
        """POST /api/groups - owner-authored group creation.

        The registry is an owner-authored input: the calling principal must
        BE the owner_member of the record it submits, so no member can mint
        a group in someone else's name.  Validation is the registry's own
        (strict, fail-closed); no scope is inferred or widened here.
        """
        context = caller_context(self.headers)
        if context is None:
            self.json_response({"ok": False, "error": "access_context_unavailable", "message": "HomeHub must provide an AccessContext before groups can be authored."}, 503, audit)
            return
        if not _same_member(context.get("principalId"), payload.get("owner_member")):
            self.json_response({"ok": False, "error": "owner_session_required", "message": "A group can only be created by the member who owns it."}, 403, audit)
            return
        try:
            record = group_registry().upsert({
                "group_id": payload.get("group_id"),
                "name": payload.get("name"),
                "owner_member": payload.get("owner_member"),
                "member_members": payload.get("member_members") or [],
                "knowledge_view": payload.get("knowledge_view"),
                "town_run_id": payload.get("town_run_id"),
            })
        except GroupsError as exc:
            self.json_response({"ok": False, "error": "invalid_group", "message": str(exc)}, 400, audit)
            return
        self.json_response({"ok": True, "group": record}, 201, audit)

    def _post_group_search(self, group_id: str, payload: dict, audit: str) -> None:
        """POST /api/groups/{id}/search - "不同群看到不同知识".

        The group tier of knowledge search: a HomeHub-issued group context
        (X-Group-Context JSON, the deployed issuance transport when it
        exists) or the local bridge (registry record + requesting member)
        feeds scoped_retrieval, which enforces validation, membership, and
        the view intersection before anything reaches synthesis.  The
        answer's citations are post-checked with source_overlap; an answer
        citing files outside the group's view is refused with the canonical
        miss sentence instead of partially shared.
        """
        registry = group_registry()
        question = str(payload.get("query", "")).strip()
        if not question:
            self.json_response({"ok": False, "error": "query_required"}, 400, audit)
            return
        record = registry.get(group_id)
        projection = self.headers.get("X-Group-Context")
        if projection is not None:
            try:
                context = validate_group_context(json.loads(projection))
            except (json.JSONDecodeError, GroupsError):
                self.json_response({"ok": False, "error": "group_context_invalid", "message": "The presented group context is malformed, expired, or revoked."}, 403, audit)
                return
            if context["group_id"] != group_id:
                self.json_response({"ok": False, "error": "group_context_mismatch", "message": "The presented group context speaks for a different group."}, 400, audit)
                return
            member_id = context["member_id"]
        else:
            if record is None:
                self.json_response({"ok": False, "error": "group_not_found", "message": "This group is not registered locally or has been dissolved."}, 404, audit)
                return
            member_id, context, ok = self._bound_group_member(payload.get("member_id"), audit)
            if not ok:
                return
            if not member_id:
                self.json_response({"ok": False, "error": "member_required", "message": "A requesting member is required to search a group."}, 400, audit)
                return
            context = local_group_context(record, member_id, (context or {}).get("jarvisNodeId"))
        all_items = [item for values in grouped_items().values() for item in values]
        allowed_items = scoped_retrieval(all_items, context, registry)
        # The effective view scoped_retrieval enforced: the validated context
        # clamped to the group's registered view (same intersection).
        view = {"project_ids": context["project_ids"], "source_ids": context["source_ids"]}
        if record is not None:
            view = intersect_views(view, record["knowledge_view"])
        # Preemptive lock (voice > query > index): mark the interactive
        # window before synthesis so an indexing worker yields the GPU.
        _touch_interactive_lock()
        result = search_answer(question, allowed_items)
        # Producer-internal cross-record statements never leave the API
        # (this tier answers without contract evidence records).
        result.pop("inferred_statements", None)
        overlap = source_overlap(result.get("sources"), view, all_items)
        if not overlap["clean"]:
            # A citation outside the view (or unresolvable) means the answer
            # cannot be proven inside the group's knowledge: speak the
            # canonical miss sentence, share no paths, no partial answer.
            result = {"answer": MISS_SENTENCE, "sources": [], "confidence": "none", "scrubbed": True}
        result.update({"ok": True, "auditId": audit, "groupId": group_id, "memberId": member_id})
        self.json_response(result, audit=audit)

    # ---- Group messaging (NandaTown wiring, audit A2) ----------------------

    def _bound_group_member(self, asserted, audit: str):
        """The requesting member for a group call, bound to a credential.

        Security fix (Studio v2, 2026-10-11): a body/query ``member_id`` used
        to win over every credential, so any caller could act as any member.
        Now the asserted id must agree with the resolved principal:

        * ``Authorization: Bearer`` - the caller's own HomeHub principal; an
          unresolvable bearer is 401 (never a fallback), a different
          ``member_id`` is 403 ``member_mismatch``;
        * loopback ``X-Agent-Member`` (voice tier) - that member; a different
          ``member_id`` is 403;
        * neither - a body/query ``member_id`` is a loopback machine caller's
          assertion (same trust as the voice header) and is honoured only on
          a loopback bind and only for non-browser requests (no ``Origin``),
          so a web page cannot post a forged member; otherwise it must equal
          the service context's principal.

        Returns ``(member_id, context, ok)``; on refusal the error response
        has already been sent and ``ok`` is False.
        """
        asserted = str(asserted or "").strip()
        auth = str(self.headers.get("Authorization") or "")
        loopback = getattr(self.server, "loopback_voice", False)
        if auth[:7].lower() == "bearer " and auth[7:].strip():
            context = load_homehub_context_for_token(auth[7:])
            if context is None:
                self.json_response({"ok": False, "error": "invalid_credentials", "message": "The presented bearer could not be resolved by HomeHub."}, 401, audit)
                return None, None, False
            principal = str(context.get("principalId") or "").strip()
            if asserted and not _same_member(asserted, principal):
                self.json_response({"ok": False, "error": "member_mismatch", "message": "member_id must match the authenticated member."}, 403, audit)
                return None, None, False
            return principal, context, True
        voice_member = str(self.headers.get("X-Agent-Member") or "").strip()
        if voice_member and loopback:
            if asserted and not _same_member(asserted, voice_member):
                self.json_response({"ok": False, "error": "member_mismatch", "message": "member_id must match the speaking member."}, 403, audit)
                return None, None, False
            return voice_member, caller_context(self.headers), True
        context = caller_context(self.headers)
        principal = str((context or {}).get("principalId") or "").strip()
        if asserted:
            machine_caller = loopback and not self.headers.get("Origin")
            if not machine_caller and not _same_member(asserted, principal):
                self.json_response({"ok": False, "error": "member_assertion_refused", "message": "A member_id assertion requires that member's own credentials."}, 403, audit)
                return None, None, False
            return asserted, context, True
        return principal or None, context, True

    def _resolve_group_member(self, group_id: str, member_hint, audit: str):
        """Resolve ``(record, member_id)`` for a group messaging call.

        The same member tiers as group search: a HomeHub-issued
        ``X-Group-Context`` projection, else body/query ``member_id``,
        loopback ``X-Agent-Member`` (the voice tier), then the caller's
        own principal.  Messaging additionally requires the group to
        exist LOCALLY - the message log and the town run mapping both
        live in the registry record - so an unknown group is an honest
        404 even when a context is presented.  Membership (owner or
        listed member) is enforced here explicitly: unlike search, which
        answers a non-member with the silent miss sentence, a message
        endpoint must refuse with 403 so no send is ever attempted -
        and never faked - for a non-member.  Returns ``(None, None)``
        after answering with the error itself.
        """
        registry = group_registry()
        record = registry.get(group_id)
        if record is None:
            self.json_response({"ok": False, "error": "group_not_found", "message": "This group is not registered locally or has been dissolved."}, 404, audit)
            return None, None
        projection = self.headers.get("X-Group-Context")
        if projection is not None:
            try:
                context = validate_group_context(json.loads(projection))
            except (json.JSONDecodeError, GroupsError):
                self.json_response({"ok": False, "error": "group_context_invalid", "message": "The presented group context is malformed, expired, or revoked."}, 403, audit)
                return None, None
            if context["group_id"] != group_id:
                self.json_response({"ok": False, "error": "group_context_mismatch", "message": "The presented group context speaks for a different group."}, 400, audit)
                return None, None
            member_id = context["member_id"]
        else:
            member_id, _context, ok = self._bound_group_member(member_hint, audit)
            if not ok:
                return None, None
            if not member_id:
                self.json_response({"ok": False, "error": "member_required", "message": "A requesting member is required to message a group."}, 400, audit)
                return None, None
        if not group_allows_member(record, member_id):
            self.json_response({"ok": False, "error": "not_a_member", "message": "Only the group's owner or its listed members can message this group."}, 403, audit)
            return None, None
        return record, member_id

    def _post_group_message(self, group_id: str, payload: dict, audit: str) -> None:
        """POST /api/groups/{id}/messages - a member speaks to the group.

        Fan-out is per-recipient (the town has no broadcast): the client
        resolves the run's directory, drops this box's own participant,
        and posts one message per peer with its own message_id.  The
        declared ``sender`` in each envelope is the resolved member; the
        town attributes delivery to this box's joined session.  Honest
        failure only: a refused join, unreachable town, or a directory
        that cannot be read answers 503 with the client's error_code and
        persists NOTHING - a message that did not leave the box must not
        appear in history as if it had.
        """
        text = str(payload.get("text") or "").strip()
        if not text:
            self.json_response({"ok": False, "error": "message_text_required", "message": "A non-empty text is required."}, 400, audit)
            return
        if len(text) > MAX_MESSAGE_TEXT:
            self.json_response({"ok": False, "error": "message_too_long", "message": f"Message text is bounded to {MAX_MESSAGE_TEXT} characters."}, 400, audit)
            return
        record, member_id = self._resolve_group_member(group_id, payload.get("member_id"), audit)
        if record is None:
            return
        run_id = group_town_run(record)
        if run_id is None:
            self.json_response({"ok": False, "error": "nandatown_run_unconfigured",
                                "message": "This group carries no town_run_id and no default UYP_NANDATOWN_RUN_ID is configured; refusing to guess a town run."}, 503, audit)
            return
        client = NandaTownClient(run_id=run_id)
        results = client.send_group_message(group_id, member_id, text)
        if not results and client.error_code is not None:
            self.json_response({"ok": False, "error": client.error_code,
                                "message": f"NandaTown refused this send: {client.last_error or client.error_code}"}, 503, audit)
            return
        delivered = [row for row in results if row.get("ok")]
        if results and not delivered:
            # Every per-recipient POST failed: report the honest per-recipient
            # error; no echo, exactly like a join/directory failure above.
            errors = sorted({str(row.get("error") or "nandatown_delivery_failed") for row in results})
            self.json_response({"ok": False, "error": errors[0],
                                "message": "The town accepted no copy of this message for any recipient.",
                                "delivery": results}, 503, audit)
            return
        sent_at = now_iso()
        row = {
            "message_id": (results[0].get("message_id") if results else None)
                          or f"local-{uuid.uuid4().hex}",
            "group_id": group_id,
            "sender": member_id,
            "sent_at": sent_at,
            "text": text,
            "direction": "out",
            "delivery": results,
        }
        append_group_message(group_id, row)
        self.json_response({
            "ok": True,
            "groupId": group_id,
            "memberId": member_id,
            "sent": {"message_id": row["message_id"], "group_id": group_id,
                     "sender": member_id, "sent_at": sent_at, "text": text,
                     "direction": "out"},
            "delivery": results,
            "deliveredTo": [entry.get("to") for entry in delivered],
        }, 201, audit)

    def _post_group_device_action(self, group_id: str, payload: dict, audit: str) -> None:
        """Validate a HomeHub-authorized group device action (P1b).

        Group text transport is intentionally not an action authority.  This
        endpoint requires a signed HomeHub group device context in
        ``X-Group-Context`` plus the stronger ``device_ids``/``action_ids``
        capability scopes.  A context that only authorizes project knowledge
        or NandaTown messages is rejected, as is any context missing the
        signature material.  Dry-run returns a provider-neutral plan; live
        execution re-verifies the context with HomeHub online, forwards the
        envelope with the caller's bearer, and confirms by state readback.
        """
        projection = self.headers.get("X-Group-Context")
        if projection is None:
            self.json_response({
                "ok": False,
                "error": "group_device_context_required",
                "message": "HomeHub must issue a group device-action context before this route can be used.",
            }, 403, audit)
            return
        try:
            context = json.loads(projection)
        except json.JSONDecodeError:
            self.json_response({
                "ok": False,
                "error": "group_context_invalid",
                "message": "The presented group context is malformed, expired, or revoked.",
            }, 403, audit)
            return
        if not isinstance(context, dict) or context.get("group_id") != group_id:
            self.json_response({
                "ok": False,
                "error": "group_context_mismatch",
                "message": "The presented group context speaks for a different group.",
            }, 400, audit)
            return
        member_id = str(context.get("member_id") or "").strip()
        # A request-carried group projection is not itself a caller
        # credential.  Bind it to the same HomeHub bearer or loopback voice
        # member used by the other protected query routes before inspecting
        # the local registry.  This prevents a caller who merely obtained a
        # different member's projection from submitting an action as them.
        auth = str(self.headers.get("Authorization") or "")
        caller_bearer = ""
        if auth[:7].lower() == "bearer " and auth[7:].strip():
            caller_bearer = auth[7:].strip()
            caller = load_homehub_context_for_token(caller_bearer)
            if caller is None:
                self.json_response({"ok": False, "error": "invalid_credentials",
                                    "message": "The presented bearer could not be resolved by HomeHub."}, 401, audit)
                return
            if not _same_member(caller.get("principalId"), member_id):
                self.json_response({"ok": False, "error": "member_mismatch",
                                    "message": "The group context member must match the authenticated member."}, 403, audit)
                return
        else:
            voice_member = str(self.headers.get("X-Agent-Member") or "").strip()
            if not (voice_member and getattr(self.server, "loopback_voice", False)):
                self.json_response({"ok": False, "error": "group_device_credentials_required",
                                    "message": "A HomeHub bearer or loopback member credential is required."}, 401, audit)
                return
            if not _same_member(voice_member, member_id):
                self.json_response({"ok": False, "error": "member_mismatch",
                                    "message": "The group context member must match the speaking member."}, 403, audit)
                return
        record = group_registry().get(group_id)
        if record is None:
            self.json_response({"ok": False, "error": "group_not_found",
                                "message": "This group is not registered locally or has been dissolved."}, 404, audit)
            return
        if not member_id or not group_allows_member(record, member_id):
            self.json_response({"ok": False, "error": "not_a_member",
                                "message": "Only a HomeHub-authorized group member can request a device action."}, 403, audit)
            return
        try:
            # The caller's HomeHub bearer is forwarded for live execution; on
            # the loopback voice path it is empty and the adapter falls back
            # to the service token file.
            plan = validate_group_device_action(
                context, payload, homehub_token=caller_bearer or None)
        except GroupDeviceActionError as exc:
            status = 409 if exc.code in {
                "group_device_scope_missing", "group_device_not_granted",
                "group_action_not_granted", "group_device_readback_mismatch",
            } else 403 if exc.code in {
                "group_device_signature_missing", "group_context_invalid",
            } else 503 if exc.code == "group_device_action_unavailable" else 400
            self.json_response({"ok": False, "error": exc.code, "message": exc.message}, status, audit)
            return
        plan["ok"] = True
        # auditId stays the HomeHub grant's audit anchor from the signed
        # context; the local request audit id rides along as uypAuditId.
        plan["uypAuditId"] = audit
        self.json_response(plan, audit=audit)

    def _get_group_messages(self, group_id: str, query: dict, audit: str) -> None:
        """GET /api/groups/{id}/messages?limit= - the member-scoped local log.

        This is what a chat UI polls: the append-only record of this
        group's sends (local echo) and receives (the poll loop), oldest
        first, newest ``limit`` rows.  Membership uses the same tiers as
        the send path; a non-member learns nothing - not even that
        history exists (403), and an unknown group is a 404.
        """
        try:
            limit = int((query.get("limit") or ["200"])[0])
        except ValueError:
            limit = 200
        limit = max(1, min(limit, MAX_MESSAGE_LOG_ROWS))
        record, member_id = self._resolve_group_member(
            group_id, (query.get("member_id") or [""])[0], audit)
        if record is None:
            return
        rows = load_group_messages(group_id)
        self.json_response({"ok": True, "groupId": group_id, "memberId": member_id,
                            "total": len(rows), "messages": rows[-limit:]}, audit=audit)

    def do_DELETE(self) -> None:
        audit = str(uuid.uuid4())
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("body_too_large")
            if length:
                self.rfile.read(length)
        except ValueError:
            pass
        parts = parsed.path.split("/")
        if (len(parts) == 4 and parts[0] == "" and parts[1] == "api"
                and parts[2] == "groups" and parts[3]):
            self._delete_group(parts[3], audit)
            return
        self.json_response({"ok": False, "error": "not_found"}, 404, audit)

    def _delete_group(self, group_id: str, audit: str) -> None:
        """DELETE /api/groups/{id} - dissolve a group (owner only).

        Revocation of any HomeHub-issued grant stays with HomeHub; locally
        this forgets the registry record, which is the input to issuance.
        After dissolution scoped_retrieval no longer knows the group, so
        searches are denied (404 on the local-bridge path, no results on
        any still-presented projection).
        """
        context = caller_context(self.headers)
        if context is None:
            self.json_response({"ok": False, "error": "access_context_unavailable", "message": "HomeHub must provide an AccessContext before groups can be dissolved."}, 503, audit)
            return
        registry = group_registry()
        record = registry.get(group_id)
        if record is None:
            self.json_response({"ok": False, "error": "group_not_found", "message": "This group is not registered locally or has been dissolved."}, 404, audit)
            return
        if not _same_member(context.get("principalId"), record["owner_member"]):
            self.json_response({"ok": False, "error": "owner_session_required", "message": "Only the group owner can dissolve a group."}, 403, audit)
            return
        removed = registry.remove(group_id)
        self.json_response({"ok": True, "group_id": group_id, "revoked": True, "removed": removed}, audit=audit)

    def log_message(self, *_args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("UYP_QUERY_PORT", "8787")))
    parser.add_argument("--lan", action="store_true", help="bind 0.0.0.0; use only behind approved transport")
    args = parser.parse_args()
    host = "0.0.0.0" if args.lan else args.host
    server = ThreadingHTTPServer((host, args.port), QueryHandler)
    # Loopback-voice handshake guard (2026-10-10): the X-Agent-Member
    # voice tier in load_request_context is valid ONLY while this API is
    # loopback-bound - a --lan deployment must never admit header-asserted
    # voice identity without the approved transport in front of it.
    server.loopback_voice = host in {"127.0.0.1", "localhost", "::1"}
    # Inbound group messaging: one background receive loop per process,
    # quiet when the town transport env is absent (fail-closed; see
    # start_nandatown_poller).
    polling = start_nandatown_poller()
    print(f"uyp-query-api v{VERSION} on {host}:{args.port} output={output_root()} "
          f"nandatown-poll={'on' if polling else 'off'}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
