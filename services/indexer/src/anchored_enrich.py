#!/usr/bin/env python3
"""Anchored enrichment (terminal-state pass 1): UA structure drives semantics.

Reads the UA knowledge-graph (tree-sitter symbols with lineRange), then
re-enriches each published KnowledgeItem with a prompt that:
  - lists the file's REAL symbols (name, lines, span) sorted by span size
  - forces purpose to name the primary actor
  - requires every key_point to cite a line range FROM THE SYMBOL TABLE
  - classifies each point fact/structure/inference
Keeps the old summary as derived_v1 for A/B comparison.

Usage: anchored_enrich.py --graph <knowledge-graph.json> --output-root <dir> \
         --host http://127.0.0.1:7121 --token-file ~/.config/uyp/token \
         --grant g_ab13bf8a [--only substr ...] [--dry-run]
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time, urllib.request

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

Rules:
1. purpose: one sentence naming the file's PRIMARY ACTOR — the largest/most
   central symbol from the table (by span) — and what it does.
2. key_points: max 4. EACH point must END with a line-range citation
   (Lxx-Lyy) taken from the symbol table. Cite only ranges that exist in
   the table. Classify each point: [fact] directly readable, [structure]
   from symbol shape, [inference] your deduction.
3. components: the symbol names that matter, with their lines.
4. Summarize the CODE, not docstrings or comments (they may be stale).
5. Answer in the SAME LANGUAGE as the file. Output ONLY the JSON object:
{"purpose": str, "key_points": [str], "components": [str], "depends_on": [str]}
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True)
    ap.add_argument("--output-root", required=True)
    ap.add_argument("--host", default="http://127.0.0.1:7121")
    ap.add_argument("--token-file", default=os.path.expanduser("~/.config/uyp/token"))
    ap.add_argument("--grant", required=True)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    token = open(os.path.expanduser(a.token_file)).read().strip()
    symbols = load_symbols(a.graph)
    import glob
    items = sorted(glob.glob(os.path.join(a.output_root, "*.knowledge.json")))
    n_done = n_tok = 0
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
        if d.get("derived", {}).get("anchored"):
            continue  # 已锚定, 幂等
        try:
            content = api(a.host, token,
                          f"/read?grant={a.grant}&relpath={urllib.request.quote(rel)}&length=262144",
                          binary=True).decode("utf-8", "replace")[:2800]
        except Exception as e:
            print(f"  read-fail {rel}: {e}", flush=True); continue
        prompt = (INSTR + "\n\nSYMBOL TABLE (tree-sitter, sorted by span):\n"
                  + "\n".join(f"  {s['kind']:8s} {s['name']}  L{s['lo']}-L{s['hi']}" for s in syms[:18])
                  + "\n\nSOURCE TEXT:\n" + content)
        if a.dry_run:
            print(f"[dry] {rel}: {len(syms)} symbols, top={syms[0]['name']} L{syms[0]['lo']}-{syms[0]['hi']}", flush=True)
            continue
        t0 = time.time()
        try:
            raw, tok = qwen(prompt)
        except RuntimeError as e:
            print(f"  qwen-fail {rel}: {e}", flush=True); continue
        import re
        m = re.search(r"\{.*\}", raw, re.S)
        parsed = None
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = None  # 截断/畸形 JSON -> raw_head 兜底
        d.setdefault("derived_v1", d.get("derived"))
        d["derived"] = parsed or {"raw_head": raw[:300]}
        d["derived"]["anchored"] = True
        d["anchor_symbols"] = len(syms)
        d["anchor_top"] = f"{syms[0]['name']} L{syms[0]['lo']}-L{syms[0]['hi']}"
        json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        n_done += 1; n_tok += tok
        print(f"  anchored {rel[:66]} | top={syms[0]['name']} | {tok}tok {time.time()-t0:.0f}s | {'OK' if parsed else 'RAW'}", flush=True)
    print(f"\nDONE anchored={n_done} tokens={n_tok}")

if __name__ == "__main__":
    main()
