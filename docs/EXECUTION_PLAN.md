# UnderstandYourProjects Execution Plan

**Status:** Review draft
**Scope:** Product, protocol, Jetson integration, Studio, Coding Agent access, and Jarvis-to-Jarvis groups
**Implementation rule:** This document is a plan and does not authorize changes to the protected HomeHub voice runtime.

## 1. Outcome and first release boundary

UnderstandYourProjects is a local project-knowledge system. A user-authorized computer, NAS, GitHub repository, or development device is connected to a Jarvis Agent Box. The box discovers projects, extracts deterministic structure, builds source-traceable knowledge, answers questions, shows project state in Jarvis Studio, and exposes a restricted interface for Coding Agents.

Independent Jarvis boxes can join an Agent Group. A group query is federated retrieval: each Jarvis searches its own local knowledge, applies its owner's grants and the group policy, and returns an attributed answer. It is not automatic database merging and it does not grant access to another owner's source files.

The first release targets code and text material:

- source code and configuration;
- Markdown, README, plain text, and technical papers;
- Git history metadata and fixed GitHub commits;
- project structure, relationships, summaries, evidence, and change state.

Image, video, CAD, arbitrary source-code execution, automatic source writes, and active-active shared databases are outside the first release.

## 2. Architectural invariants

The existing Jarvis HomeHub remains the authority for identity, device ownership, pairing, policy, revocation, and audit. UnderstandYourProjects adds a project-knowledge plane. It must reuse those foundations through adapters instead of creating a second identity or policy system.

The separation is:

```text
HomeHub control plane
  identity -> device ownership -> pairing -> policy -> revocation -> audit

UnderstandYourProjects knowledge plane
  source connectors -> indexing -> project knowledge -> retrieval -> Studio/MCP/groups
```

Voiceprint or other speaker identification remains useful. It identifies who is asking; HomeHub then resolves that identity to the user's grants and selected Jarvis/Workspace. The project-knowledge query is a new capability after identity and policy resolution, not a replacement for the existing voice flow.

One Jetson is the first Agent Box and can serve multiple authorized sources. Each source connector has its own capability and grant. If multiple Jetsons are added later, each retains a separate node identity, local queue, local knowledge store, and audit trail. They communicate through attributed federated queries; they do not initially write one shared mutable gbrain or SQLite database.

## 3. Agent-flow target

All entry points should converge on one permission-aware query path:

```text
Voice / Studio / Coding Agent / Jarvis Group
        |
        v
HomeHub identity and device context
        |
        v
Grant and policy resolution
        |
        v
Jarvis knowledge query coordinator
        |
        +--> local project/source retrieval
        +--> evidence and freshness validation
        +--> optional local model synthesis
        +--> response audit
        |
        v
Attributed answer with evidence and visibility state
```

For voice, the existing path remains:

```text
audio -> voiceprint/speaker identity -> HomeHub policy -> Agent Router
      -> project-knowledge tool (when the request concerns projects)
      -> evidence-aware answer -> existing TTS/output path
```

For a group query, the local Jarvis authenticates the remote Jarvis and sends only a bounded request. The remote Jarvis performs its own local authorization before searching. NandaTown is a transport adapter, not the final permission authority.

## 4. Repository target structure

The repository should evolve toward the following separation. Names are provisional until the protocol ADRs are approved.

```text
docs/
  PRD.md
  ARCHITECTURE.md
  THREAT_MODEL.md
  EVALUATION.md
  COLLABORATION.md
  ADR/
    0001-local-first-boundaries.md
    0002-source-connector-contract.md
    0003-one-primary-writer.md
    0004-agent-groups.md
  runbooks/

packages/
  knowledge-schema/
  protocols/
  security/

connectors/
  local-agent/
  nas/
  github/

services/
  source-gateway/
  index-coordinator/
  index-worker/
  query-api/

adapters/
  homehub/
  gbrain/
  nandatown/

apps/
  studio-web/

tests/
  conformance/
  fixtures/
  e2e/
  evaluation/
```

The repository may start with documentation, schemas, fixtures, and conformance tests before services are split into deployable processes. The adapter boundary is intentional: it prevents project-knowledge work from becoming a second HomeHub runtime.

## 5. Delivery phases and gates

### P0 — Product, safety, and protocol freeze (week 1)

Deliver:

- PRD, glossary, scope and non-goals;
- trust-boundary and data-flow diagrams;
- threat model;
- initial gold-question set (20–50 questions);
- ADRs for local-first processing, one primary writer, source connectors, and groups;
- acceptance matrix and rollback plan.

Gate G0 passes when every contributor can explain Source, Connector, Agent Box, Jarvis Node, Project, Evidence, Grant, and Agent Group; no unresolved permission flow is allowed into implementation. Do not begin complex UI or model work before G0.

### P1 — Jetson and protected-runtime baseline (week 1, parallel with P0)

Perform a read-only inventory of Jetson OS, CPU/RAM/GPU/swap, disks, services, ports, model processes, gbrain, knowledge-service, Agent Gateway, logs, data roots, and rollback paths. Record which processes own current identity, voice, policy, audit, and scheduling behavior.

Deliver `docs/baseline/<date>/`, `PROTECTED_RUNTIME.md`, and `INTERFACE_INVENTORY.md`. Add no new model or service until resource headroom and port ownership are measured. G1 requires an isolated service user, separate state/log directories, no protected process replacement, and a tested rollback.

### P2 — Shared schemas and connector contract (week 2)

Define versioned objects:

- `User`, `Workspace`, `JarvisNode`;
- `Source`, `Connector`, `SourceObject`, `Manifest`;
- `Project`, `KnowledgeItem`, `Relation`, `Evidence`;
- `Grant`, `Group`, `IndexJob`, `KnowledgeVersion`, `AuditEvent`.

Every knowledge record includes source, project, source version/epoch, stable object or path reference, content hash, parser/model versions, freshness, visibility, evidence class, and timestamps.

Minimum connector operations are `pair`, `source.register`, `source.manifest`, bounded `source.read`, `source.read_range`, `source.changes`, `source.reconcile`, `source.health`, and `source.revoke`.

G2 requires versioned schemas, idempotency keys, path/symlink escape rejection, file/type/size limits, capability-scoped reads, and revocation semantics before indexing begins.

### P3 — One read-only local Connector (weeks 3–4)

Implement a Mac/Linux connector for one user-selected directory. The user sees a manifest dry-run before approval. The connector watches changes but never writes indexing artifacts into the source directory and never executes commands received from the box.

Test empty directories, unsupported files, large files, malformed encodings, add/change/delete/rename, disconnect/reconnect, repeated manifests, path traversal, symlink escape, expired capability, and post-revocation reads. G3 requires that only approved files are readable and that every rejection is observable.

### P4 — Index coordinator and deterministic structure (weeks 4–6)

Implement a resumable state machine:

```text
DISCOVERED -> AUTHORIZED -> QUEUED -> RUNNING -> STAGED -> PUBLISHED
                         \-> BLOCKED / RETRY_WAIT / OFFLINE / REVOKED
```

Stage, validate, and atomically publish each `KnowledgeVersion`; a failed new version must not replace the last stable one. Start with one or two languages plus Markdown/README/configuration. Extract entries, symbols, imports, calls, modules, configuration, and project metadata without executing source code.

Classify results as `fact`, `structure`, or `inference`. Every result must cite a project, source object, version/epoch, and line range or symbol when applicable. G4 requires that parser failure preserves the old version with an explicit stale/failed state.

Background work is lowest priority: voice and real-time interaction, foreground query, small incremental update, then deep batch analysis. Initially allow at most one deep analysis task and pause it on resource thresholds.

### P5 — Knowledge API and Jarvis Studio (weeks 6–7)

Provide source/device, project, project-detail, index-job, evidence, timeline, privacy/audit, and group views. A project page shows goals, entry points, modules, relations, recent changes, knowledge version, freshness, parse failures, reusable candidates, and evidence.

Expose provisional read-only APIs such as `/sources`, `/projects`, `/projects/:id`, `/knowledge/search`, `/knowledge/evidence/:id`, `/index/jobs`, `/sources/:id/reconcile`, `/grants/revoke`, and `/health`. Exact names require an ADR.

Studio must distinguish `current`, `stale`, `partial`, `offline`, `failed`, `revoked`, and `unsupported`; a loaded page is not evidence of synchronization. G5 requires one visible project card and one visible failure/offline path.

### P6 — Search, reuse, and Coding Agent interface (weeks 7–8)

The query path is:

```text
identity -> grants -> metadata/structure filters -> keyword/vector retrieval
         -> evidence validation -> bounded model synthesis -> audit
```

Initial read-only tools are `project.search`, `project.get`, `project.related`, `source.locate`, `source.read_evidence`, and `index.status`. Raw reads require an explicit grant, bounded file/range, and audit record. No shell, build, test, arbitrary path read, or source write is exposed.

G6 requires that a Coding Agent in an empty sandbox can locate a prior project and obtain cited evidence without gaining unrestricted device access.

### P7 — End-to-end longitudinal slice (week 8)

Demonstrate: choose directory -> pair -> manifest dry-run -> approve -> Jetson indexing -> project card -> evidence-backed query -> Coding Agent read -> change one file -> incremental update -> source offline/stale -> revoke -> denied query.

Capture logs, screenshots, hashes, queue state, resource samples, and failure paths. API success alone is not acceptance.

### P8 — Incremental updates and one additional source (weeks 9–10)

Add durable change processing, tombstones, rename handling, manifest reconciliation, parser-version rebuild, pause/resume, and offline recovery. Choose exactly one additional connector for the milestone: read-only NAS or fixed-commit GitHub.

G7 requires affected-object recomputation, no ghost results after deletion, idempotent recovery, reproducible fixed-commit reads, and a long-running stability test (target: seven days).

### P9 — Same-user multiple Jarvis boxes (weeks 10–11)

Support an owner group containing two independent Jarvis Nodes. The user can switch nodes and issue a federated query while retaining node-specific identity, source grants, queues, freshness, and audits. Offline nodes do not block local results.

G8 requires attributed results containing producing Jarvis, project, knowledge version/epoch, freshness, and visibility. No shared mutable gbrain is introduced.

### P10 — Cross-user Agent Groups (weeks 12–13)

Add explicit group membership, source/project scope, audience, TTL, revocation, share policy, nonce, and audit. A remote Jarvis validates the request and applies its own local grants before searching. Default responses are summaries and evidence references, not raw source or full vector/database transfer.

G9 requires a successful authorized query and a failed post-revocation/expiry query, including cache invalidation and no leakage of private project names or paths.

### P11 — MIT/Harvard pilot (week 14 onward)

Use 3–5 contributors and approved/sanitized repositories. Each participant pairs a connector, authorizes one project, explores it, asks real questions, validates an incremental change, executes a group query, and revokes access. Any privacy leak is a release blocker.

## 6. Evaluation and evidence

The first evaluation set contains 20–50 real or carefully constructed questions across at least three projects. Track:

- manifest completeness for authorized supported files;
- project/file localization accuracy;
- citation and evidence coverage;
- unsupported-claim rate;
- incremental update delay and affected-object ratio;
- unauthorized-read and post-revocation counts (target zero);
- queue latency, RAM/swap/GPU use, and foreground-query latency;
- offline/stale correctness;
- group attribution, TTL, and revocation behavior;
- continuous-run stability.

Evidence must be labeled as one of `unit`, `integration`, `offline`, `Jetson`, `Studio`, `group`, or `pilot`. A mock Connector, HTTP 200, or offline test cannot be presented as live Jetson or user-visible acceptance.

## 7. Collaboration and change control

Recommended workstreams are Core schemas/security, Connectors, Index/Research, Studio, and Federation. One Integrator owns live Jetson changes, protected interfaces, deployment, keys, and rollback. Contributors work with fixtures and isolated credentials; production Jetson credentials and HomeHub private keys are never placed in the repository.

Every PR describes:

- data egress and file types;
- permission or identity impact;
- evidence level and test commands;
- Jetson resource cost;
- protected-runtime impact;
- rollback path;
- whether source data leaves the local box.

Weekly review records scope, security, freshness, resource use, reproducibility, rollback, limitations, and a decision of `Pass`, `Conditional`, or `Block`.

## 8. Red lines for the first release

- Do not rewrite or replace the HomeHub voice/runtime chain.
- Do not create a second identity, policy, revocation, or audit authority.
- Do not use speaker identity as a substitute for source/project grants.
- Do not create active-active shared writes across Jetsons.
- Do not persist a complete source mirror by default.
- Do not write index artifacts into source directories.
- Do not execute arbitrary project code.
- Do not expose uncited model guesses as facts.
- Do not allow revoked cache entries to answer new queries.
- Do not treat NandaTown as the final authorization authority.
- Do not claim current knowledge when a source is offline or stale.
- Do not add image/video/CAD processing to the Jetson MVP.

## 9. First two weeks for review

### Week 1

1. Approve this plan, glossary, scope, and the four initial ADRs.
2. Perform the read-only Jetson baseline and protected-runtime inventory.
3. Select one representative code/text project and write the first gold questions.
4. Define Source, Grant, Evidence, KnowledgeVersion, and IndexJob schemas.
5. Assign the Integrator and the five workstreams.

### Week 2

1. Implement schema fixtures and connector conformance tests.
2. Implement pairing and manifest dry-run only.
3. Add path, symlink, type, size, capability, and revoke tests.
4. Define the knowledge query envelope and evidence response.
5. Review the dry-run using real Mac-to-Jetson evidence before any deep indexing.

The next go/no-go decision is whether to proceed from P2 to P3. It should be made from the protocol, security, resource, and source-boundary evidence—not from the amount of code written.
