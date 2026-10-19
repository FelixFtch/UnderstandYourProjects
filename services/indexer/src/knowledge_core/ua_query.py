#!/usr/bin/env python3
"""knowledge_core.ua_query — the unified UA graph query interface.

One target resolution + six operations over the Understand-Anything
knowledge graph, shared by every entry (voice agent-runtime, Studio via
the UYP query API :8787, Web, iPhone through the same adapters).

Iron rules this module owns (owner decision 2026-10-19):

- the TARGET never comes from an LLM guess: the deterministic resolver
  reads it off the graph in the frozen priority order
  (path -> filename -> symbol -> natural language -> active_node_id ->
  last_target_id -> structured clarify);
- multiple candidates -> a structured clarify payload, never a guess;
- zero candidates -> an honest not-found, never a chat downgrade;
- every operation returns contract KnowledgeEvidence records (the six
  frozen fields plus the additive extensions, same discipline as
  evidence.py / knowledge_evidence.py): content is the stored graph /
  index text verbatim, never model-reworded prose.

No LLM runs in here. Operation choice (voice) and English phrasing are
the callers' constrained steps over these deterministic results.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from .evidence import SCHEMA_VERSION, freshness_of, now_iso

# ── frozen surface ─────────────────────────────────────────────────────────

OPERATIONS = ("summary", "recent_changes", "explain", "locate", "dependents", "impact")
TIME_RANGES = ("week", "day")
TARGET_TYPES = ("file", "function", "class", "concept", "project")

DEFAULT_STATE_ROOT = "~/dev/uyp/state"

# positive resolutions (owner's frozen vocabulary) ...
RESOLUTIONS = (
    "exact_path", "unique_filename", "unique_symbol", "semantic_unique",
    # ... session-continuation resolutions ...
    "session_active", "session_last", "node_id",
    # ... and the two honest negative outcomes (candidates fill on the
    # first one; the second means "ask the user which file").
    "ambiguous", "not_found", "no_context",
)

MAX_EVIDENCE = 8
MAX_EDGE_REFS = 16
MAX_CANDIDATES = 5
# A natural-language match must cover at least half the query tokens.
_SEMANTIC_MIN_COVERAGE = 0.5

_STOPWORDS = frozenset("""
the a an of to in on for with and or is are was were be been do does did
how what where which who why when this that these those it its it's
file files function functions class classes code project repo module
work works working about into from by as at py js ts mjs
""".split())
_WORD_RE = re.compile(r"[a-z0-9]+")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.\- /]+\.[A-Za-z0-9]{1,8}$")


@dataclass(frozen=True)
class UATarget:
    """What the caller asked about (LLM-extracted text, resolved HERE).

    ``type`` is the caller's guess (file / function / class / concept /
    project) and only ever NARROWS the deterministic search; ``path`` is
    a full path the user spoke; ``query`` is a name or natural-language
    fragment; ``node_id`` is an already-resolved graph node id.
    """

    type: str | None = None
    query: str | None = None
    path: str | None = None
    node_id: str | None = None


@dataclass(frozen=True)
class UAQueryRequest:
    """One unified UA query (all entries build exactly this)."""

    operation: str
    project_id: str = ""
    target: UATarget | None = None
    time_range: str | None = None  # "week" / "day" / None
    session_context: dict = field(default_factory=dict)  # active_node_id, last_target_id


@dataclass
class ResolvedTarget:
    """The resolver's verdict (never guessed, never LLM-worded)."""

    node_id: str
    resolution: str
    confidence: float
    candidates: list[dict] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return bool(self.node_id) and self.resolution not in (
            "ambiguous", "not_found", "no_context")


@dataclass
class UAQueryResult:
    """Operations return evidence records + a deterministic English note.

    ``status``: ok | ambiguous | not_found | no_context | no_graph.
    ``note`` is a code-built honest sentence (UIs may show it verbatim;
    the voice chain lets the resident model re-phrase the EVIDENCE, not
    invent beyond it).
    """

    operation: str
    project_id: str
    status: str
    target: ResolvedTarget
    evidence: list[dict] = field(default_factory=list)
    note: str = ""
    index_as_of: str | None = None


# ── graph loading + indexes ────────────────────────────────────────────────

def state_root() -> str:
    return os.path.realpath(os.path.expanduser(
        os.environ.get("UYP_STATE_ROOT", DEFAULT_STATE_ROOT)))


def _safe_component(value: str) -> str | None:
    text = str(value or "")
    if not text or text in {".", ".."} or "/" in text or "\\" in text or "\x00" in text:
        return None
    return text


def load_graph(project_id: str, *, root: str | None = None) -> "UAGraph | None":
    """Load <state>/<project>/ua/knowledge-graph.json; None when absent."""
    component = _safe_component(project_id)
    if component is None:
        return None
    base = os.path.realpath(root or state_root())
    candidate = os.path.realpath(os.path.join(base, component, "ua", "knowledge-graph.json"))
    try:
        if os.path.commonpath([base, candidate]) != base:
            return None
        with open(candidate, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        return None
    return UAGraph(component, data)


class UAGraph:
    """Deterministic indexes over one UA knowledge-graph edition."""

    def __init__(self, project_id: str, graph: dict) -> None:
        self.project_id = str(project_id)
        project = graph.get("project") if isinstance(graph.get("project"), dict) else {}
        self.version = str(graph.get("version") or "") or None
        self.analyzed_at = str(project.get("analyzedAt") or "") or None
        self.languages = [str(x) for x in (project.get("languages") or [])][:8]
        self.description = str(project.get("description") or "").strip()
        self.node_count = len(graph.get("nodes") or [])
        self.edge_count = len(graph.get("edges") or [])
        self.nodes: list[dict] = [n for n in graph.get("nodes") or []
                                  if isinstance(n, dict) and n.get("id")]
        self.by_id: dict[str, dict] = {str(n["id"]): n for n in self.nodes}
        self.files: list[dict] = [n for n in self.nodes if n.get("type") == "file"]
        self.file_by_path: dict[str, dict] = {}
        for node in self.files:
            path = str(node.get("filePath") or "")
            if not path and str(node.get("id") or "").startswith("file:"):
                path = str(node["id"])[5:]
            if path:
                self.file_by_path.setdefault(path, node)
        self.files_by_base: dict[str, list[dict]] = {}
        for node in self.files:
            self.files_by_base.setdefault(str(node.get("name") or ""), []).append(node)
        self.symbols_by_name: dict[str, list[dict]] = {}
        for node in self.nodes:
            if node.get("type") in ("function", "class"):
                self.symbols_by_name.setdefault(
                    str(node.get("name") or "").lower(), []).append(node)
        self.out_edges: dict[str, list[dict]] = {}
        self.in_edges: dict[str, list[dict]] = {}
        self.edges_by_type: dict[str, list[dict]] = {}
        for edge in graph.get("edges") or []:
            if not isinstance(edge, dict) or not edge.get("source") or not edge.get("target"):
                continue
            src, dst, kind = str(edge["source"]), str(edge["target"]), str(edge.get("type") or "")
            self.out_edges.setdefault(src, []).append(edge)
            self.in_edges.setdefault(dst, []).append(edge)
            self.edges_by_type.setdefault(kind, []).append(edge)
        # token index for the natural-language step (name + summary + tags)
        self._tokens: dict[str, frozenset] = {}
        self._name_tokens: dict[str, frozenset] = {}
        for node in self.nodes:
            self._tokens[str(node["id"])] = frozenset(_tokenize(" ".join([
                str(node.get("name") or ""),
                str(node.get("summary") or ""),
                " ".join(str(t) for t in (node.get("tags") or [])),
            ])))
            self._name_tokens[str(node["id"])] = frozenset(
                _tokenize(str(node.get("name") or "")))

    # ---- helpers --------------------------------------------------------
    def node(self, node_id: str) -> dict | None:
        return self.by_id.get(str(node_id or ""))

    def edge_refs(self, node_id: str, *, kinds: tuple[str, ...] = ("contains", "calls",
                  "imports", "related"), limit: int = MAX_EDGE_REFS) -> list[str]:
        rendered: list[str] = []
        for edge in (self.out_edges.get(node_id) or []) + (self.in_edges.get(node_id) or []):
            if str(edge.get("type")) not in kinds:
                continue
            text = f"{edge['source']}->{edge['target']}[{edge.get('type')}]"
            if text not in rendered:
                rendered.append(text)
            if len(rendered) >= limit:
                break
        return rendered

    def file_of(self, node: dict) -> dict | None:
        owner = str(node.get("id") or "")
        for edge in self.in_edges.get(owner) or []:
            if str(edge.get("type")) == "contains":
                parent = self.by_id.get(str(edge["source"]))
                if parent is not None and parent.get("type") == "file":
                    return parent
        path = str(node.get("filePath") or "")
        return self.file_by_path.get(path) if path else None


def _tokenize(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(str(text or "").lower())
            if w not in _STOPWORDS and len(w) >= 3}


def _node_label(node: dict) -> str:
    return str(node.get("name") or str(node.get("id") or "").split(":", 1)[-1])


def _node_where(node: dict) -> str:
    path = str(node.get("filePath") or "")
    span = node.get("lineRange")
    if path and isinstance(span, list) and len(span) == 2:
        return f"{path} L{span[0]}-L{span[1]}"
    return path or str(node.get("id") or "")


def _candidate(node: dict) -> dict:
    return {
        "node_id": str(node.get("id") or ""),
        "name": _node_label(node),
        "type": str(node.get("type") or ""),
        "file": str(node.get("filePath") or ""),
    }


def _first_clause(text: str, limit: int = 180) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    match = re.match(r"(.+?[.!?])(\s|$)", cleaned)
    clause = match.group(1) if match else cleaned
    return clause if len(clause) <= limit else clause[:limit].rstrip() + "…"


_DEICTIC_WORDS = frozenset("""
this that it its the a an file function class module thing one
current selected active
""".split())


def _is_deictic(query: str | None) -> bool:
    words = [w for w in re.split(r"[^A-Za-z0-9_]+", str(query or "").lower()) if w]
    return not words or all(w in _DEICTIC_WORDS for w in words)


def _name_hits(tokens: set[str], name_tokens: frozenset) -> int:
    """How many query tokens the node's NAME carries.

    Exact token, or a >=3-char prefix agreement ("sig" in
    delegation_sig.py names "signing"): file names are dense
    abbreviations, and a name that echoes the query words is the
    strongest deterministic signal the resolver has.
    """
    hits = 0
    for token in tokens:
        if token in name_tokens:
            hits += 1
            continue
        for name_token in name_tokens:
            shorter = min(len(token), len(name_token))
            if shorter >= 3 and (token.startswith(name_token)
                                 or name_token.startswith(token)):
                hits += 1
                break
    return hits


# ── the resolver (deterministic, frozen priority) ──────────────────────────

def resolve_target(target: UATarget | None, graph: UAGraph,
                   session_context: dict | None = None) -> ResolvedTarget:
    """Path -> filename -> symbol -> natural language -> active -> last.

    Every positive step returns the owner's resolution vocabulary; the
    ambiguous verdict carries the structured candidates; the two honest
    negatives are ``not_found`` (a real query matched nothing) and
    ``no_context`` (a deictic ask with no session ids - ask which file).
    """
    session_context = session_context or {}
    query = str((target.query if target else None) or "").strip()

    def _miss() -> ResolvedTarget:
        # A real, informative query that matched nothing is an honest
        # not-found; a deictic ask ("this file") with no session anchor
        # becomes the "which file?" clarify.
        if _is_deictic(query) and not target_has_speaker_content(target):
            return ResolvedTarget("", "no_context", 0.0, [])
        return ResolvedTarget("", "not_found", 0.0, [])

    # 1. an already-resolved node id (Studio selection / last_target replay)
    if target is not None and target.node_id:
        if graph.node(target.node_id) is not None:
            return ResolvedTarget(str(target.node_id), "node_id", 1.0, [])
        return ResolvedTarget("", "not_found", 0.0, [])

    # 2. a full path the user spoke: exact only, never reinterpreted
    if target is not None and str(target.path or "").strip():
        wanted = str(target.path).strip().strip("/")
        node = graph.file_by_path.get(wanted) or graph.file_by_path.get(
            "file:" + wanted)
        if node is None:
            for path, candidate in graph.file_by_path.items():
                if path.endswith("/" + wanted) or path == wanted:
                    node = candidate
                    break
        if node is not None:
            return ResolvedTarget(str(node["id"]), "exact_path", 1.0, [])
        return ResolvedTarget("", "not_found", 0.0, [])

    if not query:
        return _session_or_clarify(graph, session_context) or _miss()

    wanted_type = str((target.type if target else "") or "").strip().lower() or None

    # 3. filename: exact/unique basename (or a dotted, filename-shaped ask)
    shaped = bool(_FILENAME_RE.match(query)) or "/" in query
    base = query.rsplit("/", 1)[-1]
    matches = [n for n in graph.files_by_base.get(base, []) if _type_ok(n, wanted_type)]
    if shaped and not matches:
        # the user clearly named a file; a miss is honest not-found
        return ResolvedTarget("", "not_found", 0.0, [])
    if len(matches) == 1:
        return ResolvedTarget(str(matches[0]["id"]), "unique_filename", 0.95,
                              [_candidate(matches[0])])
    if len(matches) > 1:
        return ResolvedTarget("", "ambiguous", 0.0,
                              [_candidate(n) for n in matches[:MAX_CANDIDATES]])

    # 4. function/class symbol: exact name, then a containment fuzz
    exact = [n for n in graph.symbols_by_name.get(query.lower(), [])
             if _type_ok(n, wanted_type)]
    if len(exact) == 1:
        return ResolvedTarget(str(exact[0]["id"]), "unique_symbol", 0.95,
                              [_candidate(exact[0])])
    if len(exact) > 1:
        return ResolvedTarget("", "ambiguous", 0.0,
                              [_candidate(n) for n in exact[:MAX_CANDIDATES]])
    low = query.lower()
    fuzzy = [n for n in graph.nodes
             if n.get("type") in ("function", "class") and _type_ok(n, wanted_type)
             and low in str(n.get("name") or "").lower()]
    if len(fuzzy) == 1:
        return ResolvedTarget(str(fuzzy[0]["id"]), "unique_symbol", 0.8,
                              [_candidate(fuzzy[0])])
    if len(fuzzy) > 1:
        return ResolvedTarget("", "ambiguous", 0.0,
                              [_candidate(n) for n in fuzzy[:MAX_CANDIDATES]])

    # 5. natural language: deterministic token coverage over
    #    name/summary/tags (concept text included), ranked, unique-or-clarify
    scored = _semantic_search(query, graph, wanted_type=wanted_type)
    if scored:
        node, best, key = scored[0]
        if len(scored) == 1 or scored[1][2] != key:
            return ResolvedTarget(str(node["id"]), "semantic_unique",
                                  round(0.5 + 0.4 * best, 3),
                                  [_candidate(node)])
        return ResolvedTarget("", "ambiguous", 0.0,
                              [_candidate(n) for n, _s, _k in scored[:MAX_CANDIDATES]])

    # 6.+7. session continuation ids, then the honest clarify
    return _session_or_clarify(graph, session_context) or _miss()


def target_has_speaker_content(target: UATarget | None) -> bool:
    """True when the user actually named something (vs a deictic ask)."""
    if target is None:
        return False
    if str(target.path or "").strip() or str(target.node_id or "").strip():
        return True
    return not _is_deictic(target.query)


def _type_ok(node: dict, wanted: str | None) -> bool:
    return not wanted or str(node.get("type") or "") == wanted


def _session_or_clarify(graph: UAGraph, session_context: dict) -> ResolvedTarget | None:
    for key, resolution, confidence in (
        ("active_node_id", "session_active", 0.9),
        ("last_target_id", "session_last", 0.85),
    ):
        node_id = str(session_context.get(key) or "")
        if node_id and graph.node(node_id) is not None:
            return ResolvedTarget(node_id, resolution, confidence,
                                  [_candidate(graph.node(node_id))])
    return None


def _semantic_search(query: str, graph: UAGraph, *,
                     wanted_type: str | None = None,
                     min_coverage: float = _SEMANTIC_MIN_COVERAGE) -> list[tuple[dict, float, tuple]]:
    """Deterministic natural-language ranking over node text.

    Rank key: token coverage, then the explain-surface preference
    (file > class > function > concept - files are the primary explain
    surface, concepts are derived search material), then how many query
    tokens the node's NAME echoes. The resolver still clarifies on a
    true photo finish (top1 == top2 on the full key minus the id
    tiebreak).
    """
    tokens = _tokenize(query)
    if not tokens:
        return []
    ranked: list[tuple[tuple, dict, float, tuple]] = []
    for node in graph.nodes:
        if wanted_type and str(node.get("type") or "") != wanted_type:
            continue
        text = graph._tokens.get(str(node["id"]), frozenset())
        if not text:
            continue
        coverage = len(tokens & text) / len(tokens)
        if coverage < min_coverage:
            continue
        name_hits = _name_hits(
            tokens, graph._name_tokens.get(str(node["id"]), frozenset()))
        # Explain-surface preference ranks BEFORE name hits: file >
        # class > function > concept. Files/functions/classes are the
        # primary explain surfaces; concept nodes are derived search
        # material, so an equal-coverage file beats an equal-coverage
        # concept even when the concept's generated slug echoes more of
        # the query's words.
        type_rank = {"file": 0, "class": 1, "function": 2}.get(
            str(node.get("type")), 3)
        # comparison key WITHOUT the id tiebreak: two nodes equal on
        # (coverage, surface class, name hits) are a photo finish and the
        # resolver must clarify, not pick by alphabetical accident.
        key = (-round(coverage, 3), type_rank, -name_hits)
        ranked.append((key + (str(node.get("id") or ""),), node, coverage, key))
    ranked.sort(key=lambda item: item[0])
    return [(node, round(coverage, 3), cmp_key)
            for _full, node, coverage, cmp_key in ranked]


# ── evidence records (six frozen fields + extensions) ─────────────────────

def _model_id() -> str:
    # The graph summaries were produced by the UA enrichment pipeline;
    # mirror its model env so a record never claims a model the content
    # path did not use (knowledge_evidence discipline).
    return os.environ.get("UYP_OLLAMA_MODEL", "qwen3.5-route")


def _record(graph: UAGraph, locator: str, content: str, *,
            fact_type: str = "semantic", node_ids: list[str] | None = None,
            edge_ids: list[str] | None = None, index_as_of: str | None = None,
            retrieved_at: str | None = None) -> dict:
    stamp = retrieved_at or now_iso()
    as_of = index_as_of or graph.analyzed_at
    record = {
        "schema_version": SCHEMA_VERSION,
        "source_id": f"ua-graph:{graph.project_id}",
        "source_version": graph.analyzed_at or "unknown",
        "locator": str(locator or ""),
        "content": str(content or ""),
        "permission_checked": True,
        "retrieved_at": stamp,
        "graph_version": graph.version,
        "index_as_of": as_of,
        "freshness": freshness_of(as_of),
        "fact_type": fact_type,
        "provider": "local",
        "model_id": _model_id(),
    }
    if node_ids:
        record["node_ids"] = node_ids[:8]
    if edge_ids:
        record["edge_ids"] = edge_ids[:MAX_EDGE_REFS]
    return record


# ── operations ─────────────────────────────────────────────────────────────

def window_bounds(time_range: str | None, now: float | None = None) -> tuple[float, float]:
    """[since, until] for a UA time range: day = since local midnight."""
    now = time.time() if now is None else now
    if time_range == "day":
        midnight = datetime.fromtimestamp(now).replace(
            hour=0, minute=0, second=0, microsecond=0)
        return midnight.timestamp(), now
    return now - 7 * 86400, now  # week (and the None default)


def _iso(epoch: float | None) -> str:
    if not epoch or epoch <= 0:
        return ""
    return datetime.fromtimestamp(float(epoch)).strftime("%Y-%m-%d %H:%M")


def _summary_records(graph: UAGraph, retrieved_at: str) -> list[dict]:
    head = " ".join(filter(None, [
        f"{graph.project_id}: {len(graph.files)} indexed files, "
        f"{len(graph.symbols_by_name)} distinct symbols.",
        f"Languages: {', '.join(graph.languages)}." if graph.languages else "",
        graph.description,
    ]))
    records = [_record(graph, f"ua:{graph.project_id}", head,
                       fact_type="structural", retrieved_at=retrieved_at)]
    explained = [n for n in graph.files
                 if _first_clause(str(n.get("summary") or ""), 400)]
    explained.sort(key=lambda n: str(n.get("filePath") or ""))
    for node in explained[:MAX_EVIDENCE - 1]:
        records.append(_record(
            graph, str(node.get("filePath") or node.get("id")),
            _first_clause(str(node.get("summary") or ""), 400),
            node_ids=[str(node["id"])], retrieved_at=retrieved_at))
    return records


def _recent_changes_records(graph: UAGraph, rows: list[dict], retrieved_at: str,
                            ) -> tuple[list[dict], str | None]:
    records: list[dict] = []
    newest: float | None = None
    for row in rows[:MAX_EVIDENCE]:
        if not isinstance(row, dict) or not row.get("file"):
            continue
        mtime = _row_epoch(row.get("mtime"))
        newest = max(newest or 0, mtime or 0) or newest
        purpose = _first_clause(str(row.get("purpose") or ""), 160)
        when = _iso(mtime)
        content = " ".join(filter(None, [
            f"{row['file']} changed {when}." if when else f"{row['file']}.",
            purpose,
        ]))
        records.append(_record(graph, str(row["file"]), content,
                               fact_type="structural", retrieved_at=retrieved_at,
                               index_as_of=_iso(mtime) or None))
    return records, (_iso(newest) or None)


def _row_epoch(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
        if number > 0:
            return number
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _explain_records(graph: UAGraph, node: dict, retrieved_at: str) -> list[dict]:
    node_id = str(node["id"])
    summary = _first_clause(str(node.get("summary") or ""), 600)
    records = [_record(graph, _node_where(node), summary or _node_label(node),
                       fact_type="semantic" if summary else "structural",
                       node_ids=[node_id], edge_ids=graph.edge_refs(node_id),
                       retrieved_at=retrieved_at)]
    if node.get("type") == "file":
        children = [graph.by_id[str(e["target"])]
                    for e in (graph.out_edges.get(node_id) or [])
                    if str(e.get("type")) == "contains"
                    and str(e.get("target")) in graph.by_id]
        names = [f"{_node_label(c)} ({c.get('type')})" for c in children[:10]]
        imported = [str(e["target"])[5:] if str(e["target"]).startswith("file:")
                    else str(e["target"])
                    for e in (graph.out_edges.get(node_id) or [])
                    if str(e.get("type")) == "imports"][:6]
        structure = []
        if names:
            structure.append("Defines: " + ", ".join(names) + ".")
        if imported:
            structure.append("Imports: " + ", ".join(imported) + ".")
        callers = sorted({str(graph.by_id[str(e["source"])].get("filePath") or
                              str(e["source"]))
                          for e in (graph.in_edges.get(node_id) or [])
                          if str(e.get("type")) == "imports"
                          and str(e.get("source")) in graph.by_id})[:6]
        if callers:
            structure.append("Imported by: " + ", ".join(callers) + ".")
        if structure:
            records.append(_record(graph, str(node.get("filePath") or node_id),
                                   " ".join(structure), fact_type="structural",
                                   node_ids=[node_id], retrieved_at=retrieved_at))
    else:
        parent = graph.file_of(node)
        if parent is not None:
            records.append(_record(
                graph, str(parent.get("filePath") or parent.get("id")),
                _first_clause(str(parent.get("summary") or ""), 300),
                fact_type="semantic" if parent.get("summary") else "structural",
                node_ids=[str(parent["id"])], retrieved_at=retrieved_at))
    return records


def _reverse_dependencies(graph: UAGraph, node_id: str) -> list[tuple[dict, dict]]:
    """(dependent node, edge) for imports/calls edges pointing AT the target.

    A FILE target's dependency set includes both the file-level imports
    edges AND callers of its contained symbols (the contains edge's
    function/class children) - "who depends on this file" means both.
    """
    target_ids = [node_id]
    node = graph.node(node_id)
    if node is not None and node.get("type") == "file":
        for edge in (graph.out_edges.get(node_id) or []):
            if str(edge.get("type")) == "contains":
                target_ids.append(str(edge["target"]))
    found: list[tuple[dict, dict]] = []
    seen: set[str] = set()
    for tid in target_ids:
        for edge in (graph.in_edges.get(tid) or []):
            kind = str(edge.get("type") or "")
            if kind not in ("imports", "calls"):
                continue
            dependent = graph.by_id.get(str(edge["source"]))
            if dependent is None:
                continue
            key = f"{dependent['id']}:{kind}"
            if key in seen:
                continue
            seen.add(key)
            found.append((dependent, edge))
    found.sort(key=lambda pair: str(pair[0].get("id") or ""))
    return found


def _dependents_records(graph: UAGraph, node: dict, retrieved_at: str,
                        *, impact: bool = False) -> list[dict]:
    node_id = str(node["id"])
    records = [_record(graph, _node_where(node),
                       _first_clause(str(node.get("summary") or ""), 300)
                       or _node_label(node),
                       node_ids=[node_id], retrieved_at=retrieved_at)]
    dependencies = _reverse_dependencies(graph, node_id)
    if not dependencies:
        return records
    if impact:
        modules: dict[str, list[str]] = {}
        for dependent, edge in dependencies:
            module = str(dependent.get("filePath") or dependent.get("id"))
            modules.setdefault(module, []).append(
                f"{_node_label(dependent)} ({edge.get('type')})")
        for module, uses in list(modules.items())[:MAX_EVIDENCE - 1]:
            content = (f"Module {module} may be affected: "
                       + ", ".join(uses[:6])
                       + f" depend on {node.get('name') or node_id}. "
                         "Graph edges only - this is exposure, not a "
                         "breakage prediction.")
            records.append(_record(graph, module, content, fact_type="inferred",
                                   retrieved_at=retrieved_at))
        return records
    for dependent, edge in dependencies[:MAX_EVIDENCE - 1]:
        verb = {"imports": "imports", "calls": "calls"}.get(
            str(edge.get("type")), str(edge.get("type")))
        content = " ".join(filter(None, [
            f"{_node_where(dependent)} {verb} {_node_where(node)}.",
            _first_clause(str(dependent.get("summary") or ""), 140),
        ]))
        records.append(_record(graph, _node_where(dependent), content,
                               fact_type="structural",
                               node_ids=[str(dependent["id"])],
                               edge_ids=[f"{edge['source']}->{edge['target']}[{edge.get('type')}]"],
                               retrieved_at=retrieved_at))
    return records


def _locate_records(graph: UAGraph, query: str, retrieved_at: str) -> list[dict]:
    matches: list[tuple[dict, str]] = []
    low = query.lower()
    for node in graph.nodes:
        name = str(node.get("name") or "")
        if low and low in name.lower():
            matches.append((node, "name"))
    if not matches:
        for node, score, _key in _semantic_search(query, graph, min_coverage=0.34):
            matches.append((node, f"text {score:.2f}"))
    matches.sort(key=lambda pair: (0 if pair[1] == "name" else 1,
                                   str(pair[0].get("id") or "")))
    records: list[dict] = []
    seen: set[str] = set()
    for node, how in matches:
        if len(records) >= MAX_EVIDENCE:
            break
        key = str(node["id"])
        if key in seen:
            continue
        seen.add(key)
        records.append(_record(
            graph, _node_where(node),
            f"{_node_label(node)} ({node.get('type')}, {how}) — {_node_where(node)}",
            fact_type="structural", node_ids=[key], retrieved_at=retrieved_at))
    return records


# ── the one entry point ────────────────────────────────────────────────────

def run_ua_query(req: UAQueryRequest, *, graph: UAGraph | None = None,
                 activity: "callable | None" = None, now: float | None = None,
                 retrieved_at: str | None = None) -> UAQueryResult:
    """Resolve + execute one UA query. Pure: no LLM, no network.

    ``activity`` (optional) is ``(project_id, since, until) -> list of
    {file, mtime, purpose}`` rows - the host adapter injects its own
    index/manifest reader; without it recent_changes degrades to the
    honest "no change rows available" answer, never a guess.
    """
    operation = str(req.operation or "").strip()
    if operation not in OPERATIONS:
        return UAQueryResult(operation or "?", req.project_id, "bad_operation",
                             ResolvedTarget("", "not_found", 0.0, []),
                             note="Unknown operation.")
    graph = graph or load_graph(req.project_id)
    if graph is None:
        return UAQueryResult(operation, req.project_id, "no_graph",
                             ResolvedTarget("", "not_found", 0.0, []),
                             note=f"No analyzed code graph for {req.project_id or 'this project'} yet.")
    stamp = retrieved_at or now_iso()
    target = req.target
    needs_target = operation in ("explain", "dependents", "impact")

    if needs_target:
        resolved = resolve_target(target, graph, req.session_context)
        if resolved.resolution == "ambiguous":
            return UAQueryResult(operation, req.project_id, "ambiguous", resolved,
                                 note="Several graph nodes match; ask which one.")
        if resolved.resolution in ("not_found", "no_context"):
            note = ("I could not find that in the analyzed code graph."
                    if resolved.resolution == "not_found"
                    else "Which file or symbol do you mean?")
            return UAQueryResult(operation, req.project_id, resolved.resolution,
                                 resolved, note=note)
        node = graph.node(resolved.node_id)
        if operation == "explain":
            records = _explain_records(graph, node, stamp)
            note = f"Explaining {node.get('name') or resolved.node_id} from the code graph."
        elif operation == "dependents":
            records = _dependents_records(graph, node, stamp)
            count = len(_reverse_dependencies(graph, resolved.node_id))
            note = (f"{count} dependent{'s' if count != 1 else ''} found in the graph."
                    if count else "No importers or callers found in the graph.")
        else:  # impact
            records = _dependents_records(graph, node, stamp, impact=True)
            note = "Impact assessed from graph edges; exposure, not breakage."
        return _done(operation, req, resolved, records, stamp, note)

    if operation == "summary":
        return _done(operation, req, ResolvedTarget("", "node_id", 0.0, []),
                     _summary_records(graph, stamp), stamp,
                     f"Overview of {graph.project_id}.")

    if operation == "recent_changes":
        since, until = window_bounds(req.time_range, now)
        rows: list[dict] = []
        if activity is not None:
            try:
                rows = [r for r in (activity(req.project_id, since, until) or [])
                        if isinstance(r, dict) and r.get("file")]
            except Exception:  # noqa: BLE001 - the honest path below answers
                rows = []
        if not rows:
            return _done(operation, req, ResolvedTarget("", "node_id", 0.0, []),
                         [], stamp, "No changed files recorded in that window.")
        records, newest = _recent_changes_records(graph, rows, stamp)
        return _done(operation, req, ResolvedTarget("", "node_id", 0.0, []),
                     records, stamp,
                     f"{len(rows)} changed file{'s' if len(rows) != 1 else ''} "
                     f"in the window.", index_as_of=newest)

    # locate: search, never resolve-to-one (multiple hits are the answer)
    query = str((target.query if target else None)
                or (target.path if target else None) or "").strip()
    if target is not None and not query and target.node_id:
        node = graph.node(target.node_id)
        records = ([_record(graph, _node_where(node),
                            f"{_node_label(node)} ({node.get('type')}) — {_node_where(node)}",
                            fact_type="structural", node_ids=[str(node["id"])],
                            retrieved_at=stamp)] if node is not None else [])
        return _done(operation, req,
                     ResolvedTarget(str(target.node_id), "node_id", 1.0, []),
                     records, stamp, "Located." if records else "Not found.")
    if not query:
        query = str(req.session_context.get("last_target_id") or "")
    records = _locate_records(graph, query, stamp) if query else []
    if not records:
        return UAQueryResult(
            operation, req.project_id, "not_found",
            ResolvedTarget("", "not_found", 0.0, []),
            note="I could not find that in the analyzed code graph.")
    return _done(operation, req, ResolvedTarget("", "node_id", 0.0, []),
                 records, stamp, f"{len(records)} matching location{'s' if len(records) != 1 else ''}.")


def _done(operation: str, req: UAQueryRequest, resolved: ResolvedTarget,
          records: list[dict], stamp: str, note: str,
          index_as_of: str | None = None) -> UAQueryResult:
    as_of = index_as_of or next((str(r.get("index_as_of"))
                                 for r in records if r.get("index_as_of")), None)
    return UAQueryResult(operation=operation, project_id=req.project_id,
                         status="ok", target=resolved, evidence=records,
                         note=note, index_as_of=as_of)


# ── deterministic operation inference (used when the caller sends none) ───

_INFER_RULES: tuple[tuple[str, str], ...] = (
    ("dependents", re.compile(
        r"\b(?:who|which|what)\s+(?:files?|modules?|code)?\s*"
        r"(?:imports?|uses?|calls?|depends?\s*(?:on)?)\b"
        r"|\bdependents?\b|\breferenced\s+by\b|\bimporters?\b",
        re.IGNORECASE)),
    ("impact", re.compile(
        r"\bimpact\b|\baffects?\b|\baffected\b"
        r"|\bif\s+i\s+(?:change|delete|remove|refactor|rename)\b"
        r"|\bwhat\s+(?:would\s+)?breaks?\b|\bblast\s+radius\b",
        re.IGNORECASE)),
    ("recent_changes", re.compile(
        r"\bwhat\s+(?:did|have|has)\s+(?:i|we)\s+"
        r"(?:add|added|change|changed|do|done|work|worked|touch|touched"
        r"|edit|edited|commit|committed|ship|shipped|fix|fixed)\b"
        r"|\bwhat(?:'s|\s+is|\s+has)\s+(?:new|changed)\b"
        r"|\bwhat\s+changed\b|\brecent(?:ly)?\b|\blately\b"
        r"|\bthis\s+week\b|\blast\s+week\b|\byesterday\b|\btoday\b"
        r"|做了什么|改了什么|最近",
        re.IGNORECASE)),
    ("locate", re.compile(
        r"\bwhere\s+(?:is|are|does|do|did)\b|\bwhich\s+file\b"
        r"|\bfind\s+the\s+file\b|\blocate\b|\bwhat\s+file\b"
        r"|在哪|哪个文件",
        re.IGNORECASE)),
    ("summary", re.compile(
        r"\bsummar(?:y|i[sz]e)\b|\boverview\b|\btell\s+me\s+about\b"
        r"|\bwhat\s+is\s+this\s+(?:project|repo|codebase)\b"
        r"|\bdescribe\s+the\s+project\b",
        re.IGNORECASE)),
)


def infer_operation(question: str) -> str:
    """Keyword rules only (closed vocabulary); explain is the default."""
    text = str(question or "")
    for operation, pattern in _INFER_RULES:
        if pattern.search(text):
            return operation
    return "explain"


__all__ = [
    "OPERATIONS",
    "TIME_RANGES",
    "TARGET_TYPES",
    "RESOLUTIONS",
    "UAGraph",
    "UATarget",
    "UAQueryRequest",
    "UAQueryResult",
    "ResolvedTarget",
    "infer_operation",
    "load_graph",
    "resolve_target",
    "run_ua_query",
    "state_root",
    "window_bounds",
]
