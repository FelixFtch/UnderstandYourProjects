#!/usr/bin/env python3
"""knowledge_core.evidence — shared KnowledgeEvidence semantics.

The blocks-mode producer for the gbrain-backed front door (:8790), moved
out of service.py so both front doors share ONE module for the frozen
contract's honesty rules:

- the six frozen fields (source_id, source_version, locator, content,
  permission_checked, retrieved_at) on every record;
- ``freshness`` is computed from a provable date only (the serve's
  ``effective_date``), never asserted from nothing — the same 48h window
  the items-mode producer (knowledge_evidence.py, UYP tree) uses;
- ``content`` is the stored page text verbatim, capped as retrieval
  returned it — never model-reworded prose;
- ``fact_type`` is only set where the taxonomy honestly fits (project
  pages are model-authored derived summaries re-read verbatim ->
  semantic);
- ``permission_checked`` is True because every block on this path already
  passed the scope filters inside retrieval (prefixes went INTO
  ``search_brain``; the defensive re-check lives in the backend).

``freshness_of`` is the shared age verdict used by the core's result-level
rollup on BOTH modes (it accepts full timestamps and bare dates).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

# Evidence contract constants (harness-v1 KnowledgeEvidence).
SCHEMA_VERSION = "harness-v1"
FRESHNESS_WINDOW_DAYS = 2  # 48h, the same threshold :8787's producer uses
RETRIEVAL_PROVIDER = "local"
RETRIEVAL_MODEL_ID = "gbrain-hybrid+nomic-embed"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def freshness_from_date(effective_date: str) -> str:
    """fresh/stale/unknown from a provable date (48h window)."""
    try:
        as_of = date.fromisoformat(str(effective_date).strip()[:10])
    except (TypeError, ValueError):
        return "unknown"
    age = (date.today() - as_of).days
    return "fresh" if age <= FRESHNESS_WINDOW_DAYS else "stale"


def freshness_of(value, *, now=None) -> str:
    """Age verdict for a timestamp OR a bare date string; unknown if unprovable.

    Shared by both modes: items-mode passes an index edition stamp
    ("2026-10-18 21:41:46" local), blocks-mode passes effective_date
    ("2026-10-18").  Naive strings are interpreted as local time, exactly
    like the items-mode producer always did.
    """
    if value is None:
        return "unknown"
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        age = (datetime.now().timestamp() if now is None else now) - float(value)
        return "fresh" if age <= FRESHNESS_WINDOW_DAYS * 86400 else "stale"
    text = str(value).strip()
    if not text:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return freshness_from_date(text)
    if parsed.tzinfo is None:
        epoch = parsed.timestamp()
    else:
        epoch = parsed.timestamp()
    age = (datetime.now().timestamp() if now is None else now) - epoch
    return "fresh" if age <= FRESHNESS_WINDOW_DAYS * 86400 else "stale"


def evidence_from_blocks(blocks: list[dict],
                         retrieved_at: str | None = None) -> tuple[list[dict], list[float]]:
    """Blocks -> contract KnowledgeEvidence records + parallel scores.

    Six frozen fields on every record; freshness/fact_type/index_as_of/
    provider/model_id where the producer can prove them.  content is the
    stored page text verbatim; locator is the gbrain slug;
    source_version/index_as_of ride the serve's provable effective_date.
    """
    stamp = retrieved_at or now_iso()
    records: list[dict] = []
    scores: list[float] = []
    for b in blocks or []:
        brain = str(b.get("brain") or "brain")
        slug = str(b.get("source") or "")
        eff = str(b.get("effective_date") or "").strip()
        record = {
            "schema_version": SCHEMA_VERSION,
            "source_id": "gbrain:%s" % brain,
            "source_version": eff or "unknown",
            "locator": slug or ("gbrain://%s" % brain),
            "content": str(b.get("text") or ""),
            "permission_checked": True,
            "retrieved_at": stamp,
        }
        if eff:
            record["index_as_of"] = eff
            record["freshness"] = freshness_from_date(eff)
        else:
            record["freshness"] = "unknown"
        if brain == "project_knowledge":
            record["fact_type"] = "semantic"
        record["provider"] = RETRIEVAL_PROVIDER
        record["model_id"] = RETRIEVAL_MODEL_ID
        records.append(record)
        try:
            scores.append(round(float(b.get("score", 0) or 0), 4))
        except (TypeError, ValueError):
            scores.append(0.0)
    return records, scores
