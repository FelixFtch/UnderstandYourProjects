#!/usr/bin/env python3
"""Project digests, activity and ask for Jarvis Studio v2 (docs/STUDIO_V2.md §6.2).

Everything here reads derived knowledge only: the compact item index cached
by ``projects.compute_cache`` (KnowledgeItem purposes, key points, key-file
tiers), the UA graph summary, and - for activity - the Connector manifest's
metadata (relpath + mtime), never source bytes.  Callers pass the caller's
HomeHub AccessContext; a project outside its scopes is reported as absent.

``ask`` combines the top lexically-matching knowledge items (the same scorer
as knowledge_search) with relevant gbrain blocks and asks the local Qwen
model (``UYP_OLLAMA_MODEL``, ``think:false``) for a sourced answer.  With no
matching knowledge it answers honestly that it does not have enough
information, without calling the model.  Synthesis yields to an in-flight
voice turn (fresh interactive lock) and then marks the lock itself so the
indexer yields to it.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import project_jobs as J
import projects as P
from knowledge_search import INTERACTIVE_LOCK, score as lexical_score, tokenize

TIER_ORDER = {"A": 0, "B": 1, "C": 2, "gate": 3}
KEY_FILES_LIMIT = 12
AREAS_LIMIT = 12
DIGEST_CHANGED_LIMIT = 50
ACTIVITY_LIMIT = 500
ASK_HITS = 6
NOT_ENOUGH = "NOT_ENOUGH_INFO"
OVERVIEW_WORDS = ("overview", "about", "purpose", "summary", "summarize", "summarise", "describe",
                  "introduction", "goal", "简介", "概述", "介绍", "总结", "用途", "做什么", "是什么")
KEY_FILE_WORDS = ("key file", "main file", "important file", "core file", "entry point",
                  "关键文件", "主要文件", "核心文件", "入口")
# Ranking (2026-10-11): a bundled third-party project (e.g. an upstream repo
# copied into the owner's folder) used to win lexical matches, so "what is
# commontasks about" cited gbrain/UPSTREAM.md instead of the owner's code.
EMBEDDED_WEIGHT = 0.35       # score multiplier for files in an embedded root ...
EMBEDDED_MAX_HITS = 2        # ... and at most this many of them as sources,
                             # unless the question names that embedded folder
TIER_WEIGHT = {"A": 1.25, "B": 1.1}   # prefer the classifier's key files on near-ties
OVERVIEW_KEY_FILES = 5
STOPWORDS = frozenset((
    "the", "is", "are", "was", "be", "a", "an", "of", "to", "in", "on", "at", "and", "or", "for", "with",
    "what", "where", "which", "who", "how", "why", "when", "does", "do", "did", "this", "that", "these",
    "it", "its", "can", "could", "should", "would", "i", "my", "me", "we", "our", "you", "your", "there",
    "any", "from", "by", "as", "if", "into", "about", "tell", "show", "explain", "please", "project", "file", "files",
))
_README = re.compile(r"(?i)^readme(\.[a-z0-9]+)?$")
_MANIFEST_CACHE: dict = {}
_MANIFEST_LOCK = threading.Lock()


# ------------------------------------------------------------- lookup ----
def _sort_key(item: dict):
    return (TIER_ORDER.get(item.get("tier") or "", 4), item.get("rank") or 10**9,
            item["file"].count("/"), item["file"])


def _files(count: int) -> str:
    return f"{count} file" if count == 1 else f"{count} files"


def _question_tokens(question: str) -> list[str]:
    """knowledge_search tokens minus filler words (they match every purpose)."""
    tokens = tokenize(question)
    useful = [t for t in tokens if t not in STOPWORDS]
    return useful or tokens


def _first_clause(text: str, limit: int = 110) -> str:
    text = " ".join(str(text or "").split())
    for sep in (". ", "。", "; ", "；"):
        if sep in text:
            text = text.split(sep, 1)[0]
            break
    text = text.rstrip(".。")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def list_projects(context: dict) -> dict:
    jobs = J.jobs_by_project()
    doc = P.sync_registry(jobs_by_project=jobs)
    records = sorted((r for r in doc["projects"] if P.visible(context, r)), key=lambda r: r["project_id"])
    ids = {r["project_id"] for r in records}
    projects = [P.public_record(doc, r, ids) for r in records]
    return {"projects": projects, "tree": P.build_tree(projects)}


def _resolve(context: dict, project_id: str):
    """(doc, record, jobs, visible_ids) for a visible project, else None."""
    if not P.safe_project_id(project_id):
        return None
    jobs = J.jobs_by_project()
    doc = P.sync_registry(jobs_by_project=jobs)
    record = next((r for r in doc["projects"] if r["project_id"] == project_id), None)
    if record is None or not P.visible(context, record):
        return None
    ids = {r["project_id"] for r in doc["projects"] if P.visible(context, r)}
    return doc, record, jobs, ids


# ------------------------------------------------------------ sections ----
def overview_from(record: dict, items: list[dict]) -> str:
    own = [i for i in items if not i.get("embedded")]
    readmes = sorted((i for i in own if i["purpose"] and _README.match(posixpath.basename(i["file"]))),
                     key=lambda i: (i["file"].count("/"), i["file"]))
    lead = readmes[0]["purpose"] if readmes else ""
    if not lead:
        ranked = sorted((i for i in own if i["purpose"]), key=_sort_key)
        lead = ranked[0]["purpose"] if ranked else ""
    areas = [a for a in areas_from(items) if not a.get("embedded") and a["folder"] != "(root)"][:3]
    if not lead:
        if not items:
            return "Not analyzed yet."
        lead = f"{_files(len(items))} indexed (structure only); no summaries yet."
    text = " ".join(lead.split())
    if areas:
        text += " Main areas: " + ", ".join(f"{a['folder']} ({_files(a['files'])})" for a in areas) + "."
    return text


def overview_text(record: dict) -> str:
    """Overview for one registry record (used for a descendant's prompt context)."""
    _, items = P.project_items(record)
    return overview_from(record, items)


def key_files_from(items: list[dict]) -> list[dict]:
    pool = [i for i in items if i["purpose"] and not i.get("embedded")]
    tiered = [i for i in pool if i.get("tier") in {"A", "B"}]
    chosen = sorted(tiered or pool, key=_sort_key)[:KEY_FILES_LIMIT]
    return [{"file": i["file"], "tier": i.get("tier") or "", "purpose": i["purpose"],
             "key_points": list(i.get("key_points") or [])} for i in chosen]


def areas_from(items: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    embedded: dict[str, int] = {}
    for item in items:
        if item.get("embedded"):
            embedded[item["embedded"]] = embedded.get(item["embedded"], 0) + 1
            continue
        folder = item["file"].split("/", 1)[0] if "/" in item["file"] else "(root)"
        groups.setdefault(folder, []).append(item)
    areas = []
    for folder, members in groups.items():
        purposes, seen = [], set()
        for item in sorted(members, key=_sort_key):
            if not item["purpose"]:
                continue
            clause = _first_clause(item["purpose"], 90)
            if clause.lower() in seen:
                continue
            seen.add(clause.lower())
            purposes.append(clause)
            if len(purposes) == 3:
                break
        summary = "; ".join(purposes) if purposes else f"{_files(len(members))}, structure only (no summaries yet)."
        areas.append({"folder": folder, "files": len(members), "summary": summary, "embedded": False})
    areas.sort(key=lambda a: (-a["files"], a["folder"]))
    areas = areas[:AREAS_LIMIT]
    for root in sorted(embedded):
        areas.append({"folder": root, "files": embedded[root], "embedded": True,
                      "summary": "Embedded third-party project; kept findable but excluded from key-file analysis."})
    return areas


def _live_manifest(record: dict, ttl: float = 300.0) -> list[dict] | None:
    """Current connector manifest (relpath, mtime), cached; None if unavailable."""
    if os.environ.get("UYP_PROJECT_LIVE_ACTIVITY", "1").strip().lower() in {"0", "off", "false", "no"}:
        return None
    grant = record.get("grant_id")
    client = P.ConnectorClient(timeout=5.0)
    if not grant or not client.configured:
        return None
    key = (record["project_id"], grant)
    now = time.monotonic()
    with _MANIFEST_LOCK:
        cached = _MANIFEST_CACHE.get(key)
        if cached and now < cached[0]:
            return cached[1]
    try:
        files = [{"file": str(f.get("relpath")), "mtime": P.parse_time(f.get("mtime"))}
                 for f in client.manifest(grant).get("files", []) if f.get("kind") == "file" and f.get("relpath")]
    except (P.ConnectorError, RuntimeError, ValueError, TypeError, OSError):
        files = None
    with _MANIFEST_LOCK:
        _MANIFEST_CACHE[key] = (now + (ttl if files is not None else 60.0), files)
    return files


def changed_between(record: dict, items: list[dict], since: float, until: float,
                    manifest: list[dict] | None = None) -> list[dict]:
    """Files whose (manifest, else analyzed-version) mtime is in [since, until]."""
    purposes = {i["file"]: i["purpose"] for i in items}
    source = manifest if manifest is not None else [{"file": i["file"], "mtime": i.get("mtime")} for i in items]
    rows = [(f["mtime"], f["file"]) for f in source
            if isinstance(f.get("mtime"), (int, float)) and since <= f["mtime"] <= until]
    rows.sort(key=lambda r: (-r[0], r[1]))
    return [{"file": rel, "mtime": P.iso_from_epoch(mtime), "purpose": purposes.get(rel, "")} for mtime, rel in rows]


def activity_section(record: dict, items: list[dict], now: float, manifest=None) -> dict:
    since = now - 7 * 86400
    changed = changed_between(record, items, since, now, manifest)
    today = datetime.fromtimestamp(now).date()
    days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    counts = {day.isoformat(): 0 for day in days}
    for row in changed:
        day = datetime.fromtimestamp(P.parse_time(row["mtime"])).date().isoformat()
        if day in counts:
            counts[day] += 1
    return {"window": "7d", "changed": changed[:DIGEST_CHANGED_LIMIT],
            "by_day": [{"date": day, "count": count} for day, count in counts.items()]}


def digest(context: dict, project_id: str, *, now: float | None = None) -> dict | None:
    resolved = _resolve(context, project_id)
    if resolved is None:
        return None
    doc, record, jobs, ids = resolved
    job = jobs.get(project_id)
    meta, items = P.project_items(record, active=(job or {}).get("status") in {"queued", "running"})
    now = time.time() if now is None else now
    by_id = {r["project_id"]: r for r in doc["projects"]}

    def public(r):
        return P.public_record(doc, r, ids, P.derive_status(r, jobs.get(r["project_id"])))

    parent = by_id.get(record.get("parent_id"))
    parent = parent if parent is not None and parent["project_id"] in ids else None
    siblings = []
    if parent is not None:
        siblings = [public(by_id[c]) for c in parent.get("children", [])
                    if c in ids and c != project_id and c in by_id]
    graph = meta.get("graph") or {}
    return {
        "project": public(record),
        "overview": overview_from(record, items),
        "key_files": key_files_from(items),
        "areas": areas_from(items),
        "activity": activity_section(record, items, now, _live_manifest(record)),
        "graph": {"layers": list(graph.get("layers") or []), "top_nodes": list(graph.get("top_nodes") or [])},
        "related": {
            "parent": public(parent) if parent is not None else None,
            "children": [public(by_id[c]) for c in record.get("children", []) if c in ids and c in by_id],
            "siblings": siblings,
        },
        "generated_at": P.now_iso(),
    }


def activity(context: dict, project_id: str, since: float, until: float) -> dict | None:
    resolved = _resolve(context, project_id)
    if resolved is None:
        return None
    _, record, jobs, _ = resolved
    _, items = P.project_items(record, active=(jobs.get(project_id) or {}).get("status") in {"queued", "running"})
    return {"changed": changed_between(record, items, since, until, _live_manifest(record))[:ACTIVITY_LIMIT]}


# ------------------------------------------------------------------ ask ----
def _post_json(url: str, body: dict, timeout: float, headers: dict | None = None):
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read() or b"{}")


def gbrain_blocks(question: str, member: str, role: str) -> list[dict]:
    """gbrain knowledge-service blocks for the member; [] on any failure."""
    url = os.environ.get("UYP_GBRAIN_URL", "http://127.0.0.1:8790/query")
    try:
        value = _post_json(url, {"question": question, "member": member, "role": role}, timeout=8.0)
    except (OSError, urllib.error.URLError, ValueError):
        return []
    blocks = value.get("blocks") if isinstance(value, dict) else None
    return [b for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str)] if isinstance(blocks, list) else []


def ollama_chat(prompt: str) -> str | None:
    """Local Qwen synthesis (same model env as knowledge_search, think:false)."""
    url = os.environ.get("UYP_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    body = {"model": os.environ.get("UYP_OLLAMA_MODEL", "qwen3.5-route"), "think": False, "stream": False,
            "options": {"num_ctx": 4096}, "messages": [{"role": "user", "content": prompt}]}
    try:
        value = _post_json(url, body, timeout=80.0, headers={"X-UYP-Worker": "search"})
    except (OSError, urllib.error.URLError, ValueError):
        return None
    content = ((value.get("message") or {}).get("content") if isinstance(value, dict) else None) or ""
    return content.strip() or None


def _lock_stamp() -> float | None:
    try:
        with open(INTERACTIVE_LOCK, encoding="utf-8") as fh:
            return float(fh.read().strip())
    except (OSError, ValueError):
        try:
            return os.path.getmtime(INTERACTIVE_LOCK)
        except OSError:
            return None


def _yield_then_mark() -> str:
    """Wait briefly while another interactive turn (voice) holds a fresh lock,
    then mark our own turn so the indexer's enrichment yields to us."""
    try:
        max_wait = float(os.environ.get("UYP_ASK_YIELD_MAX_S", "5"))
    except ValueError:
        max_wait = 5.0
    waited = 0.0
    while waited < max_wait:
        stamp = _lock_stamp()
        if stamp is None or time.time() - stamp > 5:
            break
        time.sleep(0.5)
        waited += 0.5
    mine = str(time.time())
    try:
        with open(INTERACTIVE_LOCK, "w", encoding="utf-8") as fh:
            fh.write(mine)
    except OSError:
        try:
            os.utime(INTERACTIVE_LOCK, None)
        except OSError:
            pass
    return mine


def _release(mine: str) -> None:
    try:
        with open(INTERACTIVE_LOCK, encoding="utf-8") as fh:
            if fh.read().strip() != mine:
                return  # someone else (voice) refreshed it; leave theirs alone
        os.remove(INTERACTIVE_LOCK)
    except OSError:
        pass


def rank_hits(items: list[dict], question: str, names: set[str]) -> list[tuple[float, dict]]:
    """Top lexical matches as (raw_score, item), owner's own files first.

    * the project's own name is not evidence (every file "belongs" to it);
    * the classifier's tier A/B files win near-ties;
    * any match in the owner's own files outranks every match inside an
      embedded third-party root; embedded matches only fill remaining slots
      (down-weighted among themselves) and at most EMBEDDED_MAX_HITS of them -
      unless the question names that folder, in which case they compete
      normally ("how does gbrain search work").
    """
    lowered = question.lower()
    name_tokens: set[str] = set()
    for n in names:
        name_tokens.update(tokenize(n))
    tokens = [t for t in _question_tokens(question) if t not in name_tokens]
    if not tokens:
        return []
    mentioned = {root for root in {i.get("embedded") for i in items if i.get("embedded")}
                 if posixpath.basename(root.rstrip("/")).lower() in lowered}
    scored = []
    for item in items:
        raw = lexical_score({"file": item["file"], "derived": {
            "purpose": item["purpose"], "key_points": item.get("key_points") or [],
            "components": item.get("components") or []}}, tokens)
        if raw <= 0:
            continue
        weight = TIER_WEIGHT.get(item.get("tier") or "", 1.0)
        demoted = bool(item.get("embedded")) and item["embedded"] not in mentioned
        if demoted:
            weight *= EMBEDDED_WEIGHT
        scored.append((raw * weight, raw, 0 if item["purpose"] else 1, demoted, item))
    # Own files first (demoted=False sorts before True), then weighted score.
    scored.sort(key=lambda t: (t[3], -t[0], t[2], _sort_key(t[4])))
    hits: list[tuple[float, dict]] = []
    embedded_taken = 0
    for _, raw, _, demoted, item in scored:
        if demoted:
            if embedded_taken >= EMBEDDED_MAX_HITS:
                continue
            embedded_taken += 1
        hits.append((raw, item))
        if len(hits) == ASK_HITS:
            break
    return hits


def _miss(name: str) -> dict:
    return {"answer": f"I don't have enough information about that in the analyzed knowledge of {name}.",
            "sources": [], "confidence": "none"}


def ask(context: dict, project_id: str, question: str, *, member: str | None = None, role: str | None = None,
        llm=None, gbrain=None) -> dict | None:
    resolved = _resolve(context, project_id)
    if resolved is None:
        return None
    _, record, jobs, _ = resolved
    _, items = P.project_items(record, active=(jobs.get(project_id) or {}).get("status") in {"queued", "running"})
    name = record.get("root_name") or project_id
    lowered = question.lower()
    names = {name.lower(), project_id.lower()}
    tokens = _question_tokens(question)  # also used below to filter gbrain blocks
    hits = rank_hits(items, question, names)
    key_question = any(word in lowered for word in KEY_FILE_WORDS)
    # Naming the project only makes it an overview question when nothing
    # specific matched ("tell me about commontasks"); "how does commontasks
    # check evidence" must lead with the files that answer it.
    overview_question = (key_question or any(word in lowered for word in OVERVIEW_WORDS)
                         or (not hits and any(n and n in lowered for n in names)))
    blocks = []
    if member and role and gbrain is not False:
        wanted = [t for t in tokens if len(t) >= 3]
        for block in (gbrain or gbrain_blocks)(question, member, role)[:10]:
            text = block["text"].lower()
            if any(n and n in text for n in names) or sum(1 for t in wanted if t in text) >= 2:
                blocks.append(block)
            if len(blocks) == 3:
                break
    if not hits and not blocks and not overview_question:
        return _miss(name)
    overview = overview_from(record, items)
    context_blocks = [f"PROJECT: {name}\nOVERVIEW: {overview}"]
    # Overview / key-file questions always see the owner's own key files first.
    key_entries = key_files_from(items)[:OVERVIEW_KEY_FILES] if overview_question else []
    for entry in key_entries:
        context_blocks.append(f"KEY FILE ({entry['tier'] or 'ranked'}): {entry['file']}\nPURPOSE: {entry['purpose']}")
    shown = {entry["file"] for entry in key_entries}
    for _, item in hits:
        if item["file"] in shown:
            continue
        label = f"FILE (inside bundled third-party folder {item['embedded']}/)" if item.get("embedded") else "FILE"
        context_blocks.append(
            f"{label}: {item['file']}\nPURPOSE: {item['purpose'] or '(structure only, no summary)'}\n"
            f"KEY_POINTS: {'; '.join(item.get('key_points') or [])}")
    for block in blocks:
        context_blocks.append(f"MEMORY ({block.get('brain') or 'brain'}): {' '.join(block['text'].split())[:600]}")
    prompt = (
        "You are a project knowledge assistant. Answer the question using ONLY the project knowledge "
        "below (file summaries from the analyzed project and the member's memory notes). State facts "
        "directly and name file paths where relevant. At most 4 sentences, no preamble. "
        f"If the knowledge below does not answer the question, reply with exactly {NOT_ENOUGH} and nothing else. "
        "Answer in the question's language.\n\nQUESTION: " + question + "\n\n" + "\n---\n".join(context_blocks))
    ordered = [entry["file"] for entry in key_entries] + [item["file"] for _, item in hits]
    sources = [{"file": f} for f in dict.fromkeys(ordered)]
    mine = _yield_then_mark()
    try:
        reply = (llm or ollama_chat)(prompt)
    finally:
        _release(mine)
    if reply is None:
        return {"answer": "The local model is not available right now; the most relevant files are listed as sources.",
                "sources": sources, "confidence": "unavailable"}
    if reply.strip().upper().startswith(NOT_ENOUGH):
        return _miss(name)
    confidence = "high" if hits and hits[0][0] >= 4 else ("medium" if hits else "low")
    return {"answer": reply.strip(), "sources": sources, "confidence": confidence}
