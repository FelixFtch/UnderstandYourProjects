# Reference Architectures for UnderstandYourProjects

This is a research map for MIT, Harvard, and other contributors. The projects below are references for individual patterns. They are not dependencies for the first Jetson release.

| Project | Pattern to study | Apply to UnderstandYourProjects | Do not copy |
|---|---|---|---|
| [Langflow](https://github.com/langflow-ai/langflow) | Visual flow canvas, HTTP/WebSocket frontend boundary, one-way package dependencies, extension interfaces | Jarvis Studio can visualize a typed indexing/query pipeline and live task logs. Frontend talks to controlled APIs. | Do not turn production permissions into arbitrary drag-and-drop edges. Do not let Studio read gbrain or source files directly. |
| [LangGraph Studio](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/studio.mdx) | Inspectable graph state, step-by-step execution, replay and debugging | Add Agent Run Trace with policy decision, selected skill, retrieval steps, evidence, latency, and errors. | Do not send private source content to a hosted debugger by default. |
| [OpenCode](https://github.com/anomalyco/opencode) | Client/server separation, sessions, tools, providers, permissions, logs, TUI/Web clients | Voice, Studio, and Coding Agent clients should share the same Agent Gateway/session/tool contracts. Project Expert can be a restricted agent profile. | Do not make OpenCode the project knowledge authority or HomeHub authority. |
| [OpenHands](https://github.com/OpenHands/OpenHands) | Agent, controller, state, event stream, workspace/runtime separation, sandbox boundary | Use event records for indexing jobs and visible query traces. Keep coding execution in an external, separately controlled sandbox. | Do not place arbitrary project execution in the Jetson knowledge worker. |
| [GitNexus](https://github.com/nxpatterns/gitnexus) | Code knowledge graph, call-chain/process tools, impact analysis, MCP, stale-index awareness | Build project maps, context bundles, impact analysis, and MCP tools that return graph context in fewer calls. | Add Source Grant, Evidence, source epoch, and revocation. Do not silently write agent context into source repositories. |
| [CodeBoarding](https://github.com/Codeboarding/CodeBoarding) | Static analysis plus component maps, Mermaid/HTML output, analysis snapshots, diff/review views | Use architecture maps and analysis snapshots for onboarding and project comparison. | Keep deterministic facts separate from model-generated component names and explanations. |
| [Grafel](https://github.com/cajasmota/grafel) | Cross-repository lineage across UI, APIs, permissions, services, queues, and databases | Future multi-repo impact and reuse views can show real cross-project lineage. | Do not claim cross-repo relations without source/version evidence. |
| [Codebase-RAG](https://github.com/royisme/codebase-rag) | Graph analysis, temporal project memory, hybrid graph/vector retrieval, Web/REST/MCP interfaces | Use one Knowledge API for Studio, Coding Agents, and automation; preserve temporal KnowledgeVersions. | Replace its permission assumptions with HomeHub-issued AccessContext and Source/Project Grants. |
| [Continue](https://github.com/continuedev/continue) | Explicit models, context providers, rules, prompts, docs, and MCP servers | Present UnderstandYourProjects as a provider usable by many coding agents, editors, and MCP clients. | Do not couple the knowledge service to one IDE or model provider. |
| [Aider repository map](https://github.com/Aider-AI/aider/blob/main/aider/website/docs/repomap.md) | Token-budgeted map of files, classes, functions, signatures, and ranked dependencies | Add a `project.context_bundle` response: structure first, then only the relevant file ranges. This fits constrained Jetson resources. | Apply grant and source-version filtering before constructing the bundle. |
| [CocoIndex](https://github.com/cocoindex-io/cocoindex) | Declarative incremental pipeline, hash memoization, delta recomputation, source-byte lineage, retry/DLQ | Use the same principles for Connector → IndexJob → KnowledgeVersion and affected-object recomputation. | Do not import a large framework before measuring Jetson resource cost. |
| [Temporal](https://github.com/temporalio/temporal/blob/main/docs/architecture/README.md) | Durable workflows, task queues, retry/replay, event history | Model IndexJob recovery, pause/resume, replay, and audit with durable state and event records. | Do not introduce a complete Temporal cluster into the MVP. |
| [Flowise](https://github.com/FlowiseAI/FlowiseDocs/blob/main/en/README.md) | Assistant, Chatflow, Agentflow, branching, RAG, tracing, evaluations, HITL, MCP, RBAC | Borrow the idea of separating simple retrieval from richer workflows and exposing trace/evaluation views. | Do not become a general low-code platform with hundreds of connectors before the core knowledge loop works. |
| [RAGFlow](https://github.com/infiniflow/ragflow) | Knowledge compilation, document views, graph/tree/timeline representations, agentic RAG | Consider multiple project views after code/text indexing is reliable. | Do not deploy the full resource-heavy platform on Jetson for the first release. |

## Priority of study

The first five deep reads should be:

1. Langflow for service and visual-flow boundaries.
2. LangGraph Studio and OpenHands for trace, state, event, and replay patterns.
3. OpenCode for client/server, session, tool, and permission separation.
4. GitNexus and CodeBoarding for code graphs and onboarding maps.
5. CocoIndex for incremental lineage and delta processing.

The product should initially have four visual surfaces:

1. **Project Map:** files, symbols, modules, dependencies, and reusable components.
2. **Knowledge Timeline:** manifests, commits, change epochs, current/stale/failed state.
3. **Agent Run Trace:** identity, HomeHub decision, selected domain, retrieval, evidence, answer, latency, and errors.
4. **Access and Federation View:** principal, Jarvis node, source/project grant, remote peer, TTL, and revocation state.

These views explain a fixed, typed, auditable pipeline. They do not give the browser a second workflow engine or permission authority.
