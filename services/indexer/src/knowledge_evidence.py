#!/usr/bin/env python3
"""KnowledgeEvidence producer — the first runtime producer of the E7
frozen query contract (harness_contracts.connector.KnowledgeEvidence).

The 2026-10 contract audit found four inconsistent "evidence-ish"
shapes across the runtime (KnowledgeItem, mirror record, gbrain
frontmatter, Studio evidence) and zero actual producers of the frozen
contract.  This module is the fix: every evidence projection inside
the query API (search ``evidence[]``, legacy ``sources[]``, AGENTFLOW
``citations[]``, and the Studio snapshot evidence panel) is derived
from ONE list of contract records built here.

Contract notes (jetson/packages/harness_contracts, vendored beside
this file so the deployed service and its tests import the very same
class it emits):

- The six frozen fields (source_id, source_version, locator, content,
  permission_checked, retrieved_at) keep their frozen semantics.
- The 2026-10-18 additive extension (graph_version, node_ids,
  edge_ids, index_as_of, freshness, fact_type, provider, model_id) is
  Optional; records are emitted through the pydantic model and dumped
  with exclude_none so absent extensions simply do not appear.

Honesty rules enforced here, not just documented:

- permission_checked is true ONLY on paths that really passed a scope
  gate before retrieval (search: query_api.scope_allows per item;
  ask: the project-level visible() gate in project_digest).  An
  out-of-scope path never yields a record — evidence is dropped, not
  downgraded to permission_checked=false and surfaced.
- content is the indexed fragment the synthesis actually consumed,
  never model-reworded prose from the answer.
- freshness is computed from real timestamps (see FRESH_MAX_SECONDS);
  unknown when no timestamp can be proven.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone

from harness_contracts.connector import FactType, Freshness, KnowledgeEvidence

# provider/model_id: the local Jetson pipeline that produced the record.
# model_id mirrors the synthesis model env used across the indexer
# (knowledge_search / project_digest default), so evidence never claims
# a model the answer path did not use.
PROVIDER = "local"
DEFAULT_MODEL_ID = "qwen3.5-route"

# Freshness thresholds (age of the project index edition, i.e. the
# newest timestamp it can prove).  The Jetson index cadence is
# timer-driven (indexjob + grant-renewal timers, several runs a day);
# anything within 48h of "now" is fresh, older-but-dated is stale, and
# a project whose items carry no parseable timestamp at all is unknown.
FRESH_MAX_SECONDS = 48 * 3600

# Graph-ref caps: a single evidence record names at most this many
# node/edge ids so one hot file cannot bloat the response payload.
MAX_NODE_IDS = 8
MAX_EDGE_IDS = 16

_ANCHOR_LINES_RE = re.compile(r"L(\d+)-L(\d+)\s*$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def model_id() -> str:
    return os.environ.get("UYP_OLLAMA_MODEL", DEFAULT_MODEL_ID)


# ---- item accessors (raw KnowledgeItem and project_digest compact item) ---


def _file_of(item: dict) -> str:
    return str(item.get("file") or "")


def _version_of(item: dict) -> dict:
    version = item.get("version")
    if isinstance(version, dict):
        return version
    # Compact ask-path items carry the parsed mtime directly.
    mtime = item.get("mtime")
    return {"mtime": mtime} if isinstance(mtime, (int, float)) and not isinstance(mtime, bool) else {}


def _purpose_of(item: dict) -> str:
    derived = item.get("derived")
    purpose = (derived or {}).get("purpose") if isinstance(derived, dict) else None
    if not purpose:
        purpose = item.get("purpose")
    return str(purpose).strip() if isinstance(purpose, str) and purpose.strip() else ""


def _anchor_of(item: dict) -> str:
    return str(item.get("anchor_top") or "")


def _epoch_of(value) -> float | None:
    """Best-effort epoch for mtime/analyzed_at values of either shape."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            number = float(text)
            return number if number > 0 else None
        except ValueError:
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return None
    return None


def _item_epoch(item: dict) -> float | None:
    """Newest provable timestamp for one item (mtime wins, analyzed_at fallback)."""
    version = _version_of(item)
    for key in ("mtime", "time", "at"):
        epoch = _epoch_of(version.get(key))
        if epoch is not None:
            return epoch
    return _epoch_of(item.get("analyzed_at"))


# ---- field builders ---------------------------------------------------------


def source_version_of(item: dict) -> str:
    """Serialize item.version{mtime,size} into a stable edition pin.

    Deterministic key order (mtime, then size); absent keys are simply
    omitted, and an item with no version metadata at all pins to
    "unversioned" rather than inventing an edition.  Integral floats
    (the ask path's parsed mtime) print without a trailing .0 so both
    retrieval paths pin the same edition string for the same file.
    """
    def fmt(value):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    version = _version_of(item)
    parts = [f"{key}={fmt(version[key])}" for key in ("mtime", "size") if version.get(key) is not None]
    return ";".join(parts) if parts else "unversioned"


def mtime_from_source_version(source_version: str) -> str:
    """Recover the legacy ``str(version.mtime)`` projection.

    citations[] and the Studio snapshot published the raw mtime string
    long before the contract existed; deriving it back from the single
    evidence record keeps those projections value-compatible.  Items
    with no mtime keep the legacy empty string, never "unversioned".
    """
    for part in str(source_version or "").split(";"):
        key, _, value = part.partition("=")
        if key.strip() == "mtime":
            return value
    return ""


def locator_of(item: dict) -> str:
    """relpath, with the anchor's line span appended when one exists.

    anchor_top has the shape "main L10-L42"; the locator keeps the
    path addressable ("src/main.py#L10-L42") so a later verification
    can re-read the same place.  Un-anchored items stay a bare path.
    """
    path = _file_of(item)
    match = _ANCHOR_LINES_RE.search(_anchor_of(item))
    if match:
        lo, hi = int(match.group(1)), int(match.group(2))
        if lo > 0 and hi >= lo:
            return f"{path}#L{lo}-L{hi}"
    return path


def content_of(item: dict) -> str:
    """The quoted fragment retrieval actually fed to synthesis.

    Verbatim from the index, never reworded by the answer model: the
    derived purpose when the item was semantically enriched, otherwise
    the same structure-only marker the synthesis context block uses.
    """
    purpose = _purpose_of(item)
    if purpose:
        return purpose
    derived = item.get("derived")
    if isinstance(derived, dict) and derived:
        structural = {k: v for k, v in derived.items() if k in ("lines", "py_defs", "imports")}
        if structural:
            return "structure-only: " + json.dumps(structural, ensure_ascii=False)
    return "structure-only"


def fact_type_of(item: dict) -> str:
    """semantic = model-authored summary in the index; structural = pure
    structure metadata.  inferred/runtime are produced explicitly by
    the paths that compute cross-record facts (see build_evidence)."""
    return FactType.SEMANTIC.value if _purpose_of(item) else FactType.STRUCTURAL.value


def freshness_of(index_as_of_value: str | None, *, now: float | None = None) -> str:
    """Real age verdict of the index edition the record was read from."""
    epoch = _epoch_of(index_as_of_value)
    if epoch is None:
        return Freshness.UNKNOWN.value
    age = (time.time() if now is None else now) - epoch
    return Freshness.FRESH.value if age <= FRESH_MAX_SECONDS else Freshness.STALE.value


def project_index_as_of(items: list[dict]) -> str | None:
    """Newest provable timestamp across a project's items, local time."""
    epochs = [e for e in (_item_epoch(i) for i in items) if e is not None]
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(max(epochs))) if epochs else None


# ---- graph refs -------------------------------------------------------------


class GraphIndex:
    """filePath -> node/edge ids lookup over one loaded UA graph.

    Built once per graph edition (the Jetson graph is ~25 MB of JSON);
    callers keep the instance so per-record lookups stay O(1).
    """

    def __init__(self, graph: dict):
        self.version = str((graph or {}).get("version") or "") or None
        by_file: dict[str, list[str]] = {}
        for node in (graph or {}).get("nodes") or []:
            if isinstance(node, dict) and node.get("id"):
                by_file.setdefault(str(node.get("filePath") or ""), []).append(str(node["id"]))
        self._by_file = by_file
        adjacency: dict[str, list[str]] = {}
        for edge in (graph or {}).get("edges") or []:
            if isinstance(edge, dict) and edge.get("source") and edge.get("target"):
                rendered = f"{edge['source']}->{edge['target']}"
                adjacency.setdefault(str(edge["source"]), []).append(rendered)
                adjacency.setdefault(str(edge["target"]), []).append(rendered)
        self._adjacency = adjacency

    def refs_for(self, path: str) -> tuple[str | None, list[str] | None, list[str] | None]:
        node_ids = self._by_file.get(path) or []
        if not node_ids:
            return self.version, None, None
        seen: list[str] = []
        for node_id in node_ids[:MAX_NODE_IDS]:
            for rendered in self._adjacency.get(node_id) or []:
                if rendered not in seen:
                    seen.append(rendered)
                if len(seen) >= MAX_EDGE_IDS:
                    break
        return (self.version, node_ids[:MAX_NODE_IDS], seen[:MAX_EDGE_IDS] or None)


# ---- the producer -----------------------------------------------------------


def build_evidence(
    result_sources: list | None,
    items: list[dict],
    *,
    gate=None,
    default_root: str | None = None,
    graph_provider=None,
    retrieved_at: str | None = None,
    inferred_content: dict[str, str] | None = None,
    now: float | None = None,
) -> list[dict]:
    """Join retrieval outputs to (already scope-filtered) items and emit
    one contract KnowledgeEvidence record per CITED item.

    Parameters
    ----------
    result_sources:
        the retrieval layer's ``sources`` (``{"file": ..., ...}``);
        only files that join back to ``items`` produce evidence — an
        out-of-scope path yields NO record, never a fabricated one.
    items:
        the items the caller may see (search: scoped_items output;
        ask: the visible project's compact items).
    gate:
        optional per-item scope predicate (search passes
        query_api.scope_allows).  When given, an item failing it is
        dropped even if it joined — permission_checked=true is only
        ever emitted for paths that really passed a gate.
    default_root:
        project root for items that carry no ``_out_path`` (the ask
        path is single-project by construction).
    graph_provider:
        ``root -> GraphIndex | None``; absent provider leaves the
        optional graph refs unset (contract-legal).
    inferred_content:
        optional ``file -> computed statement`` map for cross-record
        facts (e.g. the temporal path's index-boundary statement);
        those records are classified fact_type=inferred.
    """
    by_file: dict[str, dict] = {}
    for item in items:
        path = _file_of(item)
        if path and path not in by_file:
            by_file[path] = item
    stamp = retrieved_at or now_iso()
    inferred_content = inferred_content or {}
    per_root: set[str] = set()
    per_project_as_of: dict[str, str | None] = {}
    graph_cache: dict[str, object] = {}
    records: list[dict] = []

    def root_of(item: dict) -> str:
        return _root_of(item) or str(default_root or "")

    for source in result_sources or []:
        if not isinstance(source, dict):
            continue
        path = str(source.get("file") or "")
        item = by_file.get(path)
        if item is None:
            continue  # cited but out of scope: no evidence record
        if gate is not None and not gate(item):
            continue
        root = root_of(item)
        if root not in per_root:
            per_root.add(root)
            per_project_as_of[root] = project_index_as_of(
                [i for i in items if root_of(i) == root])
        index_as_of_value = per_project_as_of[root]
        graph_version = node_ids = edge_ids = None
        if graph_provider is not None and root:
            if root not in graph_cache:
                graph_cache[root] = graph_provider(root)
            index = graph_cache[root]
            if index is not None:
                graph_version, node_ids, edge_ids = index.refs_for(path)
        fact_type = (
            FactType.INFERRED.value if path in inferred_content
            else fact_type_of(item)
        )
        record = KnowledgeEvidence(
            source_id=f"connector:{root}" if root else "connector:unknown",
            source_version=source_version_of(item),
            locator=locator_of(item),
            content=inferred_content.get(path) or content_of(item),
            permission_checked=True,
            retrieved_at=stamp,
            graph_version=graph_version,
            node_ids=node_ids,
            edge_ids=edge_ids,
            index_as_of=index_as_of_value,
            freshness=freshness_of(index_as_of_value, now=now),
            fact_type=fact_type,
            provider=PROVIDER,
            model_id=model_id(),
        )
        records.append(record.model_dump(exclude_none=True))
    return records


def _root_of(item: dict) -> str:
    """Project root of an item: the output-store bucket (search path
    carries ``_out_path``), else nothing (ask path is single-project)."""
    out_path = str(item.get("_out_path") or "")
    if out_path:
        parts = [p for p in out_path.replace("\\", "/").split("/") if p]
        return parts[-2] if len(parts) >= 2 else ""
    return ""


# ---- legacy projections derived FROM the evidence list ----------------------


def sources_from_evidence(evidence: list[dict], origin_sources: list | None) -> list[dict]:
    """Legacy ``sources[]`` shape, derived from the evidence records.

    Order and per-file extras (match/ts) come from the retrieval
    layer's original list; membership comes from the evidence join, so
    sources can never list a file that produced no evidence.
    """
    cited = {str(r.get("locator") or "").split("#", 1)[0]: r for r in evidence}
    projected = []
    for source in origin_sources or []:
        if not isinstance(source, dict):
            continue
        path = str(source.get("file") or "")
        if path not in cited:
            continue
        entry = {"file": path}
        for key in ("match", "ts"):
            if source.get(key) is not None:
                entry[key] = source.get(key)
        projected.append(entry)
    return projected


def citations_from_evidence(evidence: list[dict], context: dict | None,
                            origin_sources: list | None = None) -> list[dict]:
    """AGENTFLOW section-5 citations, derived from the evidence records
    (previously rebuilt ad hoc from raw items — same output, one source
    of truth now).  ``origin_sources`` only carries the retrieval
    layer's per-file extras (match/ts) back in; membership itself comes
    from the evidence join."""
    extras: dict[str, dict] = {}
    for source in origin_sources or []:
        if isinstance(source, dict) and source.get("file"):
            extras[str(source["file"])] = source
    citations = []
    for record in evidence:
        locator = str(record.get("locator") or "")
        path, _, anchor = locator.partition("#")
        root = str(record.get("source_id") or "").removeprefix("connector:")
        mtime = mtime_from_source_version(str(record.get("source_version") or ""))
        fresh = record.get("freshness")
        citations.append({
            "projectId": f"project:{root}",
            "sourceId": record.get("source_id"),
            "file": path,
            "match": extras.get(path, {}).get("match"),
            "knowledgeVersion": mtime,
            "sourceEpoch": mtime,
            "evidenceLevel": "inference" if record.get("fact_type") == FactType.SEMANTIC.value else "structure",
            "lineRange": anchor or None,
            "freshness": {"fresh": "current", "stale": "stale"}.get(fresh, "unknown"),
            "producingJarvis": (context or {}).get("jarvisNodeId"),
            # Reading access does not imply permission to reshare evidence.
            "allowedToShare": False,
        })
    return citations


def studio_entry_from_evidence(record: dict, *, evidence_id: str, project_key: str,
                               anchor_top, producing_jarvis) -> dict:
    """Studio snapshot evidence entry, derived from the evidence record.

    Field-for-field the v3.2 Studio shape (evidenceId/anchorTop stay
    snapshot-owned; kind tracks fact_type; summary IS the record's
    content) so the panel's contract is unchanged while its data now
    flows from the same records the search API returns.
    """
    locator = str(record.get("locator") or "")
    path = locator.partition("#")[0]
    fresh = record.get("freshness")
    entry = {
        "evidenceId": evidence_id,
        "projectId": project_key,
        "sourceId": record.get("source_id"),
        "knowledgeVersion": mtime_from_source_version(str(record.get("source_version") or "")),
        # Studio locator stays the legacy {"path": ...} shape; the line
        # span lives on in anchorTop, exactly as the panel expects.
        "locator": {"path": path},
        "kind": "inference" if record.get("fact_type") == FactType.SEMANTIC.value else "structure",
        "summary": record.get("content"),
        "anchorTop": anchor_top,
        "freshness": {"fresh": "current", "stale": "stale"}.get(fresh, "unknown"),
        "visibility": "private",
        "producingJarvis": producing_jarvis,
    }
    return {k: v for k, v in entry.items() if v is not None}
