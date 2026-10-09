# UnderstandYourProjects

UnderstandYourProjects is a local project-knowledge management system for the era of capable coding agents.

It connects user-authorized computers, NAS storage, GitHub repositories, and development devices to a dedicated **Jarvis Agent Box**. The box continuously discovers projects, extracts structure, builds semantic understanding, maintains a visual project map, answers questions with source evidence, and incrementally updates its knowledge as projects change.

It also lets independent Jarvis boxes join groups and communicate. Each Jarvis searches its own local project knowledge and shares only the information permitted by its owner and the group. This creates a privacy-aware project knowledge network without requiring participants to merge their complete databases or expose their original files.

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

The product has four separate concepts:

1. **Source devices** hold the original files: a Mac, PC, Linux workstation, NAS, external drive, or GitHub repository.
2. **Connectors** expose only the directories and repositories explicitly authorized by the user. They provide manifests, controlled reads, version information, and change notifications.
3. **Jarvis Agent Boxes** perform local parsing, indexing, embedding, semantic analysis, knowledge retrieval, and project management. A Jetson is the first hardware platform for this role.
4. **Jarvis Studio and Agent Groups** provide visual project management, conversation, coding-agent access, and collaboration between independent Jarvis boxes.

The original project files remain authoritative on their source devices. The Agent Box stores derived knowledge such as file manifests, code structure, project summaries, relations, source references, versions, and index state. Full source files are not copied into a persistent mirror by default.

## What users can do

UnderstandYourProjects is organized around five actions:

1. **Discover** — See which projects exist, which folders belong together, which repositories are related, and which projects may be duplicates or older versions.
2. **Understand** — Explore project goals, entry points, modules, dependencies, design decisions, known limitations, and the difference between verified code facts and model-generated interpretations.
3. **Search** — Ask questions such as “Where have I implemented cross-device permissions?” or “Which project already solved a similar camera-calibration problem?” and receive answers with file and version evidence.
4. **Reuse** — Ask what can be reused for a new project. Jarvis can recommend existing modules, interfaces, design decisions, experiments, and constraints.
5. **Maintain** — When a source changes, Jarvis updates the affected knowledge incrementally and shows what is current, queued, stale, failed, or unsupported.

The same knowledge can be exposed to a coding agent through a controlled MCP or API surface. The coding agent can discover relevant projects and files outside its current sandbox without receiving unrestricted access to the user's devices.

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

The existing Jarvis HomeHub voice, identity, pairing, policy, audit, scheduling, gbrain, and Agent communication foundations are valuable infrastructure for this product. UnderstandYourProjects should add a dedicated project-knowledge plane instead of replacing the protected voice runtime.

The detailed review documents are:

- [Execution Plan](docs/EXECUTION_PLAN.md) — staged delivery, gates, evidence, collaboration, and release boundaries.
- [AgentFlow Architecture](docs/AGENTFLOW_ARCHITECTURE.md) — voiceprint, HomeHub policy, project knowledge, Studio, Coding Agent, and Jarvis Group integration.
- [Investigation Report](docs/INVESTIGATION_REPORT_2026-10-09.md) — gbrain/framework capability audit and Jetson/Qwen capacity decision.
- [Jetson Model Strategy](docs/JETSON_MODEL_STRATEGY.md) — resident Qwen3.5-4B, maintenance profiles, memory evidence, and the safe A/B plan.
- [Visualization Design](docs/VISUALIZATION_DESIGN.md) — Project Studio information architecture, evidence language, visual tokens, states, and migration sequence.

The first hardware deployment is one Jetson Agent Box serving multiple authorized source devices. Additional boxes should be introduced when workload, network locality, privacy isolation, or availability requirements justify them—not as a requirement for every computer.

## Collaboration

This repository is intended for collaboration with MIT, Harvard, and other contributors. Early work should focus on the source-connector contract, provenance-aware knowledge schema, incremental analysis, permission-aware retrieval, visual project presentation, and federated Jarvis group queries.

The central research and engineering question is:

> Can a local Agent Box maintain a useful, source-traceable, incrementally updated understanding of a person's projects while allowing both coding agents and other Jarvis boxes to use that knowledge under explicit permissions?
