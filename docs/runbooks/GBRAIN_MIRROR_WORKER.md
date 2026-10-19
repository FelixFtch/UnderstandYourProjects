# gBrain mirror worker

The UYP `IndexJob` publishes the local KnowledgeVersion and UA projection
first.  It then writes a small durable record under
`$UYP_STATE_ROOT/gbrain-mirrors/`.  The local publish path never waits for
gBrain.  `gbrain_mirror_worker.py` is a separate one-shot process for the
optional `project_knowledge` gBrain projection.

## Run one pass

```bash
UYP_STATE_ROOT=~/dev/uyp/state \
UYP_GBRAIN_URL=http://127.0.0.1:3141 \
UYP_GBRAIN_CREDS=~/.config/uyp/project-knowledge-writer.json \
python3 services/indexer/src/gbrain_mirror_worker.py \
  --state-root ~/dev/uyp/state \
  --access-context ~/.config/uyp/access-context.json \
  --max-jobs 1
```

The configured `UYP_HOMEHUB_ACCESS_CONTEXT_URL` takes precedence over the
local projection file.  If HomeHub cannot provide a valid context, the pass
returns `homehub_access_context_unavailable`, performs no gBrain write, and
leaves queued records for the next timer tick.  This is deliberate: a
temporary policy-plane outage must not be interpreted as a revocation.

The worker compares each record's opaque `grantEpoch` and `projectId` with
the fresh HomeHub context before publishing.  A changed epoch or missing
project scope moves the record to `blocked` and prevents old knowledge from
being published after a revoke.  Remote pages already published under that
epoch still require the explicit HomeHub-authorized `gbrain_publisher.py
revoke` operation; the worker never mints a grant or silently erases remote
data.

## Inspect queue state

```bash
python3 services/indexer/src/gbrain_mirror_worker.py \
  --state-root ~/dev/uyp/state --status
```

The status projection intentionally omits `knowledgeRoot`, endpoint, and any
credential.  Phases are `queued`, `running`, `retry_wait`, `succeeded`,
`failed`, and `blocked`.  `retry_wait` uses bounded exponential backoff;
missing endpoint/credentials are configuration blockers, while transport and
serve errors are retried up to the record's `maxAttempts`.

## Jetson timer

Install `jetson/systemd/uyp-gbrain-mirror.service` and
`uyp-gbrain-mirror.timer` only after the dedicated gBrain writer principal and
`project_knowledge` serve have been provisioned.  Put the URL and credential
path in the operator-owned (untracked) file:

```text
~/.config/uyp/gbrain-mirror.env
UYP_GBRAIN_URL=http://127.0.0.1:3141
UYP_GBRAIN_CREDS=%h/.config/uyp/project-knowledge-writer.json
```

The repository contains no endpoint credential or HomeHub token.  The systemd
unit is safe to install before provisioning: without a valid AccessContext it
does a no-op, and without an explicit gBrain endpoint the records become a
visible configuration block rather than writing to the family brain.

## FAILED-queue governance (2026-10-19)

Phases today also include `terminal_expired` (the ADR lane for
grant-epoch rotation; never retried, never re-enqueued).  The `failed`
lane is governed by `services/indexer/src/gbrain_mirror_requeue.py` —
classify first, requeue only what is still CURRENT:

```bash
# dry-run triage (default; writes nothing)
python3 services/indexer/src/gbrain_mirror_requeue.py \
  --state-root ~/dev/uyp/state

# actually requeue the retryable class (one operator requeue per job
# lifetime; --max-requeue caps the batch; manifest under
# <state_root>/gbrain-mirror-requeue/)
python3 services/indexer/src/gbrain_mirror_requeue.py \
  --state-root ~/dev/uyp/state --execute

# undo the last execute (only jobs the worker has not already acted on)
python3 services/indexer/src/gbrain_mirror_requeue.py \
  --state-root ~/dev/uyp/state --rollback
```

Rules the tool enforces (all decided against LIVE state — the HomeHub
access context plus `GET /api/uyp/grants`):

- requeue ONLY `retryable`: transport-class failures (timeout /
  connection / HTTP / serve rejection incl. `queue_capacity`) whose
  grant epoch still equals the LIVE access context's epoch (the same
  comparison the worker makes at run time), whose project and source
  are still in scope (context AND active ledger row), whose
  `knowledgeVersion` is still the project's newest, with no
  succeeded/queued duplicate, and no prior operator requeue;
- never requeue: old-epoch jobs (`terminal_expired`), superseded
  versions/duplicates, revoked or scope-narrowed projects
  (`policy_blocked`), publisher precondition failures
  (`configuration_error` — fix provisioning instead), and anything
  already operator-requeued once (`permanent_failed`: capacity failures
  must not retry forever);
- audit is append-only: `lastError` is preserved, the `events` counter
  advances, and the rollback manifest snapshots prior
  phase/attempts/nextAttemptAt;
- the worker re-validates epoch and scope at run time, so even a
  requeued job that outlives its grant moves straight back to
  `terminal_expired` — revoked content can never flow back.
