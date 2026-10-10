#!/usr/bin/env python3
"""Laya triage calibration runner.

Reads benchmarks/triage_labeled_v1.jsonl (file pattern -> expected verdict +
expected think-gate level), resolves each row to a real file under the
jarvis-memory-live repo, sends the first 900 chars to the live Laya decision
service (Jev-compatible /v1/systemone on jetson-us-cf) and scores:

  * verdict accuracy (exact, and "functional" where skip ~= structure-only
    for no-LLM purposes)
  * think-gate direction agreement (expected high, i.e. gate_expected > 0.5,
    vs noul > 0.5)

Usage:  python3 benchmarks/run_calibration.py [--out FILE] [--repo PATH]

stdlib only.
"""

import argparse
import datetime as _dt
import glob
import json
import os
import subprocess
import sys
import tempfile
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
LABELS = os.path.join(HERE, "triage_labeled_v1.jsonl")
DEFAULT_REPO = os.path.expanduser("~/projects/jarvis-memory-live")
SSH_HOST = "jetson-us-cf"
ENDPOINT = "http://127.0.0.1:8901/v1/systemone"
HEAD_CHARS = 900

# Labeled patterns that no longer exist in the ground-truth repo -> closest
# artifact with the same semantic role (dep list). Recorded as substituted.
SUBSTITUTIONS = {
    "requirements-runtime.txt": "packages/agent_contracts/pyproject.toml",
}

# Verdict classes for "functional" scoring: skip and structure-only both mean
# "no LLM needed".
NO_LLM = {"skip", "structure-only"}

QUESTIONS = {
    "triage": {
        "type": "choice",
        "instructions": "What analysis does this file deserve?",
        "criteria": {
            "skip": "trivial/marker/generated",
            "structure-only": "deps/config; no LLM",
            "quick-summary": "docs worth one line",
            "deep-analysis": "core logic",
        },
    },
    "thinking": {
        "type": "noul",
        "instructions": "Does analysis need multi-step reasoning?",
    },
}


def resolve(row_file, repo):
    """Resolve a labeled pattern to an existing file. Returns (path, note)."""
    if row_file in SUBSTITUTIONS:
        cand = SUBSTITUTIONS[row_file]
        p = os.path.join(repo, cand)
        if os.path.isfile(p):
            return p, "substituted (labeled path absent from repo)"
        return None, "substitution target missing: %s" % cand
    p = os.path.join(repo, row_file)
    if os.path.isfile(p):
        return p, ""
    if "*" in row_file or "?" in row_file:
        hits = sorted(glob.glob(p, recursive=True))
        if hits:
            return hits[0], "glob, first of %d matches" % len(hits)
    return None, "not found"


def read_head(path):
    """First HEAD_CHARS chars; binary files decode with replacement markers."""
    with open(path, "rb") as f:
        raw = f.read(HEAD_CHARS)
    try:
        text = raw.decode("utf-8")
        binary = False
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        binary = True
    return text, binary


def call_laya(state):
    """POST payload to ENDPOINT via ssh+curl. Payload is scp'd as a file so
    no shell-quoting of file content is needed."""
    payload = json.dumps({"state": state, "questions": QUESTIONS})
    rtmp = "/tmp/laya_calib_%s.json" % uuid.uuid4().hex[:8]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(payload)
        ltmp = f.name
    try:
        subprocess.run(
            ["scp", "-q", "-o", "BatchMode=yes", ltmp, "%s:%s" % (SSH_HOST, rtmp)],
            check=True, timeout=60,
        )
        cmd = (
            "curl -s -m 120 %s -X POST -H 'Content-Type: application/json' -d @%s"
            % (ENDPOINT, rtmp)
        )
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", SSH_HOST, cmd],
            capture_output=True, text=True, timeout=180,
        )
    finally:
        os.unlink(ltmp)
        subprocess.run(
            ["ssh", "-o", "BatchMode=yes", SSH_HOST, "rm -f %s" % rtmp],
            timeout=30, capture_output=True,
        )
    body = proc.stdout.strip()
    if proc.returncode != 0 or not body:
        raise RuntimeError("ssh/curl failed rc=%s stderr=%s" % (proc.returncode, proc.stderr[:300]))
    return json.loads(body)


def functional(v):
    return "no-llm" if v in NO_LLM else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--out", default=None, help="results json path")
    ap.add_argument("--retry", type=int, default=1)
    args = ap.parse_args()

    with open(LABELS) as f:
        rows = [json.loads(line) for line in f if line.strip()]

    results = []
    for row in rows:
        path, note = resolve(row["file"], args.repo)
        rec = {
            "file": row["file"],
            "expected": row["expected"],
            "gate_expected": row["gate_expected"],
            "reason": row.get("reason", ""),
        }
        if path is None:
            rec.update({"error": note, "ok": False})
            results.append(rec)
            print("SKIP  %-70s %s" % (row["file"], note))
            continue
        state_text, binary = read_head(path)
        state = "repository file content:\n" + state_text
        try:
            attempt = 0
            while True:
                try:
                    resp = call_laya(state)
                    break
                except Exception as e:
                    if attempt >= args.retry:
                        raise
                    attempt += 1
            t = resp["answers"]["triage"]
            g = resp["answers"]["thinking"]
            got = t["choice"]
            rec.update({
                "ok": True,
                "resolved_path": path,
                "resolve_note": note,
                "binary": binary,
                "model": resp.get("model", ""),
                "verdict": got,
                "probabilities": t.get("probabilities", {}),
                "confidence": t.get("confidence"),
                "noul": g.get("noul"),
                "state_sent_head": state[:200],
                "exact_match": got == row["expected"],
                "functional_match": functional(got) == functional(row["expected"]),
                "gate_expected_high": row["gate_expected"] > 0.5,
                "gate_predicted_high": (g.get("noul") or 0.0) > 0.5,
            })
            rec["gate_agree"] = rec["gate_expected_high"] == rec["gate_predicted_high"]
            flag = "ok  " if rec["exact_match"] else ("~ok " if rec["functional_match"] else "FAIL")
            print("%s %-70s exp=%-14s got=%-14s p(got)=%.2f noul=%.2f" % (
                flag, row["file"], row["expected"], got,
                (t.get("probabilities", {}) or {}).get(got, 0.0),
                rec["noul"] or 0.0))
        except Exception as e:
            rec.update({"ok": False, "error": str(e)})
            print("ERR  %-70s %s" % (row["file"], e))
        results.append(rec)

    scored = [r for r in results if r.get("ok")]
    n = len(scored)
    summary = {
        "n_scored": n,
        "n_total": len(results),
        "verdict_exact_accuracy": sum(r["exact_match"] for r in scored) / n if n else 0,
        "verdict_functional_accuracy": sum(r["functional_match"] for r in scored) / n if n else 0,
        "gate_direction_agreement": sum(r["gate_agree"] for r in scored) / n if n else 0,
        "confusion": {},
        "errors": [r for r in results if not r.get("ok")],
    }
    for r in scored:
        key = "%s -> %s" % (r["expected"], r["verdict"])
        summary["confusion"][key] = summary["confusion"].get(key, 0) + 1

    print("\n=== summary ===")
    print("verdict exact:        %d/%d = %.0f%%" % (
        sum(r["exact_match"] for r in scored), n, 100 * summary["verdict_exact_accuracy"]))
    print("verdict functional:   %d/%d = %.0f%%" % (
        sum(r["functional_match"] for r in scored), n, 100 * summary["verdict_functional_accuracy"]))
    print("gate direction agree: %d/%d = %.0f%%" % (
        sum(r["gate_agree"] for r in scored), n, 100 * summary["gate_direction_agreement"]))
    for k, v in sorted(summary["confusion"].items()):
        print("  %-40s x%d" % (k, v))

    out = args.out or os.path.join(
        HERE, "calibration_results_%s.json" % _dt.date.today().isoformat())
    doc = {
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "labels": LABELS,
        "ground_truth_repo": args.repo,
        "endpoint": ENDPOINT,
        "ssh_host": SSH_HOST,
        "head_chars": HEAD_CHARS,
        "summary": summary,
        "rows": results,
    }
    with open(out, "w") as f:
        json.dump(doc, f, indent=2)
    print("\nwrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
