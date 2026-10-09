#!/usr/bin/env python3
"""knowledge_search v0 — 让已入册的 KnowledgeItem 回答"我在哪实现过X".

检索: 纯词法评分(119条不需要向量) — relpath/purpose/key_points/components
三段加权; qwen3.5-route think:false 合成带出处回答; 命中弱时诚实说没有.
用法: knowledge_search.py "哪里实现了委托签名"
"""
from __future__ import annotations
import json, os, re, subprocess, sys, glob

OUT_ROOT = os.path.expanduser("~/dev/uyp/output")

def load_items() -> list[dict]:
    items = []
    for path in glob.glob(f"{OUT_ROOT}/*/*.knowledge.json"):
        d = json.load(open(path, encoding="utf-8"))
        d["_out_path"] = path
        items.append(d)
    return items

def tokenize(q: str) -> list[str]:
    return [t for t in re.split(r"[\s/_.\-()]+", q.lower()) if len(t) > 1]

def score(item: dict, tokens: list[str]) -> float:
    rel = item["file"].lower()
    der = item.get("derived") or {}
    purpose = str(der.get("purpose", "")).lower()
    keys = " ".join(str(x) for x in (der.get("key_points") or [])).lower()
    comps = " ".join(str(x) for x in (der.get("components") or [])).lower()
    s = 0.0
    for t in tokens:
        if t in rel: s += 3.0          # 路径命中权重最高
        if t in purpose: s += 2.0
        if t in keys: s += 1.5
        if t in comps: s += 1.0
        if t in rel.split("/")[-1]: s += 1.0
    # 词法同义小词典(中英)
    syn = {"签名": ["sign", "hmac", "signature"], "记忆": ["memory", "brain", "falkordb"],
           "路由": ["router", "route", "intent"], "预约": ["clinic", "booking"],
           "语音": ["voice", "tts", "stt"], "委托": ["delegation", "agent", "contracts"],
           "密码": ["key", "password", "secret"], "端口": ["port", "listen"], "服务": ["service", "plist", "launchagent"], "图谱": ["graph", "graphiti"]}
    for k, vs in syn.items():
        if k in "".join(tokens) or any(v in "".join(tokens) for v in vs):
            for v in vs:
                if v in rel or v in purpose: s += 1.2
    return s

def answer(question: str, items: list[dict]) -> dict:
    tokens = tokenize(question)
    scored = sorted(((score(i, tokens), i) for i in items), key=lambda x: -x[0])
    top = [(s, i) for s, i in scored[:3] if s > 0]
    if not top:
        return {"answer": f"已索引的 {len(items)} 个文件里没有匹配到相关实现。",
                "sources": [], "confidence": "none"}
    ctx_blocks = []
    for s, i in top:
        der = i.get("derived") or {}
        ctx_blocks.append(
            f"FILE: {i['file']}\n"
            f"PURPOSE: {der.get('purpose', '(structure-only: ' + json.dumps({k:v for k,v in der.items() if k in ('lines','py_defs','imports')}) + ')')}\n"
            f"KEY_POINTS: {'; '.join(str(x) for x in (der.get('key_points') or [])[:3])}")
    prompt = (
        "You are a project knowledge assistant. Answer the question using ONLY the "
        "indexed file knowledge below. Cite file paths in your answer. If the indexed "
        "knowledge does not contain the answer, say so honestly. Answer in the question's "
        "language, max 3 sentences.\n\nQUESTION: " + question + "\n\n" +
        "\n---\n".join(ctx_blocks))
    body = json.dumps({"model": "qwen3.5-route", "think": False, "stream": False,
                       "options": {"num_ctx": 4096},
                       "messages": [{"role": "user", "content": prompt}]})
    r = subprocess.run(["curl", "-s", "127.0.0.1:11434/api/chat", "-d", body, "--max-time", "120"],
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    return {"answer": (d.get("message", {}) or {}).get("content", "").strip(),
            "sources": [{"file": i["file"], "match": round(s, 1)} for s, i in top],
            "confidence": "high" if top[0][0] >= 4 else "medium"}

if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or sys.stdin.read()
    result = answer(q, load_items())
    print(result["answer"])
    print("\nsources:")
    for src in result["sources"]:
        print(f"  [{src['match']:4.1f}] {src['file']}")
