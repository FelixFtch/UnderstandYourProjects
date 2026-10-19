#!/usr/bin/env python3
"""knowledge_core.core — the one authorized knowledge-search pipeline.

Shared by the UYP query API (:8787) and the household knowledge-service
(:8790).  Both front doors resolve a server-side credential FIRST (HomeHub
AccessContext projection / :8790 credential lanes), build a
``KnowledgeQueryRequest`` from it, call ``authorized_search()``, and project
the ``KnowledgeQueryResult`` into their own response shape.

Invariants this module is responsible for (2026-10 extraction):

- Identity never arrives in a request body.  The request carries a
  principal that a credential already vouched for; the core only
  re-validates structure (non-empty principal, non-empty grants,
  non-negative epoch) and never widens anything.
- The resolved scope is handed INTO retrieval (``retriever`` receives the
  ``ResolvedScope``; gbrain backends turn slug prefixes into pre-filters
  inside ``search_brain``).  Nothing is retrieved first and masked later;
  the items path's evidence gate is a defensive re-check, and an item that
  fails it produces NO evidence record — it is never downgraded to
  ``permission_checked=false`` and surfaced.
- ``permission_checked`` is True only on paths that really passed the scope
  gate.  A structurally invalid request yields a denied result with
  ``permission_checked=False`` and no evidence, never a degraded search.
- Qwen never judges permission; synthesis (when an items backend composes
  an answer) only rewrites what an already-authorized retrieval returned.

The two retrieval families differ by what the backend returns:

- ``retriever`` (items mode, :8787): the full list of scope-allowed
  KnowledgeItems; the core ranks them lexically, composes the answer
  (lexical hit -> qwen synthesis; temporal question -> temporal answer),
  and joins the cited sources back to contract KnowledgeEvidence records
  via the host tree's ``knowledge_evidence.build_evidence``.
- ``blocks_retriever`` (blocks mode, :8790): already-ranked retrieval
  blocks from the gbrain ring; the core projects them through
  ``evidence_from_blocks`` (same six frozen contract fields plus the
  additive extensions) and leaves answer composition to the voice chain.
"""
from __future__ import annotations

import os
import glob
import json
from dataclasses import dataclass, field
from typing import Callable

from .evidence import FRESHNESS_WINDOW_DAYS, evidence_from_blocks, freshness_of

# The canonical miss sentence (knowledge_search keeps the same constant);
# duplicated here so a denied/empty-scope result never needs the host tree.
MISS_SENTENCE = "Not in the indexed projects."

DEFAULT_OUTPUT_ROOT = "~/dev/uyp/output"

# Scope prefixes with slashes (gbrain slug scopes like
# "project_knowledge/<project>/<epoch>/") are passed into retrieval
# verbatim; bare capability tokens stay in the source set.
ItemsRetriever = Callable[["KnowledgeQueryRequest", "ResolvedScope"], list]
BlocksRetriever = Callable[["KnowledgeQueryRequest", "ResolvedScope"], tuple]


@dataclass(frozen=True)
class KnowledgeQueryRequest:
    """One authorized knowledge query.

    ``principal_id``/``grants``/``grant_epoch`` describe the CALLER a
    credential already resolved (HomeHub AccessContext on :8787, the
    credential lanes on :8790).  ``grants`` carries project capability
    scopes (``project:<name>`` entries, bare project names, or ``*``);
    ``source_scope`` carries source capability scopes (``connector:<id>``,
    ``*``) and, for slug-scoped backends, the verbatim retrieval prefixes
    (``project_knowledge/<project>/<epoch>/``).  ``auth_level`` is advisory
    metadata only — no permission decision is ever derived from it.
    """

    request_id: str
    session_id: str
    principal_id: str
    auth_level: str  # voice_verified / second_factor_verified / guest (advisory)
    grants: list[str]
    grant_epoch: int
    source_scope: list[str]
    query: str
    hint: str | None = None  # voice slow-answer hint, pass-through
    project: str | None = None  # selector; narrows AFTER scope filtering


@dataclass
class SourceSummary:
    """Legacy Studio ``sources[]`` entry, projected FROM evidence records."""

    file: str
    match: float | None = None
    ts: str | None = None


@dataclass
class ResolvedScope:
    """What the caller's grants actually allow, in retrieval terms."""

    projects: frozenset[str]  # verbatim projectScopes-style entries
    sources: frozenset[str]  # verbatim sourceScopes-style entries
    prefixes: tuple[str, ...]  # slug prefixes handed INTO retrieval
    epoch: int
    all_projects: bool = False
    all_sources: bool = False

    def allows_path(self, path: str) -> bool:
        return any(str(path or "").startswith(p) for p in self.prefixes)


@dataclass
class KnowledgeQueryResult:
    answer: str
    evidence: list  # contract KnowledgeEvidence records (dicts)
    sources: list  # SourceSummary entries (items mode) / [] (blocks mode)
    permission_checked: bool
    index_as_of: str | None
    freshness: str  # fresh / stale / unknown
    audit_id: str | None
    # Adapter-only data that never belongs to the shared contract:
    # confidence + slow (items), scores/brains_searched/hint (blocks), or
    # the denial code of a failed validation.
    extras: dict = field(default_factory=dict)


def validate_request(req: KnowledgeQueryRequest) -> str | None:
    """Structural validation; returns a denial code or None.

    Credential freshness/revocation was already decided where the caller's
    projection was resolved (homehub_adapter on :8787, the uyp_grants
    ledger re-read on :8790).  This is the shared second gate: a request
    without a principal, without any grant, or with a negative epoch never
    reaches a retriever.
    """
    if not str(req.principal_id or "").strip():
        return "principal_required"
    if not str(req.query or "").strip():
        return "query_required"
    if not req.grants and not req.source_scope:
        return "grants_required"
    if req.grant_epoch < 0:
        return "grant_epoch_invalid"
    return None


def _safe_state_component(value: str) -> str | None:
    text = str(value or "")
    if not text or text in {".", ".."} or "/" in text or "\\" in text or "\x00" in text:
        return None
    return text


def resolve_scope(req: KnowledgeQueryRequest) -> ResolvedScope:
    """Grants -> the sets and prefixes retrieval is allowed to touch."""
    return scope_from_grants(req.grants, req.source_scope, req.grant_epoch)


def scope_from_grants(grants, source_scope, epoch: int = 0) -> ResolvedScope:
    """Grant lists -> ResolvedScope (the parsing half of resolve_scope).

    Verbatim semantics of the :8787 scope gate are preserved: project
    entries match the output-store bucket (bare name or ``project:<name>``)
    and source entries match ``{item.source, connector:<project>}``;
    ``*`` widens exactly the dimension it appears in.  Entries with a
    slash are slug prefixes and are handed to the backend verbatim so the
    backend can filter BEFORE ranking (never after).
    """
    projects = frozenset(str(g) for g in grants or [])
    sources = frozenset(str(s) for s in source_scope or [])
    prefixes = tuple(sorted({str(s) for s in (source_scope or []) if "/" in str(s)}))
    epoch = int(epoch or 0)
    return ResolvedScope(
        projects=projects,
        sources=sources,
        prefixes=prefixes,
        epoch=epoch,
        all_projects="*" in projects,
        all_sources="*" in sources,
    )


def item_root(out_path) -> str:
    root, _ = os.path.split(str(out_path or ""))
    return os.path.basename(root)


def scope_allows_item(scope: ResolvedScope, item: dict) -> bool:
    """The shared per-item scope gate (ported verbatim from query_api).

    Source scopes are capability identifiers, never arbitrary paths; the
    Connector remains the only component allowed to resolve a path.
    """
    project = item_root(item.get("_out_path", ""))
    projects = set(scope.projects)
    sources = set(scope.sources)
    project_allowed = ("*" in projects or project in projects
                       or f"project:{project}" in projects)
    source_ids = {str(item.get("source", "")), f"connector:{project}"}
    source_allowed = "*" in sources or bool(source_ids & sources)
    return project_allowed and source_allowed


def output_root() -> str:
    return os.path.realpath(os.path.expanduser(
        os.environ.get("UYP_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT)))


def grouped_items() -> dict[str, list[dict]]:
    """Load the output store once per call: root -> KnowledgeItems."""
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


def scoped_items_for_scope(scope: ResolvedScope, project_id: str | None = None) -> list[dict]:
    """Apply the scope filter; fail closed without grants.

    ``/api/knowledge/search`` and ``/api/health`` must never disagree about
    how much knowledge is visible, so both use this one helper (moved here
    from query_api).  A project selector narrows AFTER HomeHub scope
    filtering — it is a selector, never an authorization grant.
    """
    requested = str(project_id or "").strip().removeprefix("project:")
    if requested and _safe_state_component(requested) is None:
        return []
    return [
        item
        for values in grouped_items().values()
        for item in values
        if scope_allows_item(scope, item)
        and (not requested or item_root(item.get("_out_path", "")) == requested)
    ]


def file_store_items(req: KnowledgeQueryRequest, scope: ResolvedScope) -> list[dict]:
    """Default items retriever: the UYP output store under the request scope."""
    return scoped_items_for_scope(scope, req.project)


def _lazy(module: str, name: str):
    """Import a host-tree helper late so blocks-only deployments stay lean."""
    import importlib
    return getattr(importlib.import_module(module), name)


def _sources_from_records(evidence: list, origin_sources: list | None) -> list[dict]:
    """Fallback projection of legacy ``sources[]`` from evidence records.

    Same contract as knowledge_evidence.sources_from_evidence (used when
    the host tree is importable): membership comes from the evidence join,
    order and per-file extras (match/ts) from the retrieval layer — sources
    can never list a file that produced no evidence.
    """
    cited = {str(r.get("locator") or "").split("#", 1)[0] for r in evidence}
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


def _denied(req: KnowledgeQueryRequest, code: str) -> KnowledgeQueryResult:
    return KnowledgeQueryResult(
        answer=MISS_SENTENCE,
        evidence=[],
        sources=[],
        permission_checked=False,
        index_as_of=None,
        freshness="unknown",
        audit_id=str(req.request_id) if req.request_id else None,
        extras={"error": code, "confidence": "none"},
    )


def _rollup_freshness(evidence: list, index_as_of: str | None,
                      now: float | None = None) -> str:
    """Result-level freshness: the newest edition the evidence can prove."""
    best: str | None = index_as_of
    for record in evidence:
        stamp = record.get("index_as_of") if isinstance(record, dict) else None
        if isinstance(stamp, str) and (best is None or stamp > best):
            best = stamp
    return freshness_of(best, now=now)


def authorized_search(
    req: KnowledgeQueryRequest,
    *,
    retriever: ItemsRetriever | None = None,
    blocks_retriever: BlocksRetriever | None = None,
    composer: Callable[[str, list], dict] | None = None,
    will_synthesize: Callable[[str, list], bool] | None = None,
    evidence_builder=None,
    graph_provider=None,
    before_synthesis: Callable[[], None] | None = None,
    retrieved_at: str | None = None,
    now: float | None = None,
) -> KnowledgeQueryResult:
    """The single knowledge-retrieval entry point.

    Pipeline: validate context -> resolve scope -> scope-filtered retrieval
    (the scope goes INTO the backend) -> build contract KnowledgeEvidence ->
    compose the answer (items mode only; blocks mode leaves the voice-chain
    answer to the caller).  ``before_synthesis`` fires after retrieval but
    before the qwen pass, which is where :8787 streams its slow-answer
    headers.  ``evidence_builder``/``composer``/``will_synthesize`` default
    to the host tree's knowledge_evidence / knowledge_search modules; tests
    and adapters may inject their own (late-bound module references keep
    ``patch.object`` working).
    """
    denial = validate_request(req)
    if denial is not None:
        return _denied(req, denial)

    scope = resolve_scope(req)

    if blocks_retriever is not None:
        blocks, brains_searched = blocks_retriever(req, scope)
        evidence, scores = evidence_from_blocks(blocks, retrieved_at=retrieved_at)
        hint = None
        if scope.prefixes and not any(
                scope.allows_path(str((r or {}).get("locator") or "")) for r in evidence):
            hint = ("project knowledge has no pages at the current grant "
                    "epoch yet; earlier epochs are out of scope")
        return KnowledgeQueryResult(
            answer="",
            evidence=evidence,
            sources=[],
            permission_checked=True,
            index_as_of=max((r.get("index_as_of") for r in evidence
                             if isinstance(r, dict) and r.get("index_as_of")),
                            default=None),
            freshness=_rollup_freshness(evidence, None, now=now),
            audit_id=str(req.request_id) if req.request_id else None,
            extras={"scores": scores, "brains_searched": brains_searched,
                    "hint": hint, "epoch": scope.epoch},
        )

    if retriever is None:
        retriever = file_store_items
    items = retriever(req, scope)
    if composer is None:
        composer = _lazy("knowledge_search", "answer")
    if will_synthesize is None:
        will_synthesize = _lazy("knowledge_search", "will_synthesize")
    slow = bool(will_synthesize(req.query, items))
    if slow and before_synthesis is not None:
        before_synthesis()
    composed = composer(req.query, items)
    if not isinstance(composed, dict):
        composed = {"answer": str(composed), "sources": []}
    inferred = composed.pop("inferred_statements", None) \
        if isinstance(composed.get("inferred_statements"), dict) else None
    if evidence_builder is None:
        evidence_builder = _lazy("knowledge_evidence", "build_evidence")
    evidence = evidence_builder(
        composed.get("sources"), items,
        gate=lambda item: scope_allows_item(scope, item),
        graph_provider=graph_provider,
        inferred_content=inferred,
        retrieved_at=retrieved_at,
    )
    try:
        sources_from_evidence = _lazy("knowledge_evidence", "sources_from_evidence")
    except ImportError:
        sources_from_evidence = _sources_from_records
    projected = sources_from_evidence(evidence, composed.get("sources"))
    sources = [
        SourceSummary(file=str(s.get("file") or ""),
                      match=s.get("match"), ts=s.get("ts"))
        for s in projected if isinstance(s, dict)
    ]
    return KnowledgeQueryResult(
        answer=str(composed.get("answer") or ""),
        evidence=evidence,
        sources=sources,
        permission_checked=True,
        index_as_of=composed.get("index_as_of"),
        freshness=_rollup_freshness(evidence, composed.get("index_as_of"), now=now),
        audit_id=str(req.request_id) if req.request_id else None,
        extras={"confidence": composed.get("confidence"), "slow": slow},
    )
