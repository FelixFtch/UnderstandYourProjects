#!/usr/bin/env python3
"""knowledge_search v0 — 让已入册的 KnowledgeItem 回答"我在哪实现过X".

检索: 纯词法评分(119条不需要向量) — relpath/purpose/key_points/components
三段加权; qwen3.5-route think:false 合成带出处回答; 检索无命中或知识真缺答案时
只回 "Not in the indexed projects." (统一口径, 不许半遮半掩的免责声明).
用法: knowledge_search.py "哪里实现了委托签名"
"""
from __future__ import annotations
import json, os, re, subprocess, sys, glob

OUT_ROOT = os.path.expanduser(os.environ.get("UYP_OUTPUT_ROOT", "~/dev/uyp/output"))

def load_items(root: str | None = None) -> list[dict]:
    items = []
    root = root or OUT_ROOT
    for path in glob.glob(f"{root}/*/*.knowledge.json"):
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

INTERACTIVE_LOCK = "/tmp/uyp_interactive.lock"

def _touch_interactive_lock():
    """交互查询在途标志: 索引侧富集看到新鲜旗标即让路(语音>查询>索引铁律,
    2026-10-10 现场事故: 全量索引占满 ollama 5 槽, 'say OK' 都 10s 超时)。"""
    import time as _t
    with open(INTERACTIVE_LOCK, "w") as fh:
        fh.write(str(_t.time()))

def _clear_interactive_lock():
    try:
        os.remove(INTERACTIVE_LOCK)
    except OSError:
        pass


def answer(question: str, items: list[dict]) -> dict:
    _touch_interactive_lock()
    try:
        return _answer_locked(question, items)
    finally:
        _clear_interactive_lock()


def _answer_locked(question: str, items: list[dict]) -> dict:
    tokens = tokenize(question)
    scored = sorted(((score(i, tokens), i) for i in items), key=lambda x: -x[0])
    top = [(s, i) for s, i in scored[:3] if s > 0]
    if not top:
        # Same canonical miss sentence the synthesis prompt demands - a genuine
        # miss is never partially hedged, from either path.
        return {"answer": "Not in the indexed projects.",
                "sources": [], "confidence": "none"}
    ctx_blocks = []
    for s, i in top:
        der = i.get("derived") or {}
        ctx_blocks.append(
            f"FILE: {i['file']}\n"
            f"PURPOSE: {der.get('purpose', '(structure-only: ' + json.dumps({k:v for k,v in der.items() if k in ('lines','py_defs','imports')}) + ')')}\n"
            f"KEY_POINTS: {'; '.join(str(x) for x in (der.get('key_points') or [])[:3])}")
    prompt = (
        "You are a project knowledge assistant. Answer using ONLY the indexed file "
        "knowledge below. The indexed knowledge IS the ground truth - do NOT apologize "
        "or hedge; if the sources name files, state them directly as fact.\n"
        "Answer shape: first sentence answers the question and names the file path(s); "
        "second sentence says what that code does; then stop. Never open with preambles "
        "like 'based on the provided documents'. Max 2 sentences.\n"
        "If the indexed knowledge genuinely lacks the answer, reply with exactly "
        "'Not in the indexed projects.' and nothing else - no partial hedging.\n"
        "Answer in the question's language.\n\nQUESTION: " + question + "\n\n" +
        "\n---\n".join(ctx_blocks))
    body = json.dumps({"model": "qwen3.5-route", "think": False, "stream": False,
                       "options": {"num_ctx": 4096},
                       "messages": [{"role": "user", "content": prompt}]})
    r = subprocess.run(["curl", "-s", "127.0.0.1:11434/api/chat", "-d", body, "--max-time", "120"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return {"answer": "本地模型服务暂不可用，无法生成带出处的回答。", "sources": [{"file": i["file"], "match": round(s, 1)} for s, i in top], "confidence": "unavailable"}
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"answer": "本地模型返回了无法解析的结果，无法生成带出处的回答。", "sources": [{"file": i["file"], "match": round(s, 1)} for s, i in top], "confidence": "unavailable"}
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
