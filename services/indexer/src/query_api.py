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
import json
import os
import glob
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from knowledge_search import answer as search_answer, load_items


VERSION = "0.1.0"
DEFAULT_OUTPUT = "~/dev/uyp/output"
DEFAULT_STATE = "~/dev/uyp/state"
MAX_BODY = 64 * 1024


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


def load_access_context() -> dict | None:
    path = os.environ.get("UYP_ACCESS_CONTEXT_FILE")
    if not path:
        return None
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            value = json.load(fh)
        if not isinstance(value, dict):
            return None
        # The service accepts a projection from HomeHub; it does not infer one.
        required = {"principalId", "sessionId", "jarvisNodeId", "projectScopes", "sourceScopes", "grantEpoch", "policyDigest", "expiresAt", "auditId"}
        return value if required.issubset(value) and access_context_valid(value) else None
    except (OSError, json.JSONDecodeError):
        return None


def access_context_valid(context: dict) -> bool:
    if context.get("revoked") is True or context.get("validation") in {"revoked", "expired"}:
        return False
    try:
        expires = datetime.fromisoformat(str(context["expiresAt"]).replace("Z", "+00:00"))
        return expires > datetime.now(timezone.utc)
    except (KeyError, TypeError, ValueError):
        return False


def item_root(path: str) -> str:
    return os.path.basename(os.path.dirname(path))


def grouped_items() -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for path in glob.glob(os.path.join(output_root(), "*", "*.knowledge.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                item = json.load(fh)
            item["_out_path"] = path
        except (OSError, json.JSONDecodeError):
            continue
        groups.setdefault(item_root(path), []).append(item)
    return groups


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


def load_nandatown_peers() -> list[dict]:
    """Load public directory metadata emitted by the NandaTown adapter only."""
    path = os.environ.get("UYP_NANDATOWN_DIRECTORY_FILE")
    if not path:
        return []
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            value = json.load(fh)
        peers = value.get("peers", []) if isinstance(value, dict) else value
        if not isinstance(peers, list):
            return []
        allowed = {"peerId", "nodeId", "displayLabel", "handle", "transport", "trust", "status", "lastSeen", "capabilities", "advertisedProjectCount"}
        return [{key: peer[key] for key in peer.keys() & allowed} for peer in peers if isinstance(peer, dict) and peer.get("peerId") and peer.get("displayLabel")]
    except (OSError, json.JSONDecodeError):
        return []


def project_snapshot(project_id: str | None = None) -> dict:
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
    root = requested_root if requested_root in groups else next(iter(groups), "Access context pending" if context is None else "No authorized project")
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
    evidence = []
    for index, item in enumerate(sorted(items, key=lambda value: value.get("file", ""))[:200]):
        derived = item.get("derived") or {}
        summary = str(derived.get("purpose") or "Structure metadata only")
        kind = "inference" if derived.get("purpose") else "structure"
        evidence.append({
            "evidenceId": f"knowledge:{root}:{index}", "projectId": project_key, "sourceId": source_id,
            "knowledgeVersion": str(item.get("version", {}).get("mtime", "")),
            "locator": {"path": item.get("file")}, "kind": kind, "summary": summary,
            "freshness": "current", "visibility": "private", "producingJarvis": context.get("jarvisNodeId") if context else None,
        })
    evidence = [{k: v for k, v in entry.items() if v is not None} for entry in evidence]
    state = "current" if items and connector["state"] == "current" else "partial" if items else "unsupported"
    reason = None if state == "current" else "Knowledge output exists, but connector freshness or HomeHub context is not attached."
    source = {"sourceId": source_id, "label": root if visible_project else "Authorized source pending", "kind": "local", "state": connector["state"] if context else "unsupported", "detail": connector["detail"] if context else "HomeHub AccessContext required before source metadata is published"}
    node_id = (context or {}).get("jarvisNodeId") or "agent-node-pending"
    node_pairing = "paired" if context else "discovered"
    node_transport = os.environ.get("UYP_AGENT_TRANSPORT", "unknown") if context else "unknown"
    connector_projection = {"connectorId": source_id, "nodeId": node_id, "kind": "local", "label": root, "state": connector["state"], "manifestState": "ready" if items else "pending", "sourceIds": [source_id]}
    snapshot = {
        "project": {
            "projectId": project_key, "sourceId": source_id, "name": root if visible_project else "Project scope unavailable",
            "description": f"{len(items)} authorized KnowledgeItems with a vendored UA structure graph." if visible_project and ua_graph else (f"{len(items)} authorized KnowledgeItems from the Agent Box output store." if visible_project else "HomeHub has not supplied a project scope to Studio."),
            "languages": graph_project.get("languages", []) if visible_project else [], "frameworks": graph_project.get("frameworks", []) if visible_project else [],
            "counts": {"files": graph_files or len(items), "nodes": len(graph_nodes) or len(items), "relations": len(graph_edges), "layers": layers},
            "entryPoints": [item.get("file") for item in items[:4] if item.get("file")] if visible_project else [],
            "knowledgeVersion": updated, "sourceEpoch": updated, "freshness": state, "updatedAt": updated,
            "schemaVersion": graph_project.get("graphVersion") or ua_graph.get("version") if ua_graph else None,
            "visibility": "private" if visible_project else None,
            "grantEpoch": context.get("grantEpoch") if context else None,
            "policyDigest": context.get("policyDigest") if context else None,
            "auditId": context.get("auditId") if context else None,
        },
        "health": {
            "state": state, "knowledgeVersion": updated, "sourceEpoch": updated,
            "coverage": {"filesIndexed": len(items)}, "lastSuccessfulAt": updated,
            "connectorStatus": connector["state"], "reason": reason,
        },
        "evidence": evidence, "evidenceOrigin": "service" if items else "graph-fallback",
        "jobs": [{"jobId": f"job:{root}:{updated}", "projectId": project_key, "sourceId": source_id,
                  "phase": "published" if items else "discovered", "progress": {"processed": len(items), "total": len(items)},
                  "knowledgeVersion": updated, "finishedAt": updated}],
        "sources": [source],
        "agentNodes": [{"nodeId": node_id, "label": os.environ.get("UYP_AGENT_LABEL", "Jetson Agent Box") if context else "Jetson Agent Box · identity pending", "transport": node_transport, "pairing": node_pairing, "lastSeen": updated if items else None, "capabilities": ["Incremental index", "Knowledge search", "Evidence citations"], "connectorIds": [source_id]}],
        "connectors": [connector_projection],
        "peers": load_nandatown_peers(),
    }
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


def scope_allows(context: dict, item: dict) -> bool:
    path = str(item.get("file", ""))
    project = item_root(str(item.get("_out_path", "")))
    projects = [str(value) for value in context.get("projectScopes", [])]
    sources = [str(value) for value in context.get("sourceScopes", [])]
    project_allowed = "*" in projects or project in projects or f"project:{project}" in projects
    source_ids = {str(item.get("source", "")), f"connector:{project}"}
    source_allowed = "*" in sources or bool(source_ids.intersection(sources))
    # Source scopes are capability identifiers, never arbitrary paths. The
    # Connector remains the only component allowed to resolve a path.
    return project_allowed and source_allowed


class QueryHandler(BaseHTTPRequestHandler):
    def _headers(self, audit: str) -> None:
        allowed = os.environ.get("UYP_CORS_ORIGIN", "http://127.0.0.1:4173,http://localhost:4173")
        self.send_header("Access-Control-Allow-Origin", allowed.split(",")[0])
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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
            items = sum(len(value) for value in grouped_items().values())
            self.json_response({"ok": True, "service": "uyp-query-api", "version": VERSION, "knowledgeItems": items, "accessContext": bool(load_access_context()), "connector": configured_connector_status()}, audit=audit)
            return
        if parsed.path == "/api/studio/snapshot":
            self.json_response(project_snapshot((query.get("projectId") or [None])[0]), audit=audit)
            return
        if parsed.path == "/api/knowledge-graph":
            context = load_access_context()
            if context is None:
                self.json_response({"ok": False, "error": "access_context_unavailable", "message": "HomeHub must provide an AccessContext before the UA graph can be published."}, 503, audit)
                return
            snapshot = project_snapshot((query.get("projectId") or [None])[0])
            graph = snapshot.get("graph")
            if graph is None:
                self.json_response({"ok": False, "error": "knowledge_graph_unavailable"}, 404, audit)
            else:
                self.json_response(graph, audit=audit)
            return
        if parsed.path == "/api/sources":
            self.json_response({"sources": project_snapshot((query.get("projectId") or [None])[0])["sources"]}, audit=audit)
            return
        if parsed.path == "/api/nandatown/peers":
            self.json_response({"peers": load_nandatown_peers(), "metadataOnly": True}, audit=audit)
            return
        if parsed.path == "/api/index/jobs":
            self.json_response({"jobs": project_snapshot((query.get("projectId") or [None])[0])["jobs"]}, audit=audit)
            return
        if parsed.path.startswith("/api/knowledge/evidence/"):
            evidence_id = parsed.path.rsplit("/", 1)[-1]
            evidence = next((item for item in project_snapshot((query.get("projectId") or [None])[0])["evidence"] if item["evidenceId"] == evidence_id), None)
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
        if parsed.path != "/api/knowledge/search":
            self.json_response({"ok": False, "error": "not_found"}, 404, audit)
            return
        context = load_access_context()
        if context is None:
            self.json_response({"ok": False, "error": "access_context_unavailable", "message": "HomeHub must provide an AccessContext before project knowledge can be searched."}, 503, audit)
            return
        question = str(payload.get("query", "")).strip()
        if not question:
            self.json_response({"ok": False, "error": "query_required"}, 400, audit)
            return
        allowed_items = [item for values in grouped_items().values() for item in values if scope_allows(context, item)]
        result = search_answer(question, allowed_items)
        result.update({"ok": True, "auditId": audit, "projectId": payload.get("projectId"), "access": {"grantEpoch": context.get("grantEpoch"), "expiresAt": context.get("expiresAt")}})
        self.json_response(result, audit=audit)

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
    print(f"uyp-query-api v{VERSION} on {host}:{args.port} output={output_root()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
