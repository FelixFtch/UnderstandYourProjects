#!/usr/bin/env bash
# Hotfix 2026-10-11: Studio sign-out loop + project access on the clinic Jetson.
#  1. companion-api gets the HomeHub node id (the main HomeHub unit's
#     ROBOTDESK_HOMEHUB_HUB_ID); without it /api/uyp/access-context fails with
#     uyp_homehub_node_id_unconfigured and every project request is refused.
#  2. companion-api never relays a project-service 401 as 401 (was signing the owner out).
#  3. Studio only forgets its saved login when HomeHub itself rejects it.
set -euo pipefail
HH=~/code/jarvis-homehub/jetson
UYP=~/code/UnderstandYourProjects
STAMP=$(date +%Y%m%d-%H%M%S)

( cd "$UYP/studio" && npx -y pnpm@9 exec vite build >/dev/null )
ssh jetson "mkdir -p ~/backups/hotfix-$STAMP && cp ~/jetson/services/companion-api/src/companion_api/routes/studio_projects.py ~/backups/hotfix-$STAMP/ && tar -czf ~/backups/hotfix-$STAMP/studio_dist.tgz -C ~/jetson/services/companion-api studio_dist"
scp -q "$HH/services/companion-api/src/companion_api/routes/studio_projects.py" jetson:jetson/services/companion-api/src/companion_api/routes/studio_projects.py
rsync -a --delete "$UYP/studio/dist/" jetson:jetson/services/companion-api/studio_dist/
ssh jetson 'set -e
  HUB=$(systemctl cat robotdesk-homehub-clinic | sed -n "s/^Environment=ROBOTDESK_HOMEHUB_HUB_ID=//p" | tail -1)
  test -n "$HUB"
  mkdir -p ~/.config/systemd/user/companion-api.service.d
  printf "[Service]\nEnvironment=ROBOTDESK_HOMEHUB_HUB_ID=%s\n" "$HUB" > ~/.config/systemd/user/companion-api.service.d/50-node-id.conf
  systemctl --user daemon-reload
  systemctl --user restart companion-api
  for i in $(seq 1 30); do curl -sf -m 2 http://127.0.0.1:5120/health >/dev/null && break; sleep 1; done
  echo "companion-api: $(systemctl --user is-active companion-api)"
  T=$(cat ~/.config/uyp/homehub.token)
  curl -s -m 10 -H "Authorization: Bearer $T" "http://127.0.0.1:5120/api/uyp/access-context?member=robin" | python3 -c "import sys,json;d=json.load(sys.stdin);print(\"access-context:\", \"OK principal=\"+str(d.get(\"principalId\")) if d.get(\"principalId\") else d)"'
echo "hotfix done (backups in ~/backups/hotfix-$STAMP)"
