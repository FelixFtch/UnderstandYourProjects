# UnderstandYourProjects

UnderstandYourProjects is a local project-knowledge management system for the era of capable coding agents.

It connects user-authorized computers, NAS storage, GitHub repositories, and development devices to a dedicated **Jarvis Agent Box**. The box continuously discovers projects, extracts structure, builds semantic understanding, maintains a visual project map, answers questions with source evidence, and incrementally updates its knowledge as projects change.

It also lets independent Jarvis boxes join groups and communicate. Each Jarvis searches its own local project knowledge and shares only the information permitted by its owner and the group. This creates a privacy-aware project knowledge network without requiring participants to merge their complete databases or expose their original files.

> **Project status:** This is an active engineering prototype. The single-node P7 slice has passed a bounded Jetson acceptance (IndexJob publish, Understand Anything graph, cited query, and revocation lockdown). Full-project coverage, durable GBrain integration, automatic pairing/discovery, and multi-Jarvis federation are still in progress.

## The problem

Coding agents make it possible for one person or a small team to produce many more prototypes, repositories, experiments, and documents. That productivity creates a new problem:

- People lose track of what they have already built.
- Important implementations are scattered across computers, NAS folders, external drives, and GitHub repositories.
- A new coding agent often sees only its current sandbox or working directory and misses relevant prior work.
- Teams repeat old experiments because the reasoning, constraints, and reusable modules are difficult to find.
- New team members need too much time to understand existing projects and workflows.
- Leaders need a reliable, inspectable view of project progress without asking every engineer for a manual summary.

UnderstandYourProjects turns this growing body of project work into a maintained, searchable, and permission-aware knowledge space.

## Who it is for

The initial audience includes:

- Heavy AI developers who create many repositories and experiments.
- NAS users and developers with large local project archives.
- Researchers managing code, experiments, papers, and multiple lines of investigation.
- Developers working across several computers or locations.
- Small startups with fast-changing software workflows and frequent onboarding.
- Larger organizations with substantial code assets, established workflows, and strong access-control requirements.

The first product slice should focus on individual developers and small teams. Larger organizations can use the same architecture with stricter deployment, identity, audit, and data-residency requirements.

## Product model

The product has five separate concepts:

1. **Source devices** hold the original files: a Mac, PC, Linux workstation, NAS, external drive, or GitHub repository.
2. **Connectors** expose only the directories and repositories explicitly authorized by the user. They provide manifests, controlled reads, version information, and change notifications.
3. **HomeHub** is the control plane for identity, voiceprint evidence, device ownership, pairing, policy, grants, revocation, and audit. UYP consumes its short-lived access context; it does not replace HomeHub or issue permissions.
4. **Jarvis Agent Boxes** perform local parsing, indexing, embedding, semantic analysis, knowledge retrieval, and project management. A Jetson is the first hardware platform for this role.
5. **Jarvis Studio and Agent Groups** provide visual project management, conversation, coding-agent access, and collaboration between independent Jarvis boxes.

The original project files remain authoritative on their source devices. The Agent Box stores derived knowledge such as file manifests, code structure, project summaries, relations, source references, versions, and index state. Full source files are not copied into a persistent mirror by default. HomeHub remains the authority for who may access each derived result.

## What users can do

UnderstandYourProjects is organized around five actions:

1. **Discover** — See which projects exist, which folders belong together, which repositories are related, and which projects may be duplicates or older versions.
2. **Understand** — Explore project goals, entry points, modules, dependencies, design decisions, known limitations, and the difference between verified code facts and model-generated interpretations.
3. **Search** — Ask questions such as “Where have I implemented cross-device permissions?” or “Which project already solved a similar camera-calibration problem?” and receive answers with file and version evidence.
4. **Reuse** — Ask what can be reused for a new project. Jarvis can recommend existing modules, interfaces, design decisions, experiments, and constraints.
5. **Maintain** — When a source changes, Jarvis updates the affected knowledge incrementally and shows what is current, queued, stale, failed, or unsupported.

The same knowledge can be exposed to a coding agent through a controlled MCP or API surface. The coding agent can discover relevant projects and files outside its current sandbox without receiving unrestricted access to the user's devices.

## Jarvis Studio v2

The current web console is the main operator surface for the Agent Box. It includes:

- streaming Jarvis conversations with an inspectable identity, policy, retrieval, tool, and evidence trace;
- Agents with directory discovery, invitations, direct chats, group chats, and per-chat share cards;
- Devices with connector-backed folder hierarchy, project digests, treemaps, sensor cards, and offline/last-seen states;
- Data views for privacy layers, schedules, and HomeHub-backed household context;
- Flow views for inspecting the configured Jarvis agent graph.

Studio v2 is a client of the companion/query APIs. It does not make HomeHub decisions in the browser and it must show pending, offline, revoked, or partial states instead of turning them into success claims. See [Studio v2 contract](docs/STUDIO_V2.md) for the API and state model.

## Understand Anything and GBrain

Understand Anything is the project's **structural understanding engine**. It scans authorized source bytes in a Jetson staging area, extracts files, symbols, imports, calls, layers, and guided tours, and produces a source-linked project graph. It is deliberately not the chat model and it never writes analysis artifacts into a source repository.

GBrain is the existing long-term knowledge and retrieval foundation. It is useful for cross-project search, timelines, embeddings, graph links, and MCP access. UYP places a project-specific boundary in front of it so that HomeHub scopes and source epochs are checked before retrieval, and evidence and freshness are checked before an answer is returned.

The intended split is:

```text
Understand Anything = current-project structure, dependencies, layers, and evidence
GBrain              = long-term semantic retrieval, timelines, and cross-project memory
HomeHub             = identity, ownership, policy, revocation, and audit
```

The Jetson UYP path publishes to its own state and output stores and exposes the Query API. A bounded project-brain publish and revoke rehearsal has been verified, but the repository-level durable UYP-to-GBrain adapter, full-project coverage, and long-term invalidation path are still in progress.

## Jarvis Agent Groups

Multiple Jarvis boxes can communicate in a group through an Agent-to-Agent transport such as NandaTown.

For example, a user can ask a group:

> Has anyone already implemented a versioned permission system that can be reused for this project?

Each participating Jarvis searches its own local knowledge, applies its owner's grants and the group's audience policy, and returns an attributed answer. A response should identify:

- Which Jarvis produced it.
- Which project and knowledge version were used.
- Which sources can be shared.
- Whether the answer is a verified fact, a deterministic structural result, or a model inference.
- When the source was last synchronized.

Group communication is federated retrieval, not automatic database merging. A Jarvis does not gain access to another owner's computer, NAS, complete gbrain database, or unrestricted source files.

The same user can own multiple Jarvis boxes. Those boxes may belong to a personal group and share a default owner-level view, while retaining separate device identities, local permissions, queues, and audit records. A group containing other people's Jarvis boxes requires explicit project and source grants.

## Local-first architecture

```text
Mac / PC / NAS / GitHub
          |
          v
  Authorized Source Connector
          |
          v
  HomeHub access context
          |
          v
  Jarvis Agent Box (Jetson first)
    - manifest and version tracking
    - deterministic structure extraction
    - local semantic analysis
    - project knowledge and relations
    - permission-aware retrieval
    - persistent incremental jobs
          |
          +--> Jarvis Studio / mobile / voice
          +--> Coding Agent MCP or API
          +--> Agent Groups and NandaTown
```

The intended processing flow is:

```text
discover source changes
  -> filter by authorization and supported file type
  -> read a stable source version
  -> extract deterministic structure
  -> generate constrained semantic records
  -> validate evidence, versions, and permissions
  -> stage and atomically publish a knowledge version
  -> expose the result to Studio, agents, and groups
```

The system should distinguish:

- Facts directly stated in a source file.
- Structure found by deterministic parsing.
- Explanations inferred by a model.

The first version is intended for code and text-based project material. Image, video, CAD, and other heavy multimodal understanding are outside the initial Jetson scope.

## Privacy and trust boundaries

- A Connector can expose only user-approved directories or repositories.
- The Agent Box performs local analysis by default; cloud enhancement is an explicit project-level option.
- Retrieval filters permissions before content reaches a model context.
- Derived summaries, vectors, and relations inherit the restrictions of their sources.
- Revoking a grant invalidates future retrieval and relevant cached context.
- Source devices remain the authority for current original files.
- If a source is offline, the interface must show the last successful knowledge version instead of claiming that it is current.
- The analysis pipeline must not execute arbitrary source-project code or write analysis artifacts into the source directory.

## Initial milestones

1. Build a read-only Connector for one computer and one authorized project directory.
2. Add manifest, source-version, evidence, and incremental-job schemas.
3. Run deterministic structure extraction and local semantic analysis on the Jetson.
4. Publish a project page with source-linked summaries and a searchable project map.
5. Expose a controlled project-search interface for a coding agent.
6. Demonstrate a file change, incremental re-analysis, and a new answer with updated evidence.
7. Add one Jarvis-to-Jarvis group query with explicit sharing and revocation.
8. Add additional source types such as NAS and GitHub fixed-commit reads.

## Current direction

The existing Jarvis HomeHub voice, identity, pairing, policy, audit, scheduling, gbrain, and Agent communication foundations are valuable infrastructure for this product. UnderstandYourProjects adds a dedicated project-knowledge plane instead of replacing the protected voice runtime. A project question still follows the existing voice path — speaker evidence, HomeHub principal resolution, HomeHub policy, Jarvis intent routing — and then enters the Project Knowledge domain.

The detailed review documents are:

- [Execution Plan](docs/EXECUTION_PLAN.md) — staged delivery, gates, evidence, collaboration, and release boundaries.
- [AgentFlow Architecture](docs/AGENTFLOW_ARCHITECTURE.md) — voiceprint, HomeHub policy, project knowledge, Studio, Coding Agent, and Jarvis Group integration.
- [Investigation Report](docs/INVESTIGATION_REPORT_2026-10-09.md) — gbrain/framework capability audit and Jetson/Qwen capacity decision.
- [Jetson Model Strategy](docs/JETSON_MODEL_STRATEGY.md) — resident Qwen3.5-4B, maintenance profiles, memory evidence, and the safe A/B plan.
- [Visualization Design](docs/VISUALIZATION_DESIGN.md) — Project Studio information architecture, evidence language, visual tokens, states, and migration sequence.

The first hardware deployment is one Jetson Agent Box serving multiple authorized source devices. Additional boxes should be introduced when workload, network locality, privacy isolation, or availability requirements justify them—not as a requirement for every computer.

## Current implementation boundary

The repository contains working code slices for the single-node path, plus the first verified cross-box steps:

- a Connector contract with manifest and controlled-read operations;
- HomeHub `AccessContext` validation and fail-closed project queries;
- a durable `IndexJob` state machine with separate HomeHub and Connector capabilities;
- a vendored Understand Anything bridge that keeps analysis state outside source projects;
- Jetson Query API projections for Studio, sources, jobs, evidence, project search, and the groups HTTP endpoints;
- Studio views for project structure, freshness, privacy, and Jarvis groups, plus a live group chat UI;
- a groups engine with scoped group search and NandaTown messaging — send/receive/poll loop with cross-box delivery verified between the clinic and home boxes;
- a read-only MCP stdio surface with six tools: `project.search`, `project.get`, `project.related`, `source.locate`, `source.read_evidence`, `index.status`;
- a provisioned gBrain project brain on `:3142` — provisioning runbook executed end to end, revoke rehearsal passed, and scoped retrieval reserving the project slot;
- preemptive yield across voice, query, and indexing workloads (voice > query > index), including satellite turns;
- incremental indexing driven by a one-minute reconcile timer, crash-resilient `systemd-run` indexing, and grant auto-renewal (24-hour TTL design, three-hour renewal cadence).

The single-node P7 acceptance is recorded in [P7 Acceptance](docs/P7_ACCEPTANCE_2026-10-10.md): one project published 118/120 bounded items with a 766-node/963-edge UA graph, cited query results, and revoke/re-grant lockdown. A bounded 150-item second-project run and the read-only G6 MCP surface have also been exercised. The following are still integration work and must not be inferred from the UI alone:

- full-project indexing and durable resume after transport/model failures;
- production coding-agent onboarding and a full-project MCP acceptance beyond the bounded G6 rehearsal;
- tombstones for source deletes in the incremental indexing path;
- source-epoch lineage and final UA-first enrichment ordering;
- a second Connector and persistent multi-Connector registration;
- LAN/mDNS or Cloudflare pairing and automatic discovery;
- P9 multi-box federation — NandaTown invites and federation beyond the verified clinic–home messaging pair.

In the current development topology, HomeHub is local to Jetson on `:5120`, the UYP `query_api` is on `:8787`, Jarvis Studio is served on `:4173`, the gBrain project brain is on `:3142`, the existing GBrain service is on `:8790`, and satellite boxes connect on `:8765` through the voice-p1 speech backend. The Mac Connector may be reached through an SSH reverse tunnel on Jetson `127.0.0.1:7121`; the reverse tunnel is a development transport, not the final pairing design.

## Collaboration

This repository is intended for collaboration with MIT, Harvard, and other contributors. Early work should focus on the source-connector contract, provenance-aware knowledge schema, incremental analysis, permission-aware retrieval, visual project presentation, and federated Jarvis group queries.

The central research and engineering question is:

> Can a local Agent Box maintain a useful, source-traceable, incrementally updated understanding of a person's projects while allowing both coding agents and other Jarvis boxes to use that knowledge under explicit permissions?
