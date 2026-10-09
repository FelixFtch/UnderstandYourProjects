# UnderstandYourProjects AgentFlow Architecture

**Status:** Review draft
**Scope:** Existing Jarvis/HomeHub integration and the Project Knowledge capability
**Rule:** This document adds a knowledge domain. It does not authorize a second HomeHub runtime, identity authority, policy engine, or audit store.

## 1. The central decision

UnderstandYourProjects is a capability of the existing Jarvis, not a second Jarvis product hidden inside the same box.

The existing voice interaction remains valid:

```text
microphone
  -> wake word / VAD
  -> ASR
  -> speaker evidence
  -> HomeHub principal resolution
  -> HomeHub policy and grants
  -> Jarvis intent router
  -> domain capability
  -> response or action
  -> HomeHub audit
```

The new capability is one additional domain selected by the intent router:

```text
project question / project status / reuse search / project group query
  -> Project Knowledge Domain
```

Speaker recognition answers **who is asking**. It does not, by itself, answer **which source or project that person may read**. Project access is decided by HomeHub grants and policy for the resolved principal, source, project, group, operation, and policy epoch.

## 2. Responsibility boundaries

### HomeHub control plane

HomeHub remains the unique authority for:

- principal and session resolution;
- voiceprint and other identity evidence;
- device ownership and pairing;
- policy and grant decisions;
- revocation and token invalidation;
- audit events;
- existing home, robot, and device tool authority;
- the existing runtime and model scheduling boundary.

The Project Knowledge service may verify a HomeHub-issued `AccessContext`, but it cannot issue a new identity, widen a grant, or decide that two users are the same because they share an email, IP address, or device name.

### Project Knowledge plane

UnderstandYourProjects adds:

- Source Connector registration and health;
- manifest reconciliation;
- project discovery;
- deterministic code and document parsing;
- project graph and relationship extraction;
- summaries, embeddings, and reuse candidates;
- source-traceable Evidence;
- freshness and KnowledgeVersion state;
- project search and related-project tools;
- Studio project views;
- Coding Agent MCP/API tools;
- Jarvis Group retrieval adapter.

The source device, NAS, or fixed GitHub commit remains authoritative for original bytes. The knowledge plane stores derived knowledge and bounded evidence according to the granted retention policy.

### Existing execution plane

Home, robot, and device actions continue through the existing HomeHub tool and safety path. Project search is read-only by default. A future code-writing or project-administration capability must have a separate permission and confirmation path; it must not be smuggled into a read-only project query.

### Presentation plane

Voice, Jarvis Studio, Coding Agent MCP, and a Jarvis Group request are different input/output surfaces. They all use the same request and knowledge contracts after identity and policy resolution.

### Federation plane

NandaTown provides discovery and transport between Jarvis boxes. Each receiving Jarvis performs its own local authorization and retrieval. NandaTown is not the final permission authority and does not receive a complete gbrain, vector store, or identity database.

## 3. Unified request flow

Every entry point should normalize to a common envelope:

```text
RequestEnvelope {
  request_id,
  channel,
  device_id,
  session_id,
  principal_candidate,
  auth_evidence,
  intent,
  requested_action,
  requested_scope
}
```

The end-to-end flow is:

```text
Voice / Studio / Coding Agent / Jarvis Group
  -> RequestEnvelope
  -> HomeHub resolves principal and session
  -> HomeHub checks policy, grants, audience, expiry, and revocation
  -> short-lived AccessContext / capability
  -> Intent and Domain Router
       |-- home / robot action: existing HomeHub execution path
       |-- project knowledge: Project Knowledge service
       |-- general conversation: existing conversation memory path
       |-- group query: Federation adapter
  -> pre-retrieval scope filter
  -> keyword / symbol / graph / vector retrieval
  -> Evidence and freshness validation
  -> optional model synthesis over allowed context only
  -> post-synthesis provenance and ACL validation
  -> voice, Studio, MCP, or group response
  -> HomeHub audit
```

The model never expands the `AccessContext`. Permission filtering happens before retrieval, and the final response is checked again for evidence, freshness, redaction, and revocation.

For voice, the practical path is:

```text
audio -> ASR -> voiceprint evidence -> HomeHub principal
      -> project grant check -> project.search / project.related
      -> evidence-backed response -> existing TTS
```

Low-confidence speaker evidence should either allow only low-sensitivity metadata or require a stronger session, phone, web, or PIN confirmation before revealing private project evidence.

## 4. Existing knowledge base migration

The existing knowledge architecture should not be discarded. The migration is a bounded extension:

```text
Existing Knowledge Service / gbrain foundation
  + conversation_memory namespace
  + system_policy namespace
  + project_knowledge namespace
  + federated_cache namespace with TTL
```

The important change is the boundary and schema, not necessarily a new database.

Reuse the existing gbrain or knowledge store only if it can provide:

- source/project namespace isolation;
- grant filtering before retrieval;
- source version or epoch binding;
- evidence provenance;
- freshness and stale states;
- revocation tombstones;
- atomic KnowledgeVersion publication;
- invalidation of embeddings and group cache after revoke/delete.

If the existing store cannot provide these properties, place a `ProjectKnowledgeService` adapter or bounded project index in front of it. Do not let the voice runtime or a generic conversation-memory query read the project database directly.

The following identities must remain separate:

```text
principal_id       = person
homehub_account_id = account
jarvis_node_id     = one Agent Box
source_id          = one authorized device/directory/repository
project_id         = logical project
grant_id           = one permission decision
session_id         = one interaction session
request_id         = one request
group_id           = one Jarvis collaboration group
```

The original flow of “voiceprint -> person -> accessible information -> scheduling” therefore remains. It becomes more precise because project access is additionally scoped by source, project, operation, audience, expiry, and revocation epoch.

## 5. Project Knowledge tools

The first tools exposed through the existing Agent Gateway are read-only:

```text
project.search
project.get
project.related
source.locate
source.read_evidence
index.status
group.query
```

Each result must include:

```text
source_id
project_id
knowledge_version
source_epoch
file or source_object reference
line or symbol range when available
evidence_level: fact | structure | inference
freshness
producing_jarvis
allowed_to_share
```

`source.read_evidence` is separately scoped. It is not equivalent to unrestricted file access. The first release does not expose shell, build, test, arbitrary URI reads, or source writes through this interface.

## 6. Project Group queries

For a same-user owner group, multiple Jarvis boxes retain independent identities and local audits. The owner group permits federated search but does not collapse the nodes into one database.

For a cross-user group, the request carries:

```text
group_id
sender_node_id
receiver_node_id
request_id
nonce
issued_at
expires_at
query_scope
allowed_source_or_project_scope
share_policy
```

The receiving Jarvis checks its own grants before searching and returns only the permitted summary or evidence. A response is attributed to the producing Jarvis and knowledge version. Expiry and revocation must invalidate new requests and cached remote results.

## 7. What we learn from existing open-source projects

These projects are references for specific patterns, not dependencies to copy wholesale:

- [Langflow architecture](https://github.com/langflow-ai/langflow/blob/main/docs/agents/ARCHITECTURE.md): use one-way package boundaries and keep the frontend communicating with backend services through HTTP/WebSocket. This suggests that Jarvis Studio should be a client of controlled APIs, never a direct reader of source files or gbrain tables. Langflow's visual flow canvas and runtime logs are useful inspiration for showing an indexing workflow and live task state.
- [OpenCode](https://github.com/anomalyco/opencode): study its separation of agents, sessions, tools, configuration, database migrations, logging, and TUI. The useful product distinction is between a read-only planning/retrieval profile and a separately authorized build/write profile. OpenCode should remain an external Coding Agent client, not become our knowledge or HomeHub authority.
- [OpenHands agent architecture](https://github.com/OpenHands/docs/blob/main/sdk/arch/agent.mdx): reuse the idea of an event-driven reasoning/action loop with context management and security validation before tools execute. For us, an indexing job and a project query should have observable events, but source execution remains prohibited in the knowledge MVP.
- [GitNexus](https://github.com/abhigyanpatwari/GitNexus): study precomputed code graphs, impact analysis, process traces, stale-index visibility, and MCP tools. Its central lesson is that graph-aware tools can return complete architectural context in one call instead of forcing an LLM to grep repeatedly. We must add our Source Grant, Evidence, epoch, and revocation boundaries, and must not silently write files into source repositories.
- [Grafel](https://github.com/cajasmota/grafel): study cross-repository lineage from UI components through APIs, permissions, services, queues, and databases. This is a strong model for future multi-repo project maps and impact analysis.
- [Codebase-RAG](https://github.com/royisme/codebase-rag): study the combination of graph analysis, temporal project memory, hybrid vector/graph search, Web UI, REST, and MCP. The temporal memory and multi-interface pattern fit our Project Knowledge plane, but its permission model must be replaced by HomeHub grants.
- [Continue configuration and MCP](https://github.com/continuedev/continue/blob/main/docs/reference.mdx): study the explicit separation of models, context providers, rules, prompts, documentation sources, and MCP servers. This supports exposing UnderstandYourProjects as a context provider to many Coding Agents without coupling it to one editor.

The first five to study deeply are Langflow, OpenHands/LangGraph-style execution traces, OpenCode, GitNexus/CodeBoarding-style code graphs, and CocoIndex-style incremental lineage. Flowise, Dify, RAGFlow, Temporal, and CodeSee can remain secondary references until the first vertical slice works.

## 8. Recommended Studio design

Jarvis Studio should have two complementary views:

### Project view

- project cards;
- repository/source status;
- architecture graph;
- module and dependency navigation;
- timeline and recent changes;
- reusable project candidates;
- evidence panel;
- current/stale/failed/offline state;
- new-member guided tour.

### AgentFlow view

Show the actual request or indexing job as a trace:

```text
Request
  -> identity resolved
  -> policy decision
  -> source/project scope
  -> retrieval plan
  -> evidence selected
  -> model synthesis
  -> response / denial
```

This is where Langflow/LangGraph-style flow visualization is useful. It should show state, latency, tool arguments, result counts, errors, and policy decisions without exposing private source content by default. The flow view is an observability and explanation surface, not a second execution engine.

## 9. Migration order

1. Add a read-only Project Knowledge adapter behind the existing Agent Gateway.
2. Pass HomeHub-issued `AccessContext` into project queries.
3. Reuse existing knowledge storage where it satisfies provenance, ACL, epoch, and revoke requirements.
4. Add Source Connector, manifest, IndexJob, and KnowledgeVersion.
5. Add Studio project and evidence views.
6. Add MCP tools for Coding Agents.
7. Add NandaTown federation only after local retrieval and revocation are reliable.

The final result is one Jarvis with one identity and communication model, plus a new project-expert capability. Voiceprint remains the identity signal; HomeHub remains the authority; Project Knowledge becomes the specialized information domain.
