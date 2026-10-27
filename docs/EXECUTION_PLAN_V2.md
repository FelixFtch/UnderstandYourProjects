# UnderstandYourProjects execution plan v2

> **2026-10-27：新方向已批准并开始实施。** 当前目标是 Pi 上的 HomeHub +
> OpenClaw + gBrain，以及原生 iPhone / macOS App。以
> [Pi 原生家庭迁移说明](PI_NATIVE_HOME_TRANSITION_20261027.md)及其中链接的 HomeHub 架构/计划为准。
> 下文保留为旧 UYP/Jetson 路线的历史记录，其中的“current / active / accepted”
> 和部署描述均属于原记录日期，不代表本轮现场状态。Jetson 与 XVF3800 不改动。

**Status:** active plan; implementation is staged, not a production-complete claim
**Updated:** 2026-10-16
**Current UYP head:** `9e3585e` (`fix(uyp): enforce project scoped retrieval`)

This plan turns `TARGET_ARCHITECTURE_V2.md` into bounded work packages. It
assumes the existing Connector, UA bridge, KnowledgeItem store, Query API,
Studio, HomeHub runtime, Langflow artifacts, and gBrain publisher are reused.
No work package may create a second identity, permission, device-action, or
live-execution authority.

## Invariants and ownership

| Concern | Owner | UYP responsibility |
| --- | --- | --- |
| Identity, device ownership, grants, revocation, audit | HomeHub | consume the validated AccessContext and preserve its epochs |
| Connector registration and source manifest | HomeHub/Connector | read the manifest and retain source/device scope; never mint a grant |
| Project discovery, UA graph, KnowledgeItems, evidence, freshness | Agent Box/UYP | index, version, filter, cite, and expose bounded projections |
| Semantic project mirror | dedicated gBrain project brain | optional asynchronous mirror; never the canonical source or ACL |
| Langflow | HomeHub live flow specification | visualization/replay of the same turn bundle, never a second runtime |
| NandaTown | discovery and transport | bounded attributed envelopes only; receiver performs local authorization |

## Work packages

### 0. Delivered baseline

- `552fca3` records the accepted target architecture and is pushed to
  `origin/main`.
- `c47174e` adds the first implementation tranche:
  - request-scoped HomeHub bearer forwarding in Studio;
  - the URL-addressable `#/understanding` entry point over the existing UA
    graph and ProjectStudio;
  - caller-scoped Studio snapshot, sources, graph, jobs, connectors, and
    evidence endpoints;
  - registered-folder hierarchy (`folder_tree`) without inventing graph
    directory nodes;
  - durable post-publication gBrain mirror queue with bounded retry state;
  - source epoch and evidence-anchor metadata in mirror pages and safe Query
    API status projection.

These changes are tested. The HomeHub runtime Intent Gate is deployed to the
Jetson voice/studio runtime at commit `720388c`, and the UYP mirror worker is
deployed at commit `7168898` with a user-level timer. A live gBrain network
publication is still not claimed until a dedicated project brain accepts a
scoped item and manifest.

### 1. Intent Gate and fast paths — HomeHub runtime owner

Add a small typed gate after identity/policy and before expensive retrieval.
It returns `action`, `understand`, `project_query`, `memory_query`,
`agent_query`, `chat`, or `clarify`, with confidence and a latency trace.

Reuse the current HomeHub ActionEnvelope and read-back route. High-confidence
light/sensor/scene operations go directly to the governed action route; normal
chat skips the gBrain preflight; explicit memory requests still use gBrain;
project questions use UYP/UA first. Low confidence falls back to the existing
router and asks one bounded clarification when needed.

Required tests in `jarvis-homehub`:

1. ordinary chat does not call the gBrain `:8790` preflight;
2. `turn on kitchen light` uses the existing action route and read-back;
3. an explicit memory question uses gBrain;
4. denied/revoked actions still fail through HomeHub;
5. Studio, voice, iPhone, and group calls produce the same route trace.

### 2. Durable UA and project knowledge lane — UYP owner

Keep the current `IndexJob -> Connector manifest -> KnowledgeItems -> UA
bridge -> atomic publication` path. Add or finish:

- a timer/systemd worker that drains the durable gBrain mirror queue without
  blocking local publication;
- explicit full reconciliation for deletions and incremental waves for
  additions/modifications;
- source epoch, KnowledgeVersion, git commit, and evidence anchor propagation;
- revocation/grant-epoch invalidation or tombstone of mirror pages and answer
  caches;
- a visual Understanding workspace with project/folder tree, UA graph/layers/
  tour, evidence inspector, IndexJob state, freshness, and mirror state.

The UYP registry remains the folder hierarchy authority; the UA graph remains
the file/symbol/relation authority. A nested folder gets its own project only
when it is separately registered and authorized.

### 3. gBrain contract and retrieval

Use the existing `project_knowledge` namespace as a secondary semantic mirror.
Publish item pages first and a complete-version manifest last. Every result
must carry project, relative path, KnowledgeVersion, source epoch, and grant
epoch; UYP rehydrates exact evidence before an answer or share. Never publish
raw source bytes or family-brain data.

Acceptance requires a real dedicated project brain, a successful mirror,
scoped retrieval, and a grant-epoch revoke that makes the same page/citation
unusable. A queue record alone is not acceptance.

### 4. Studio and Langflow parity

Studio remains the user-facing conversation and Understanding surface. The
Langflow canvas must be generated from the live HomeHub flow/spec and must
show the same branch, skipped nodes, tool arguments, evidence, receipt, and
latency as the turn bundle.

The existing Mac launcher must detect a canonical artifact mismatch and offer
an explicit re-import of the flow artifact. It must not silently keep an old
database flow by name, and it must not create a second execution path. Validate
typed source handles, JSON handles, and `selected_output` before import.

### 5. Shared Agent Identity & Messaging skill

Specify one reusable protocol for Miku, Felix's Jarvis, Robin's Jarvis, and
other enrolled agents:

`identity.describe`, `identity.verify`, `directory.discover`,
`contact.invite/accept`, `message.send/receive`, `group.list/create/invite`,
and `audit.reference`.

HomeHub issues the identity card and remains the authority. NandaTown only
discovers/transports public metadata and bounded envelopes. The receiver must
verify expiry, audience, nonce, contact/group policy, and local grants before
retrieval. No shared skill can make an unregistered agent trusted.

### 6. Live Jetson and P7 acceptance

Only after packages 1–5 pass locally:

1. deploy the exact UYP commit and worker to Jetson;
2. obtain a real HomeHub AccessContext and Connector grant;
3. authorize one folder and run an IndexJob;
4. verify UA graph, KnowledgeItems, evidence, folder tree, and Studio session;
5. mirror and search the dedicated gBrain brain;
6. revoke the grant and verify search, evidence, mirror, and group sharing are
   denied/tombstoned;
7. repeat one safe device action through voice, Studio, iPhone, and group chat
   only in the HomeHub-owned route;
8. verify one bounded Jarvis-to-Jarvis question with attribution and audit.

The acceptance record must include commit, Jetson service status, HomeHub
grant/session epoch, source epoch, KnowledgeVersion, request IDs, read-back,
and revoke evidence. A localhost demo, stale Studio card, or queue record does
not substitute for this gate.

#### 6.1 Deployment evidence (2026-10-15)

The Jetson deployment used the existing Cloudflare SSH alias and preserved a
rollback snapshot at:

`/home/jetson/dev/uyp/backups/mirror-worker-20261015-201616`

Verified after deployment:

- `uyp-query-api.service`: active;
- `uyp-gbrain-mirror.timer`: active and enabled;
- Query API health: `ok=true`, AccessContext projection available;
- Connector registry: 3 connectors and 4 active grants;
- Knowledge projection: 4,218 items;
- mirror worker: exited successfully with an empty queue.

This proves deployment and safe scheduling only. It does not prove a remote
gBrain publish, device mutation, or revoke acceptance.

#### 6.2 Production acceptance evidence (2026-10-16)

The first real authorized acceptance run used the existing Mac Connector grant
and the already-enrolled Jetson; it did not change pairing or add a new QR
flow. Durable job `accept-202610160025` reached `published` after the existing
UA bridge analyzed `jarvis-memory-live` locally. The published projection
contained 120 KnowledgeItems, a 634-node/829-edge graph, four layers, source
epoch `56668491db5fd2163c71f7bf2d6e1214`, and HomeHub grant epoch `52`.

The dedicated gBrain writer check passed against the existing
`project_knowledge` serve on Jetson `:3142` (the family brain and read-only
`:8790` were not used). The mirror record reached `succeeded`; its manifest
reported 120 entries, `uyp_revoked=false`, and the same KnowledgeVersion and
grant epoch. A scoped UYP search returned three citations, all from
`project:jarvis-memory-live`, with a HomeHub audit id.

The revoke path was then exercised through the real HomeHub route. HomeHub
revoked the project grant and advanced the context epoch to `53`; the mirror
worker fail-closed with `homehub_grant_epoch_mismatch`. The gBrain revoke
operation deleted the epoch-52 pages and wrote a manifest with
`uyp_revoked=true`, `uyp_entry_count=0`, and `KnowledgeVersion: revoked`.
The same scoped UYP search returned `Not in the indexed projects.` with zero
citations. A fresh HomeHub grant was issued afterward (epoch `54`), the
renewal keep-list backup was restored, and the project search recovered with
three in-scope citations. A post-regrant IndexJob
`job-cddaad5f78e54e83bdc144c58499dc15` then reached `published` with
KnowledgeVersion/source epoch `47fe1cc96493f770fdb7dd377df4a81f`; its mirror
`mirror-33dd5e38b6b252099cff3bd2cb0f9ccf` succeeded and the epoch-54 manifest
reported `uyp_revoked=false` with 121 entries.

This closes the real Connector -> IndexJob -> UA -> KnowledgeItem -> gBrain ->
scoped search -> HomeHub revoke/tombstone loop. The remaining acceptance gates
are the same-action-route proof for group device control and the second-party
NandaTown P7 federation; the current voice/Studio/iPhone route audit is
documented separately. The Studio companion BFF also accepted non-mutating
`home.light.turn_on` and `home.light.turn_off` dry-runs for both registered
`homeDeviceId` values through the governed local fallback. No physical light
mutation was performed in this run. Group device control and NandaTown P7
remain explicitly unaccepted until a real group context and a second signed
Jarvis participant are available.

## Parallel ownership and sequencing

| Lane | Parallel owner | Depends on | Output |
| --- | --- | --- | --- |
| Intent/latency | HomeHub runtime agent | none; preserve ActionEnvelope | typed gate, fast-path tests, route trace |
| UA/index/mirror | UYP agent | current c47174e | worker, revoke hook, incremental tests |
| Studio/Langflow | dashboard/HomeHub agent | canonical flow artifacts | Understanding UX and explicit re-import validator |
| Identity/federation | protocol agent | HomeHub identity contract | skill doc, envelope validators, NandaTown mapping |
| Live acceptance | integration owner | all four lanes | Jetson/P7 evidence bundle |

Each lane may inspect in parallel, but live device mutations, HomeHub grants,
revocation, and Jetson deployment stay with one integration owner. Merges are
explicit-file commits; secrets and source outputs never enter Git.

## Definition of done

The project is complete only when the eight completion gates in
`TARGET_ARCHITECTURE_V2.md §10` have live evidence. Until then, statuses must
remain explicitly `partial`, `offline`, `stale`, `graph-only`, `queued`, or
`revoked` as appropriate.
