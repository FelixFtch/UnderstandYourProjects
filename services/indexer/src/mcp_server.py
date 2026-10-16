#!/usr/bin/env python3
"""Read-only MCP (Model Context Protocol) stdio server — P6 Coding Agent surface.

Exposes the six P6 tools (EXECUTION_PLAN.md P6 / AGENTFLOW_ARCHITECTURE.md 5)
to coding agents over newline-delimited JSON-RPC 2.0 on stdio:

    project.search        scoped retrieval with citations (per-member)
    project.get           one project's summary and IndexJob status
    project.related       related files/projects via the UA graph and tags
    source.locate         file/line symbol locations (anchored_enrich tables)
    source.read_evidence  the indexed evidence backing a knowledge item
    index.status          job/queue/worker status

Everything is READ-ONLY.  No shell, build, test, arbitrary path read, or
source write is exposed, and no tool mutates registry/state/output files.

Retrieval is not reimplemented: the tools call the same functions
``query_api.py`` routes call (``scoped_items``, ``search_answer``,
``project_snapshot`` helpers, ``load_persisted_index_jobs``,
``load_ua_graph``, ``anchored_enrich.symbols_from_graph``).  With ``--api``
the three route-bound tools are served by the running query API over
loopback HTTP instead, inheriting that service's enforcement verbatim.

Principal story (fail closed, mirroring the query API handshake):

* member tier — ``--principal`` / ``UYP_MCP_PRINCIPAL`` names the HomeHub
  member the agent acts for.  HTTP mode presents ``X-Agent-Member`` (the
  loopback voice tier; the API must be loopback-bound, which is the
  default); direct mode calls ``homehub_adapter.load_context_for_member``,
  the exact function behind the voice handshake.  The resolved projection
  must speak for exactly that member with a non-empty project scope.
* bearer tier — ``UYP_MCP_TOKEN_FILE`` holds the agent's own HomeHub
  Companion bearer (the voice-chain token-file approach); the projection is
  resolved for that credential alone (``Authorization: Bearer`` in HTTP
  mode, ``load_context_for_token`` in direct mode).
* neither configured — every tool call is denied ``principal_required``.
  The MCP surface never falls back to the box's ambient service context.

Run (HTTP mode, next to a loopback query API):

    python3 services/indexer/src/mcp_server.py \
        --api http://127.0.0.1:8787 --principal ly

Run (direct mode, same env/box as query_api, no HTTP hop):

    UYP_MCP_PRINCIPAL=ly python3 services/indexer/src/mcp_server.py

Source text is never read from the live tree: the Connector stays the only
path resolver, graph reads go through ``query_api.load_ua_graph`` (whose
realpath/commonpath containment is reused untouched), and evidence is
served from the indexed bounded KnowledgeItem payload.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

import anchored_enrich
import knowledge_search
import query_api
from homehub_adapter import load_context_for_member, load_context_for_token


VERSION = "0.1.0"
SERVER_NAME = "uyp-mcp"
JSONRPC = "2.0"
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18"})

ERROR_PARSE = -32700
ERROR_INVALID_REQUEST = -32600
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS = -32602
ERROR_INTERNAL = -32603
ERROR_NOT_INITIALIZED = -32002

MAX_QUERY_CHARS = 4096          # same bound as federation_protocol requests
MAX_TEXT_CHARS = 256
DEFAULT_LOCATE_LIMIT = 25
MAX_LOCATE_LIMIT = 100
MAX_EVIDENCE_ITEMS = 200        # mirrors project_snapshot's evidence window
MAX_RELATED_PROJECTS = 10
MAX_RELATED_FILES = 25
MAX_TAGS = 15
HTTP_TIMEOUT = 10

# anchored_enrich key_point labels: the line protocol is
# "K: <fact|structure|inference> <point> (L<lo>-L<hi>)" — a bare leading
# word (the bracketed spelling is exactly what validate() rejects).
KP_LABEL = re.compile(r"^(fact|structure|inference)[ \t]+", re.IGNORECASE)
# trailing citation on purpose/components/key_points: "(L83-L91)"
CITATION_TAIL = re.compile(r"\s*\((?:unverified\s+)?L\d{1,4}\s*[-–]\s*L\d{1,4}\)\s*$")


class ToolDenial(Exception):
    """An honest fail-closed refusal for one tool call.

    Denials are tool results (``isError`` content with the same
    ``{"ok": false, "error": ..., "message": ...}`` shape the HTTP API
    returns), never crashes and never a fallback to unscoped data.
    """

    def __init__(self, error: str, message: str, status: int = 403):
        super().__init__(message)
        self.error = error
        self.message = message
        self.status = status


class ToolArgumentError(ToolDenial):
    """Invalid tool arguments — reported as JSON-RPC -32602 (MCP tools/call)."""

    def __init__(self, message: str):
        super().__init__("invalid_params", message, status=400)


# ---------------------------------------------------------------------------
# principal resolution (the MCP mirror of query_api.load_request_context)
# ---------------------------------------------------------------------------


PRINCIPAL_REQUIRED_MESSAGE = (
    "The MCP server needs a service principal: set UYP_MCP_PRINCIPAL "
    "(member tier, resolved like the voice handshake) or UYP_MCP_TOKEN_FILE "
    "(bearer tier). Without one every tool is denied.")


def configured_principal() -> str:
    return str(os.environ.get("UYP_MCP_PRINCIPAL") or "").strip()


def configured_token_file() -> str:
    return str(os.environ.get("UYP_MCP_TOKEN_FILE") or "").strip()


def resolve_principal(explicit: str | None = None) -> dict:
    """Decide HOW the server authenticates: member tier, bearer tier, or none.

    Mirrors the ordering of ``query_api.load_request_context``: a presented
    credential tier wins over ambient configuration, and no tier at all is a
    denial — the MCP surface never silently inherits the box context.
    """
    subject = str(explicit or configured_principal()).strip()
    if subject:
        return {"tier": "member", "subject": subject}
    if configured_token_file():
        return {"tier": "bearer", "subject": None}
    return {"tier": None, "subject": None}


def _read_token_file() -> str:
    path = configured_token_file()
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError:
        raise ToolDenial("principal_required",
                         f"UYP_MCP_TOKEN_FILE is configured but unreadable: {os.path.basename(path)}")
    if not token:
        raise ToolDenial("principal_required", "UYP_MCP_TOKEN_FILE is empty; no principal to act for.")
    return token


def direct_context(principal: dict) -> dict:
    """Resolve the principal's AccessContext in direct mode (fail closed).

    Same tiers and the same HomeHub functions as the HTTP API's per-request
    handshake: the member tier is the exact voice-handshake resolution
    (``load_context_for_member`` validates that the projection speaks for
    the requested member and carries project scopes), the bearer tier is
    the Studio-session resolution for the token's own principal.
    """
    if principal["tier"] == "member":
        context = load_context_for_member(principal["subject"])
        if context is None:
            raise ToolDenial(
                "member_access_denied",
                "HomeHub has no active project grant for this member; "
                "the MCP tool call is denied for them.")
        return context
    if principal["tier"] == "bearer":
        context = load_context_for_token(_read_token_file())
        if context is None:
            raise ToolDenial(
                "access_context_unavailable",
                "HomeHub could not resolve the presented bearer; failing closed.")
        return context
    raise ToolDenial(
        "principal_required",
        PRINCIPAL_REQUIRED_MESSAGE)


def _principal_view(principal: dict) -> dict:
    """The honest principal block for status payloads (no policy material)."""
    if principal["tier"] is None:
        return {"tier": None}
    view = {"tier": principal["tier"]}
    if principal["subject"]:
        view["subject"] = principal["subject"]
    return view


# ---------------------------------------------------------------------------
# loopback HTTP client for the route-bound tools (--api mode)
# ---------------------------------------------------------------------------


class QueryApiClient:
    """Minimal loopback client for the three route-bound query API reads."""

    def __init__(self, base_url: str, principal: dict):
        self.base_url = base_url.rstrip("/")
        self.principal = principal

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.principal["tier"] == "member":
            # The loopback voice tier: the API resolves this member with its
            # own HomeHub credential (loopback-bound deployments only).
            headers["X-Agent-Member"] = self.principal["subject"]
        elif self.principal["tier"] == "bearer":
            headers["Authorization"] = f"Bearer {_read_token_file()}"
        return headers

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = self._headers()
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                body = json.loads(response.read() or b"{}")
                return response.status, body if isinstance(body, dict) else {}
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read() or b"{}")
            except (json.JSONDecodeError, OSError):
                body = {}
            return exc.code, body if isinstance(body, dict) else {}
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
            raise ToolDenial(
                "query_api_unreachable",
                f"The query API at {self.base_url} is unreachable; failing closed.",
                status=503)

    def _deny_from_status(self, status: int, body: dict) -> None:
        error = str(body.get("error") or "")
        message = str(body.get("message") or error or "the query API refused the call")
        if error in {"member_access_denied", "access_context_unavailable",
                     "query_required", "query_api_unreachable"}:
            raise ToolDenial(error, message, status=status if status >= 400 else 403)
        raise ToolDenial("query_api_error", f"HTTP {status}: {message}", status=status)

    def knowledge_search(self, query: str, project_id: str | None) -> dict:
        payload = {"query": query}
        if project_id:
            payload["projectId"] = project_id
        status, body = self.request("POST", "/api/knowledge/search", payload)
        if status != 200:
            self._deny_from_status(status, body)
        return body

    def studio_snapshot(self, project_id: str) -> dict:
        query = urllib.parse.urlencode({"projectId": project_id})
        status, body = self.request("GET", f"/api/studio/snapshot?{query}")
        if status != 200:
            self._deny_from_status(status, body)
        return body

    def health(self) -> dict:
        status, body = self.request("GET", "/api/health")
        if status != 200:
            self._deny_from_status(status, body)
        return body


# ---------------------------------------------------------------------------
# shared helpers over query_api (the same functions the routes call)
# ---------------------------------------------------------------------------


def _scoped_items(context: dict) -> list[dict]:
    """The one scope filter search and health both use (query_api.scoped_items)."""
    return query_api.scoped_items(context)


def _scoped_roots(context: dict) -> dict[str, list[dict]]:
    """Scoped items grouped by their output-root project directory."""
    roots: dict[str, list[dict]] = {}
    for item in _scoped_items(context):
        roots.setdefault(query_api.item_root(str(item.get("_out_path", ""))), []).append(item)
    return roots


def _normalized_project_id(value) -> str:
    text = str(value or "").removeprefix("project:").strip()
    # Reuse the state-component validator: a project id is a capability
    # label here, never a filesystem path.
    if query_api.safe_state_project(text) is None:
        raise ToolArgumentError("project_id must be a single safe path component")
    return text


def _require_query(arguments: dict) -> str:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ToolArgumentError("A non-empty query is required.")
    if len(query) > MAX_QUERY_CHARS:
        raise ToolArgumentError(f"query exceeds {MAX_QUERY_CHARS} characters")
    return query


def _citations(result_sources: list, scoped: list[dict], context: dict) -> list[dict]:
    """Project search citations into the AGENTFLOW section-5 contract fields."""
    return query_api.search_citations(result_sources, scoped, context)


def _evidence_rows(root: str, items: list[dict], context: dict) -> list[dict]:
    """Evidence entries in the same deterministic order as project_snapshot."""
    ordered = sorted(items, key=lambda value: str(value.get("file", "")))[:MAX_EVIDENCE_ITEMS]
    rows = []
    for index, item in enumerate(ordered):
        derived = item.get("derived") or {}
        rows.append({
            "evidenceId": f"knowledge:{root}:{index}",
            "projectId": f"project:{root}",
            "sourceId": f"connector:{root}",
            "file": item.get("file"),
            "summary": str(derived.get("purpose") or "Structure metadata only"),
            "kind": "inference" if derived.get("purpose") else "structure",
            "knowledgeVersion": str((item.get("version") or {}).get("mtime", "")),
            "anchorTop": item.get("anchor_top"),
            "freshness": "current",
        })
    return [{k: v for k, v in row.items() if v is not None} for row in rows]


def _normalize_tag(value: str) -> str:
    return CITATION_TAIL.sub("", str(value or "")).strip().casefold()


def _project_tags(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        for component in (item.get("derived") or {}).get("components") or []:
            tag = _normalize_tag(component)
            if tag:
                counts[tag] = counts.get(tag, 0) + 1
    return counts


def _strip_kp_label(text: str) -> tuple[str | None, str]:
    match = KP_LABEL.match(str(text or ""))
    if match:
        return match.group(1), text[match.end():]
    return None, str(text or "")


def _citation_range(text: str) -> tuple[int, int] | None:
    match = re.search(r"(?:unverified\s+)?L(\d{1,4})\s*[-–]\s*L(\d{1,4})\)?\s*$", str(text or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


# ---------------------------------------------------------------------------
# tool implementations
# ---------------------------------------------------------------------------


class ToolRunner:
    """Dispatches the six read-only tools onto query_api's own logic."""

    def __init__(self, *, api_url: str | None = None, principal: dict | None = None):
        self.api_url = api_url
        self.principal = principal or resolve_principal()
        self.api = QueryApiClient(api_url, self.principal) if api_url else None

    # -- context helpers ----------------------------------------------------

    @property
    def mode(self) -> str:
        return "http" if self.api is not None else "direct"

    def _local_context(self) -> dict:
        """The principal's context, resolved with the voice-handshake tiers.

        Used for every locally-computed tool (related, locate, evidence, and
        the whole direct mode); the route-bound HTTP tools inherit the query
        API's own enforcement instead.
        """
        return direct_context(self.principal)

    def call(self, name: str, arguments: dict) -> dict:
        audit = str(uuid.uuid4())
        started = time.time()
        try:
            # Mode-independent fail-closed gate: without a configured tier
            # no tool runs at all — in HTTP mode too, where the API would
            # otherwise fall back to its service-level box context (tier c)
            # and serve the ambient principal's grants.
            if self.principal["tier"] is None:
                raise ToolDenial("principal_required", PRINCIPAL_REQUIRED_MESSAGE)
            payload = getattr(self, "_tool_" + name.replace(".", "_"))(arguments)
            payload.setdefault("auditId", audit)
        except ToolDenial as denial:
            denial.audit_id = audit  # type: ignore[attr-defined]
            self._log(name, "denied", started, audit, error=denial.error)
            raise
        self._log(name, "ok", started, audit)
        return payload

    def _log(self, tool: str, outcome: str, started: float, audit: str, error: str | None = None) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "server": SERVER_NAME, "tool": tool, "outcome": outcome,
            "principal": _principal_view(self.principal), "auditId": audit,
            "durationMs": round((time.time() - started) * 1000),
        }
        if error:
            entry["error"] = error
        sys.stderr.write(json.dumps(entry, ensure_ascii=False) + "\n")
        sys.stderr.flush()

    # -- project.search -------------------------------------------------

    def _tool_project_search(self, arguments: dict) -> dict:
        question = _require_query(arguments)
        project_id = arguments.get("project_id")
        project_key = _normalized_project_id(project_id) if project_id else None
        if self.api is not None:
            # Route-bound: the query API resolves the principal (member tier
            # via X-Agent-Member), filters with scoped_items, synthesizes,
            # and returns the cited answer or its own honest denial.
            result = self.api.knowledge_search(question, project_key)
            result.setdefault("ok", True)
            result["backend"] = "http"
            return result
        context = self._local_context()
        # Keep direct MCP retrieval identical to the HTTP Query API: the
        # caller's HomeHub scopes are applied first, then an explicit project
        # selector narrows that already-authorized set.  A project id is
        # never a grant and must not widen the search.
        allowed_items = query_api.scoped_items(context, project_key)
        result = query_api.search_answer(question, allowed_items)
        result.update({
            "ok": True,
            "projectId": project_key,
            "access": {"grantEpoch": context.get("grantEpoch"), "expiresAt": context.get("expiresAt")},
            "citations": _citations(result.get("sources"), allowed_items, context),
            "backend": "direct",
        })
        return result

    # -- project.get ------------------------------------------------------

    def _tool_project_get(self, arguments: dict) -> dict:
        root = _normalized_project_id(arguments.get("project_id"))
        if self.api is not None:
            snapshot = self.api.studio_snapshot(root)
            project = snapshot.get("project") or {}
            if project.get("name") in {"Project scope unavailable"} or project.get("projectId") == "project:unavailable":
                raise ToolDenial("project_not_in_scope",
                                 "No authorized project matches this id for the calling principal.",
                                 status=404)
            return {
                "ok": True,
                "project": project,
                "health": snapshot.get("health"),
                "jobs": snapshot.get("jobs", []),
                "evidenceCount": len(snapshot.get("evidence") or []),
                "backend": "http",
            }
        context = self._local_context()
        roots = _scoped_roots(context)
        items = roots.get(root)
        if items is None:
            # Same reply whether the project does not exist or is merely
            # out of scope: no names, counts, or paths are shared.
            raise ToolDenial("project_not_in_scope",
                             "No authorized project matches this id for the calling principal.",
                             status=404)
        connector = query_api.configured_connector_status()
        graph = query_api.load_ua_graph(root)
        graph_project = (graph or {}).get("project", {})
        nodes = (graph or {}).get("nodes", [])
        edges = (graph or {}).get("edges", [])
        updated = max((str(item.get("analyzed_at", "")) for item in items), default="")
        state = "current" if items and connector["state"] == "current" else "partial" if items else "unsupported"
        jobs = query_api.load_persisted_index_jobs(root, context)
        return {
            "ok": True,
            "project": {
                "projectId": f"project:{root}",
                "sourceId": f"connector:{root}",
                "name": root,
                "description": f"{len(items)} authorized KnowledgeItems"
                               + (" with a vendored UA structure graph." if graph else
                                  " from the Agent Box output store."),
                "languages": graph_project.get("languages", []),
                "frameworks": graph_project.get("frameworks", []),
                "counts": {"files": len(items), "nodes": len(nodes), "relations": len(edges)},
                "entryPoints": [item.get("file") for item in items[:4] if item.get("file")],
                "knowledgeVersion": updated,
                "sourceEpoch": updated,
                "freshness": state,
                "updatedAt": updated,
                "grantEpoch": context.get("grantEpoch"),
            },
            "health": {
                "state": state,
                "knowledgeVersion": updated,
                "coverage": {"filesIndexed": len(items)},
                "connectorStatus": connector["state"],
            },
            "jobs": jobs,
            "evidence": _evidence_rows(root, items, context)[:20],
            "evidenceCount": min(len(items), MAX_EVIDENCE_ITEMS),
            "backend": "direct",
        }

    # -- project.related ----------------------------------------------------

    def _tool_project_related(self, arguments: dict) -> dict:
        query = str(arguments.get("query") or "").strip()[:MAX_QUERY_CHARS]
        explicit = arguments.get("project_id")
        if not query and not explicit:
            raise ToolArgumentError("Provide either query or project_id.")
        context = self._local_context()
        roots = _scoped_roots(context)
        if explicit:
            root = _normalized_project_id(explicit)
            if root not in roots:
                raise ToolDenial("project_not_in_scope",
                                 "No authorized project matches this id for the calling principal.",
                                 status=404)
        else:
            # Reuse knowledge_search's own tokenizer/scoring to pick the
            # project the query is about (same ranking as project.search).
            tokens = knowledge_search.tokenize(query)
            scored = sorted(
                ((knowledge_search.score(item, tokens), item)
                 for item in _scoped_items(context) if item.get("file")),
                key=lambda pair: -pair[0])
            root = query_api.item_root(str(scored[0][1].get("_out_path", ""))) if scored and scored[0][0] > 0 else None
            if root is None:
                return {"ok": True, "match": False, "answer": query_api.MISS_SENTENCE,
                        "related": {}, "backend": self.mode}
        items = roots[root]
        graph = query_api.load_ua_graph(root)
        related_files, hubs = self._graph_relations(graph)
        tags = dict(sorted(_project_tags(items).items(), key=lambda kv: -kv[1])[:MAX_TAGS])
        related_projects = []
        files_by_root = {str(item.get("file") or "") for item in items}
        for other, other_items in sorted(roots.items()):
            if other == root:
                continue
            shared_tags = sorted(set(tags).intersection(_project_tags(other_items)))
            other_files = {str(item.get("file") or "") for item in other_items}
            shared_paths = sorted(files_by_root.intersection(other_files) - {""})[:5]
            if shared_tags or shared_paths:
                related_projects.append({
                    "projectId": f"project:{other}",
                    "sharedTags": shared_tags[:5],
                    "sharedPaths": shared_paths,
                    "knowledgeVersion": max((str(i.get("analyzed_at", "")) for i in other_items), default=""),
                })
        related_projects = related_projects[:MAX_RELATED_PROJECTS]
        return {
            "ok": True,
            "match": True,
            "projectId": f"project:{root}",
            "related": {
                "files": related_files,
                "hubs": hubs,
                "tags": tags,
                "projects": related_projects,
                "graphAvailable": graph is not None,
            },
            "backend": self.mode,
        }

    @staticmethod
    def _graph_relations(graph: dict | None) -> tuple[list[dict], list[dict]]:
        """Import/dependency neighbours from the vendored UA graph (no new reads)."""
        if not graph:
            return [], []
        imports: dict[str, set[str]] = {}
        degree: dict[str, int] = {}
        for edge in graph.get("edges", [])[:2000]:
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            kind = str(edge.get("type") or "")
            if not source.startswith("file:") or not target.startswith("file:"):
                continue
            source_file, target_file = source[len("file:"):], target[len("file:"):]
            if source_file == target_file:
                continue
            if kind in {"contains", "part_of"}:
                continue
            imports.setdefault(source_file, set()).add(target_file)
            degree[target_file] = degree.get(target_file, 0) + 1
        files = [{
            "file": file,
            "imports": sorted(targets)[:MAX_RELATED_FILES],
        } for file, targets in sorted(imports.items())][:MAX_RELATED_FILES]
        hubs = [{"file": file, "importedBy": count}
                for file, count in sorted(degree.items(), key=lambda kv: -kv[1])[:MAX_RELATED_FILES]]
        return files, hubs

    # -- source.locate --------------------------------------------------------

    def _tool_source_locate(self, arguments: dict) -> dict:
        symbol = str(arguments.get("symbol") or "").strip()
        file_pattern = str(arguments.get("file_pattern") or "").strip()
        if not symbol and not file_pattern:
            raise ToolArgumentError("Provide symbol and/or file_pattern.")
        if len(symbol) > MAX_TEXT_CHARS or len(file_pattern) > MAX_TEXT_CHARS:
            raise ToolArgumentError("symbol/file_pattern exceed the text bound")
        try:
            limit = int(arguments.get("limit") or DEFAULT_LOCATE_LIMIT)
        except (TypeError, ValueError):
            raise ToolArgumentError("limit must be an integer")
        limit = max(1, min(limit, MAX_LOCATE_LIMIT))
        context = self._local_context()
        roots = _scoped_roots(context)
        if arguments.get("project_id"):
            requested = _normalized_project_id(arguments.get("project_id"))
            if requested not in roots:
                raise ToolDenial("project_not_in_scope",
                                 "No authorized project matches this id for the calling principal.",
                                 status=404)
            targets = [requested]
        else:
            targets = sorted(roots)
        needle = symbol.casefold()
        matches: list[dict] = []
        for project in targets:
            # anchored_enrich's own node filter over query_api's contained loader
            symbols = anchored_enrich.symbols_from_graph(query_api.load_ua_graph(project) or {})
            for file, table in sorted(symbols.items()):
                if file_pattern and not fnmatch.fnmatchcase(file, file_pattern):
                    continue
                for entry in table:
                    if needle and needle not in str(entry["name"]).casefold():
                        continue
                    matches.append({
                        "projectId": f"project:{project}",
                        "file": file,
                        "symbol": entry["name"],
                        "kind": entry["kind"],
                        "lineRange": [entry["lo"], entry["hi"]],
                    })
                    if len(matches) >= limit:
                        break
                if len(matches) >= limit:
                    break
            if len(matches) >= limit:
                break
        return {"ok": True, "matches": matches, "count": len(matches),
                "truncated": len(matches) >= limit, "backend": self.mode}

    # -- source.read_evidence ---------------------------------------------------

    def _tool_source_read_evidence(self, arguments: dict) -> dict:
        context = self._local_context()
        roots = _scoped_roots(context)
        item, root = self._resolve_evidence_item(arguments, roots)
        derived = item.get("derived") or {}
        lo = hi = None
        lines = arguments.get("lines")
        if lines is not None:
            lo, hi = self._parse_lines(lines)
        key_points = []
        for point in derived.get("key_points") or []:
            level, text = _strip_kp_label(point)
            key_points.append({"evidenceLevel": level, "point": text})
        if lo is not None:
            def cited_within(kp: dict) -> bool:
                rng = _citation_range(kp["point"])
                return rng is not None and rng[1] >= lo and rng[0] <= hi
            key_points = [kp for kp in key_points if cited_within(kp)]
        raw_head = derived.get("raw_head")
        if raw_head is not None and lo is not None:
            # The verbatim head carries no line range we can verify against
            # the requested window; serve it only for whole-file reads.
            raw_head = None
        return {
            "ok": True,
            "evidence": {
                "projectId": f"project:{root}",
                "sourceId": f"connector:{root}",
                "file": item.get("file"),
                "knowledgeVersion": str((item.get("version") or {}).get("mtime", "")),
                "freshness": "current",
                "purpose": derived.get("purpose"),
                "keyPoints": key_points,
                "components": derived.get("components") or [],
                "anchorTop": item.get("anchor_top"),
                # Bounded verbatim head kept by the indexer when enrichment
                # could not parse; the live tree is never read (the Connector
                # stays the only path resolver).
                "rawHead": raw_head,
                "lines": [lo, hi] if lo is not None else None,
            },
            "backend": self.mode,
        }

    @staticmethod
    def _parse_lines(lines) -> tuple[int, int]:
        if (not isinstance(lines, (list, tuple)) or len(lines) != 2):
            raise ToolArgumentError("lines must be a [lo, hi] pair of line numbers")
        try:
            lo, hi = int(lines[0]), int(lines[1])
        except (TypeError, ValueError):
            raise ToolArgumentError("lines must be integers")
        if lo < 1 or hi < lo or hi - lo > 5000:
            raise ToolArgumentError("lines must satisfy 1 <= lo <= hi <= lo+5000")
        return lo, hi

    def _resolve_evidence_item(self, arguments: dict, roots: dict[str, list[dict]]) -> tuple[dict, str]:
        """Resolve an item by snapshot evidence id or by (scoped) file path."""
        item_id = str(arguments.get("item_id") or "").strip()
        path = str(arguments.get("path") or "").strip()
        if bool(item_id) == bool(path):
            raise ToolArgumentError("Provide exactly one of item_id or path.")
        if item_id:
            if not item_id.startswith("knowledge:"):
                raise ToolDenial("evidence_not_found", "Unknown evidence id.", status=404)
            parts = item_id[len("knowledge:"):].rsplit(":", 1)
            if len(parts) != 2 or not parts[1].isdigit():
                raise ToolDenial("evidence_not_found", "Unknown evidence id.", status=404)
            root, index = parts[0], int(parts[1])
            items = roots.get(root)
            if items is None or index >= MAX_EVIDENCE_ITEMS:
                # Out of scope and unknown are the same honest 404.
                raise ToolDenial("evidence_not_found", "Unknown evidence id.", status=404)
            ordered = sorted(items, key=lambda value: str(value.get("file", "")))[:MAX_EVIDENCE_ITEMS]
            if index >= len(ordered):
                raise ToolDenial("evidence_not_found", "Unknown evidence id.", status=404)
            return ordered[index], root
        # Path form: only files the context can already see resolve; a path
        # held solely by an out-of-scope project is an honest miss.
        for root, items in sorted(roots.items()):
            for item in items:
                if str(item.get("file") or "") == path:
                    return item, root
        raise ToolDenial("evidence_not_found",
                         "No indexed evidence for this path in the calling principal's scope.",
                         status=404)

    # -- index.status ------------------------------------------------------------

    def _tool_index_status(self, arguments: dict) -> dict:
        if arguments:
            raise ToolArgumentError("index.status takes no arguments")
        principal_view = _principal_view(self.principal)
        if self.api is not None:
            health = self.api.health()
            health.update({"ok": True, "backend": "http", "api": self.base_url_public(),
                           "principal": principal_view, "readOnly": True})
            return health
        context = self._local_context()
        jobs = query_api.load_persisted_index_jobs(None, context)
        return {
            "ok": True,
            "service": "uyp-mcp",
            "version": VERSION,
            "backend": "direct",
            "principal": principal_view,
            "readOnly": True,
            "knowledgeItems": len(_scoped_items(context)),
            "accessContext": True,
            "connector": query_api.configured_connector_status(),
            "connectorRegistry": query_api.registry_health(),
            "indexJobs": query_api.index_jobs_health(context),
            "jobs": jobs[:20],
            "interactiveLock": os.path.exists(knowledge_search.INTERACTIVE_LOCK),
        }

    def base_url_public(self) -> str:
        return self.api_url or ""


# ---------------------------------------------------------------------------
# MCP tool declarations
# ---------------------------------------------------------------------------

READ_ONLY_NOTE = ("Read-only. Results are scoped to the calling member's HomeHub "
                  "grants; out-of-scope projects are indistinguishable from missing ones.")

TOOLS = [
    {
        "name": "project.search",
        "description": "Search the indexed project knowledge and return a cited "
                       "answer (same per-member enforcement as the voice/Studio "
                       "knowledge search). " + READ_ONLY_NOTE,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language question about the indexed projects.",
                          "maxLength": MAX_QUERY_CHARS},
                "project_id": {"type": "string", "description": "Optional project capability id that narrows retrieval to one authorized project."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "project.get",
        "description": "Project summary, freshness, and IndexJob status for one "
                       "authorized project. " + READ_ONLY_NOTE,
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project capability id, e.g. 'demo-project' or 'project:demo-project'."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "project.related",
        "description": "Related files (UA graph imports), hub files, tags, and "
                       "other in-scope projects sharing tags or paths. Accepts a "
                       "query (lexical project match) or an explicit project_id. "
                       + READ_ONLY_NOTE,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Question used to pick the project (same lexical ranking as project.search)."},
                "project_id": {"type": "string", "description": "Explicit project capability id."},
            },
        },
    },
    {
        "name": "source.locate",
        "description": "Locate symbols or files with exact line ranges from the "
                       "indexed tree-sitter symbol tables (anchored enrichment "
                       "data). " + READ_ONLY_NOTE,
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Symbol name substring (case-insensitive), e.g. 'sign_request'."},
                "file_pattern": {"type": "string", "description": "glob matched against indexed file paths, e.g. 'src/*.py'."},
                "project_id": {"type": "string", "description": "Restrict to one authorized project."},
                "limit": {"type": "integer", "description": f"Max matches (default {DEFAULT_LOCATE_LIMIT}, max {MAX_LOCATE_LIMIT})."},
            },
        },
    },
    {
        "name": "source.read_evidence",
        "description": "Read the indexed bounded evidence backing a knowledge "
                       "item: labelled key points with line ranges, components, "
                       "anchor, and the verbatim raw head when the indexer kept "
                       "one. Serves indexed evidence only — never the live "
                       "source tree. " + READ_ONLY_NOTE,
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "Evidence id from project.get/project.search, e.g. 'knowledge:demo-project:0'."},
                "path": {"type": "string", "description": "Indexed file path (as cited in results) instead of an item_id."},
                "lines": {"type": "array", "items": {"type": "integer"}, "description": "Optional [lo, hi] line window to filter cited key points."},
            },
        },
    },
    {
        "name": "index.status",
        "description": "Index job/queue/worker status: scoped knowledge count, "
                       "job phases, connector and registry health.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]
TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS)

SERVER_INSTRUCTIONS = (
    "UnderstandYourProjects read-only knowledge tools. Every call is scoped to "
    "the configured MCP principal's HomeHub grants and fails closed without one; "
    "denials are honest results, not errors to retry with different paths.")


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 stdio server (MCP subset: initialize, ping, tools/*)
# ---------------------------------------------------------------------------


def _response(request_id, result=None, error=None) -> dict:
    message = {"jsonrpc": JSONRPC, "id": request_id}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result
    return message


def _rpc_error(code: int, message: str, data=None) -> dict:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return error


class McpStdioServer:
    """Newline-delimited JSON-RPC 2.0 MCP server over stdio (stdlib only)."""

    def __init__(self, runner: ToolRunner):
        self.runner = runner
        self.initialized = False

    # -- request handling ---------------------------------------------------

    def handle_message(self, message) -> dict | None:
        """Handle one decoded message; returns the response or None (notification)."""
        if not isinstance(message, dict):
            return _response(None, error=_rpc_error(ERROR_INVALID_REQUEST, "Invalid Request"))
        # MCP 2025-06-18 removed JSON-RPC batching; reject arrays at the caller.
        method = message.get("method")
        request_id = message.get("id")
        if not isinstance(method, str) or not method:
            return _response(request_id if isinstance(request_id, (str, int)) else None,
                             error=_rpc_error(ERROR_INVALID_REQUEST, "Invalid Request"))
        if method.startswith("notifications/"):
            return None  # notifications never get a response, even unknown ones
        if method == "initialize":
            return self._initialize(message, request_id)
        if not self.initialized:
            return _response(request_id, error=_rpc_error(
                ERROR_NOT_INITIALIZED, "Server not initialized"))
        if method == "ping":
            return _response(request_id, result={})
        if method == "tools/list":
            return _response(request_id, result={"tools": TOOLS})
        if method == "tools/call":
            return self._tools_call(message, request_id)
        return _response(request_id, error=_rpc_error(ERROR_METHOD_NOT_FOUND, f"Method not found: {method}"))

    def _initialize(self, message: dict, request_id) -> dict:
        params = message.get("params")
        if params is not None and not isinstance(params, dict):
            return _response(request_id, error=_rpc_error(ERROR_INVALID_PARAMS, "params must be an object"))
        requested = str((params or {}).get("protocolVersion") or "")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        self.initialized = True
        return _response(request_id, result={
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": VERSION},
            "instructions": SERVER_INSTRUCTIONS,
        })

    def _tools_call(self, message: dict, request_id) -> dict:
        params = message.get("params")
        if not isinstance(params, dict):
            return _response(request_id, error=_rpc_error(ERROR_INVALID_PARAMS, "params must be an object"))
        name = params.get("name")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(name, str) or name not in TOOL_NAMES:
            return _response(request_id, error=_rpc_error(
                ERROR_INVALID_PARAMS, f"Unknown tool: {name!r}", data={"tools": sorted(TOOL_NAMES)}))
        if not isinstance(arguments, dict):
            return _response(request_id, error=_rpc_error(ERROR_INVALID_PARAMS, "arguments must be an object"))
        try:
            payload = self.runner.call(name, arguments)
            return _response(request_id, result={
                "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                "isError": False,
            })
        except ToolArgumentError as exc:
            # MCP tools/call: invalid arguments are a JSON-RPC -32602 error.
            return _response(request_id, error=_rpc_error(
                ERROR_INVALID_PARAMS, exc.message,
                data={"auditId": getattr(exc, "audit_id", None)}))
        except ToolDenial as denial:
            body = {"ok": False, "error": denial.error, "message": denial.message,
                    "status": denial.status, "readOnly": True}
            audit = getattr(denial, "audit_id", None)
            if audit:
                body["auditId"] = audit
            return _response(request_id, result={
                "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}],
                "isError": True,
            })
        except Exception:  # pragma: no cover - defensive; keep the session alive
            traceback.print_exc(file=sys.stderr)
            return _response(request_id, error=_rpc_error(ERROR_INTERNAL, "Internal error"))

    # -- stdio loop -----------------------------------------------------------

    def serve(self, stream_in, stream_out) -> None:
        """Read newline-delimited JSON-RPC until EOF; write one-line responses."""
        while True:
            line = stream_in.readline()
            if not line:
                break
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                self._write(stream_out, _response(
                    None, error=_rpc_error(ERROR_PARSE, "Parse error")))
                continue
            if isinstance(message, list):
                self._write(stream_out, _response(
                    None, error=_rpc_error(
                        ERROR_INVALID_REQUEST,
                        "Invalid Request: batch messages are not supported")))
                continue
            response = self.handle_message(message)
            if response is not None:
                self._write(stream_out, response)

    @staticmethod
    def _write(stream, message: dict) -> None:
        stream.write(json.dumps(message, ensure_ascii=False) + "\n")
        stream.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UnderstandYourProjects read-only MCP stdio server (P6)")
    parser.add_argument("--api", default=None, metavar="URL",
                        help="query API base URL (e.g. http://127.0.0.1:8787); "
                             "omit to run in direct mode over the shared functions")
    parser.add_argument("--principal", default=None, metavar="MEMBER",
                        help="HomeHub member the agent acts for (member tier; "
                             "env UYP_MCP_PRINCIPAL; requires a loopbound --api "
                             "in HTTP mode, exactly like the voice handshake)")
    parser.add_argument("--version", action="version", version=f"{SERVER_NAME} {VERSION}")
    args = parser.parse_args(argv)
    principal = resolve_principal(args.principal)
    runner = ToolRunner(api_url=args.api, principal=principal)
    if principal["tier"] is None:
        sys.stderr.write(
            json.dumps({"server": SERVER_NAME, "warning": "no principal configured",
                        "hint": "set UYP_MCP_PRINCIPAL or UYP_MCP_TOKEN_FILE; "
                                "every tool call will be denied principal_required"}) + "\n")
    server = McpStdioServer(runner)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    server.serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
