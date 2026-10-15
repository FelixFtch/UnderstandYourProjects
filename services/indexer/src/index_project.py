#!/usr/bin/env python3
"""First-real-index runner (UYP indexer v0).

Chain: Connector manifest -> rule layer -> key-file classifier (importance
tiers A/B/C, key_file_classifier.py) -> Laya triage (/v1/systemone) ->
qwen3.5 enrichment (think per gate, brace-extraction fallback) -> derived
KnowledgeItems to ~/dev/uyp/output/, state to ~/dev/uyp/state/.
Red lines: reads source bytes ONLY via the connector; never writes anything
into the source project; state/output live outside it by construction.

Usage: index_project.py --host http://127.0.0.1:7121 --grant g_xxx [--limit 20]
Requires: Laya llama-server on :8901 (start_laya.sh), ollama qwen3.5:4b.
"""
from __future__ import annotations
import argparse, http.client, json, os, posixpath, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
import threading

import key_file_classifier as kfc
import ua_llm_client as ua_llm  # UA 云端/本地分析模式 (2026-10-15): 只切换 qwen 富集段

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
        # Percent-encode non-ASCII in the request line (2026-10-11 crash:
        # a CJK-named source file put raw UTF-8 into the URL and
        # http.client raised UnicodeEncodeError, killing the whole worker).
        # Structural chars stay literal; the connector's query parser
        # percent-decodes values back to the original path.
        safe_path = urllib.parse.quote(path, safe="/?=&")
        req = urllib.request.Request(host.rstrip("/") + safe_path,
                                     headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = r.read()
                return d if binary else json.loads(d)
        except urllib.error.HTTPError:
            raise  # policy answers (403/404/413) are final - do not mask them
        except (OSError, urllib.error.URLError, json.JSONDecodeError,
                http.client.IncompleteRead, http.client.HTTPException) as exc:
            # IncompleteRead (2026-10-11 field): a large /read cut mid-body by
            # the launchd tunnel blip killed the worker - the jetson hotfix
            # had this and a repo redeploy regressed it. HTTPException broadly
            # covers truncation/reset shapes; retries are idempotent reads.
            last = exc
            if attempt < retries - 1:  # no backoff after the FINAL attempt: the
                time.sleep(min(2 ** attempt * 5, 60))  # failure must record promptly
    raise last

def fetch_full_manifest(host, token, grant, *, api_fn=None) -> dict:
    """Follow the connector's page cursor (PAGE_CAP 2000) to the end.

    The first page alone silently dropped every file sorting after entry
    2000 - e.g. a project with a large vendored folder lost its own top-level
    packages that sort later alphabetically (2026-10-11, commontasks).
    """
    api_fn = api_fn or api
    # No quoting here: api() percent-encodes the request line itself, and
    # pre-quoting the base64 cursor ("=" -> %3D) double-encoded it, so the
    # connector fell back to page 1 forever (caught by the guard below).
    q = grant
    man = api_fn(host, token, f"/manifest?grant={q}")
    files = list(man.get("files", []))
    seen_cursors = set()
    while man.get("has_more") and man.get("next_cursor"):
        cur = man["next_cursor"]
        if cur in seen_cursors:
            raise RuntimeError("connector manifest cursor did not advance")
        seen_cursors.add(cur)
        man = api_fn(host, token, f"/manifest?grant={q}&cursor={cur}")
        files.extend(man.get("files", []))
    out = dict(man)
    out["files"], out["has_more"], out["next_cursor"] = files, False, None
    return out


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

# Optional orientation text (Studio v2 hierarchy: a sub-folder analysis gets
# its parent project's overview).  Empty by default -> prompt unchanged.
EXTRA_CONTEXT = ""

def _yield_to_interactive(max_wait_s: int = 600):
    """语音>查询>索引 + 强制抢占 (owner design 2026-10-10):
    语音进来 -> 杀掉在途 qwen curl -> GPU 立刻 100% 给语音
    -> 30秒无交互 -> 恢复索引, 被截断的文件从零重做。
    pkill 模式必须锚定到 index 标记后紧跟的 ollama URL (2026-10-10 二次
    友军伤害: "X-UYP-Worker.*index" 的 .* 能跨过整个命令行, 检索 curl 的
    提示词里有 "indexed" 一词, 于是每次抢占把检索综合也杀了 - 语音问知识
    必得 "本地模型服务暂不可用"。锚定后只匹配真正的 index worker curl。)"""
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
        _sp.run(["pkill", "-f",
                 "X-UYP-Worker: index 127[.]0[.]0[.]1:11434/api/chat"],
                capture_output=True)
        time.sleep(0.5)
        waited += 0.5


def _enrich_instruction() -> str:
    """The enrichment prompt preamble, shared verbatim by the local ollama
    path (qwen_enrich) and the UA cloud path (cloud_enrich) so both modes ask
    the identical question (2026-10-15)."""
    instr = ("You are a project file analyzer. Output ONLY a JSON object with keys: "
             "purpose (one sentence), key_points (max 3 strings), components (max 3), "
             "depends_on (max 3). Answer in the SAME LANGUAGE as the file. No other text.")
    if EXTRA_CONTEXT:
        instr += ("\nPROJECT CONTEXT (orientation only; describe THIS file): " + EXTRA_CONTEXT)
    return instr

def cloud_enrich(client: "ua_llm.CloudClient", content: str):
    """UA 云端分析模式 (2026-10-15): same prompt and content window as
    qwen_enrich, routed to the user-chosen provider.  `think` is a local
    ollama concept — cloud calls are plain completions.  No
    _yield_to_interactive here: voice preemption exists to free the local
    GPU, and a cloud call holds none of it.  Raises ua_llm.CloudError on
    failure; the caller degrades the file to structure-only (never crashes)."""
    return client.chat([{"role": "user", "content": _enrich_instruction()
                         + "\n\nFILE CONTENT:\n" + content[:2600]}])

def qwen_enrich(content: str, think: bool):
    _yield_to_interactive()
    instr = _enrich_instruction()
    model = os.environ.get("UYP_OLLAMA_MODEL", "qwen3.5-route")
    body = json.dumps({"model": model, "think": think, "stream": False,
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
        r = subprocess.run(["curl", "-s", "-H", "X-UYP-Worker: index", "127.0.0.1:11434/api/chat", "-d", body, "--max-time", "400"],
                           capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
            break
        except (json.JSONDecodeError, ValueError):
            d = None
            subprocess.run(["curl", "-s", "-H", "X-UYP-Worker: index", "127.0.0.1:11434/api/chat", "-d",
                            json.dumps({"model": model, "think": False, "stream": False,
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
        r2 = subprocess.run(["curl", "-s", "-H", "X-UYP-Worker: index", "127.0.0.1:11434/api/chat", "-d", body2, "--max-time", "120"],
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

def _safe_relative_path(value: str) -> str:
    """Mirror of ua_bridge.safe_relative_path (copied rather than imported so
    the indexer CLI stays loadable while the bridge is refactored).  Connector
    relpaths are metadata, never filesystem paths - normalizing and rejecting
    escapes keeps a malformed manifest entry from writing outside the
    directory a caller anchored it to."""
    candidate = posixpath.normpath(value.replace("\\", "/"))
    if candidate in {"", ".", ".."} or candidate.startswith("../") or candidate.startswith("/"):
        raise ValueError(f"unsafe connector path: {value!r}")
    return candidate

def _ua_cache_write(state_root, root, relpath, data, size, mtime) -> None:
    """Best-effort mirror of one full-content connector read into the shared
    UA byte cache (ua_bridge.py reuses these bytes to skip re-transferring
    files the indexer already fetched):

      <state_root>/<root>/ua-cache/files/<relpath>       complete file bytes
      <state_root>/<root>/ua-cache/meta/<relpath>.json   {"size", "mtime"}

    meta is the reader's validity record, so an entry may only ever hold the
    COMPLETE file: partial payloads (e.g. the 256 KiB-capped fetch of a
    larger file) write nothing and the bridge re-fetches as before.  A no-op
    when state_root is unset (standalone CLI run) and silent on any disk or
    path failure - the cache must never be able to fail an analysis run."""
    if not state_root or mtime is None or size <= 0 or len(data) != size:
        return
    tmp = None
    try:
        rel = _safe_relative_path(relpath)
        base = os.path.join(os.path.expanduser(state_root), root, "ua-cache")
        # Bytes first, meta last: an interrupted write then leaves at most an
        # unreferenced files/ blob, never a meta vouching for truncated bytes.
        # tmp+rename keeps a concurrent reader from seeing a half-written body.
        for target, payload in (
            (os.path.join(base, "files", rel), data),
            (os.path.join(base, "meta", rel + ".json"),
             json.dumps({"size": int(size), "mtime": float(mtime)}).encode()),
        ):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            tmp = f"{target}.tmp.{os.getpid()}.{threading.get_ident()}"
            with open(tmp, "wb") as fh:
                fh.write(payload)
            os.replace(tmp, target)
            tmp = None
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return

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
    ap.add_argument("--context-file", metavar="PATH",
                    help="optional orientation text (e.g. the parent project's overview) added to enrichment prompts")
    a = ap.parse_args()
    if a.context_file:
        global EXTRA_CONTEXT
        with open(a.context_file, encoding="utf-8") as fh:
            EXTRA_CONTEXT = " ".join(fh.read().split())[:1200]
    token = open(a.token_file).read().strip()

    # UA 云端/本地分析模式 (owner decision 2026-10-15): ONLY this qwen
    # enrichment stage is switchable.  The Laya front-stage — hard gates in
    # key_file_classifier plus laya_decide triage on :8901 — is ALWAYS local,
    # owner-pinned (业主钦定); never route it through a cloud client.
    ua_client = None
    try:
        ua_client = ua_llm.load_client()
    except ua_llm.CloudConfigError as exc:
        # Honest fallback: a broken cloud config must not kill a job that can
        # still enrich locally.  Loud warning; the local path is untouched.
        print(f"WARNING: UA cloud config error, using LOCAL enrichment: {exc}", flush=True)
    ua_breaker = ua_llm.CloudBreaker()
    if ua_client is not None:
        print(f"UA analysis mode: CLOUD ({ua_client.provider}/{ua_client.model}); "
              "local ollama enrichment bypassed, Laya triage stays local", flush=True)

    man = fetch_full_manifest(a.host, token, a.grant)
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

    # Key-file classifier (stage before Laya).  Heads are fetched once here
    # (the same 2 KB read process_file used to make) so the classifier can
    # build an import graph across the whole run before any model call.
    heads: dict[str, str] = {}
    keyfile: dict[str, dict] = {}
    enrich_cap = os.environ.get("UYP_KEYFILE_MAX_ENRICH")
    enrich_cap = int(enrich_cap) if enrich_cap else None
    enrich_used = [0]
    if kfc.enabled() and files:
        def fetch_head(f):
            try:
                return f["relpath"], api(a.host, token,
                    f"/read?grant={a.grant}&relpath={f['relpath']}&length=2048",
                    binary=True).decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code != 413:
                    raise
                return f["relpath"], ""
        from concurrent.futures import ThreadPoolExecutor as _TPE
        t_k = time.time()
        with _TPE(max_workers=8) as _pool:
            heads = dict(_pool.map(fetch_head, files))
        keyfile = kfc.classify(files, heads, changed=only or ())
        tiers = {}
        for v in keyfile.values():
            tiers[v["tier"]] = tiers.get(v["tier"], 0) + 1
        files = sorted(files, key=lambda f: -keyfile.get(f["relpath"], {}).get("score", 0.0))
        with open(f"{STATE}/{root}.keyfiles.json", "w", encoding="utf-8") as fh:
            json.dump({"ran_at": time.strftime("%FT%T"), "tiers": tiers,
                       "files": keyfile}, fh, ensure_ascii=False, indent=1)
        print(f"key-file classifier: {json.dumps(tiers)} in {time.time()-t_k:.1f}s "
              f"(A -> Laya+qwen, B -> Laya then qwen only if deep, C/gate -> structure-only)",
              flush=True)

    # UA byte cache (see _ua_cache_write): active only when a worker pointed
    # UYP_STATE_ROOT at its staging root, so the standalone CLI keeps its old
    # behavior and never sprays cache dirs nobody reads.
    ua_state_root = os.environ.get("UYP_STATE_ROOT") or None

    def safe_read(rel, size, maxb, mtime=None):
        if size > READ_CAP:
            return None
        try:
            data = api(a.host, token,
                       f"/read?grant={a.grant}&relpath={rel}&length={maxb}",
                       binary=True)
            # Cache the raw bytes BEFORE the lossy replace-decode: the bridge
            # needs byte-identical content, not the indexer's text view.
            _ua_cache_write(ua_state_root, root, rel, data, size, mtime)
            return data.decode("utf-8", "replace")
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

        if rel in heads:
            head = heads[rel]
        else:
            try:
                # 2048B read for a 600-char window: slack for multibyte (CJK ~3B/char)
                head = api(a.host, token,
                           f"/read?grant={a.grant}&relpath={rel}&length=2048", binary=True).decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                head = ""  # unreadable head (e.g. range cap) -> triage on metadata alone
                if e.code != 413:
                    raise
        rule_verdict = rule_pretriage(rel, size, head)
        kf = keyfile.get(rel)
        if rule_verdict is None and kf and kf["tier"] in ("C", "gate"):
            # Not a key file: keep it findable (path + symbol counts + the UA
            # structure graph) but spend no Laya/qwen time on it.
            rule_verdict = "skip" if kf.get("gate") == "minified" else "structure-only"
            bump("keyfile_" + kf["tier"])
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
        if kf:
            item["keyfile"] = {"tier": kf["tier"], "score": kf["score"],
                               "rank": kf.get("rank"), "gate": kf.get("gate"),
                               "embedded": kf.get("embedded")}
        if kf and verdict in ("quick-summary", "deep-analysis"):
            # Tier B: Laya judged it, but qwen only for deep-analysis.  Any
            # tier: respect the absolute enrichment budget when set.
            with stats_lock:
                over = enrich_cap is not None and enrich_used[0] >= enrich_cap
                demote = (kf["tier"] == "B" and verdict != "deep-analysis") or over
                if not demote:
                    enrich_used[0] += 1
            if demote:
                item["laya_verdict"] = verdict
                verdict = item["verdict"] = "structure-only"
                bump("keyfile_budget_demoted" if over else "keyfile_B_demoted")
        if verdict == "skip":
            bump("rule_skip" if rule_verdict is not None else "laya_skip")
        elif verdict == "structure-only":
            full = safe_read(rel, size, min(size, 262144), f["mtime"])
            item["derived"] = structure_only_summary(full or "")
            if full is None:
                item["derived"]["too_large"] = True
            bump("rule_structure" if rule_verdict is not None else "laya_structure")
        else:
            full = safe_read(rel, size, min(size, 262144), f["mtime"])
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
            if ua_client is not None:
                # 云端模式失败策略 (2026-10-15 contract): 单次调用失败 -> 该文件
                # 诚实降级 structure-only + enrich_warning, 作业不炸; 连续 5 次
                # 失败 -> 熔断, 本作业剩余文件全部 structure-only, run-state 记
                # cloud_enrich_broken (ua_bridge 汇总进作业 uaSummary)。
                if ua_breaker.tripped:
                    verdict = item["verdict"] = "structure-only"
                    item["derived"] = structure_only_summary(full)
                    item["enrich_warning"] = "cloud_enrich_broken"
                    bump("cloud_breaker_structure")
                else:
                    try:
                        raw, tok = cloud_enrich(ua_client, full)
                    except ua_llm.CloudError as exc:
                        tripped = ua_breaker.fail()
                        verdict = item["verdict"] = "structure-only"
                        item["derived"] = structure_only_summary(full)
                        item["enrich_warning"] = "cloud_enrich_failed"
                        bump("cloud_fail")
                        print(f"  WARNING cloud enrich failed ({ua_breaker.failures} consecutive): "
                              f"{exc} -> structure-only: {rel[:60]}", flush=True)
                        if tripped:
                            print(f"  WARNING cloud enrichment broken after {ua_breaker.threshold} "
                                  "consecutive failures; remaining files degrade to structure-only",
                                  flush=True)
                    else:
                        ua_breaker.ok()
                        bump("tokens", tok)
                        parsed = brace_json(raw)
                        item["derived"] = parsed or {"raw_head": raw[:400]}
                        item["think_used"] = think
                        item["eval_tokens"] = tok
                        item["enrich_s"] = round(time.time() - t0, 1)
                        bump("deep" if think else "quick")
                        bump("json_ok" if parsed else "json_bad")
            else:
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

    run_state = {"grant": a.grant, "root": root, "ran_at": time.strftime("%FT%T"),
                 "stats": stats, "ua_mode": "cloud" if ua_client is not None else "local"}
    if ua_client is not None and ua_breaker.tripped:
        # 熔断标记 (2026-10-15): ua_bridge.run 把它汇总进作业 uaSummary 的
        # "cloud_enrich_broken": true, 让操作员看到诚实降级而非沉默的全 structure-only。
        run_state["cloud_enrich_broken"] = True
    json.dump(run_state, open(f"{STATE}/{root}.json", "w"))
    print(f"\nDONE in {time.time()-t_start:.0f}s | {json.dumps(stats)}")

if __name__ == "__main__":
    main()
