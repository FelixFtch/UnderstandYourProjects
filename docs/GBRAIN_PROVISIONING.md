# gBrain `project_knowledge` provisioning runbook (Jetson)

Owner-facing steps to provision the dedicated brain that the UYP publisher
(`services/indexer/src/gbrain_publisher.py`) writes to. Everything runs on
the Jetson unless a step says otherwise. Read the whole page once before
running anything; the "do NOT" box first.

Audited facts this runbook is built on (2026-10-10): gbrain 0.59.0.0 at
`~/.bun/bin/gbrain`; family serve = systemd `gbrain-serve-family.service`
on 127.0.0.1:3141; embeddings via `llama-embed.service`
(`LLAMA_SERVER_BASE_URL=http://127.0.0.1:8108/v1`, nomic-q8);
knowledge-service = systemd `knowledge-service.service` on 127.0.0.1:8790;
serve admin token at `~/jarvis/gbrain/.serve_admin_token` (0600); port
3142 is free.

## 0. Non-negotiables

**Do NOT reuse the family writer at 127.0.0.1:3141 — for reads or writes —
and do NOT point the UYP publisher at it.**

Evidence (why this is a hard rule, not a preference):

- gbrain 0.51+ serves enforce a **per-principal receipt-byte quota**. The
  family brain's writer quota was burned through around 2026-09-21 by the
  5-minute `gbrain-refresh.timer` doing no-op force-puts; the serve answers
  `queue_capacity: Write capacity exhausted` (recorded in the
  2026-09-27 rework comment in `~/jarvis/gbrain/refresh_brains.sh`).
- Those failures were **invisible for a week** because `mcp_ingest.py`
  misread `result.isError` responses as success (fixed 2026-09-27; it now
  exits non-zero). A second writer on the same principal would repeat the
  failure class with a different blast radius.
- There is **no upstream quota admin yet** ("Until upstream ships quota
  admin", same comment): an exhausted principal cannot be refilled, only
  replaced. Burning family's lane for project knowledge would force the
  family refresh onto the CLI stop-serve path permanently.

Second rule: **knowledge-service :8790 stays a read facade.** It has no
page-write endpoint and none is being added; the publisher speaks MCP to a
dedicated serve, and :8790 only searches (after section 4).

Third rule: **separate brain = separate PGLite dir = separate quota.** The
`project_knowledge` brain is disposable: it is a mirror of the UYP output
store (`~/dev/uyp/output/<project>/` on the indexer host), never a source
of truth.

## 1. Create the brain and its serve (one-time)

```bash
ssh jetson-us-cf

# 1.1 Brain directory + init (PGLite single-file engine, like the others)
mkdir -p ~/jarvis/gbrain/project_knowledge
GBRAIN_HOME=~/jarvis/gbrain/project_knowledge ~/.bun/bin/gbrain init --pglite

# 1.2 systemd unit — mirrors gbrain-serve-family.service, new port + brain
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/gbrain-serve-project-knowledge.service <<'UNIT'
[Unit]
Description=gbrain MCP serve (project_knowledge brain, UYP publisher)

[Service]
Environment=PATH=/home/jetson/.bun/bin:/usr/bin:/bin
Environment=GBRAIN_HOME=/home/jetson/jarvis/gbrain/project_knowledge
Environment=LLAMA_SERVER_BASE_URL=http://127.0.0.1:8108/v1
Environment=OPENAI_BASE_URL=http://127.0.0.1:11434/v1
Environment=OPENAI_API_KEY=ollama
ExecStart=/bin/bash -c "exec env GBRAIN_ADMIN_BOOTSTRAP_TOKEN=$(cat /home/jetson/jarvis/gbrain/.serve_admin_token) gbrain serve --http --port 3142"
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now gbrain-serve-project-knowledge
curl -s http://127.0.0.1:3142/health || systemctl --user status gbrain-serve-project-knowledge --no-pager
```

The serve holds the brain's exclusive PGLite lock from here on — that is
intended (it is why the read route in 1.5 is mandatory: the CLI cannot
read a serve-held brain, it fails closed to "brain dark").

## 2. Writer client, creds, slug fence

```bash
# 2.1 Creds directory (0600 convention, same as the family writer)
mkdir -p ~/jarvis/gbrain/.creds && chmod 700 ~/jarvis/gbrain/.creds

# 2.2 Grant a DEDICATED writer principal, fenced to the namespace.
#     --bound-slug-prefixes is a DIRECT WRITE FENCE: every put_page /
#     delete_page from this client must target project_knowledge/* or the
#     serve rejects it. The fence is the boundary; the profile only shapes
#     the tool list.
GBRAIN_ADMIN_BOOTSTRAP_TOKEN=$(cat ~/jarvis/gbrain/.serve_admin_token) \
  ~/.bun/bin/gbrain mcp grant uyp-indexer \
    --harness uyp-indexer --profile memory-writer \
    --url http://127.0.0.1:3142 \
    --bound-slug-prefixes project_knowledge/ \
    --credentials-out ~/jarvis/gbrain/.creds/project_knowledge.json
chmod 600 ~/jarvis/gbrain/.creds/project_knowledge.json
```

Notes:
- Deliberately NO `--source`: pages go into the default source so
  `gbrain query` (and therefore knowledge-service) can see them. A
  dedicated non-federated source would hide them from every read.
- The creds json carries `client_id`/`client_secret` (plus serve metadata);
  the publisher only uses those two keys.

```bash
# 2.3 Widen the writer surface so revoke() can actually delete.
#     delete_page is NOT in the starter/memory-writer surface — without
#     this step, publisher revoke() falls back to tombstone-only and
#     --check refuses to probe quota (it will not write what it cannot
#     clean up). The slug fence still bounds every write to
#     project_knowledge/*.
GBRAIN_HOME=~/jarvis/gbrain/project_knowledge ~/.bun/bin/gbrain auth clients
GBRAIN_HOME=~/jarvis/gbrain/project_knowledge \
  ~/.bun/bin/gbrain auth rescope-client <uyp-indexer-client-id> --surface full
```

```bash
# 2.4 (Mandatory) read route for knowledge-service. Without this entry the
#     service cannot search the serve-held brain (CLI path is locked out)
#     and the brain is dark: fail-closed empty, never an error.
cp ~/jarvis/gbrain/serve_routes.json ~/jarvis/gbrain/serve_routes.json.bak-$(date +%Y%m%d)
python3 - <<'EDIT'
import json, os
path = os.path.expanduser("~/jarvis/gbrain/serve_routes.json")
routes = json.load(open(path))
routes["project_knowledge"] = {"url": "http://127.0.0.1:3142",
                               "creds": "~/jarvis/gbrain/.creds/project_knowledge.json"}
json.dump(routes, open(path, "w"), indent=2)
EDIT
cat ~/jarvis/gbrain/serve_routes.json   # expect family + project_knowledge
```

The route is read per request (`_serve_route` reloads the file), so no
service restart is needed.

## 3. Validate from the Mac (before anything else uses it)

```bash
# From the UYP repo (any branch with gbrain_publisher.py):
python3 services/indexer/src/gbrain_publisher.py check \
  --url http://127.0.0.1:3142 \
  --creds ~/jarvis/gbrain/.creds/project_knowledge.json   # via ssh/scp of the creds, or run on the Jetson
```

`check` proves, in order: writer OAuth creds work; the principal's honest
tool surface (`tools/list`) shows `put_page` and `delete_page`; and quota
headroom is real, via one tiny put+delete round-trip on
`project_knowledge/__probe__` (a few receipt bytes — the same signal the
family timer burned, but bounded and self-cleaning). It exits non-zero and
prints a JSON verdict on any failure; it never writes real payload, and it
skips the probe entirely when `delete_page` is not visible so it cannot
leave litter. On the Jetson side, `gbrain mcp verify --client <id>
--harness uyp-indexer --url http://127.0.0.1:3142 --credentials-file
~/jarvis/gbrain/.creds/project_knowledge.json` is the second opinion.

Then a full dress rehearsal without going live:

```bash
python3 services/indexer/src/gbrain_publisher.py publish \
  --knowledge-root <output-dir-of-a-project> --project-id <id> \
  --version <sourceEpoch> --grant-epoch <epoch>          # DRY RUN by default: prints the plan only
```

## 4. Make :8790 able to see it (env-gated, default off)

This is the step that changes a production service; do it last.

1. Apply `patches/knowledge-service-project-prefilter.patch` (from this
   repo, `feat/gbrain-launch-prep`) to `~/jarvis/gbrain/knowledge-service.py`.
   Default behavior is byte-identical until the env gate in step 3:

   ```bash
   # from the Mac:
   scp patches/knowledge-service-project-prefilter.patch jetson-us-cf:~/jarvis/gbrain/
   ssh jetson-us-cf
   cd ~/jarvis/gbrain
   cp knowledge-service.py knowledge-service.py.bak-uyp
   git apply --check knowledge-service-project-prefilter.patch   # dry run
   git apply knowledge-service-project-prefilter.patch
   python3 -m py_compile knowledge-service.py && echo compiles    # sanity
   ```

   The patch header carries the full reasoning; in short: env-gated
   `ALL_BRAINS` registration (default off), a fail-closed
   `project_scope_filter()` wired into `/query` and both `/synthesize`
   retrieval paths, and no new error surfaces.
2. Grant brain access per member (owner decision; `owner: system` is the
   bypass in `grant_access`):

   ```bash
   curl -s -X POST http://127.0.0.1:8790/permissions/grant -d '{
     "brain": "project_knowledge", "owner": "system",
     "grantee_type": "member", "grantee_id": "felix"}'
   ```

   Being listed in `ALL_BRAINS` exposes nothing by itself —
   `get_accessible_brains()` still requires a non-revoked `brain_grants`
   row for every brain, so ungranted members see nothing.
3. Enable the gate in the unit and restart:

   ```bash
   systemctl --user edit knowledge-service
   #   [Service]
   #   Environment=KNOWLEDGE_PROJECT_BRAIN=1
   systemctl --user restart knowledge-service
   curl -s http://127.0.0.1:8790/health
   ```

4. Confirm the prefilter: a plain `POST /query` (no project/epoch params)
   must return ZERO `project_knowledge/*` blocks; a query with matching
   `project` + `grant_epoch` params may return them; a revoked epoch never
   does (tombstone `uyp_revoked: true`). Fail-closed means a mismatch
   yields empty results, never an error that reveals what exists.

## 5. Quota monitoring

- Run publisher `check` at the start of every publish window; treat
  `probePut: rejected` as page-worthy (that is the exact family failure
  signature, now visible in seconds instead of a week).
- `GBRAIN_HOME=~/jarvis/gbrain/project_knowledge ~/.bun/bin/gbrain auth
  clients --usage` shows per-client op counts and last-seen; the serve's
  `mcp_request_log` table is the audit trail.
- There is no quota refill admin yet. If the writer principal is ever
  exhausted: stop, grant a NEW principal (new creds file), update
  `serve_routes.json`, re-run `check`. Never switch the publisher to the
  family principal.

## 6. First live publish and revoke rehearsal

```bash
# Small project first. Order matters: check -> dry run -> apply.
python3 services/indexer/src/gbrain_publisher.py check --url http://127.0.0.1:3142 --creds <creds>
python3 services/indexer/src/gbrain_publisher.py publish --knowledge-root <dir> \
  --project-id <id> --version <v> --grant-epoch <e>              # plan
python3 services/indexer/src/gbrain_publisher.py publish --knowledge-root <dir> \
  --project-id <id> --version <v> --grant-epoch <e> --apply --url http://127.0.0.1:3142 --creds <creds>

# Verify on the Jetson (read tools only):
GBRAIN_HOME=~/jarvis/gbrain/project_knowledge \
  ~/.bun/bin/gbrain get "project_knowledge/<id>/<e>/<relpath>"

# Revoke rehearsal (deletes exactly one epoch's subtree + tombstones it):
python3 services/indexer/src/gbrain_publisher.py revoke --project-id <id> \
  --grant-epoch <e> --knowledge-root <dir>                       # plan
python3 services/indexer/src/gbrain_publisher.py revoke --project-id <id> \
  --grant-epoch <e> --knowledge-root <dir> --apply --url http://127.0.0.1:3142 --creds <creds>
```

Soft-deleted pages stay recoverable for 72h (`restore_page` / CLI); hard
purge is trusted-local-CLI only. If a grant revocation requires immediate
erasure, run the CLI purge on the Jetson in the same window.

## 7. Rollback

```bash
systemctl --user disable --now gbrain-serve-project-knowledge   # stop the serve
curl -s -X POST http://127.0.0.1:8790/permissions/revoke -d '{"brain":"project_knowledge","owner":"system","grantee_type":"member","grantee_id":"felix"}'
# remove the KNOWLEDGE_PROJECT_BRAIN=1 drop-in and restart knowledge-service
# the brain dir is a disposable mirror: rm -rf ~/jarvis/gbrain/project_knowledge
# restore serve_routes.json from the .bak-* copy made in 2.4
```

No UYP-side rollback is needed beyond not running `--apply`: the publisher
is dry-run by default and has no configured endpoint unless `--url` /
`UYP_GBRAIN_URL` is supplied explicitly.
