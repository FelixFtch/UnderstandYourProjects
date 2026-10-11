#!/usr/bin/env bash
# Deploy Jarvis Studio v2 (branch robin/studio-revamp) from this Mac to the clinic Jetson.
# Backs up everything it replaces; restarts one service at a time with a health check.
set -euo pipefail
UYP=~/code/UnderstandYourProjects
HH=~/code/jarvis-homehub/jetson
STAMP=$(date +%Y%m%d-%H%M%S)
B="backups/studio-v2-$STAMP"

echo "== 0. build Studio SPA"
( cd "$UYP/studio" && npx -y pnpm@9 exec tsc -b --noEmit && npx -y pnpm@9 exec vite build >/dev/null )
test -f "$UYP/studio/dist/index.html"

echo "== 1. backups on Jetson -> ~/$B"
ssh jetson "set -e; mkdir -p ~/$B
  tar -czf ~/$B/companion-api-src.tgz -C ~/jetson/services/companion-api --exclude=__pycache__ src
  [ -d ~/jetson/services/companion-api/studio_dist ] && tar -czf ~/$B/studio_dist.tgz -C ~/jetson/services/companion-api studio_dist || true
  tar -czf ~/$B/agent-gateway-src.tgz -C ~/jetson/services/agent-gateway --exclude=__pycache__ src
  tar -czf ~/$B/agent-runtime-src.tgz -C ~/dev/voice-p1/src/services/agent-runtime --exclude=__pycache__ src
  tar -czf ~/$B/uyp-indexer.tgz -C ~/dev/uyp --exclude=__pycache__ indexer
  python3 -c \"import sqlite3,os;s=sqlite3.connect(os.path.expanduser('~/.companion-api/data.db'));d=sqlite3.connect(os.path.expanduser('~/$B/companion-data.db'));s.backup(d)\"
  ls -la ~/$B"

echo "== 2. sync code"
rsync -a --exclude __pycache__ "$HH/services/companion-api/src/" jetson:jetson/services/companion-api/src/
rsync -a --delete "$UYP/studio/dist/" jetson:jetson/services/companion-api/studio_dist/
rsync -a --exclude __pycache__ "$HH/services/agent-gateway/src/" jetson:jetson/services/agent-gateway/src/
rsync -a --exclude __pycache__ "$HH/services/agent-runtime/src/" jetson:dev/voice-p1/src/services/agent-runtime/src/
rsync -a --exclude node_modules --exclude __pycache__ --exclude 'studio/dist' --exclude .git "$UYP/" jetson:dev/uyp/repo/
ssh jetson "rsync -a --delete --exclude __pycache__ ~/dev/uyp/repo/services/indexer/src/ ~/dev/uyp/indexer/"

echo "== 3. service config"
ssh jetson 'set -e; U=~/.config/systemd/user
  mkdir -p $U/uyp-query-api.service.d
  cat > $U/uyp-query-api.service.d/60-studio.conf <<EOF
[Service]
Environment=UYP_CONNECTOR_TOKEN_FILE=%h/.config/uyp/token
Environment=UYP_UA_ROOT=%h/dev/uyp/understand-anything-src-20261009
Environment=UYP_OWNER_MEMBER=robin
Environment=UYP_NANDATOWN_PARTICIPANT=uyp-indexer
Environment=UYP_ENRICH_WORKERS=2
EOF
  cat > $U/uyp-grant-renew.service <<EOF
[Unit]
Description=Renew HomeHub UYP project grants for the owner (Studio v2)
[Service]
Type=oneshot
ExecStart=/bin/sh -c "T=%h/.config/uyp/homehub.token; [ -s \$T ] || exit 0; curl -fsS -m 30 -X POST -H \"Authorization: Bearer \$(cat \$T)\" http://127.0.0.1:5120/api/studio/projects/sync-grants >/dev/null"
EOF
  cat > $U/uyp-grant-renew.timer <<EOF
[Unit]
Description=Renew UYP project grants every 6 hours
[Timer]
OnBootSec=3min
OnUnitActiveSec=6h
Persistent=true
[Install]
WantedBy=timers.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now uyp-grant-renew.timer'

health() { # name url
  for i in $(seq 1 40); do ssh jetson "curl -sf -m 3 $2 >/dev/null" && { echo "   $1 healthy"; return 0; }; sleep 1; done
  echo "   $1 NOT healthy"; return 1; }

echo "== 4. restarts"
ssh jetson "systemctl --user restart companion-api"; health companion-api http://127.0.0.1:5120/health
ssh jetson "systemctl --user restart agent-gateway"; health agent-gateway http://127.0.0.1:8891/api/agents
ssh jetson "systemctl --user restart uyp-query-api"; health uyp-query-api http://127.0.0.1:8787/api/health
ssh jetson "systemctl --user restart voice-agent-runtime"; health voice-agent-runtime http://127.0.0.1:8868/health

echo "== 5. smoke"
ssh jetson 'curl -s -m 90 -H "Content-Type: application/json" -d "{\"text\": \"what time is it\"}" http://127.0.0.1:8868/v1/agent/turn | head -c 200; echo
  curl -s -m 5 http://127.0.0.1:8868/v1/agent/flows; echo
  curl -s -o /dev/null -w "studio page %{http_code}\n" http://127.0.0.1:5120/studio/
  curl -s -o /dev/null -w "studio me (no token) %{http_code}\n" http://127.0.0.1:5120/api/studio/me
  curl -s -o /dev/null -w "uyp projects (no token) %{http_code}\n" http://127.0.0.1:8787/api/projects
  for u in companion-api agent-gateway uyp-query-api voice-agent-runtime voice-hub-stub clinic-agent; do printf "%-22s %s\n" $u $(systemctl --user is-active $u); done
  for u in robotdesk-homehub-clinic robotdesk-xvf-phase-b-clinic voice-stt voice-tts voice-voiceprint; do printf "%-30s %s\n" $u $(systemctl is-active $u); done'
echo "== DONE (backups in ~/$B)"
