#!/bin/bash
# uyp-onboard-folder.sh — one-command onboarding of a Mac folder into UYP
# (UnderstandYourProjects) so Jarvis can answer questions about it.
#
# Runs ON the Jetson (yahboom). The Mac connector is reachable on loopback
# 7121 through the reverse tunnel, so all three doors are knocked from here:
#
#   1. Mac connector grant   POST 127.0.0.1:7121/grants          (ro, DENY-listed
#                                                             paths rejected by the connector)
#   2. HomeHub project grant  grants-to-keep.json + uyp_grant_renewal.py
#                             (issues the 24h grant, refreshes access-context scopes)
#   3. Durable IndexJob       index_job.py create ...            (per-minute timer
#                             picks it up; GPU yields to voice turns)
#
# HARD RULE learned 2026-10-14: the job's --project-id MUST equal the
# connector manifest's root_name (the folder's basename) or the run dies
# later with manifest_project_mismatch. This script derives it, never asks.
#
# Studio equivalent: Devices -> "+" ("Analyze a folder") - same chain wrapped
# in a button; this script is the agent/CLI door (Codex/Kimi can't click).
#
# Usage: uyp-onboard-folder.sh <absolute-or-~ path on the Mac> [--yes]
# Exit: 0 job created & picked up; 1 preflight/chain failure; 2 usage.

set -euo pipefail

CONNECTOR="http://127.0.0.1:7121"     # Mac connector via the -R tunnel
TOKEN_FILE="$HOME/.config/uyp/token"
KEEP_FILE="$HOME/.config/uyp/grants-to-keep.json"
STATE_ROOT="$HOME/dev/uyp/state"
OUTPUT_ROOT="$HOME/dev/uyp/output"
ACCESS_CTX="$HOME/.config/uyp/access-context.json"
UA_ROOT="$HOME/dev/uyp/understand-anything-src-20261009"
INDEXER="$HOME/dev/uyp/indexer"
SUBJECT_MEMBER="felix"
SOURCE_ID="mac-connector"
# The ~ prefix must expand to the MAC's home, not the Jetson's (this script
# runs on the Jetson; the connector validates paths under its own $HOME).
MAC_HOME="${UYP_MAC_HOME:-/Users/felixfang}"

say() { printf '%s\n' "$*"; }
die() { printf 'ABORT %s\n' "$*" >&2; exit 1; }

[ $# -ge 1 ] || { say "usage: $0 <mac-folder-path> [--yes]" >&2; exit 2; }
RAW_PATH="$1"
[ "${2:-}" = "" ] || [ "${2:-}" = "--yes" ] || { say "usage: $0 <path> [--yes]" >&2; exit 2; }
YES="${2:-}"

# Normalize ~ on the MAC side (the connector validates under its $HOME).
case "$RAW_PATH" in
  ~/*) MAC_PATH="$MAC_HOME/${RAW_PATH#~/}" ;;
  ~)   MAC_PATH="$MAC_HOME" ;;
  *)   MAC_PATH="$RAW_PATH" ;;
esac

[ -f "$TOKEN_FILE" ] || die "connector token file missing: $TOKEN_FILE"
TOKEN=$(tr -d '[:space:]' < "$TOKEN_FILE")

say "== preflight: connector alive =="
curl -fsS -m 5 -H "Authorization: Bearer $TOKEN" "$CONNECTOR/status" >/dev/null \
  || die "Mac connector not answering on 7121 (tunnel down?)"

say "== 1/3 connector grant =="
# Idempotent: a path that is already granted reuses its grant - the
# connector mints a fresh grant on every POST, so never POST blindly.
GRANT_ID=$(curl -fsS -m 8 -H "Authorization: Bearer $TOKEN" "$CONNECTOR/grants" \
  | python3 -c "
import json, sys
path = sys.argv[1]
hits = [g['id'] for g in json.load(sys.stdin).get('grants', []) if g.get('path') == path]
print(hits[0] if hits else '')" "$MAC_PATH")
if [ -n "$GRANT_ID" ]; then
  say "   already granted: $GRANT_ID  $MAC_PATH (reused)"
else
  GRANT_JSON=$(curl -fsS -m 10 -X POST "$CONNECTOR/grants" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"path\": \"$MAC_PATH\"}") || die "connector refused the grant (path not under \$HOME, not a dir, or DENY-listed)"
  GRANT_ID=$(printf '%s' "$GRANT_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
  say "   grant $GRANT_ID  $MAC_PATH"
fi

say "== reading manifest root_name =="
sleep 2  # the watcher needs one poll cycle to see the grant
ROOT_NAME=""
for i in 1 2 3 4 5 6; do
  ROOT_NAME=$(curl -fsS -m 10 -H "Authorization: Bearer $TOKEN" \
    "$CONNECTOR/manifest?grant=$GRANT_ID" 2>/dev/null \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('root_name') or '')" 2>/dev/null || true)
  [ -n "$ROOT_NAME" ] && break
  sleep 5
done
[ -n "$ROOT_NAME" ] || die "manifest never answered with a root_name"
[ "$ROOT_NAME" != ".." ] && [ "${ROOT_NAME#/}" = "$ROOT_NAME" ] || die "suspicious root_name: $ROOT_NAME"
say "   project id = $ROOT_NAME (derived, never guessed)"

if [ "$YES" != "--yes" ]; then
  printf 'onboard "%s" as project "%s" (grant %s)? [y/N] ' "$MAC_PATH" "$ROOT_NAME" "$GRANT_ID"
  read -r a; [ "$a" = "y" ] || die "user declined"
fi

say "== 2/3 HomeHub grant (keep list + renewal) =="
python3 - "$KEEP_FILE" "$ROOT_NAME" "$SOURCE_ID" "$SUBJECT_MEMBER" << 'PY'
import json, sys
path, project, source, member = sys.argv[1:5]
keep = json.load(open(path))
if not any(k.get("project_id") == project for k in keep):
    keep.append({"project_id": project, "source_ids": [source],
                 "subject_member_id": member})
    json.dump(keep, open(path, "w"), indent=1, ensure_ascii=False)
print("keep list:", [k["project_id"] for k in json.load(open(path))])
PY
/usr/bin/python3 "$INDEXER/uyp_grant_renewal.py" | tail -2
python3 - "$ACCESS_CTX" "$ROOT_NAME" << 'PY' || die "project missing from access-context scopes after renewal"
import json, sys
ctx, project = sys.argv[1], sys.argv[2]
scopes = json.load(open(ctx)).get("projectScopes", [])
print("projectScopes:", scopes)
sys.exit(0 if project in scopes else 1)
PY

say "== 3/3 durable IndexJob =="
# Idempotent: a live job for this project already running/queued/published
# means the chain is in flight or done - never stack a duplicate.
EXISTING=$(/usr/bin/python3 "$INDEXER/index_job.py" \
  --state-root "$STATE_ROOT" --output-root "$OUTPUT_ROOT" \
  --access-context "$ACCESS_CTX" --connector-host "$CONNECTOR" \
  --token-file "$TOKEN_FILE" --ua-root "$UA_ROOT" \
  list 2>/dev/null | python3 -c "
import json, sys
project = sys.argv[1]
live = {'discovered','authorized','queued','running','staged','retry_wait','published'}
try:
    jobs = json.load(sys.stdin)
except ValueError:
    jobs = []
items = jobs if isinstance(jobs, list) else jobs.get('jobs', [])
hits = [j.get('jobId','') for j in items
        if j.get('projectId') == project and j.get('phase') in live]
print(hits[0] if hits else '')" "$ROOT_NAME")
if [ -n "$EXISTING" ]; then
  JOB_ID="$EXISTING"
  say "   job already exists: $JOB_ID (reused, not duplicated)"
else
  JOB_JSON=$(/usr/bin/python3 "$INDEXER/index_job.py" \
    --state-root "$STATE_ROOT" --output-root "$OUTPUT_ROOT" \
    --access-context "$ACCESS_CTX" --connector-host "$CONNECTOR" \
    --token-file "$TOKEN_FILE" --ua-root "$UA_ROOT" \
    create --project-id "$ROOT_NAME" --source-id "$SOURCE_ID" \
    --connector-grant-id "$GRANT_ID")
  JOB_ID=$(printf '%s' "$JOB_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['jobId'])")
  say "   job $JOB_ID created"
fi

say "== waiting for the per-minute timer to pick it up =="
for i in $(seq 1 18); do
  PHASE=$(python3 - "$STATE_ROOT" "$JOB_ID" << 'PY'
import json, sys
print(json.load(open(f"{sys.argv[1]}/index-jobs/{sys.argv[2]}.json")).get("phase"))
PY
)
  case "$PHASE" in
    running|staged|published) say "   phase=$PHASE (t+${i}0s)"; break ;;
    blocked|revoked|failed|offline)
      REASON=$(python3 -c "import json; print(json.load(open('$STATE_ROOT/index-jobs/$JOB_ID.json')).get('reason'))")
      die "job $JOB_ID went $PHASE ($REASON) - check scopes/grant" ;;
  esac
  sleep 10
done
say "DONE: $ROOT_NAME onboarding in flight; enrichment yields the GPU to voice turns."
say "Query it from Studio (Understanding page) or by voice: '在 $ROOT_NAME 里 …'"
