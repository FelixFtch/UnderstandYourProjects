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

Output STRICTLY in this line format (one line each, no JSON, no code fences,
no extra text; write key_point text WITHOUT double quotes):
P: <one sentence, subject = the PRIMARY ACTOR named below>
K: [fact|structure|inference] <point> (L<lo>-L<hi>)   <- range copy-pasted from the table
C: <symbol name> (L<lo>-L<hi>)
D: <import>
Rules: max 4 K lines; ranges only from the symbol table rows; summarize the
CODE not docstrings; depends_on only imports actually present; answer in the
file's language.
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
    ap.add_argument("--force", action="store_true", help="re-anchor even if already anchored (v3 upgrade)")
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
        if d.get("derived", {}).get("anchored") and not a.force:
            continue  # 已锚定, 幂等 (--force 供 v3 升级重跑)
        try:
            content = api(a.host, token,
                          f"/read?grant={a.grant}&relpath={urllib.request.quote(rel)}&length=262144",
                          binary=True).decode("utf-8", "replace")[:2800]
        except Exception as e:
            print(f"  read-fail {rel}: {e}", flush=True); continue
        prompt = (INSTR + f"\n\nPRIMARY ACTOR: {syms[0]['name']} L{syms[0]['lo']}-L{syms[0]['hi']} (largest span — purpose MUST be about this symbol)\n\n"
                  + "SYMBOL TABLE (tree-sitter, sorted by span):\n"
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
        def snap_all(text: str) -> str:
            """行号吸附: 生成区间吸附到重叠符号的精确区间, 无重叠标 unverified。"""
            def rep(m):
                lo, hi = int(m.group(1)), int(m.group(2))
                cands = [sy for sy in syms if not (hi < sy["lo"] or lo > sy["hi"])]
                if not cands:
                    return f"(unverified L{lo}-L{hi})"
                best = max(cands, key=lambda sy: min(hi, sy["hi"]) - max(lo, sy["lo"]))
                return f"(L{best['lo']}-L{best['hi']})"
            return re.sub(r"\(?(?:L ?)?(\d{1,4})\s*[-\u2013]\s*(?:L ?)?(\d{1,4})\)?", lambda m: rep(m), text)
        cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw.strip(), flags=re.M)
        # v3.2: 行式协议确定性解析 (JSON 在含引号代码上反复失败)
        parsed = {"purpose": "", "key_points": [], "components": [], "depends_on": []}
        import re as _re2
        # 先按内嵌标记切分(模型偶发把 K:/C: 塞进同一行), 再逐段归类
        segments = []
        for line in cleaned.split("\n"):
            line = line.strip().strip("`")
            if not line:
                continue
            for part in _re2.split(r"(?=(?:^|\s)(?:P|K|C|D): )", line):
                part = part.strip()
                if part:
                    segments.append(part)
        for part in segments:
            if part.startswith("P:") and not parsed["purpose"]:
                parsed["purpose"] = part[2:].strip()
            elif part.startswith("K:"):
                parsed["key_points"].append(snap_all(part[2:].strip()))
            elif part.startswith("C:"):
                parsed["components"].append(snap_all(part[2:].strip()))
            elif part.startswith("D:"):
                parsed["depends_on"].append(part[2:].strip())
        if not parsed["purpose"] and not parsed["key_points"]:
            parsed = None  # 完全没按协议来 -> raw_head 兜底
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
