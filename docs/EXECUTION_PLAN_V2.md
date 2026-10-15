# UnderstandYourProjects execution plan v2

**Status:** active plan; implementation is staged, not a production-complete claim
**Updated:** 2026-10-15
**Current UYP head:** `c47174e` (`feat(uyp): connect understanding and gbrain mirror lanes`)

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

These changes are local and tested. They do not claim a live HomeHub session,
Jetson deployment, or successful gBrain network mirror.

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
