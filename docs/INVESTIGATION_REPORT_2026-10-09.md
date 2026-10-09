# Investigation Report — 2026-10-09

**Scope:** official knowledge tools, current Jarvis/HomeHub framework, and Jetson Qwen capacity
**Evidence level:** official documentation plus read-only local/Jetson audit
**Runtime policy:** no service restart, model replacement, file mutation, or production deployment was performed.

## Executive decision

The current Jarvis framework already contains most of the control-plane and agent-flow skeleton needed for UnderstandYourProjects:

```text
voiceprint -> IdentityContext -> HomeHub policy/grant
           -> agent-runtime -> knowledge-service/gbrain
           -> governed tools -> TTS / Studio / audit
```

The missing product layer is project-specific rather than a new Jarvis runtime:

```text
Source Connector
  -> durable Manifest / SourceObject
  -> Project IndexJob
  -> structure graph + derived knowledge
  -> Evidence / KnowledgeVersion / freshness
  -> permission-aware project.* tools
  -> Studio / Coding Agent / Jarvis Group
```

The present Jetson is not a safe host for a resident Qwen3.8-27B service. It is a 16 GB unified-memory Jetson Orin NX with the existing voice, gbrain, embedding, and agent services already using nearly all memory and swap. The practical direction is to keep Qwen3-4B as the resident route, test a controlled 8B–9B path only in an isolated maintenance window, and place 27B-class reasoning on a 4090, a larger Jetson AGX/Thor, or an explicitly selected cloud provider.

## 1. Official gbrain capability audit

The upstream GBrain design is useful as a derived knowledge backend, but it is not a replacement for HomeHub authority and it is not a complete code-project index.

### Capabilities that map well to the plan

- A single brain can contain multiple logical sources, with separate source IDs, slug namespaces, sync state, and opt-in federation. See the official [multi-source brains guide](https://github.com/garrytan/gbrain/blob/master/docs/guides/multi-source-brains.md).
- The current data model combines compiled truth, append-only timeline evidence, full-text search, embeddings, links, tags, raw data, and ingest audit. See the official [GBrain README](https://github.com/garrytan/gbrain).
- Retrieval supports keyword/vector hybrid search, multi-query expansion, graph traversal, source filtering, and MCP access.
- The official skillpack separates deterministic collectors from model judgment and emphasizes source attribution and timeline evidence. See [GBRAIN_SKILLPACK.md](https://github.com/garrytan/gbrain/blob/master/docs/GBRAIN_SKILLPACK.md).
- Jobs support pause, resume, retry, cancel, progress, checkpoints, and incremental sync patterns.
- Source and client grants, operation scopes, visibility filters, token expiry, and revocation are available in the current upstream direction.
- MCP makes one local brain available to multiple clients such as Coding Agents.

### Gaps for UnderstandYourProjects

Current upstream GBrain already contains substantial code chunking, Tree-sitter metadata, and call/reference edges. It does not directly provide the complete project-product contract we need:

- Source Connector pairing and directory authorization;
- durable `SourceObject` manifests with stable file IDs;
- a complete multi-repository project contract around those code chunks and edges;
- `Project` and `ProjectRelation` as first-class objects;
- a stable line-range or symbol-level Evidence contract tied to a source epoch;
- atomic `KnowledgeVersion` publication for a whole project snapshot;
- project-level freshness and delete/rename tombstones;
- NandaTown/Jarvis Group protocol;
- HomeHub voice identity and device ownership;
- a permission contract that accepts HomeHub `AccessContext` instead of client-supplied member/role fields.

### Current Jetson knowledge-service findings

The existing Jetson service at `:8790` is already a useful facade:

- `/query` and `/synthesize` exist;
- `/permissions` and grant/revoke paths exist;
- brain-level grants and member/role-based access exist;
- gbrain MCP/HTTP integration exists;
- current connectors already write or update gbrain pages.

The current contract is still too coarse for project knowledge:

- query inputs currently include `member` and `role` rather than a signed HomeHub `AccessContext`;
- access is primarily brain-level, not source/project/file/version scoped;
- current connectors rely on mtime and process state rather than durable manifest/hash/epoch reconciliation;
- gbrain slugs are not sufficient for symbol/line Evidence;
- delete, rename, tombstone, and atomic project snapshot semantics need a new layer;
- the Project service must ignore caller-provided identity fields and accept only HomeHub-issued context.

### Recommended gbrain integration

Keep gbrain behind a `ProjectKnowledgeService` adapter:

```text
HomeHub AccessContext
  -> ProjectKnowledgeService (ACL/source/project/epoch prefilter)
  -> gbrain keyword/vector/graph retrieval
  -> Evidence validator
  -> model synthesis over allowed results
```

If the Jetson deployment is still on an older gbrain build, first record the exact version and schema. Do not overwrite the production brain with current upstream code. Run migration, doctor, re-index, permission, and retrieval regression tests in an isolated copy before considering an upgrade.

## 2. Current framework mapping

| Area | Current evidence | Status for UnderstandYourProjects | Required next slice |
|---|---|---|---|
| Voiceprint and principal | Voice gateway identifies speaker; unknown/failure degrades to Guest; HomeHub produces identity/session context | Reusable | Add project scopes to a HomeHub-issued AccessContext |
| Identity and policy | HomeHub owns identity fusion, device/session context, policy epoch, short-lived grants, and revocation | Reusable authority | Do not duplicate it in project service |
| Agent runtime | Existing turn loop, knowledge-first path, gated tools, sessions, resident model, and governed backend | Reusable | Add `project.*` ToolSpecs and a Project Expert route |
| Knowledge facade | `knowledge-service :8790`, gbrain MCP/HTTP, brain grants, query/synthesize | Partial | Add source/project/epoch/Evidence-aware prefilter |
| gbrain | Sources, hybrid retrieval, graph, MCP, sync, checkpoints, grants | Partial backend | Wrap with ProjectKnowledgeService; do not make it identity authority |
| Connectors | Existing Markdown/voice/meeting-style connectors and gbrain upsert paths | Partial | Add pairing, manifest, stable hash, change log, revoke, reconcile |
| Agent Gateway | DelegationGate, A2A protocol, capability/delegation/task/event/result contracts, idempotent task store, audit | Reusable federation skeleton | Add project capability and bounded KnowledgeResult |
| Companion/Studio | Companion API, tasks, observe, databases, A2A card and event views | Partial presentation | Add sources, projects, index jobs, Evidence, group and audit views |
| Jarvis Group | Town/A2A transport and delegation foundation | Partial | Add signed project query, audience, TTL, source/project grant, attribution |
| Project graph | No complete source/version/symbol/line-range project graph contract | Missing | Build deterministic structure index and versioned Evidence layer |

The existing framework therefore should be extended, not replaced. The largest missing boundary is **project-scoped ACL + versioned Evidence + incremental source synchronization**.

## 3. Qwen and Jetson capacity

### Read-only Jetson snapshot

The read-only audit identified:

- Jetson Orin NX Engineering Reference Developer Kit Super;
- Ubuntu 22.04.5, JetPack/L4T 36.4.4, CUDA 12.6;
- 16 GB unified LPDDR5 memory;
- roughly 15.3 GiB total memory, with about 14 GiB used and less than 1 GiB available during the audit;
- roughly 14.5 GiB of a 16 GiB swap area already used;
- current Ollama 0.31.2;
- resident `qwen3-4b-route` at context 4096, with approximately 5.7 GB reported VRAM use;
- `qwen3-4b-think` and `qwen3-4b-route` Q4 files around 2.5 GB each;
- gbrain embedding server using a roughly 146 MB `nomic-q8.gguf` model;
- existing voice, STT, TTS, agent, gbrain, and NandaTown services.

This is a capacity snapshot, not a long-run performance acceptance. The current swap pressure alone is enough to block an in-place large-model experiment.

### Qwen3.8-27B facts

The official Qwen3.8 repository lists Qwen3.8-27B as a dense 27B multimodal model and publishes it through Hugging Face and ModelScope. The model card describes a 262K native context window and vision support. See the [official Qwen3.8 repository](https://github.com/QwenLM/Qwen3.8) and the [official model listing](https://huggingface.co/Qwen/Qwen3.8-27B).

For local packaging, compare the [official ggml-org GGUF files](https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF), the [Ollama Qwen3.8 tags](https://ollama.com/library/qwen3.8/tags), and the [vLLM Qwen3.8 recipe](https://github.com/vllm-project/recipes/blob/main/models/Qwen/Qwen3.8-27B.yaml). NVIDIA's [Jetson deployment article](https://developer.nvidia.com/blog/frontier-reasoning-reaches-the-edge-how-to-deploy-and-optimize-models-on-nvidia-jetson) demonstrates larger Qwen3.8 deployments on higher-memory Jetson targets; it does not establish support for the current NX16.

The published GGUF sizes are much larger than a 16 GB Jetson can safely host:

| Variant | Approximate weight size | Result on current NX16 |
|---|---:|---|
| BF16 | 53.8 GB | Impossible |
| Q8 | 28.6 GB | Impossible |
| Official/community Q4_K_M | about 19 GB | Does not fit |
| Extreme community Q3/Q2/IQ variants | roughly 7–13 GB | May fit numerically, but leaves too little room for OS, voice services, KV cache, and embeddings |

The official vLLM Qwen3.8-27B recipe lists high-memory NVIDIA/Blackwell and other accelerator targets, not Jetson Orin NX. NVIDIA’s NVFP4 examples target newer hardware and do not prove Orin NX support. A community one-bit or two-bit GGUF may load with a recent `llama.cpp`, but that would be an experimental offline process, not a production resident model.

Qwen3.8 is bilingual and multimodal, but the vision tower and `mmproj` add memory that the code/text MVP does not need. For UnderstandYourProjects, a smaller text/code model is more appropriate on Jetson.

### Practical model tiers

| Tier | Model direction | Jetson role | Decision |
|---|---|---|---|
| Resident | Qwen3-4B Q4 or current equivalent | Voice/router/short project summaries | Keep and protect first |
| Controlled experiment | Qwen3.5/Qwen3 8B–9B Q4 | Offline indexing or low-concurrency query | Test only in isolated maintenance window |
| External worker | Qwen3.5/3.6/3.8 27B-class quantized model | Deep project synthesis, difficult bilingual coding questions | Run on 4090, larger AGX/Thor, or explicit cloud route |
| Experimental research | Extreme Q2/IQ1/Q1 27B GGUF | No-resident, offline quality/compatibility test | Do not connect to voice or production gbrain |

The recommended design is therefore a two-tier model route:

```text
Jetson resident Qwen4B
  -> identity-adjacent routing, short answers, metadata, lightweight summaries

4090 / larger box / opted-in cloud Qwen27B+
  -> deep indexing, cross-project synthesis, difficult bilingual coding analysis
```

The external worker must receive only an already permission-filtered context bundle, never unrestricted source access or HomeHub credentials.

## 4. Safe next experiments

The next model experiment should not replace the current service. It should be an isolated benchmark with:

1. a fresh model runtime or container outside the resident service;
2. a copy of a small approved text/code fixture;
3. no voice, TTS, HomeHub, or production gbrain connection;
4. context lengths of 2K, 4K, and 8K;
5. bilingual project questions and code navigation questions;
6. measurements of load time, RAM, swap, GPU, tokens/second, first-token latency, and crash recovery;
7. explicit tool-call and citation tests;
8. a cleanup and rollback record.

Do not download or load Qwen3.8-27B on the production Jetson until a maintenance window is approved and the current voice chain has a tested rollback. Based on the read-only snapshot, the correct immediate action is to preserve Qwen3-4B and move the 27B experiment to the 4090 or another larger-memory host.
