#!/usr/bin/env python3
"""knowledge_search v0 — 让已入册的 KnowledgeItem 回答"我在哪实现过X".

检索: 纯词法评分(119条不需要向量) — relpath/purpose/key_points/components
三段加权; qwen3.5-route think:false 合成带出处回答; 检索无命中或知识真缺答案时
只回 "Not in the indexed projects." (统一口径, 不许半遮半掩的免责声明).

Freshness path (2026-10 incident fix): time/freshness questions ("今天 homehub
仓改了什么", "what changed recently") are routed to _temporal_answer, which
orders candidates by the index's own time metadata (version.mtime, then
analyzed_at) and answers with per-file timestamps.  When the index has no
dated items, or the newest indexed content predates the asked window, it
answers honestly ("索引最新内容止于 X") instead of letting synthesis invent a
confident "nothing changed today".

用法: knowledge_search.py "哪里实现了委托签名"
"""
from __future__ import annotations
import json, os, re, subprocess, sys, glob, time
from datetime import datetime, timedelta

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

# 统一口径的"知识真缺"回答: 检索无命中、或(群检索)引用越界时都说这一句,
# 不许半遮半掩的免责声明。query_api 的群检索后置检查也复用同一常量。
MISS_SENTENCE = "Not in the indexed projects."

# ---- Freshness / temporal questions ---------------------------------------
# A question about WHEN something changed must not be answered from lexical
# similarity alone: the 2026-10 incident had group search confidently invent
# "no changes today" because synthesis never saw any time metadata.

_TEMPORAL_RE = re.compile(
    r"今天|今日|昨天|昨日|这周|本周|最近|最新|改动|变更|改了|"
    r"\btoday\b|\byesterday\b|\brecent(?:ly)?\b|\blatest\b|"
    r"\bchanged?\b|\bchanges\b|\bupdated\b|\bthis week\b",
    re.IGNORECASE)

# Words that pin an explicit day/week window; bare "recent/latest" words only
# ask for recency ordering and never trigger the stale-index fallback.
_WINDOW_DAYS = (
    (re.compile(r"今天|今日|\btoday\b", re.IGNORECASE), 0),
    (re.compile(r"昨天|昨日|\byesterday\b", re.IGNORECASE), 1),
)


def is_temporal_question(question: str) -> bool:
    """True when the question asks about time/freshness rather than topic."""
    return bool(_TEMPORAL_RE.search(question or ""))


def _item_epoch(item: dict) -> float | None:
    """Best available timestamp of a KnowledgeItem, as epoch seconds.

    version.mtime (connector manifest, the source file's own mtime) wins;
    analyzed_at (indexer stamp, naive local %FT%T) is the fallback.  None
    when neither parses - such an item can never anchor a freshness answer.
    """
    mtime = (item.get("version") or {}).get("mtime")
    if isinstance(mtime, bool):
        mtime = None
    if isinstance(mtime, (int, float)):
        return float(mtime) if mtime > 0 else None
    if isinstance(mtime, str) and mtime.strip():
        try:
            return float(mtime)
        except ValueError:
            try:
                return datetime.fromisoformat(mtime.strip().replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
    stamp = item.get("analyzed_at")
    if isinstance(stamp, str) and stamp.strip():
        try:
            # naive %FT%T is written in the indexer's local time.
            return datetime.fromisoformat(stamp.strip()).timestamp()
        except ValueError:
            return None
    return None


def _fmt_local(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


def index_as_of(items: list[dict]) -> str | None:
    """Newest timestamp the index can prove, local time; None when undated."""
    epochs = [e for e in (_item_epoch(i) for i in items) if e is not None]
    return _fmt_local(max(epochs)) if epochs else None


def _window_start(question: str) -> float | None:
    """Local-midnight start of an explicitly asked day window, else None."""
    for pattern, days_back in _WINDOW_DAYS:
        if pattern.search(question or ""):
            day = (datetime.now() - timedelta(days=days_back)).date()
            return time.mktime(datetime.combine(day, datetime.min.time()).timetuple())
    if re.search(r"这周|本周|\bthis week\b", question or "", re.IGNORECASE):
        today = datetime.now().date()
        monday = today - timedelta(days=today.weekday())
        return time.mktime(datetime.combine(monday, datetime.min.time()).timetuple())
    return None


def _prefers_zh(question: str) -> bool:
    return bool(re.search(r"[一-鿿]", question or ""))


def _temporal_answer(question: str, items: list[dict]) -> dict:
    """Freshness-aware answer: order by time metadata, never invent recency."""
    zh = _prefers_zh(question)
    dated = []
    for item in items:
        epoch = _item_epoch(item)
        if epoch is not None:
            dated.append((epoch, item))
    snapshot = index_as_of(items)
    if not dated:
        # Nothing in the index carries a parseable timestamp: say so plainly.
        text = ("索引内容没有时间元数据，无法回答时间相关问题。"
                if zh else
                "The indexed knowledge carries no time metadata, so I cannot answer time-based questions.")
        return {"answer": text, "sources": [], "confidence": "none",
                "index_as_of": None}
    dated.sort(key=lambda pair: -pair[0])
    window = _window_start(question)
    if window is not None and dated[0][0] < window:
        # The newest indexed content predates the asked window ("today",
        # "yesterday"): honest staleness, never a fabricated "no changes".
        newest_epoch, newest_item = dated[0]
        stamp = _fmt_local(newest_epoch)
        text = (f"索引最新内容止于 {stamp}（最新条目：{newest_item['file']}）；"
                f"这之后的改动尚未入册，无法据索引回答该时间窗内的情况。"
                if zh else
                f"The index's newest content stops at {stamp} (newest item: "
                f"{newest_item['file']}); anything after that is not indexed, "
                f"so I cannot answer for the asked window.")
        return {"answer": text,
                "sources": [{"file": newest_item["file"], "ts": stamp}],
                "confidence": "medium", "index_as_of": snapshot,
                # Producer-internal (query_api pops it before
                # responding): the staleness answer is a fact COMPUTED
                # across index metadata, not a quote from any one
                # item, so its evidence record is fact_type=inferred.
                "inferred_statements": {
                    newest_item["file"]:
                    f"Index edition ends at {stamp} (newest item: "
                    f"{newest_item['file']}); the asked time window is "
                    "beyond the indexed edition."}}
    # Fresh enough: order by time, lexical hits first as the topical filter.
    tokens = tokenize(question)
    hits = [(e, i) for e, i in dated if score(i, tokens) > 0]
    pool = (hits or dated)[:5]
    ctx_blocks = []
    for e, i in pool:
        der = i.get("derived") or {}
        ctx_blocks.append(
            f"FILE: {i['file']}\n"
            f"MODIFIED: {_fmt_local(e)}\n"
            f"PURPOSE: {der.get('purpose', '(structure-only)')}\n"
            f"KEY_POINTS: {'; '.join(str(x) for x in (der.get('key_points') or [])[:3])}")
    prompt = (
        "You are a project knowledge assistant answering a TIME/FRESHNESS question. "
        "Answer using ONLY the indexed file knowledge below, which is ordered newest "
        "first; each entry carries its own MODIFIED timestamp. The indexed knowledge "
        f"IS the ground truth; the index snapshot is as of {snapshot}.\n"
        "Answer shape: first sentence answers the question and names the file path(s) "
        "with their timestamps, newest first; then one sentence on what that code "
        "does; then stop. If none of the entries fall inside the asked window, say "
        "so honestly and name the newest entry's timestamp - never claim 'no changes' "
        "beyond what the timestamps prove. Max 3 sentences.\n"
        "If the indexed knowledge genuinely lacks the answer, reply with exactly "
        "'Not in the indexed projects.' and nothing else - no partial hedging.\n"
        "Answer in the question's language.\n\nQUESTION: " + question + "\n\n" +
        "\n---\n".join(ctx_blocks))
    body = json.dumps({"model": os.environ.get("UYP_OLLAMA_MODEL", "qwen3.5-route"), "think": False, "stream": False,
                       "options": {"num_ctx": 4096},
                       "messages": [{"role": "user", "content": prompt}]})
    r = subprocess.run(["curl", "-s", "-H", "X-UYP-Worker: search", "127.0.0.1:11434/api/chat", "-d", body, "--max-time", "120"],
                       capture_output=True, text=True)
    sources = [{"file": i["file"], "ts": _fmt_local(e)} for e, i in pool]
    if r.returncode != 0 or not r.stdout.strip():
        return {"answer": "本地模型服务暂不可用，无法生成带出处的回答。", "sources": sources,
                "confidence": "unavailable", "index_as_of": snapshot}
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"answer": "本地模型返回了无法解析的结果，无法生成带出处的回答。", "sources": sources,
                "confidence": "unavailable", "index_as_of": snapshot}
    return {"answer": (d.get("message", {}) or {}).get("content", "").strip(),
            "sources": sources, "confidence": "medium", "index_as_of": snapshot}

INTERACTIVE_LOCK = "/tmp/uyp_interactive.lock"

def _touch_interactive_lock():
    """交互查询在途标志: 索引侧富集看到新鲜旗标即让路(语音>查询>索引铁律,
    2026-10-10 现场事故: 全量索引占满 ollama 5 槽, 'say OK' 都 10s 超时)。
    锁只是让路提示, 绝不是闸门: root 属主的锁文件(satellite yield watcher
    以 root 运行时创建)写入失败时降级为 mtime touch, 绝不让查询本身挂掉。"""
    import time as _t
    try:
        with open(INTERACTIVE_LOCK, "w") as fh:
            fh.write(str(_t.time()))
    except OSError:
        try:
            os.utime(INTERACTIVE_LOCK, None)
        except OSError:
            pass

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


def _retrieval(question: str, items: list[dict]) -> list[tuple[float, dict]]:
    """Lexical top-3 (score>0). Pure code, instant, shared by answer() and
    will_synthesize() so the hint can never disagree with the answer path."""
    tokens = tokenize(question)
    scored = sorted(((score(i, tokens), i) for i in items), key=lambda x: -x[0])
    return [(s, i) for s, i in scored[:3] if s > 0]


def will_synthesize(question: str, items: list[dict]) -> bool:
    """True when answering requires the qwen synthesis pass (retrieval hit).

    The query API calls this BEFORE answering: lexical retrieval is instant,
    but a hit means qwen synthesis (5-15s plus queue wait under load), which
    is exactly the wait the X-UYP-Slow-Hint response header exists to flag.
    A miss is answered instantly, so it is never hinted slow."""
    return bool(_retrieval(question, items))


def _answer_locked(question: str, items: list[dict]) -> dict:
    if is_temporal_question(question):
        return _temporal_answer(question, items)
    top = _retrieval(question, items)
    if not top:
        # Same canonical miss sentence the synthesis prompt demands - a genuine
        # miss is never partially hedged, from either path.
        return {"answer": MISS_SENTENCE,
                "sources": [], "confidence": "none",
                "index_as_of": index_as_of(items)}
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
    body = json.dumps({"model": os.environ.get("UYP_OLLAMA_MODEL", "qwen3.5-route"), "think": False, "stream": False,
                       "options": {"num_ctx": 4096},
                       "messages": [{"role": "user", "content": prompt}]})
    r = subprocess.run(["curl", "-s", "-H", "X-UYP-Worker: search", "127.0.0.1:11434/api/chat", "-d", body, "--max-time", "120"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return {"answer": "本地模型服务暂不可用，无法生成带出处的回答。", "sources": [{"file": i["file"], "match": round(s, 1)} for s, i in top], "confidence": "unavailable", "index_as_of": index_as_of(items)}
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"answer": "本地模型返回了无法解析的结果，无法生成带出处的回答。", "sources": [{"file": i["file"], "match": round(s, 1)} for s, i in top], "confidence": "unavailable", "index_as_of": index_as_of(items)}
    return {"answer": (d.get("message", {}) or {}).get("content", "").strip(),
            "sources": [{"file": i["file"], "match": round(s, 1)} for s, i in top],
            "confidence": "high" if top[0][0] >= 4 else "medium",
            "index_as_of": index_as_of(items)}

if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or sys.stdin.read()
    result = answer(q, load_items())
    print(result["answer"])
    print("\nsources:")
    for src in result["sources"]:
        print(f"  [{src['match']:4.1f}] {src['file']}")
