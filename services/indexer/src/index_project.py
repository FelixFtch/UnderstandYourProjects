#!/usr/bin/env python3
"""First-real-index runner (UYP indexer v0).

Chain: Connector manifest -> rule layer -> Laya triage (/v1/systemone) ->
qwen3.5 enrichment (think per gate, brace-extraction fallback) -> derived
KnowledgeItems to ~/dev/uyp/output/, state to ~/dev/uyp/state/.
Red lines: reads source bytes ONLY via the connector; never writes anything
into the source project; state/output live outside it by construction.

Usage: index_project.py --host http://127.0.0.1:7121 --grant g_xxx [--limit 20]
Requires: Laya llama-server on :8901 (start_laya.sh), ollama qwen3.5:4b.
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time, urllib.request

MODELS = "/home/jetson/dev/uyp/models"
BIN = "/home/jetson/dev/uyp/llama.cpp-build/build/bin"
STATE = os.path.expanduser("~/dev/uyp/state")
OUT = os.path.expanduser("~/dev/uyp/output")

def api(host, token, path, binary=False, timeout=90):
    req = urllib.request.Request(host.rstrip("/") + path,
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = r.read()
        return d if binary else json.loads(d)

def laya_decide(content: str) -> tuple[str, float]:
    body = json.dumps({"state": "repository file content:\n" + content[:900], "questions": {
        "triage": {"type": "choice", "instructions": "What analysis does this file deserve?",
          "criteria": {"skip": "trivial/marker/generated", "structure-only": "deps/config; no LLM",
                       "quick-summary": "docs worth one line", "deep-analysis": "core logic"}},
        "thinking": {"type": "noul",
                     "instructions": "Does analysis need multi-step reasoning?"}}}).encode()
    r = urllib.request.Request("http://127.0.0.1:8901/v1/systemone", data=body,
                               headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(r, timeout=60).read())["answers"]
    return d["triage"]["choice"], d["thinking"]["noul"]

def qwen_enrich(content: str, think: bool):
    instr = ("You are a project file analyzer. Output ONLY a JSON object with keys: "
             "purpose (one sentence), key_points (max 3 strings), components (max 3), "
             "depends_on (max 3). Answer in the SAME LANGUAGE as the file. No other text.")
    body = json.dumps({"model": "qwen3.5-route", "think": think, "stream": False,
                       "options": {"num_ctx": 4096},
                       "messages": [{"role": "user", "content": instr + "\n\nFILE CONTENT:\n" + content[:2600]}]})
    r = subprocess.run(["curl", "-s", "127.0.0.1:11434/api/chat", "-d", body, "--max-time", "400"],
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    content = (d.get("message", {}) or {}).get("content", "") or ""
    tokens = d.get("eval_count", 0)
    if not content.strip():
        # thinking 空转修复 (2026-10-09 实测: thinking 偶发把预算全烧在 reasoning,
        # content 为空)。降档 think:false 重试一次 - 15s 封顶, 保证必有可解析输出。
        body2 = body.replace('"think": true', '"think": false')
        r2 = subprocess.run(["curl", "-s", "127.0.0.1:11434/api/chat", "-d", body2, "--max-time", "120"],
                            capture_output=True, text=True)
        try:
            d2 = json.loads(r2.stdout)
            content = (d2.get("message", {}) or {}).get("content", "") or ""
            tokens += d2.get("eval_count", 0)
        except json.JSONDecodeError:
            pass
    return content, tokens

def brace_json(text: str):
    """Thinking mode sometimes wraps JSON - extract first {...} block."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

def rule_pretriage(rel: str, size: int) -> str | None:
    """Zero-cost layer: extension/size rules decided before any model call."""
    ext = os.path.splitext(rel)[1].lower()
    if size == 0:
        return "skip"
    if ext in {".md", ".markdown"}:
        return None  # let Laya judge docs (known over-triage, calibrated later)
    if ext in {".py", ".ts", ".tsx", ".js", ".swift", ".rs", ".go", ".cpp", ".c", ".h", ".m"}:
        return None  # code -> Laya
    if ext in {".toml", ".yaml", ".yml", ".json", ".cfg", ".ini", ".lock", ".txt", ".sh"}:
        return "structure-only"
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".onnx", ".gguf", ".bin"}:
        return "skip"
    return "structure-only"

def structure_only_summary(content: str) -> dict:
    lines = content.split("\n")
    return {"kind": "structure-only",
            "lines": len(lines),
            "py_defs": len(re.findall(r"^\s*(def|class) ", content, re.M)) if content else 0,
            "imports": len(re.findall(r"^(import|from) ", content, re.M)) if content else 0}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:7121")
    ap.add_argument("--token-file", default=os.path.expanduser("~/.config/uyp/token"))
    ap.add_argument("--grant", required=True)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--force", action="store_true", help="re-analyze even if same-version output exists")
    a = ap.parse_args()
    token = open(a.token_file).read().strip()

    man = api(a.host, token, f"/manifest?grant={a.grant}")
    root = man["root_name"]
    os.makedirs(f"{STATE}", exist_ok=True)
    os.makedirs(f"{OUT}/{root}", exist_ok=True)

    stats = {"rule_skip": 0, "rule_structure": 0, "laya_skip": 0, "laya_structure": 0,
             "quick": 0, "deep": 0, "json_ok": 0, "json_bad": 0, "tokens": 0}
    t_start = time.time()
    def worth(f):
        rel, ext = f["relpath"], os.path.splitext(f["relpath"])[1].lower()
        if ext in {".py", ".ts", ".tsx", ".js", ".swift", ".rs", ".go", ".m"}: rank = 0
        elif ext in {".md", ".markdown"}: rank = 1
        elif ext in {".sh", ".toml", ".yaml", ".yml"}: rank = 2
        elif ext in {".json", ".plist", ".cfg", ".ini", ".txt"}: rank = 3
        else: rank = 4
        return (rank, rel.count("/"), rel)
    all_files = sorted([f for f in man["files"] if f["kind"] == "file"], key=worth)
    # 增量/续跑: 同版本已有产出则跳过 (首扫幂等化的关键)
    def done_before(f):
        safe = f["relpath"].replace("/", "__") + ".knowledge.json"
        path = f"{OUT}/{root}/{safe}"
        if not os.path.exists(path):
            return False
        try:
            return json.load(open(path)).get("version", {}).get("mtime") == f["mtime"]
        except Exception:
            return False
    if not a.force:
        skipped = sum(1 for f in all_files if done_before(f))
        files = [f for f in all_files if not done_before(f)][:a.limit]
        if skipped:
            print(f"resume: skipping {skipped} already-processed files", flush=True)
    else:
        files = all_files[:a.limit]
    print(f"indexing {root}: {len(files)} files (of {man['total']})", flush=True)
    for f in files:
        rel, size = f["relpath"], f["size"]
        head = api(a.host, token,
                   f"/read?grant={a.grant}&relpath={rel}&length=1024", binary=True).decode("utf-8", "replace")
        verdict = rule_pretriage(rel, size)
        gate = 0.0
        if verdict is None:
            verdict, gate = laya_decide(head)
        # 首扫铺底策略 (ADR-0001 分层): 全量 think:false 铺覆盖, gate 值照记;
        # deep 留给维护窗口的第二遍 (按 gate 挑 top 文件), 不在首扫烧 thinking。
        think = False
        item = {"file": rel, "version": {"mtime": f["mtime"], "size": size},
                "verdict": verdict, "think_gate": round(gate, 2),
                "source": "mac-connector", "analyzed_at": time.strftime("%FT%T")}
        READ_CAP = 16 * 1024 * 1024  # connector /read per-file cap
        def safe_read(rel, size, maxb):
            # 超限文件不读字节, 只回空串(下游走 metadata-only)
            if size > READ_CAP:
                return None
            try:
                return api(a.host, token,
                           f"/read?grant={a.grant}&relpath={rel}&length={maxb}",
                           binary=True).decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code == 413:
                    return None
                raise
        if verdict == "skip":
            stats["rule_skip" if gate == 0.0 and rel.startswith((".", "assets")) else "laya_skip"] += 1
        elif verdict == "structure-only":
            full = safe_read(rel, size, min(size, 262144))
            item["derived"] = structure_only_summary(full or "")
            if full is None:
                item["derived"]["too_large"] = True
            stats["rule_structure" if gate == 0.0 else "laya_structure"] += 1
        else:
            full = safe_read(rel, size, min(size, 262144))
            if full is None:
                item["derived"] = {"too_large": True, "size": size}
                item["verdict"] = "structure-only"
                stats["rule_structure"] += 1
                safe = rel.replace("/", "__") + ".knowledge.json"
                with open(f"{OUT}/{root}/{safe}", "w", encoding="utf-8") as fh:
                    json.dump(item, fh, ensure_ascii=False, indent=1)
                print(f"  too-large->{verdict:15s} {rel[:70]}", flush=True)
                continue
            t0 = time.time()
            raw, tok = qwen_enrich(full, think)
            stats["tokens"] += tok
            parsed = brace_json(raw)
            item["derived"] = parsed or {"raw_head": raw[:400]}
            item["think_used"] = think
            item["eval_tokens"] = tok
            item["enrich_s"] = round(time.time() - t0, 1)
            stats["deep" if think else "quick"] += 1
            stats["json_ok" if parsed else "json_bad"] += 1
        safe = rel.replace("/", "__") + ".knowledge.json"
        with open(f"{OUT}/{root}/{safe}", "w", encoding="utf-8") as fh:
            json.dump(item, fh, ensure_ascii=False, indent=1)
        print(f"  {verdict:15s} {'think' if think else '     '} {rel[:70]}", flush=True)
    json.dump({"grant": a.grant, "root": root, "ran_at": time.strftime("%FT%T"), "stats": stats},
              open(f"{STATE}/{root}.json", "w"))
    print(f"\nDONE in {time.time()-t_start:.0f}s | {json.dumps(stats)}")

if __name__ == "__main__":
    main()
