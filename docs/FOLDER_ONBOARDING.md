# Folder Onboarding — how Jarvis learns a new folder

Audience: a human or an agent who wants Jarvis to answer questions about a new
folder on the Mac. Everything below was verified end-to-end on 2026-10-14.
Companion reading: `docs/STUDIO_V2.md` (architecture contract) and
`docs/QUERY_API.md` (query-side details).

## 1. Concept model

Four boxes, one direction of trust:

```
Mac (connector-mac)          SSH reverse tunnel           Jetson (yahboom)
┌──────────────────────┐   ssh -R 127.0.0.1:7121   ┌────────────────────────────┐
│ connector :7121      │ ◄──────────────────────── │ indexer (index_job.py)     │
│  · grants (ro only)  │   loopback on both sides  │  uyp-indexjob.timer 1 min  │
│  · DENY regex        │                           │   → run-pending --max-jobs 1│
│  · EXCLUDE_DIRS      │   lid closed → tunnel     │  durable job, resumes      │
│  · 30 s poll /       │   drops; lid open →       │  GPU yields:               │
│    FSEvents watcher  │   launchd KeepAlive       │  voice > query > index     │
│    → event log       │   reconnects              │                            │
└──────────────────────┘                           │ publish → output/<proj>/   │
                                                   │   + projects registry      │
                                                   │ query_api :8787            │
                                                   └────────────────────────────┘
```

- **Mac connector** (`services/connector-mac/src/main.py`; deployed on the Mac at
  `~/.local/lib/uyp-connector/main.py`): an HTTP service bound to loopback on port
  **7121**, bearer-token required. Grants are **read-only subtrees** (`"mode": "ro"`).
  A compiled `DENY` regex list (`.ssh`, `.config`, keychain, `.pem`, `.env`,
  credentials, secrets, …) is enforced at grant time *and* at read time, and an
  `EXCLUDE_DIRS` set (`.git`, `node_modules`, `.venv`, `dist`, …) is skipped during
  scans. A background watcher polls every **30 s**
  (`UYP_WATCHER_POLL_SECONDS`, FSEvents when `watchdog` is installed) and appends
  changes to an append-only event log (`~/.config/uyp/events_log.jsonl`,
  `GET /events?since=<id>`). Every request carries an audit id logged to
  `~/Library/Logs/uyp/connector.log`.
- **SSH reverse tunnel**: the Jetson reaches the connector as
  `http://127.0.0.1:7121` via `ssh -R`. When the Mac lid closes the tunnel drops;
  on wake, launchd `KeepAlive` re-establishes it automatically. Nothing on the
  Jetson side needs to change — the indexer sees the connector as `offline` and
  retries.
- **Jetson indexer**: `uyp-indexjob.timer` fires every minute
  (`OnUnitActiveSec=1min`) and runs `index_job.py … run-pending --max-jobs 1`
  (`jetson/systemd/uyp-indexjob.{service,timer}`). Jobs are **durable** — state in
  `~/dev/uyp/state/index-jobs/<job_id>.json`, resumable across tunnel drops and
  restarts. GPU etiquette is strict: **voice > query > index** — enrichment curls
  are marked `X-UYP-Worker: index` and are preempted when an interactive
  (voice/query) lock is fresh (`services/indexer/src/query_api.py`,
  `test_index_project.py`).
- **Publish**: a finished job publishes to `~/dev/uyp/output/<project>/` and the
  project appears in the registry at `<state>/projects/registry.json`
  (`services/indexer/src/projects.py`, `sync_registry`).
- **Query API**: `query_api` on **8787** serves `/api/projects*`,
  `POST /api/knowledge/search`, and group search. It never answers without a
  HomeHub AccessContext (fail-closed, §5).

## 2. The two doors

### Door A — Studio UI (for humans)

Studio → **Devices → "+" → "Analyze a folder"** (owner role only). This lands on
`POST /api/studio/projects/analyze` on companion-api, which first creates the
HomeHub `uyp_grants` row for the owner (project + `connector:<root>`), then calls
UYP `POST /api/projects/analyze`, which validates the path, finds or creates the
connector grant, registers the project (with hierarchy relation), and launches a
detached job (`docs/STUDIO_V2.md` §6.2). Progress is visible in the UI and via
`GET /api/projects/jobs/{job_id}` (`status`, `phase`, `progress`, `log_tail`).

### Door B — CLI (for agents)

```
jetson/uyp-onboard-folder.sh <absolute-or-~ path on the Mac> [--yes]
```

Runs **on the Jetson** and knocks all three doors from there (script header):

1. **Connector grant** — `POST 127.0.0.1:7121/grants {path}`. *Idempotent:*
   existing grants are listed first and reused if the path matches (the connector
   mints a fresh grant on every POST, so the script never POSTs blindly).
2. **HomeHub project grant** — appends the project to
   `~/.config/uyp/grants-to-keep.json` (*idempotent:* skipped if `project_id`
   already present), then runs `uyp_grant_renewal.py` immediately, which issues
   the 24 h grant with the full derived scope set and refreshes
   `~/.config/uyp/access-context.json`. The script aborts if the project is
   missing from `projectScopes` afterwards.
3. **Durable IndexJob** — `index_job.py create --project-id <root_name> …`.
   *Idempotent:* if a live job (phase `discovered|authorized|queued|running|
   staged|retry_wait|published`) already exists for the project it is reused,
   never duplicated.

The script then watches the per-minute timer pick the job up (up to ~3 min) and
aborts loudly if the job lands in `blocked|revoked|failed|offline`. Pass `--yes`
to skip the confirmation prompt (agents).

The project id is **derived, never guessed**: after the grant, the script polls
`GET /manifest?grant=<id>` until `root_name` appears and uses that as
`--project-id` (see hard rule (a) below).

## 3. Three hard rules

### (a) Project id == the folder's basename

The job's `--project-id` **must equal the connector manifest's `root_name`** —
the basename of the granted folder. Anything else dies at authorize time with
`failed / manifest_project_mismatch` (`index_job.py`: the manifest's `root_name`
is compared to `job["projectId"]` on every attempt). Never invent a prettier id;
rename the folder first if you want a prettier name.

### (b) A HomeHub grant needs BOTH source scopes

`projects.visible()` (`services/indexer/src/projects.py`) applies **two gates**,
and both must pass:

- **project gate** — `projectScopes` contains the project id (or `*` /
  `project:<id>`);
- **source gate** — `sourceScopes` contains `connector:<project_id>` (or
  `connector:<root_name>`, or `*`).

Meanwhile the **indexer** side authorizes against the `mac-connector` source
capability. So every grant must carry `source_ids = ["mac-connector",
"connector:<project_id>"]`. Since the 2026-10-14 LingoQA incident fix,
`uyp_grant_renewal.py` **derives** this set automatically
(`required_sources()` — never hand-written) and checks both TTL *and* source
coverage: an existing narrow grant missing `connector:<project_id>` is revoked
and re-issued with no manual intervention. Symptom of a narrow grant: indexing
runs fine but the project is invisible to every query.

### (c) Grants are read-only — and macOS will ask

Connector grants are `ro` by construction; the connector cannot write. But the
first scan of a folder macOS has never authorized for the connector's Python
triggers a **TCC prompt** ("python3.13 would like to access files in your
Documents/Desktop/… folder"). This is expected; approve it once per folder class.
Annoyance from repeated prompts is why the owner disabled the `voiceink-sync`
folder grant on 2026-10-14.

To **revoke a folder's authorization completely** (all three layers):

```bash
# on the Jetson:
TOKEN=$(tr -d '[:space:]' < ~/.config/uyp/token)
# 1. connector grant
curl -fsS -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:7121/grants/<grant_id>
# 2. HomeHub grant (so queries lose visibility immediately)
#    revoke via the renewal script's hub API:
curl -fsS -X POST -H "Authorization: Bearer $(cat ~/.config/uyp/homehub.token)" \
  -H 'Content-Type: application/json' \
  -d '{"reason":"owner_revoked"}' \
  http://127.0.0.1:5120/api/uyp/grants/<hub_grant_id>/revoke
# 3. remove the entry from ~/.config/uyp/grants-to-keep.json,
#    or the hourly renewal will simply re-issue the HomeHub grant.
```

## 4. Grant renewal

HomeHub project grants have a hard TTL ceiling of **24 h**
(`UYP_GRANT_TTL_SECONDS`, default 86400). Any long-running index crosses day
boundaries, so expiry must be refreshed ahead of time:

- `uyp-grant-renewal.timer` (hourly, on the Jetson) runs
  `services/indexer/src/uyp_grant_renewal.py`.
- The script is **keep-list driven**: `~/.config/uyp/grants-to-keep.json`
  (`[{"project_id": …, "source_ids": […], "subject_member_id": …}]`) is the
  desired state; it never touches grants not on the list.
- When an active grant has **< 12 h** left (`RENEW_BEFORE`, default 43200) — or
  its sources don't cover the derived set — it is **revoked first**
  (`reason=scheduled_renewal`) and then re-created; create on a live grant
  returns 409, so revoke-then-create is the only path. There is a ~1–2 s scope
  gap between the two calls. Idempotent: with nothing due it writes nothing;
  failures are retried by the next timer tick.
- The same pass refreshes `~/.config/uyp/access-context.json` (used by
  `run-pending`; a stale context makes incremental waves silently skip).

**`grantEpoch` is monotonic**: every (re-)issue bumps it, the job records the
epoch it was authorized with, and on any later attempt a mismatch flips the job
to `revoked` (`reason=grant_epoch_mismatch`, `index_job.py`). A revoked or
blocked job is not retried as-is — fix the scope/grant and create a fresh job
(re-running `uyp-onboard-folder.sh` is safe).

## 5. Where queries come from

All query paths resolve the caller's HomeHub **AccessContext** first and are
**fail-closed**: no context, no search. `X-Agent-Member` identity headers are
accepted **only on a loopback bind** (`query_api.py`).

| Entry | Path | Notes |
|---|---|---|
| Voice | agent-runtime project-knowledge pin → `POST :8787/api/knowledge/search` | loopback `X-Agent-Member`/`X-Agent-Role` headers; triggers include "哪个项目实现过 X", "哪个项目里有 X", "which project covers X" |
| Studio project page | `POST /api/studio/projects/{id}/ask` → companion-api BFF → `POST :8787/api/projects/{id}/ask` | bearer forwarded; answer + sources + confidence |
| Group chat | `POST :8787/api/groups/{id}/search` | per-group knowledge views ("不同群看到不同知识") |

Visibility on every path still goes through the two gates of §3(b).

## 6. Acceptance checklist

Run on the Jetson after onboarding (script finished with `DONE`):

```bash
TOKEN=$(tr -d '[:space:]' < ~/.config/uyp/token)   # Jetson-local only, never leaves the box

# 1. connector grant is live
curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:7121/grants | python3 -m json.tool

# 2. HomeHub keep list + scopes
cat ~/.config/uyp/grants-to-keep.json
python3 -c "import json; c=json.load(open('$HOME/.config/uyp/access-context.json')); print(c['projectScopes']); print(c['sourceScopes'])"
#    projectScopes must contain the project; sourceScopes must contain connector:<project>

# 3. job phase advancing (repeat; discovered → authorized → queued → running → staged → published)
/usr/bin/python3 ~/dev/uyp/indexer/index_job.py --state-root ~/dev/uyp/state \
  --output-root ~/dev/uyp/output --access-context ~/.config/uyp/access-context.json \
  --connector-host http://127.0.0.1:7121 --token-file ~/.config/uyp/token \
  --ua-root ~/dev/uyp/understand-anything-src-20261009 list

# 4. registry entry exists
python3 -c "import json; d=json.load(open('$HOME/dev/uyp/state/projects/registry.json')); print([p['project_id'] for p in d['projects']])"

# 5. visible via the query API (loopback voice-style headers)
curl -fsS -H 'X-Agent-Member: felix' -H 'X-Agent-Role: owner' \
  http://127.0.0.1:8787/api/projects | python3 -m json.tool

# 6. one real search
curl -fsS -X POST http://127.0.0.1:8787/api/knowledge/search \
  -H 'X-Agent-Member: felix' -H 'X-Agent-Role: owner' \
  -H 'Content-Type: application/json' \
  -d '{"query": "what does <project> do?", "limit": 5}'
```

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Connector refuses grant: `path_not_grantable` (400) | path is not under the **Mac's** `$HOME` or not a directory | pass a real directory under `/Users/<you>/…`; remember `~` must expand on the Mac side (`UYP_MAC_HOME`) |
| Connector refuses grant: `denied_pattern` (403) | path matches the `DENY` regex (`.ssh`, `.config`, keychain, `.env`, secrets…) | pick another folder; the deny list is non-negotiable |
| Job `blocked`, reason `homehub_scope_denied` | HomeHub grant's scopes don't include this project | add the project to `grants-to-keep.json` and run `uyp_grant_renewal.py` (or just re-run the onboard script) |
| Job `failed`, reason `manifest_project_mismatch` | `--project-id` ≠ manifest `root_name` (not the folder basename) | never hand-pick ids; delete the job and let `uyp-onboard-folder.sh` derive it |
| Project in registry but absent from `/api/projects` | `sourceScopes` missing `connector:<project_id>` (narrow legacy grant) | run `uyp_grant_renewal.py` — it detects the missing source, revokes, and re-issues with the full derived set |
| Job `revoked`, reason `grant_epoch_mismatch` | grant was renewed (epoch bumped) after the job authorized | expected; create a fresh job (re-run the onboard script) |
| No incremental updates after the Mac slept | tunnel dropped while lid closed | none needed — launchd `KeepAlive` reconnects on wake; the per-minute timer retries the job automatically (`offline` is recoverable via a new run) |
| TCC prompt on the Mac ("python3.13 would like to access…") | first scan of a folder class macOS hasn't approved | approve once; to stop scanning a folder entirely, revoke per §3(c) |
