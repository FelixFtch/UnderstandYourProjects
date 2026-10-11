#!/usr/bin/env python3
"""Analyze-a-folder jobs for Jarvis Studio v2 (docs/STUDIO_V2.md §6.2).

``POST /api/projects/analyze`` lands here: validate the folder path, find or
create the Mac Connector grant, register the project and its hierarchy
relation, write a per-job script to ``<state>/project-jobs/<job_id>/run.sh``
and launch it detached (``systemd-run --user --unit uyp-analyze-<job_id>``
when available, else a double-forked ``setsid`` shell).

The script is the same chain as the hand-run ``run_commontasks.sh``:
start Laya (only if it was not already running) -> ``index_project.py
--limit 0`` -> stop Laya (only if this job started it) -> ``ua_bridge.py``.
Jobs are serialized with ``flock`` on ``project-jobs/.analyze.lock`` so two
analyses never fight over the GPU.  A generated script is never edited after
launch; a new request writes a new job directory.

Hierarchy reuse (``seed`` subcommand, run first inside the job):

* analyzing an ANCESTOR of analyzed projects copies each child's knowledge
  items into the ancestor's output with the child's relative prefix, so the
  indexer's same-version resume check skips them (children are linked and
  not re-enriched; their outputs are reused);
* analyzing a DESCENDANT of an analyzed project copies the parent's enriched
  items under that subtree (prefix stripped) and passes the parent's
  overview to ``index_project.py --context-file`` as orientation for the
  files that still need enrichment.

Usage (inside a job script): project_jobs.py seed|finalize --job-dir DIR
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid

import projects as P

JOB_ID = re.compile(r"^job_[0-9a-f]{12}$")
_FILE_LINE = re.compile(r"^  (?:too-large->)?(skip|structure-only|quick-summary|deep-analysis|PREEMPTED)\s")
_INDEXING = re.compile(r"^indexing .+: (\d+) files \(of (\d+)\)")
_LAUNCH_GRACE_S = 120.0
PASSTHROUGH_ENV = (
    "UYP_OLLAMA_MODEL", "UYP_LAYA_URL", "UYP_ENRICH_WORKERS", "UYP_LAYA_FALLBACK",
    "UYP_KEYFILE", "UYP_KEYFILE_TIER_A", "UYP_KEYFILE_TIER_B", "UYP_KEYFILE_MAX_ENRICH",
    "UYP_KEYFILE_MIN_A", "UYP_KEYFILE_EMBEDDED", "UYP_MODELS_ROOT", "UYP_LLAMACPP_BIN",
    "PATH", "HOME", "LANG",
)
SRC_DIR = os.path.dirname(os.path.abspath(__file__))


class AnalyzeError(Exception):
    def __init__(self, code: str, status: int, message: str):
        super().__init__(message)
        self.code, self.status, self.message = code, status, message


def jobs_root() -> str:
    return os.path.join(P.state_root(), "project-jobs")


def job_dir(job_id: str) -> str | None:
    return os.path.join(jobs_root(), job_id) if JOB_ID.match(str(job_id or "")) else None


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _write_job(directory: str, job: dict) -> None:
    P._atomic_write_json(os.path.join(directory, "job.json"), job)


def _tail_lines(path: str, max_bytes: int = 256 * 1024) -> list[str]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()
            return fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


# ------------------------------------------------------------ job state --
def job_state(job_id: str) -> dict | None:
    """Status/phase/progress for one job, parsed from its log and markers."""
    directory = job_dir(job_id)
    if directory is None:
        return None
    job = _read_json(os.path.join(directory, "job.json"))
    if not isinstance(job, dict):
        return None
    lines = _tail_lines(os.path.join(directory, "job.log"))
    exit_code = None
    with contextlib.suppress(OSError, ValueError):
        with open(os.path.join(directory, "exit_code"), encoding="utf-8") as fh:
            exit_code = int(fh.read().strip())
    pid = None
    with contextlib.suppress(OSError, ValueError):
        with open(os.path.join(directory, "pid"), encoding="utf-8") as fh:
            pid = int(fh.read().strip())
    phases = [line.split()[1] for line in lines if line.startswith("PHASE ") and len(line.split()) > 1]
    started = "start" in phases
    total = done = 0
    index_done = False
    keyfile_seen = False
    for line in lines:
        match = _INDEXING.match(line)
        if match:
            total = int(match.group(1))
        elif _FILE_LINE.match(line):
            done += 1
        elif line.startswith("key-file classifier:"):
            keyfile_seen = True
        elif line.startswith("DONE in"):
            index_done = True
    finished_at = None
    if exit_code is not None:
        status = "done" if exit_code == 0 else "failed"
        with contextlib.suppress(OSError):
            finished_at = P.iso_from_epoch(os.path.getmtime(os.path.join(directory, "exit_code")))
    elif pid is not None and _pid_alive(pid):
        status = "running" if started else "queued"
    elif pid is not None:
        status = "failed"  # the script died without writing an exit code
    elif time.time() - (P.parse_time(job.get("created_at")) or time.time()) > _LAUNCH_GRACE_S:
        status = "failed"  # never started
    else:
        status = "queued"
    if status == "done":
        phase = "done"
    elif status == "failed":
        phase = "interrupted" if exit_code is None and pid is not None else (
            "launch_failed" if exit_code is None else (phases[-1] if phases else "failed"))
    elif not started:
        phase = "waiting" if pid is not None else "queued"
    else:
        last = phases[-1]
        if last == "index":
            phase = "enrich" if (keyfile_seen or done) and not index_done else ("index_done" if index_done else "classify")
        else:
            phase = last
    if status == "done" and total:
        done = total
    done = min(done, total) if total else done
    return {
        "job_id": job["job_id"], "project_id": job["project_id"], "status": status, "phase": phase,
        "progress": {"done": done, "total": total},
        "log_tail": [line[:300] for line in lines[-15:]],
        "created_at": job.get("created_at"), "finished_at": finished_at,
    }


def public_job(state: dict) -> dict:
    return {key: state[key] for key in ("job_id", "project_id", "status", "phase", "progress", "log_tail")}


def jobs_by_project() -> dict[str, dict]:
    """Latest job state per project (by creation time)."""
    latest: dict[str, tuple[str, str]] = {}
    for path in glob.glob(os.path.join(jobs_root(), "job_*", "job.json")):
        job = _read_json(path)
        if not isinstance(job, dict) or not JOB_ID.match(str(job.get("job_id", ""))):
            continue
        key = str(job.get("created_at") or "")
        current = latest.get(job.get("project_id"))
        if current is None or key > current[0]:
            latest[str(job.get("project_id"))] = (key, job["job_id"])
    result = {}
    for project_id, (_, job_id) in latest.items():
        state = job_state(job_id)
        if state:
            result[project_id] = state
    return result


# ---------------------------------------------------------------- launch --
def _ua_root() -> str:
    configured = os.environ.get("UYP_UA_ROOT")
    if configured:
        return os.path.realpath(os.path.expanduser(configured))
    default = os.path.expanduser("~/dev/uyp/understand-anything-src-20261009")
    return default if os.path.isdir(default) else ""


def render_script(job: dict) -> str:
    """The per-job bash script.  Every value is shell-quoted."""
    q = shlex.quote
    directory = job["dir"]
    redirect = job["root_name"] != job["output_dir"]
    out_root, state_root = P.output_root(), P.state_root()
    index_out = os.path.join(directory, "out") if redirect else out_root
    index_state = os.path.join(directory, "state") if redirect else state_root
    env = {key: os.environ[key] for key in PASSTHROUGH_ENV if os.environ.get(key)}
    env.setdefault("UYP_ENRICH_WORKERS", "2")
    env.setdefault("UYP_LAYA_URL", "http://127.0.0.1:8901")
    if os.environ.get("UYP_ANALYZE_OLLAMA_MODEL"):
        env["UYP_OLLAMA_MODEL"] = os.environ["UYP_ANALYZE_OLLAMA_MODEL"]
    python = os.environ.get("UYP_ANALYZE_PYTHON") or sys.executable or "python3"
    laya_unit = os.environ.get("UYP_ANALYZE_LAYA_UNIT", "uyp-laya")
    ua_root = _ua_root()
    connector = [ "--host", job["connector_host"], "--token-file", job["connector_token_file"], "--grant", job["grant_id"]]
    index_cmd = [python, "index_project.py", *connector, "--limit", "0"]
    if job.get("context_file"):
        index_cmd += ["--context-file", job["context_file"]]
    ua_cmd = [python, "ua_bridge.py", *connector, "--ua-root", ua_root or "-", "--state-root", state_root,
              "--project-name", job["output_dir"], "--knowledge-root", os.path.join(out_root, job["output_dir"])]
    exports = "\n".join(f"export {key}={q(value)}" for key, value in sorted(env.items()))
    lock = os.path.join(jobs_root(), ".analyze.lock")
    return f"""#!/usr/bin/env bash
# Generated by project_jobs.py for {job['job_id']} ({job['project_id']}).
# Never edit this file while the job runs; a new analyze request writes a new job.
set -u
JOB_DIR={q(directory)}
echo $$ > "$JOB_DIR/pid"
exec >>"$JOB_DIR/job.log" 2>&1
finish() {{ echo "$1" > "$JOB_DIR/exit_code.tmp" && mv "$JOB_DIR/exit_code.tmp" "$JOB_DIR/exit_code"; }}
echo "PHASE waiting $(date -u +%FT%TZ)"
if command -v flock >/dev/null 2>&1; then exec 9>>{q(lock)}; flock 9; fi
echo "PHASE start $(date -u +%FT%TZ)"
{exports}
export UYP_OUTPUT_ROOT={q(index_out)}
export UYP_STATE_ROOT={q(index_state)}
PY={q(python)}
cd {q(SRC_DIR)} || {{ finish 2; exit 2; }}
echo "PHASE seed"
UYP_OUTPUT_ROOT={q(out_root)} UYP_STATE_ROOT={q(state_root)} "$PY" project_jobs.py seed --job-dir "$JOB_DIR" || echo "seed failed (continuing without reuse)"
LAYA_UNIT={q(laya_unit)}
LAYA_STARTED=0
if [ -n "$LAYA_UNIT" ] && command -v systemctl >/dev/null 2>&1; then
  if ! systemctl --user is-active --quiet "$LAYA_UNIT"; then
    if systemctl --user start "$LAYA_UNIT"; then
      LAYA_STARTED=1
      echo "laya started ($LAYA_UNIT)"
      for _ in $(seq 1 60); do curl -sf "$UYP_LAYA_URL/health" >/dev/null 2>&1 && break; sleep 2; done
    else
      echo "laya start failed ($LAYA_UNIT); continuing"
    fi
  fi
fi
echo "PHASE index"
{' '.join(q(part) for part in index_cmd)}
INDEX_EXIT=$?
echo "index_project exit=$INDEX_EXIT"
if [ "$LAYA_STARTED" = 1 ]; then systemctl --user stop "$LAYA_UNIT" || true; echo "laya stopped"; fi
export UYP_OUTPUT_ROOT={q(out_root)}
export UYP_STATE_ROOT={q(state_root)}
UA_EXIT=0
if [ "$INDEX_EXIT" -eq 0 ]; then
  if [ -n {q(ua_root)} ] && [ -d {q(ua_root or '/nonexistent')} ]; then
    echo "PHASE graph"
    {' '.join(q(part) for part in ua_cmd)}
    UA_EXIT=$?
    echo "ua_bridge exit=$UA_EXIT"
  else
    echo "ua_bridge skipped (UYP_UA_ROOT not configured)"
  fi
fi
echo "PHASE finalize"
"$PY" project_jobs.py finalize --job-dir "$JOB_DIR" || echo "finalize failed"
if [ "$INDEX_EXIT" -ne 0 ]; then finish "$INDEX_EXIT"; exit "$INDEX_EXIT"; fi
if [ "$UA_EXIT" -ne 0 ]; then finish "$UA_EXIT"; exit "$UA_EXIT"; fi
echo "PHASE done $(date -u +%FT%TZ)"
finish 0
"""


def default_launcher(job: dict, script: str) -> dict:
    """Start the script detached; prefer a transient systemd user unit."""
    unit = f"uyp-analyze-{job['job_id']}"
    mode = os.environ.get("UYP_ANALYZE_LAUNCHER", "auto")
    if mode in {"auto", "systemd"} and shutil.which("systemd-run"):
        try:
            result = subprocess.run(["systemd-run", "--user", "--unit", unit, "--collect", "--quiet",
                                     "/bin/bash", script], capture_output=True, text=True, timeout=20)
            if result.returncode == 0:
                return {"launcher": "systemd-run", "unit": unit}
        except (OSError, subprocess.SubprocessError):
            pass
    # Double fork: the shell exits at once, the job is re-parented to init,
    # so this server never accumulates zombies and pid checks stay honest.
    proc = subprocess.Popen(["/bin/sh", "-c", 'nohup /bin/bash "$0" >/dev/null 2>&1 &', script],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True, close_fds=True)
    with contextlib.suppress(subprocess.SubprocessError):
        proc.wait(timeout=10)
    return {"launcher": "setsid", "unit": None}


def _connector_error(exc: P.ConnectorError) -> AnalyzeError:
    if exc.code in {"path_not_grantable", "bad_request"}:
        return AnalyzeError("path_not_grantable", 400, "The connector cannot grant that folder (it must be an existing folder under the Mac home).")
    if exc.code == "denied_pattern":
        return AnalyzeError("path_denied", 403, "The connector's deny-list forbids that folder.")
    if exc.code == "unauthorized":
        return AnalyzeError("connector_unauthorized", 502, "The connector rejected this Agent Box's token.")
    if exc.code == "connector_unconfigured":
        return AnalyzeError("connector_unconfigured", 503, "UYP_CONNECTOR_HOST is not configured on this Agent Box.")
    return AnalyzeError("connector_unavailable", 503, "The Mac connector is not reachable right now.")


def _parent_context(parent: dict, record: dict) -> str:
    try:
        from project_digest import overview_text
        overview = overview_text(parent)
    except Exception:  # noqa: BLE001 - context is a best-effort hint
        overview = ""
    rel = P.relative_inside(parent["path"], record["path"])
    text = (f"This folder ({rel}) is part of the larger project '{parent.get('root_name')}'. "
            f"Parent project overview: {overview or 'not summarized yet'}")
    return text[:1200]


def create_analyze_job(path, device_id=None, *, connector: P.ConnectorClient | None = None,
                       launcher=None, registry: P.ProjectRegistry | None = None, actor: str | None = None) -> dict:
    """Register + launch an analysis; returns the 202 body of §6.2."""
    try:
        normalized = P.normalize_folder_path(path)
    except P.PathError as exc:
        raise AnalyzeError("invalid_path", 400, str(exc)) from exc
    device = P.connector_device_id()
    if device_id not in (None, ""):
        requested = P.safe_device_id(device_id)
        if requested is None:
            raise AnalyzeError("invalid_device_id", 400, "device_id must be an opaque identifier.")
        if requested != device:
            # Folders are reached only through the paired Mac connector.
            raise AnalyzeError("unsupported_device", 400, f"Only folders on the connector device ({device}) can be analyzed.")
    connector = connector or P.ConnectorClient()
    if not connector.configured:
        raise AnalyzeError("connector_unconfigured", 503, "UYP_CONNECTOR_HOST is not configured on this Agent Box.")
    try:
        grant = P.match_grant(connector.grants(), normalized) or connector.create_grant(normalized)
    except P.ConnectorError as exc:
        raise _connector_error(exc) from exc
    P.reset_caches()
    real_path = P.normalize_folder_path(str(grant["path"]))
    root_name = os.path.basename(real_path)
    if not P.safe_component(root_name):
        raise AnalyzeError("invalid_path", 400, "The folder name cannot be used as an index root.")
    registry = registry or P.ProjectRegistry()
    existing = jobs_by_project()
    job_id = "job_" + uuid.uuid4().hex[:12]
    with registry.edit() as doc:
        record = P.find_by_path(doc, real_path, device)
        if record is None:
            # An imported project whose path was never learned (connector was
            # offline at import) is the same folder: adopt it, don't duplicate.
            record = next((r for r in doc["projects"] if not r.get("path") and (
                r.get("grant_id") == str(grant["id"]) or r.get("root_name") == root_name)), None)
            if record is not None:
                record["path"] = real_path
        if record is None:
            project_id = P.allocate_project_id(doc, root_name, device, real_path)
            record = P.new_record(project_id, root_name=root_name, path=real_path, device_id=device,
                                  output_dir=project_id, grant_id=str(grant["id"]), origin="analyze")
            doc["projects"].append(record)
        else:
            record["grant_id"] = str(grant["id"])
            record["updated_at"] = P.now_iso()
        active = existing.get(record["project_id"])
        if active and active["status"] in {"queued", "running"}:
            P.relink(doc)
            return {"job_id": active["job_id"], "project_id": record["project_id"],
                    "relation": {"parent_id": record["parent_id"], "children": list(record["children"])},
                    "status": "queued", "_existing": True}
        P.relink(doc)
        by_id = {r["project_id"]: r for r in doc["projects"]}
        parent = by_id.get(record["parent_id"])
        children = [by_id[c] for c in record["children"] if c in by_id]
        seeds = []
        for child in children:
            if P.has_outputs(child):
                seeds.append({"mode": "ancestor", "from": child.get("output_dir") or child["project_id"],
                              "project_id": child["project_id"],
                              "prefix": P.relative_inside(real_path, child["path"])})
        if parent is not None and P.has_outputs(parent):
            seeds.append({"mode": "descendant", "from": parent.get("output_dir") or parent["project_id"],
                          "project_id": parent["project_id"],
                          "strip": P.relative_inside(parent["path"], real_path)})
        record["linked_children"] = [s["project_id"] for s in seeds if s["mode"] == "ancestor"]
        context_text = _parent_context(parent, record) if parent is not None else ""
        record["context"] = {"parent_id": parent["project_id"], "text": context_text} if parent is not None else None
        record["last_job_id"] = job_id
        relation = {"parent_id": record["parent_id"], "children": list(record["children"])}
        project = dict(record)
    directory = os.path.join(jobs_root(), job_id)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    context_file = None
    if context_text:
        context_file = os.path.join(directory, "context.txt")
        with open(context_file, "w", encoding="utf-8") as fh:
            fh.write(context_text)
    output_dir = project.get("output_dir") or project["project_id"]
    job = {
        "job_id": job_id, "project_id": project["project_id"], "root_name": root_name,
        "output_dir": output_dir, "path": real_path, "device_id": device,
        "grant_id": str(grant["id"]), "connector_host": connector.host,
        "connector_token_file": connector.token_file, "relation": relation, "seeds": seeds,
        "context_file": context_file, "created_at": P.now_iso(), "actor": actor, "dir": directory,
    }
    if root_name != output_dir:
        # The indexer names its output dir after the connector root; point
        # that name at this project's own directory so ids stay unique.
        os.makedirs(os.path.join(P.output_root(), output_dir), exist_ok=True)
        os.makedirs(os.path.join(directory, "out"), exist_ok=True)
        os.makedirs(os.path.join(directory, "state"), exist_ok=True)
        link = os.path.join(directory, "out", root_name)
        if not os.path.lexists(link):
            os.symlink(os.path.join(P.output_root(), output_dir), link)
    script = os.path.join(directory, "run.sh")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(render_script(job))
    os.chmod(script, 0o700)
    _write_job(directory, job)
    try:
        launched = (launcher or default_launcher)(job, script) or {}
    except Exception as exc:  # noqa: BLE001 - surface as a failed launch, keep the job record
        launched = {"launcher": "error", "error": type(exc).__name__}
    job.update({"launcher": launched.get("launcher"), "unit": launched.get("unit")})
    _write_job(directory, job)
    if launched.get("launcher") == "error":
        raise AnalyzeError("launch_failed", 500, "The analysis job could not be started.")
    return {"job_id": job_id, "project_id": project["project_id"], "relation": relation, "status": "queued"}


# -------------------------------------------------------- in-job commands --
def seed(job: dict) -> dict:
    """Reuse already-analyzed items across the hierarchy (see module doc)."""
    target = os.path.join(P.output_root(), job["output_dir"])
    os.makedirs(target, exist_ok=True)
    report = {"reused": 0, "sources": []}
    for plan in job.get("seeds") or []:
        source_dir = P.safe_component(plan.get("from"))
        if source_dir is None:
            continue
        copied = 0
        for path in glob.glob(os.path.join(glob.escape(os.path.join(P.output_root(), source_dir)), "*.knowledge.json")):
            try:
                with open(path, encoding="utf-8") as fh:
                    item = json.load(fh)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            rel = str(item.get("file") or "")
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                continue
            derived = item.get("derived") if isinstance(item.get("derived"), dict) else {}
            if plan.get("mode") == "ancestor":
                new_rel = f"{plan['prefix']}/{rel}"
            else:
                strip = str(plan.get("strip") or "")
                if not rel.startswith(strip + "/") or not derived.get("purpose"):
                    continue  # only enriched files; the rest get this folder's own context
                new_rel = rel[len(strip) + 1:]
            out_path = os.path.join(target, new_rel.replace("/", "__") + ".knowledge.json")
            current = None
            if os.path.exists(out_path):
                try:
                    with open(out_path, encoding="utf-8") as fh:
                        current = json.load(fh)
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    current = None
            if isinstance(current, dict):
                current_derived = current.get("derived") if isinstance(current.get("derived"), dict) else {}
                if current_derived.get("purpose") or not derived.get("purpose"):
                    continue
            reused = dict(item)
            reused["file"] = new_rel
            reused["reused_from"] = plan.get("project_id")
            P._atomic_write_json(out_path, reused)
            copied += 1
        report["reused"] += copied
        report["sources"].append({"project_id": plan.get("project_id"), "mode": plan.get("mode"), "items": copied})
        print(f"seed: reused {copied} item(s) from {plan.get('project_id')} ({plan.get('mode')})", flush=True)
    return report


def finalize(job: dict) -> None:
    """Publish redirected state files and refresh the registry cache."""
    if job["root_name"] != job["output_dir"]:
        for suffix in (".json", ".keyfiles.json"):
            source = os.path.join(job["dir"], "state", job["root_name"] + suffix)
            if os.path.isfile(source):
                shutil.copyfile(source, os.path.join(P.state_root(), job["output_dir"] + suffix))
    P.sync_registry(use_connector=False)
    print(f"finalize: registry refreshed for {job['project_id']}", flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("seed", "finalize", "status"))
    parser.add_argument("--job-dir", required=True)
    args = parser.parse_args(argv)
    job = _read_json(os.path.join(args.job_dir, "job.json"))
    if not isinstance(job, dict):
        print("job.json missing or unreadable", file=sys.stderr)
        return 2
    if args.command == "seed":
        seed(job)
    elif args.command == "finalize":
        finalize(job)
    else:
        print(json.dumps(job_state(job["job_id"]), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
