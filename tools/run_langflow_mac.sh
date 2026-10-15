#!/usr/bin/env bash
set -euo pipefail

# Run the real HomeHub/Jarvis Langflow component pack on the Mac.
# The UI is loopback-only; the only remote connection is the SSH tunnel to
# Jetson's loopback-bound agent-runtime.

HH_ROOT="${JARVIS_HOMEHUB_ROOT:-/Users/felixfang/projects/jarvis-homehub}"
LANGFLOW_IMAGE="${LANGFLOW_IMAGE:-langflowai/langflow:1.12.5}"
LANGFLOW_CONTAINER="${LANGFLOW_CONTAINER:-uyp-langflow}"
LANGFLOW_PORT="${LANGFLOW_PORT:-7860}"
AGENT_RUNTIME_PORT="${AGENT_RUNTIME_PORT:-8868}"
LANGFLOW_USER="${LANGFLOW_SUPERUSER:-felix}"
# LangFlow persists imported flows in its local database.  An old canvas can
# otherwise remain in the database forever and still show pre-typed-handle
# edges as "invalid" after the .flow artifact is fixed.  Re-import/delete is
# explicit because a user may intentionally keep a hand-edited canvas.
LANGFLOW_SYNC_FLOWS="${LANGFLOW_SYNC_FLOWS:-0}"

COMPONENTS="$HH_ROOT/jetson/services/agent-runtime/langflow_components/components"
EXAMPLES="$HH_ROOT/jetson/services/agent-runtime/langflow_components/examples"
RUNTIME_SRC="$HH_ROOT/jetson/services/agent-runtime/src"
VOICE_COMMON_SRC="$HH_ROOT/jetson/packages/voice_common/src"

die() { echo "run_langflow_mac: $*" >&2; exit 1; }
command -v docker >/dev/null || die "Docker is required (start Docker Desktop first)."
command -v ssh >/dev/null || die "ssh is required."
command -v curl >/dev/null || die "curl is required."

[[ -d "$COMPONENTS" ]] || die "Missing Langflow component pack: $COMPONENTS"
[[ -f "$EXAMPLES/studio.flow" ]] || die "Missing studio.flow: $EXAMPLES/studio.flow"
[[ -f "$EXAMPLES/voice.flow" ]] || die "Missing voice.flow: $EXAMPLES/voice.flow"
[[ -d "$RUNTIME_SRC" ]] || die "Missing agent-runtime source: $RUNTIME_SRC"
[[ -d "$VOICE_COMMON_SRC" ]] || die "Missing voice_common source: $VOICE_COMMON_SRC"

docker info >/dev/null 2>&1 || die "Docker Desktop is not running."

# The runtime remains private on Jetson. Forward only its loopback port to the
# Mac; Langflow itself stays bound to 127.0.0.1 below.
if ! curl -fsS --max-time 3 "http://127.0.0.1:${AGENT_RUNTIME_PORT}/health" >/dev/null 2>&1; then
  ssh -fN \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -L "${AGENT_RUNTIME_PORT}:127.0.0.1:${AGENT_RUNTIME_PORT}" \
    jetson-us-cf
fi
curl -fsS --max-time 5 "http://127.0.0.1:${AGENT_RUNTIME_PORT}/health" >/dev/null \
  || die "Jetson agent-runtime is not reachable through the SSH tunnel."

if [[ -z "${LANGFLOW_SUPERUSER_PASSWORD:-}" ]]; then
  die "Set LANGFLOW_SUPERUSER_PASSWORD for the local Langflow login."
fi

if ! docker ps --format '{{.Names}}' | grep -Fxq "$LANGFLOW_CONTAINER"; then
  docker rm -f "$LANGFLOW_CONTAINER" >/dev/null 2>&1 || true
  docker run -d \
    --name "$LANGFLOW_CONTAINER" \
    -p "127.0.0.1:${LANGFLOW_PORT}:7860" \
    -e LANGFLOW_COMPONENTS_PATH=/app/custom \
    -e PYTHONPATH=/app/agent-runtime-src:/app/voice-common-src \
    -e LANGFLOW_SUPERUSER="$LANGFLOW_USER" \
    -e LANGFLOW_SUPERUSER_PASSWORD="$LANGFLOW_SUPERUSER_PASSWORD" \
    -e LANGFLOW_CUSTOM_COMPONENT_ADMIN_ONLY=true \
    -v "$COMPONENTS:/app/custom:ro" \
    -v "$RUNTIME_SRC:/app/agent-runtime-src:ro" \
    -v "$VOICE_COMMON_SRC:/app/voice-common-src:ro" \
    -v "$EXAMPLES:/app/jarvis-flows:ro" \
    "$LANGFLOW_IMAGE" \
    langflow run --host 0.0.0.0 --port 7860 >/dev/null
fi

echo "Waiting for Langflow on http://127.0.0.1:${LANGFLOW_PORT} ..."
for _ in {1..30}; do
  if curl -fsS --max-time 2 "http://127.0.0.1:${LANGFLOW_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS --max-time 3 "http://127.0.0.1:${LANGFLOW_PORT}/health" >/dev/null \
  || die "Langflow did not become healthy. Check: docker logs $LANGFLOW_CONTAINER"

# Import the checked-in canvases once. Docker sees the Mac tunnel through
# host.docker.internal, so rewrite only the imported copy; source .flow files
# remain portable for native Jetson/Mac runs.
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/uyp-langflow.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT
for flow in studio voice; do
  sed 's#http://127\.0\.0\.1:8868#http://host.docker.internal:8868#g' \
    "$EXAMPLES/$flow.flow" > "$TMP_DIR/$flow.flow"
done

TOKEN="$(curl -fsS -X POST "http://127.0.0.1:${LANGFLOW_PORT}/api/v1/login" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode "username=$LANGFLOW_USER" \
  --data-urlencode "password=$LANGFLOW_SUPERUSER_PASSWORD" | \
  python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")"

verify_imported_flow() {
  local flow_id="$1"
  local expected_file="$2"
  local actual_file="$TMP_DIR/$(basename "$expected_file").actual.json"
  curl --compressed -fsS \
    "http://127.0.0.1:${LANGFLOW_PORT}/api/v1/flows/${flow_id}" \
    -H "Authorization: Bearer $TOKEN" > "$actual_file"
  python3 - "$actual_file" "$expected_file" <<'PY'
import json
import sys

actual = json.load(open(sys.argv[1], encoding="utf-8"))
expected = json.load(open(sys.argv[2], encoding="utf-8"))
data = actual.get("data") if isinstance(actual, dict) else None
expected_data = expected.get("data") or {}
if not isinstance(data, dict):
    raise SystemExit("Langflow returned no flow data after import")
actual_nodes = {node.get("id") for node in data.get("nodes") or []}
expected_nodes = {node.get("id") for node in expected_data.get("nodes") or []}
actual_edges = data.get("edges") or []
expected_edges = expected_data.get("edges") or []
if actual_nodes != expected_nodes:
    raise SystemExit(
        f"Langflow changed canonical node set ({len(actual_nodes)} != {len(expected_nodes)})"
    )
if len(actual_edges) != len(expected_edges):
    raise SystemExit(
        f"Langflow dropped canonical edges ({len(actual_edges)} != {len(expected_edges)})"
    )
for edge in actual_edges:
    if edge.get("source") not in actual_nodes or edge.get("target") not in actual_nodes:
        raise SystemExit("Langflow returned an edge with an unknown endpoint")
    source = edge.get("data", {}).get("sourceHandle", {})
    target = edge.get("data", {}).get("targetHandle", {})
    if source.get("id") != edge.get("source") or target.get("id") != edge.get("target"):
        raise SystemExit("Langflow returned a handle whose node id does not match its edge")
print(f"verified {len(actual_nodes)} nodes / {len(actual_edges)} edges")
PY
}

for flow in studio voice; do
  name="Jarvis $flow flow"
  # The upload endpoint upserts a flow when its stable id is present.  If an
  # older import has a different id (or duplicate rows share the name), remove
  # those rows first so the UI cannot keep loading a stale canvas.
  matching_ids="$(curl --compressed -fsS \
    "http://127.0.0.1:${LANGFLOW_PORT}/api/v1/flows/" \
    -H "Authorization: Bearer $TOKEN" | \
    python3 -c 'import json,sys; name=sys.argv[1]; print("\n".join(str(f.get("id")) for f in json.load(sys.stdin) if f.get("name") == name and f.get("id")))' "$name")"
  canonical_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$TMP_DIR/$flow.flow")"
  if [[ "${LANGFLOW_SYNC_FLOWS}" == "1" ]]; then
    while IFS= read -r existing_id; do
      [[ -z "$existing_id" || "$existing_id" == "$canonical_id" ]] && continue
      curl --compressed -fsS -X DELETE \
        "http://127.0.0.1:${LANGFLOW_PORT}/api/v1/flows/${existing_id}" \
        -H "Authorization: Bearer $TOKEN" >/dev/null
      echo "Removed stale $name ($existing_id)"
    done <<< "$matching_ids"
    curl --compressed -fsS -X POST \
      "http://127.0.0.1:${LANGFLOW_PORT}/api/v1/flows/upload/" \
      -H "Authorization: Bearer $TOKEN" \
      -F "file=@$TMP_DIR/$flow.flow;type=application/json" >/dev/null
    verify_imported_flow "$canonical_id" "$TMP_DIR/$flow.flow"
    echo "Synchronized $name ($canonical_id)"
  elif [[ -z "$matching_ids" ]]; then
    curl --compressed -fsS -X POST \
      "http://127.0.0.1:${LANGFLOW_PORT}/api/v1/flows/upload/" \
      -H "Authorization: Bearer $TOKEN" \
      -F "file=@$TMP_DIR/$flow.flow;type=application/json" >/dev/null
    verify_imported_flow "$canonical_id" "$TMP_DIR/$flow.flow"
    echo "Imported $name ($canonical_id)"
  else
    echo "Keeping existing $name (LANGFLOW_SYNC_FLOWS=0)"
  fi
done

echo "Langflow: http://127.0.0.1:${LANGFLOW_PORT}"
echo "Flows:    Jarvis studio flow, Jarvis voice flow"
echo "Runtime:  Jetson via http://host.docker.internal:${AGENT_RUNTIME_PORT}"
echo "Stop:     docker rm -f $LANGFLOW_CONTAINER"
