#!/usr/bin/env python3
"""Anchored enrichment (terminal-state pass 1): UA structure drives semantics. v3.3.

Reads the UA knowledge-graph (tree-sitter symbols with lineRange), then
re-enriches each published KnowledgeItem with a prompt that:
  - lists the file's REAL symbols (name, lines, span) sorted by span size
  - forces purpose to name the primary actor — v3.3 selects the actor by
    ROLE, not raw largest span: the EXPORTED (public, no leading
    underscore) symbol the file is named after wins; else the largest
    EXPORTED span; largest span only when no public symbol exists.
    (v3.2 blind re-audit case: signing.py anchored the SeenDelegations
    helper so sign/verify never appeared.)
  - requires every key_point to cite a line range FROM THE SYMBOL TABLE
  - classifies each point fact/structure/inference
  - v3.3 protocol validation (re-audit prescription 1): purpose /
    key_points / components that echo instruction text, keep the unparsed
    [fact|structure|inference] placeholder, or splice a citation
    mid-sentence are REJECTED — one corrective retry, then raw_head.
    Empty key_points get one retry ("include at least two key_points
    about what the code DOES"); empty components fall back to the top-3
    table rows verbatim (deterministic, always available).
  - v3.3 docstring guard (prescription 4): the prompt warns the top
    docstring may be STALE; contradicting key_points carry
    [docstring-stale].
Citations that are not exactly a symbol-table interval after snapping keep
the (unverified Lx-Ly) marker — honest marking, verified for components too.
Keeps the old summary as derived_v1 for A/B comparison.

Usage: anchored_enrich.py --graph <knowledge-graph.json> --output-root <dir> \
         --host http://127.0.0.1:7121 --token-file ~/.config/uyp/token \
         --grant g_ab13bf8a [--only substr ...] [--dry-run]
"""
from __future__ import annotations
import argparse, glob, json, os, re, subprocess, time, unicodedata, urllib.request

def api(host, token, path, binary=False):
    req = urllib.request.Request(host.rstrip("/") + path,
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = r.read()
        return d if binary else json.loads(d)

def load_symbols(graph_path: str) -> dict[str, list[dict]]:
    g = json.load(open(graph_path, encoding="utf-8"))
    per_file: dict[str, list[dict]] = {}
    for n in g.get("nodes", []):
        if n.get("type") in ("function", "class") and n.get("filePath") and n.get("lineRange"):
            per_file.setdefault(n["filePath"], []).append(
                {"name": n["name"], "kind": n["type"],
                 "lo": int(n["lineRange"][0]), "hi": int(n["lineRange"][1])})
    for syms in per_file.values():
        syms.sort(key=lambda s: (s["hi"] - s["lo"]), reverse=True)  # 主角(最大跨度)在前
    return per_file

def qwen(prompt: str) -> tuple[str, int]:
    body = json.dumps({"model": "qwen3.5-route", "think": False, "stream": False,
                       "options": {"num_ctx": 4096},
                       "messages": [{"role": "user", "content": prompt}]})
    import time as _t
    for attempt in range(3):
        r = subprocess.run(["curl", "-s", "127.0.0.1:11434/api/chat", "-d", body, "--max-time", "200"],
                           capture_output=True, text=True)
        if r.stdout.strip():
            try:
                d = json.loads(r.stdout)
                return (d.get("message", {}) or {}).get("content", ""), d.get("eval_count", 0)
            except json.JSONDecodeError:
                pass
        print(f"  [qwen retry {attempt}] rc={r.returncode} out={r.stdout[:50]!r}", flush=True)
        _t.sleep(5)
    raise RuntimeError("qwen unavailable after retries")

INSTR = """You are a project file analyzer. You are given a file's REAL symbol table
extracted by tree-sitter (authoritative structure) and the file's source text.

Output STRICTLY in this line format (one line each, no JSON, no code fences,
no extra text; write key_point text WITHOUT double quotes):
P: <one sentence, subject = the PRIMARY ACTOR named below>
K: [fact|structure|inference] <point> (L<lo>-L<hi>)   <- range copy-pasted from the table
C: <symbol name> (L<lo>-L<hi>)
D: <import>
Rules: 2-4 K lines; ranges only from the symbol table rows; summarize the
CODE not docstrings; depends_on only imports actually present; answer in the
file's language. The (L<lo>-L<hi>) citation is the LAST thing on every K and
C line — never continue the sentence after the range. The file's top
docstring may be STALE — if the code contradicts it, describe the code and
add [docstring-stale] to that key_point.
"""

# --------------------------------------------------------------------------- v3.3 pure logic (unit-tested)

def _norm_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())

def select_anchor(syms: list[dict], rel_path: str) -> dict | None:
    """v3.3 anchor by role, not largest span (re-audit prescription 2).

    Tier 1 (role): the file is NAMED after this public symbol — normalized
      stem and symbol name share a >=4-char prefix in either direction
      (signing.py -> sign, chat_bridge.py -> ChatBridge). This is what the
      plain "public + largest span" rule cannot express: signing.py's
      largest public symbol is still the SeenDelegations helper class.
    Tier 2 (prescribed): largest span among EXPORTED symbols (public names,
      no leading underscore); private helpers never anchor while a public
      symbol exists.
    Tier 3 (prescribed fallback): largest span overall — only when the file
      has no public symbol at all.
    The full span-sorted table is still passed alongside (both, per audit).
    """
    if not syms:
        return None
    def span(s: dict) -> int:
        return s["hi"] - s["lo"]
    public = [s for s in syms if not s["name"].startswith("_")]
    stem = _norm_name(os.path.basename(rel_path).rsplit(".", 1)[0])
    def file_named_after(s: dict) -> bool:
        n = _norm_name(s["name"])
        return (len(n) >= 4 and stem.startswith(n)) or (len(stem) >= 4 and n.startswith(stem))
    pool = [s for s in public if file_named_after(s)] or public or syms
    return max(pool, key=span)

# instruction-text fragments that must never appear in purpose/KP/component text
LEAK_FRAGMENTS = ("primary actor", "purpose must", "per instruction",
                  "symbol table", "tree-sitter", "span")
LABEL_PLACEHOLDER = re.compile(r"\[\s*fact\s*\|\s*structure\s*\|\s*inference\s*\]", re.IGNORECASE)
# citations after snap_all: "(L83-L91)" or "(unverified L12-L34)"
CITATION = re.compile(r"\((?:unverified\s+)?L\d{1,4}\s*[-\u2013]\s*L\d{1,4}\)")
STALE_MARKER = re.compile(r"\[\s*docstring-stale\s*\]", re.IGNORECASE)

def _continuation_words(tail: str) -> str:
    """Non-punctuation content left in `tail` ('' -> citation may sit there)."""
    t = STALE_MARKER.sub("", tail)
    return "".join(ch for ch in t
                   if not unicodedata.category(ch).startswith("P") and not ch.isspace())

def leak_reason(text: str) -> str | None:
    """v3.3 protocol validation (re-audit prescription 1). None = clean."""
    if not text:
        return None
    low = text.lower()
    for frag in LEAK_FRAGMENTS:
        if re.search(rf"\b{re.escape(frag)}\b", low):
            return f"instruction fragment {frag!r}"
    if LABEL_PLACEHOLDER.search(text):
        return "unparsed label placeholder"
    # citation must be the FINAL token run: any range followed by
    # continuation words (earlier citations included) is a mid-sentence splice
    for m in CITATION.finditer(text):
        if _continuation_words(text[m.end():]):
            return "citation not final (mid-sentence splice)"
    return None

def snap_all(text: str, syms: list[dict]) -> str:
    """行号吸附: 生成区间吸附到重叠符号的精确区间, 无重叠标 unverified。"""
    def rep(m):
        lo, hi = int(m.group(1)), int(m.group(2))
        cands = [sy for sy in syms if not (hi < sy["lo"] or lo > sy["hi"])]
        if not cands:
            return f"(unverified L{lo}-L{hi})"
        best = max(cands, key=lambda sy: min(hi, sy["hi"]) - max(lo, sy["lo"]))
        return f"(L{best['lo']}-L{best['hi']})"
    return re.sub(r"\(?(?:L ?)?(\d{1,4})\s*[-\u2013]\s*(?:L ?)?(\d{1,4})\)?", lambda m: rep(m), text)

def settle_stale_marker(text: str) -> str:
    """Move a trailing [docstring-stale] BEFORE the final citation so the
    dashboard's trailing-citation chips (v3.2 format) keep parsing."""
    cites = list(CITATION.finditer(text))
    if not cites:
        return text
    last = cites[-1]
    m = STALE_MARKER.search(text, last.end())
    if not m:
        return text
    rest = (text[last.end():m.start()] + text[m.end():]).strip()
    head = text[:last.start()].rstrip()
    if not _continuation_words(rest):
        rest = ""  # punctuation-only tail: drop it, the citation is final again
    return f"{head} {m.group(0)} {text[last.start():last.end()]}" + (f" {rest}" if rest else "")

def parse_response(raw: str, syms: list[dict]) -> dict | None:
    """v3.2 line protocol (deterministic; JSON kept failing on quoted code)
    + v3.3 citation snapping on every purpose/KP/component."""
    cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw.strip(), flags=re.M)
    parsed = {"purpose": "", "key_points": [], "components": [], "depends_on": []}
    # 先按内嵌标记切分(模型偶发把 K:/C: 塞进同一行), 再逐段归类
    segments = []
    for line in cleaned.split("\n"):
        line = line.strip().strip("`")
        if not line:
            continue
        for part in re.split(r"(?=(?:^|\s)(?:P|K|C|D): )", line):
            part = part.strip()
            if part:
                segments.append(part)
    # v3.3.1 修复优先于拒收(实测 RAW 率 100%: 模型常漏 C 行行号/带 P 行尾注)
    repaired = []
    sym_by_name = {sy["name"]: sy for sy in syms}
    for part in segments:
        if part.startswith("P:"):
            body = part[2:].strip()
            for meta in (" — the file", " (the file", " — purpose", " (purpose",
                         " (largest span", " — largest span", " (anchor", " — anchor",
                         " (the P line", " — the P line"):
                if meta in body:
                    body = body.split(meta)[0].rstrip(" -–(").strip()
            part = "P: " + body
        if part.startswith("C:") and not re.search(r"\(L\d+", part):
            name = part[2:].split("(")[0].strip().strip("`\"'")
            base = name.split(".")[0].split("=")[0].strip()
            sy = sym_by_name.get(name) or sym_by_name.get(base)
            if sy:
                part = f"C: {name} (L{sy['lo']}-L{sy['hi']})"
            else:
                continue  # 丢一行不丢整个回答
        repaired.append(part)
    segments = repaired
    for part in segments:
        if part.startswith("P:") and not parsed["purpose"]:
            parsed["purpose"] = snap_all(part[2:].strip(), syms)
        elif part.startswith("K:"):
            parsed["key_points"].append(settle_stale_marker(snap_all(part[2:].strip(), syms)))
        elif part.startswith("C:"):
            parsed["components"].append(snap_all(part[2:].strip(), syms))
        elif part.startswith("D:"):
            parsed["depends_on"].append(part[2:].strip())
    if not any(parsed.values()):
        return None  # 完全没按协议来
    return parsed

def validate(parsed: dict | None) -> list[str]:
    """Rejection reasons for a parsed response (empty list = accept)."""
    if not parsed:
        return ["no protocol lines"]
    reasons = []
    if parsed["purpose"]:
        r = leak_reason(parsed["purpose"])
        if r:
            reasons.append(f"purpose {r}")
    for kp in parsed["key_points"]:
        r = leak_reason(kp)
        if r:
            reasons.append(f"key_point {r}")
    for c in parsed["components"]:
        r = leak_reason(c)
        if r:
            reasons.append(f"component {r}")
    if not parsed["key_points"]:
        reasons.append("key_points empty")
    return reasons

def nudge_for(reasons: list[str]) -> str:
    """Corrective nudge for the single v3.3 retry."""
    parts = []
    if any(("fragment" in r) or ("placeholder" in r) or ("not final" in r)
           or ("no protocol" in r) for r in reasons):
        parts.append("Your previous answer broke the output protocol: it echoed "
                     "instruction text, kept the literal [fact|structure|inference] "
                     "placeholder, or continued a sentence after a (L<lo>-L<hi>) citation. "
                     "Output again strictly: ONE chosen label in brackets, prose about the "
                     "CODE only, and every K and C line ends with its (L<lo>-L<hi>) range "
                     "as the final tokens.")
    if any("empty" in r for r in reasons):
        parts.append("Your previous answer had no key points — include at least two "
                     "key_points about what the code DOES.")
    return " ".join(parts) or "Follow the line protocol exactly."

def component_fallback(syms: list[dict]) -> list[str]:
    """Deterministic components when the model emitted none: top-3 rows of
    the span-sorted table, verbatim (always available)."""
    return [f"{s['name']} (L{s['lo']}-L{s['hi']})" for s in syms[:3]]

def build_prompt(anchor: dict, syms: list[dict], content: str) -> str:
    """Primary actor line AND the full span-sorted table (both, per audit)."""
    return (INSTR
            + f"\n\nPRIMARY ACTOR: {anchor['name']} L{anchor['lo']}-L{anchor['hi']}"
              " (the file's main symbol — the P line is about it)\n\n"
            + "SYMBOL TABLE (tree-sitter, sorted by span):\n"
            + "\n".join(f"  {s['kind']:8s} {s['name']}  L{s['lo']}-L{s['hi']}" for s in syms[:18])
            + "\n\nSOURCE TEXT:\n" + content)

# --------------------------------------------------------------------------- driver

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True)
    ap.add_argument("--output-root", required=True)
    ap.add_argument("--host", default="http://127.0.0.1:7121")
    ap.add_argument("--token-file", default=os.path.expanduser("~/.config/uyp/token"))
    ap.add_argument("--grant", required=True)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-anchor even if already anchored (v3 upgrade)")
    a = ap.parse_args()
    token = open(os.path.expanduser(a.token_file)).read().strip()
    symbols = load_symbols(a.graph)
    items = sorted(glob.glob(os.path.join(a.output_root, "*.knowledge.json")))
    n_done = n_tok = n_retry = 0
    for path in items:
        d = json.load(open(path, encoding="utf-8"))
        rel = d.get("file", "")
        if a.only and not any(s in rel for s in a.only):
            continue
        # 有真符号表的代码文件都值得锚定富集——包括被规则层/Laya 误判 structure-only 的核心文件
        # (审计盲区 #1/#2: platform_policy.py / chat_bridge.py 正是这类)
        syms = symbols.get(rel)
        if not syms:
            continue
        if d.get("derived", {}).get("anchored") and not a.force:
            continue  # 已锚定, 幂等 (--force 供 v3 升级重跑)
        anchor = select_anchor(syms, rel)
        if anchor is None:
            continue
        try:
            content = api(a.host, token,
                          f"/read?grant={a.grant}&relpath={urllib.request.quote(rel)}&length=262144",
                          binary=True).decode("utf-8", "replace")[:2800]
        except Exception as e:
            print(f"  read-fail {rel}: {e}", flush=True); continue
        prompt = build_prompt(anchor, syms, content)
        if a.dry_run:
            print(f"[dry] {rel}: {len(syms)} symbols, anchor={anchor['name']} "
                  f"L{anchor['lo']}-L{anchor['hi']} (table top={syms[0]['name']})", flush=True)
            continue
        t0 = time.time()
        raw, tok = "", 0
        parsed = None
        try:
            raw, tok = qwen(prompt)
            parsed = parse_response(raw, syms)
            reasons = validate(parsed)
            if reasons:
                # v3.3: reject -> one corrective retry -> raw_head
                n_retry += 1
                retry_prompt = (prompt + "\n\nCORRECTION — your previous answer was rejected ("
                                + "; ".join(reasons[:3]) + "). " + nudge_for(reasons)
                                + " Output the complete answer again in the strict line format.")
                try:
                    raw2, tok2 = qwen(retry_prompt)
                    tok += tok2
                    raw = raw2
                    parsed2 = parse_response(raw2, syms)
                    parsed = parsed2 if not validate(parsed2) else None
                except RuntimeError as e:
                    print(f"  qwen-fail(retry) {rel}: {e}", flush=True)
                    parsed = None
        except RuntimeError as e:
            print(f"  qwen-fail {rel}: {e}", flush=True); continue
        if parsed and not parsed["components"]:
            # 结构性泄漏修复: 72/119 零 components -> 表内前三行兜底 (确定性)
            parsed["components"] = component_fallback(syms)
            parsed["components_table_fallback"] = True
        d.setdefault("derived_v1", d.get("derived"))
        d["derived"] = parsed or {"raw_head": raw[:300]}
        d["derived"]["anchored"] = True
        d["anchor_symbols"] = len(syms)
        d["anchor_top"] = f"{anchor['name']} L{anchor['lo']}-L{anchor['hi']}"
        json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        n_done += 1; n_tok += tok
        print(f"  anchored {rel[:66]} | anchor={anchor['name']} | {tok}tok {time.time()-t0:.0f}s | {'OK' if parsed else 'RAW'}", flush=True)
    print(f"\nDONE anchored={n_done} retries={n_retry} tokens={n_tok}")

if __name__ == "__main__":
    main()
