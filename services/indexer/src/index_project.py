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
import argparse, json, os, re, subprocess, sys, time, urllib.error, urllib.request
import threading

MODELS = os.environ.get("UYP_MODELS_ROOT", "/home/jetson/dev/uyp/models")
BIN = os.environ.get("UYP_LLAMACPP_BIN", "/home/jetson/dev/uyp/llama.cpp-build/build/bin")
# A worker can point one run at an isolated staging root.  Keeping these as
# environment-controlled paths is also what prevents a failed candidate from
# replacing the last published knowledge version.
STATE = os.path.realpath(os.path.expanduser(os.environ.get("UYP_STATE_ROOT", "~/dev/uyp/state")))
OUT = os.path.realpath(os.path.expanduser(os.environ.get("UYP_OUTPUT_ROOT", "~/dev/uyp/output")))

def api(host, token, path, binary=False, timeout=90, retries=5):
    # transport retry (2026-10-10 hotfix, second-project run): the connector is
    # reached through the launchd ssh -R tunnel, which blips on network changes
    # (observed 10:26:45Z tunnel restart -> ConnectionReset -> job killed).
    # Retry with backoff instead of crashing the whole IndexJob.
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(host.rstrip("/") + path,
                                     headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = r.read()
                return d if binary else json.loads(d)
        except urllib.error.HTTPError:
            raise  # policy answers (403/404/413) are final - do not mask them
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(min(2 ** attempt * 5, 60))
    raise last

def laya_decide(head: str, mid: str = "") -> tuple[str, float]:
    # Calibration 2026-10-10 (benchmarks/calibration_results_2026-10-10.json,
    # 10 rows, 40% exact): a 900-char head window often stops inside the
    # import block, so core-logic files read as "deps" -> structure-only.
    # head+mid windows let function/class bodies reach the model.  Criteria
    # reworded so each class has an anchor the old wording lacked
    # (skip never fired; quick-summary never fired).
    state = "repository file content:\n" + head[:600]
    if mid:
        state += "\n...\n" + mid[:600]
    body = json.dumps({"state": state, "questions": {
        "triage": {"type": "choice", "instructions": "What analysis does this file deserve?",
          "criteria": {"skip": "minified/vendored bundles, generated files, binary/non-text assets",
                       "structure-only": "pure manifest of dependencies/settings, no executable logic",
                       "quick-summary": "natural-language prose/docs (any language) worth one line, not code",
                       "deep-analysis": "contains executable logic: functions/classes implementing behavior"}},
        # TODO(noul-gate): noul is saturated - 0.77-1.00 on ALL 10 calibration
        # rows incl. dep lists (0.77) and a PNG (0.85); direction agrees with
        # labels only 4/10.  Do NOT tune this question; redesign the gate
        # after re-calibration (derive from triage prob mass, or reword to a
        # calibratable scale).  Tracked for post-recalibration work.
        "thinking": {"type": "noul",
                     "instructions": "Does analysis need multi-step reasoning?"}}}).encode()
    laya_url = os.environ.get("UYP_LAYA_URL", "http://127.0.0.1:8901")
    r = urllib.request.Request(laya_url.rstrip("/") + "/v1/systemone", data=body,
                               headers={"Content-Type": "application/json"})
    try:
        d = json.loads(urllib.request.urlopen(r, timeout=60).read())["answers"]
        return d["triage"]["choice"], d["thinking"]["noul"]
    except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, TypeError):
        # The production profile keeps Laya resident.  A deliberate operator
        # fallback is useful during a model-service outage: the rule layer
        # still preserves coverage while every Qwen enrichment remains
        # think:false.  It is opt-in so an accidental outage cannot silently
        # change the normal routing contract.
        if os.environ.get("UYP_LAYA_FALLBACK") == "rule":
            return "quick-summary", 0.0
        raise

INTERACTIVE_LOCK = "/tmp/uyp_interactive.lock"

def _yield_to_interactive(max_wait_s: int = 600):
    """语音>查询>索引 + 强制抢占 (owner design 2026-10-10):
    语音进来 -> 杀掉在途 qwen curl -> GPU 立刻 100% 给语音
    -> 30秒无交互 -> 恢复索引, 被截断的文件从零重做。"""
    import time as _t
    import subprocess as _sp
    waited = 0.0
    while waited < max_wait_s:
        try:
            ts = float(open(INTERACTIVE_LOCK).read().strip())
        except (OSError, ValueError):
            return
        if _t.time() - ts > 30:
            return
        _sp.run(["pkill", "-f", "curl.*127.0.0.1:11434/api/chat"],
                capture_output=True)
        time.sleep(0.5)
        waited += 0.5


def qwen_enrich(content: str, think: bool):
    _yield_to_interactive()
    instr = ("You are a project file analyzer. Output ONLY a JSON object with keys: "
             "purpose (one sentence), key_points (max 3 strings), components (max 3), "
             "depends_on (max 3). Answer in the SAME LANGUAGE as the file. No other text.")
    body = json.dumps({"model": "qwen3.5-route", "think": think, "stream": False,
                       "options": {"num_ctx": 4096},
                       "messages": [{"role": "user", "content": instr + "\n\nFILE CONTENT:\n" + content[:2600]}]})
    # transport retry (2026-10-10 hotfix, second-project run): ollama shares
    # qwen3.5-route with the live voice router and sporadically 500s/restarts
    # mid-request (observed 06:06 EDT restart -> empty curl stdout -> job
    # worker_command_failed). Warm with a think:false ping and retry instead
    # of crashing the IndexJob; after 3 strikes emit empty (json_bad) so the
    # job keeps going.
    d = None
    for _attempt in range(3):
        r = subprocess.run(["curl", "-s", "127.0.0.1:11434/api/chat", "-d", body, "--max-time", "400"],
                           capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
            break
        except (json.JSONDecodeError, ValueError):
            d = None
            subprocess.run(["curl", "-s", "127.0.0.1:11434/api/chat", "-d",
                            json.dumps({"model": "qwen3.5-route", "think": False, "stream": False,
                                        "messages": [{"role": "user", "content": "ping"}]}),
                            "--max-time", "30"], capture_output=True, text=True)
            time.sleep(10)
    if d is None:
        return "", 0
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

# Images / archives / binaries / fonts: never worth an LLM call.
SKIP_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tif", ".tiff", ".heic", ".pdf",
    ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".tar", ".dmg", ".pkg", ".whl",
    ".onnx", ".gguf", ".bin", ".dylib", ".so", ".a", ".o", ".exe", ".dll",
    ".woff", ".woff2", ".ttf", ".otf",
}

def minified(head: str) -> bool:
    """Minification heuristic: avg line length >300 chars over the first 40
    lines -> machine-generated/minified bundle (calibration 2026-10-10:
    Laya triaged force-graph.min.js as deep-analysis; dense code looks like
    core logic to the model).  Also catches extension-less binaries, whose
    decoded head has no newlines."""
    if not head:
        return False
    lines = head.split("\n")[:40]
    return sum(len(ln) for ln in lines) / max(len(lines), 1) > 300

def rule_pretriage(rel: str, size: int, head: str = "") -> str | None:
    """Zero-cost layer: extension/size/minification rules decided before any
    model call."""
    ext = os.path.splitext(rel)[1].lower()
    if size == 0:
        return "skip"
    if rel.lower().endswith(".min.js") or ext in SKIP_EXT:
        return "skip"  # vendored/binary: deterministic skip, no Laya call
    if minified(head):
        return "skip"
    if ext in {".md", ".markdown"}:
        return None  # let Laya judge docs (known over-triage, calibrated later)
    if ext in {".py", ".ts", ".tsx", ".js", ".swift", ".rs", ".go", ".cpp", ".c", ".h", ".m"}:
        return None  # code -> Laya
    if ext in {".toml", ".yaml", ".yml", ".json", ".cfg", ".ini", ".lock", ".txt", ".sh"}:
        return "structure-only"
    return "structure-only"

def structure_only_summary(content: str) -> dict:
    lines = content.split("\n")
    return {"kind": "structure-only",
            "lines": len(lines),
            "py_defs": len(re.findall(r"^\s*(def|class) ", content, re.M)) if content else 0,
            "imports": len(re.findall(r"^(import|from) ", content, re.M)) if content else 0}

def load_changed_paths(only_changed, changes_file):
    """Merge --only-changed and --changes-file into one relpath set (or None).

    ``changes_file`` holds the JSON array the IndexJob worker writes into its
    staging root (run_job passes --changes-file); --only-changed is the
    hand-friendly spelling for manual incremental runs. Both are additive.
    """
    paths = [str(p) for p in (only_changed or [])]
    if changes_file:
        with open(changes_file, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, list):
            raise ValueError(f"changes file must hold a JSON array: {changes_file}")
        paths.extend(str(p) for p in raw)
    if not paths:
        return None
    return set(paths)

def select_files(all_files, *, limit, done_before, only=None, force=False):
    """Pick this run's files. Returns (selected, skipped, missing).

    ``only`` restricts the candidate pool to those relpaths (incremental
    mode); relpaths inside ``only`` but absent from the manifest (deleted
    upstream, or excluded by the connector) simply never match and are
    reported as ``missing`` - never invented. done_before still applies
    unless --force, so a resumed incremental run skips files it already
    re-processed at the same version.
    """
    if only is None:
        pool, missing = all_files, 0
    else:
        pool = [f for f in all_files if f["relpath"] in only]
        missing = len(only) - len(pool)
    if force:
        return (pool if limit <= 0 else pool[:limit]), 0, missing
    pending = [f for f in pool if not done_before(f)]
    selected = pending if limit <= 0 else pending[:limit]
    return selected, len(pool) - len(pending), missing

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:7121")
    ap.add_argument("--token-file", default=os.path.expanduser("~/.config/uyp/token"))
    ap.add_argument("--grant", required=True)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--force", action="store_true", help="re-analyze even if same-version output exists")
    ap.add_argument("--only-changed", nargs="+", metavar="RELPATH",
                    help="incremental: only (re-)analyze these relpaths")
    ap.add_argument("--changes-file", metavar="PATH",
                    help="incremental: JSON array of relpaths to (re-)analyze; merged with --only-changed")
    a = ap.parse_args()
    token = open(a.token_file).read().strip()

    man = api(a.host, token, f"/manifest?grant={a.grant}")
    root = str(man["root_name"])
    # Connector root names are metadata, never filesystem paths.  Rejecting
    # separators here keeps a malformed manifest from escaping the configured
    # output/state roots.
    if not root or root in {".", ".."} or "/" in root or "\\" in root or "\x00" in root:
        raise ValueError(f"unsafe connector root name: {root!r}")
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
    # ``--limit 0`` is the worker's explicit full-project mode.  The
    # interactive CLI keeps its historical default of 20, but a durable
    # IndexJob must be able to request all pending files.
    only = load_changed_paths(a.only_changed, a.changes_file)
    files, skipped, missing = select_files(all_files, limit=a.limit, only=only,
                                           force=a.force, done_before=done_before)
    if only is not None:
        print(f"incremental: {len(only)} changed path(s), {missing} not in manifest (deleted/excluded)", flush=True)
    if skipped:
        print(f"resume: skipping {skipped} already-processed files", flush=True)
    print(f"indexing {root}: {len(files)} files (of {man['total']})", flush=True)
    READ_CAP = 16 * 1024 * 1024  # connector /read per-file cap

    def safe_read(rel, size, maxb):
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

    stats_lock = threading.Lock()

    def bump(key, n=1):
        with stats_lock:
            stats[key] = stats.get(key, 0) + n

    def process_file(f):
        rel, size = f["relpath"], f["size"]

        try:
            # 2048B read for a 600-char window: slack for multibyte (CJK ~3B/char)
            head = api(a.host, token,
                       f"/read?grant={a.grant}&relpath={rel}&length=2048", binary=True).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            head = ""  # unreadable head (e.g. range cap) -> triage on metadata alone
            if e.code != 413:
                raise
        rule_verdict = rule_pretriage(rel, size, head)
        verdict, gate = rule_verdict, 0.0
        if rule_verdict is None:
            # Mid-file sample via connector offset read: calibration showed
            # head-only windows stop inside the import block.  413 (range
            # cap) -> empty mid, triage proceeds on head alone.
            try:
                mid = api(a.host, token,
                          f"/read?grant={a.grant}&relpath={rel}&offset={size // 2}&length=2048",
                          binary=True).decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code != 413:
                    raise
                mid = ""
            verdict, gate = laya_decide(head, mid)
        # 首扫铺底策略 (ADR-0001 分层): 全量 think:false 铺覆盖, gate 值照记;
        # deep 留给维护窗口的第二遍 (按 gate 挑 top 文件), 不在首扫烧 thinking。
        think = False
        item = {"file": rel, "version": {"mtime": f["mtime"], "size": size},
                "verdict": verdict, "think_gate": round(gate, 2),
                "source": "mac-connector", "analyzed_at": time.strftime("%FT%T")}
        if verdict == "skip":
            bump("rule_skip" if rule_verdict is not None else "laya_skip")
        elif verdict == "structure-only":
            full = safe_read(rel, size, min(size, 262144))
            item["derived"] = structure_only_summary(full or "")
            if full is None:
                item["derived"]["too_large"] = True
            bump("rule_structure" if rule_verdict is not None else "laya_structure")
        else:
            full = safe_read(rel, size, min(size, 262144))
            if full is None:
                item["derived"] = {"too_large": True, "size": size}
                item["verdict"] = "structure-only"
                bump("rule_structure")
                safe = rel.replace("/", "__") + ".knowledge.json"
                with open(f"{OUT}/{root}/{safe}", "w", encoding="utf-8") as fh:
                    json.dump(item, fh, ensure_ascii=False, indent=1)
                print(f"  too-large->{verdict:15s} {rel[:70]}", flush=True)
                return
            t0 = time.time()
            raw, tok = qwen_enrich(full, think)
            bump("tokens", tok)
            parsed = brace_json(raw)
            item["derived"] = parsed or {"raw_head": raw[:400]}
            item["think_used"] = think
            item["eval_tokens"] = tok
            item["enrich_s"] = round(time.time() - t0, 1)
            bump("deep" if think else "quick")
            bump("json_ok" if parsed else "json_bad")
        # 抢占检查: 锁新鲜时不写输出 — 文件保持未分析, 恢复时重做
        try:
            _lk = float(open(INTERACTIVE_LOCK).read().strip())
            _fresh = (time.time() - _lk) <= 30
        except (OSError, ValueError):
            _fresh = False
        if _fresh and verdict not in ("skip", "structure-only"):
            print(f"  PREEMPTED         {rel[:70]} (redo on resume)", flush=True)
            return verdict
        safe = rel.replace("/", "__") + ".knowledge.json"
        with open(f"{OUT}/{root}/{safe}", "w", encoding="utf-8") as fh:
            json.dump(item, fh, ensure_ascii=False, indent=1)
        print(f"  {verdict:15s} {'think' if think else '     '} {rel[:70]}", flush=True)

    workers = max(1, min(int(os.environ.get("UYP_ENRICH_WORKERS", "4")), 4))
    print(f"parallel enrichment: {workers} workers", flush=True)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(process_file, files))

    json.dump({"grant": a.grant, "root": root, "ran_at": time.strftime("%FT%T"), "stats": stats},
              open(f"{STATE}/{root}.json", "w"))
    print(f"\nDONE in {time.time()-t_start:.0f}s | {json.dumps(stats)}")

if __name__ == "__main__":
    main()
