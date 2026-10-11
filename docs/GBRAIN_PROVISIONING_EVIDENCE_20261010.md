# gBrain provisioning runbook — first-execution evidence (audit item A8)

Date: 2026-10-10 (late evening EDT) / 2026-10-11 UTC. Executor: Claude (this
session). Host: jetson-us-cf (Jetson, user jetson). Runbook under test:
`docs/GBRAIN_PROVISIONING.md`.

Verdict up front: **the provisioning contract works end to end** — brain on
:3142, fenced writer principal, patch + env gate on :8790, live publish,
revocation rehearsal — with **one material functional finding (F1)**: the
scoped read path through :8790 never surfaces project blocks in practice
(fail-closed direction perfect, positive direction starved by ranking), and
**one process finding (F2)**: the runbook had already been partially executed
at 10:47–10:56 EDT the same morning by an unrecorded session, so "first run"
was in practice a verification + completion run. Never touched: :3141
directly, family creds, robotdesk-*/voice-*/uyp-query-api/nandatown units,
the in-flight index worker.

## 0. Headline table

| Runbook step | Result | Notes |
|---|---|---|
| §1 brain + serve :3142 | PASS (pre-existing, verified) | unit/brain/routes created 10:47–10:53 EDT; serve healthy since boot |
| §2 writer principal + fence | PASS (pre-existing, verified) | client `uyp-indexer`, fence `project_knowledge/`, surface full |
| §2.3 rescope via local CLI | **FAIL as written** (B1) | PGLite lock; rescope already in effect (surface full, grant_revision 2) |
| §3 `check` | PASS | ok=true, 90 tools, probe put+delete ok, exit 0 — after flag-order fix (B2) |
| §3 `mcp verify` (2nd opinion) | PASS after flag fix (B3) | all functional stages passed |
| §4.1 patch applied | PASS (pre-existing, verified) | .bak-uyp md5 == patch header target md5 exactly |
| §4.2 grant to felix | PASS (pre-existing, verified) | brain_grants row present, not revoked |
| §4.3 env gate live | PASS (pre-existing, verified) | drop-in override.conf, `systemctl cat` shows it |
| §4.4 prefilter confirm | PASS fail-closed / **F1** positive path starved | see finding F1 |
| Env-absent regression | PASS | import without `KNOWLEDGE_PROJECT_BRAIN` → project_knowledge NOT in ALL_BRAINS |
| §6 first live publish | PASS | 1 item + manifest, ok=1, manifestWritten=true |
| §6 revoke rehearsal | PASS | 1/1 deleted, tombstone written, all invalidation checks hold |
| §5 quota monitoring cmd | **FAIL as written** (B1) | same PGLite lock; `gbrain mcp admin clients --url` works instead |

## 1. Environmental facts at execution time

- gbrain `0.59.0.0` at `~/.bun/bin/gbrain` (0.60.x upgrade banner ignored on
  purpose). Note: `~/.bun/bin/gbrain` over non-interactive ssh needs
  `PATH=$HOME/.bun/bin:$PATH` (shebang `#!/usr/bin/env bun`).
- Jetson booted 2026-10-10 23:17:12 EDT. `gbrain-serve-project-knowledge` and
  `knowledge-service` up since 23:16:23 EDT (boot), NRestarts=0 each.
- Ports: 3142 (bun, pid 1605, project brain), 3141 (family), 8790
  (knowledge-service v3, python3), 8108 (llama-embed) — all healthy:
  - `curl :3142/health` → `{"status":"ok","version":"0.59.0.0","engine":"pglite"}`
  - `curl :3141/health` → `{"status":"ok","version":"0.59.0.0","engine":"pglite"}`
  - `curl :8790/health` → `{"status": "ok", "service": "knowledge-service-v3", "dynamic": true}`

## 2. Finding F2 — the runbook had already been partially executed (morning session)

The task brief said "never executed". The filesystem says otherwise. Created
2026-10-10 10:47–10:56 EDT by an unrecorded session (probably launch-prep):

| Artifact | mtime | Content |
|---|---|---|
| `~/.config/systemd/user/gbrain-serve-project-knowledge.service` | 10:47:47 | byte-matches runbook §1.2 unit text |
| `~/jarvis/gbrain/project_knowledge/` (+ `.gbrain`) | 10:47 | pglite brain init |
| `~/jarvis/gbrain/.creds/project_knowledge.json` (0600) | 10:48 | client_id `gbrain_cl_612d9d82c316…002825`, profile memory-writer, **harness `generic`** (runbook §2.2 says `--harness uyp-indexer` — deviation) |
| `serve_routes.json` + `.bak-20261010` | 10:53 | family + project_knowledge entries exactly as §2.4 |
| patch scp'd + `knowledge-service.py.bak-20261010` + `.bak-uyp` | 10:55 | patch applied (see §4 below) |
| epoch-2 publish in the brain | 14:56:07Z | manifest `uyp_published_at`, `uyp_revoked: false`, "Entries: 120" — the P7 118/120-item output (job-2a1f2742d9, knowledgeVersion 2026-10-10T08:05:32.353010Z, grantEpoch 2) |

Consequences for this run: §1/§2/§4.1–4.3 were *verifications* of standing
state, not executions; §6 publish was re-done by me on a fresh epoch; §6
**revoke had never been run by anyone** and is genuinely first-run here.

## 3. Step-by-step with actual outputs

### §1/§2 — brain, serve, writer principal, fence (verified standing state)

- Unit active: `gbrain-serve-project-knowledge.service — active (running)
  since Sat 2026-10-10 23:16:23 EDT; Main PID 1605 (bun)`.
- Writer client (via live-serve admin, `gbrain mcp admin clients --url
  http://127.0.0.1:3142` with `GBRAIN_ADMIN_BOOTSTRAP_TOKEN`):
  `client_name uyp-indexer`, scopes `[read, write, skills_member_self]`,
  `boundSlugPrefixes ["project_knowledge/"]`, **91 allowed operations
  including put_page and delete_page** (runbook §2.3's rescope is in effect;
  `gbrain mcp verify` independently reports `"surface": "full"`,
  `grant_revision: 2`).
- Slug fence attack test (this run, writer creds):
  - `put_page` slug `fence_test_outside` → **rejected** `invalid_params`
  - `put_page` slug `family/fence_test` → **rejected** `invalid_params`
- Runbook §2.3's own commands (`GBRAIN_HOME=~/jarvis/gbrain/project_knowledge
  gbrain auth clients` / `auth rescope-client …`) **fail while the serve
  runs** (bug B1): `Error: GBrain's local database is already open through
  'gbrain serve' (MCP, PID 1605). … Never remove a live holder's lock.`
  Same for §5's `auth clients --usage` and §6's `gbrain get`.
- `serve_routes.json` holds family + project_knowledge; route is read per
  request (no restart needed) — confirmed by behavior in §4.

### §3 — `check` and `verify`

`check` (run on the Jetson, `~/dev/uyp/indexer/gbrain_publisher.py`, md5
identical to repo `services/indexer/src/gbrain_publisher.py`):

```
check: token OK, 90 tools visible (put_page=True, delete_page=True)
check: probe PUT ok (quota headroom confirmed)
check: probe DELETE ok (namespace clean)
"ok": true, "quotaHeadroom": "ok", "warnings": [], EXIT=0
```

Command-form bug B2: `--url/--creds/--apply` are top-level flags; the
runbook's invocations (`… check --url …`, `… --grant-epoch <e> --apply …`)
exit 2 `unrecognized arguments`. Working form:
`python3 gbrain_publisher.py --url U --creds C [--apply] <subcommand> …`.

`gbrain mcp verify` (second opinion): runbook form fails
(`Endpoint does not match the private credential handoff`). Working form
(bug B3): `--url http://127.0.0.1:3142/mcp --harness generic` →
`status: partial` with transport/authentication/permissions/read/write
(`lost_response_reconciled_by_readback`)/write_readback/cleanup all
`passed`; "partial" only because the native-harness SDK probe and delegation
were not requested (N/A for a machine client). It soft-deletes its own
fixture page `project_knowledge/gbrain-verification-3dda8733…` (cleanup
semantics: soft_delete).

### §4 — knowledge-service patch, gate, grant, regression

- Patch state: current file 653 lines; `.bak-uyp` md5
  `82fafe72b3e39562b555dac350e5a266` **equals the patch header's recorded
  target md5 exactly** — the deployed patch applied cleanly to the audited
  base.
- Gate: `systemctl --user cat knowledge-service` shows
  `Environment=KNOWLEDGE_PROJECT_BRAIN=1` (drop-in `override.conf`).
- Grant row (SQLite `~/.companion-api/data.db`, brain_grants):
  `('project_knowledge','system','member','felix','system',NULL)` — not revoked.
- **Env-absent regression**: importing `knowledge-service.py` in a subprocess
  without `KNOWLEDGE_PROJECT_BRAIN` yields
  `ALL_BRAINS = ['personal_felix','personal_mom','personal_ly','family','public','external']`
  — `project_knowledge` NOT registered; `project_scope_filter` present but
  only ever excludes. Default-off behavior confirmed at the registration
  level. (I did not restart knowledge-service at any point in this run —
  the drop-in was already live from boot.)
- §4.4 matrix (post-publish, member felix):

| Query | project blocks | family blocks |
|---|---|---|
| plain, no params (pre-publish baseline) | 0 | 3 |
| plain, no params (post-publish) | 0 | 3–4 |
| scoped project+epoch5 (hash term) | **0** | — |
| scoped wrong epoch (4) | 0 | — |
| scoped wrong project | 0 | — |
| scoped epoch2 (prior publish) | **0** | — |
| post-revoke scoped epoch5 (hash + tombstone term) | 0 | 2–4 |

  Fail-closed: perfect, including no tombstone leak. Positive path: see F1.

### §6 — first live publish (epoch 5) and revoke rehearsal

Target: the small, stable, already-published incremental `incr-3821406c765f`
(project `jarvis-memory-live`, knowledgeVersion
`58e5ed122bec7e28619d261f1b4b30d5`, grantEpoch 5, published 17:44Z, 1 item)
— NOT the in-flight full-index job (job writing `~/dev/uyp/output/jarvis-homehub`,
1002+ items, dir mtime advancing during the run). The P7 118-item tree was
already mirrored by the morning session as epoch 2.

Dry run → `1 items + manifest, 807 bytes` (entry slug
`project_knowledge/jarvis-memory-live/5/brain_graph.json` + `…/5/__manifest__`).
Apply (correct flag order):

```json
{"dryRun": false, "entries": 1, "ok": 1, "notAttempted": 0, "failed": null,
 "manifestSlug": "project_knowledge/jarvis-memory-live/5/__manifest__",
 "manifestWritten": true, "endpoint": "http://127.0.0.1:3142"}   EXIT=0
```

Verification on :3142 (MCP read tools — §6's `gbrain get` CLI form is broken
by the same serve lock, B1):
- `get_page` entry → id 126, title `jarvis-memory-live: brain_graph.json`,
  compiled_truth carries verdict/think-gate, `uyp_*` frontmatter intact.
- `get_page` manifest → id 127, `KnowledgeVersion: 58e5ed12…`, `Entries: 1`,
  lists the entry slug (citations intact).
- brain census (list_pages, 100-per-call cap — see F4): 98–99 pages under
  epoch 2 (alive, morning session), 2 under epoch 5 (mine).

Revoke rehearsal (never previously executed by anyone):

```json
{"targets": ["project_knowledge/jarvis-memory-live/5/brain_graph.json"],
 "deleted": ["project_knowledge/jarvis-memory-live/5/brain_graph.json"],
 "deleteUnsupported": [], "tombstoneWritten": true}   EXIT=0
```

Invalidation contract, all as promised:
- deleted entry `get_page` → `page_not_found` (soft-delete hides it)
- manifest is now a tombstone: `uyp_revoked: True`, body "…was revoked…"
- version-hash query (matched the manifest pre-revoke) → **0 hits**
- `list_pages` epoch-5 → only the tombstone manifest remains; epoch-2 pages
  untouched (99)
- :8790 scoped epoch-5 (hash and tombstone-body terms) → 0 project blocks;
  plain query → family blocks present, 0 project (family brain regression
  clean throughout)

End state: epoch 5 left revoked (honest rehearsal outcome); recoverable 72h
via `restore_page` (present in surface) — not exercised.

### §5 — quota monitoring

- The publisher probe remains the working end-to-end signal (ran twice).
- `GBRAIN_HOME=… gbrain auth clients --usage` fails (B1, serve lock).
- Working alternative: `gbrain mcp admin clients --url http://127.0.0.1:3142`
  (admin token) lists clients/grants; no `--usage` equivalent over admin HTTP
  in 0.59. `mcp_request_log` is likewise inside the serve-locked DB.

## 4. Findings

- **F1 (material)**: scoped :8790 queries never return project blocks.
  Mechanism: `multi_brain_search()` merges all accessible brains and keeps a
  global top-10 by score. The project serve's hits score 0.16–0.40 —
  keyword-only, because the serve reports
  `_meta.retrieval.degraded: [{"stage":"embed_unavailable","reason":"no_provider"}]`
  (despite `LLAMA_SERVER_BASE_URL` being set identically to the family unit)
  — while family/public/personal hybrid-query expansion noise scores
  ~0.85–0.87 even for a 32-hex version-hash query that matches nothing
  there. Direct :3142 MCP `query` returns the correct hits (1 = the epoch-5
  manifest for the hash; 5 epoch-2 pages for "brain_graph verdict"). The
  runbook §4.4's "may return them" is technically true and operationally
  never. Publish/revoke at the brain layer is unaffected.
- **F2 (process)**: unrecorded morning session pre-executed §1/§2/§4.1–4.3
  and an epoch-2 publish at 10:47–14:56Z (see table above).
- **F3 (context, pre-existing)**: the family serve :3141 bounces every 5
  minutes in step with `gbrain-refresh.timer` (ExecMainStartTimestamp tracks
  timer fire times exactly; NRestarts=0, i.e. deliberate stop/start, journal
  silent). This is the CLI stop-serve refresh path the runbook's §0 warns
  about — living proof of the quota-exhaustion narrative. Not caused or
  touched by this run; :3141 health ok, serving family blocks to :8790
  throughout.
- **F4 (minor)**: `list_pages` caps at 100 slugs per call (limit=1000 still
  returned 100); census/monitoring code must paginate. `revoke()` is
  unaffected (slugs come from the local knowledge_root).
- **F5 (minor)**: `/synthesize` (the patch's second integration path) ran
  but could not complete its compose stage during this window — scoped
  attempt returned after 121 s with
  `{"answer": "(deep compose failed: Remote end closed connection without
  response)", "brain": "family", "blocks_considered": 12, "latency_ms": 120999}`
  i.e. retrieval through the patched code path executed cleanly (12 blocks,
  no filter error) and the failure is the local ollama (:11434) dropping the
  connection under the running full-index job's load. Re-run when the index
  job finishes to see a composed answer.

## 5. Runbook corrections needed (for folding back into GBRAIN_PROVISIONING.md)

1. Add a pre-flight "already provisioned?" section (unit exists, creds exist,
   routes entry present, patch applied, drop-in present) — F2 shows silent
   pre-execution happens; also refresh the "port 3142 is free" audit fact.
2. Replace every `GBRAIN_HOME=~/jarvis/gbrain/project_knowledge gbrain …`
   command (§2.3 `auth clients`/`auth rescope-client`, §5 `auth clients
   --usage`, §6 `gbrain get`) — they all fail with the serve's PGLite lock.
   Live-serve alternatives: `gbrain mcp admin clients --url http://127.0.0.1:3142`
   (admin token) for listing/rescoping decisions, and MCP read tools
   (`get_page`/`query`/`list_pages` with the writer creds) for verification.
3. Fix publisher invocations: `--url`, `--creds` and `--apply` are top-level
   flags and must precede the subcommand. All §3/§6 command lines as written
   exit 2 (`unrecognized arguments`).
4. Fix §3's verify command: needs `--url http://127.0.0.1:3142/mcp`
   (with `/mcp`) and `--harness generic` (the creds handoff records harness
   `generic`; either that or re-grant with `--harness uyp-indexer` and keep
   the doc).
5. §2.2/§2.3: state whether `--harness uyp-indexer` matters; the standing
   grant is harness `generic`, surface full (91 ops), which is what the
   publisher actually needs (`put_page`, `delete_page`, read tools).
6. §4.4 needs an honest addendum for F1: a scoped request is *allowed* to
   see project blocks but currently never does (global top-10 + degraded
   embeddings on :3142). Track two fixes: wire the embed provider on the
   project serve (env var is set but the serve reports `no_provider`), and
   consider brain priority/per-brain quota for requests carrying
   project+grant_epoch.
7. Note `list_pages` 100-per-call pagination (F4) wherever census/monitoring
   is described; §5's `--usage` recipe must switch to the admin HTTP path.
8. Document that `gbrain mcp verify` leaves a soft-deleted fixture page
   (72h recovery) and reports `status: partial` for machine clients (native
   harness probe not applicable) — partial-with-all-stages-passed is the
   success shape.

## 6. Final state after this run

- :3142 `gbrain-serve-project-knowledge` — active, healthy, NRestarts=0;
  brain contains the morning session's epoch-2 pages (98–99, alive) and my
  epoch-5 tombstone (revoked).
- :3141 `gbrain-serve-family` — healthy, untouched by me; keeps bouncing
  with the 5-min refresh timer (pre-existing, F3).
- :8790 `knowledge-service` — v3 patched, `KNOWLEDGE_PROJECT_BRAIN=1` live,
  felix granted; never restarted by me; fail-closed prefilter verified in
  both directions; family reads unchanged before/after.
- Publisher lane: `check` green; epoch-5 rehearsal left revoked; a few
  receipt bytes burned on the new principal (probe ×2, 2 puts, 1 delete,
  tombstone put, verify fixture put+delete) — quota exhaustion would surface
  as `probePut: rejected` in seconds, per design.
