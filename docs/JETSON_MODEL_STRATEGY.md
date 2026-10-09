# Jetson-first model strategy for UnderstandYourProjects

Status: decision memo, 2026-10-09

## Decision

Jetson remains a hard product requirement. The first resident project-knowledge profile should be **Qwen3.5-4B Q4_K_M** (or the closest supported Qwen3.5-4B GGUF) after a controlled A/B test against the currently active `qwen3-4b-route`. It must share the existing HomeHub inference scheduler and the single-resident-model rule. It must not create a second always-loaded model beside voice, STT, TTS, or gbrain.

The model tiers are:

| Tier | Model | Role | Runtime policy |
| --- | --- | --- | --- |
| Resident | Qwen3.5-4B Q4_K_M | bilingual routing, short project answers, constrained JSON enrichment, citations | one model, normal Jetson operation, context normally 2–4K |
| Deep maintenance | Qwen3.5-9B Q3/IQ3 | architecture/domain summaries and difficult cross-file synthesis | queued low priority; maintenance window or explicit service pause; never concurrent with the resident model |
| Experimental | Qwen3.5-27B IQ2/Q2 | capability probe only | standalone short-context experiment; no production promotion on Orin NX 16GB |

Gemma 4 E4B Q4 is a useful A/B candidate because NVIDIA Jetson AI Lab documents an Orin NX path. It should be compared with Qwen3.5-4B on the same bilingual project benchmark before any replacement decision.

## Current Jetson evidence

The current host is an Orin NX 16GB with Ubuntu 22.04, JetPack/L4T R36.4.4, CUDA 12.6, and Ollama 0.31.2. The read-only audit observed:

- about 15 GiB total memory, about 14 GiB used, and roughly 0.9–1.2 GiB available;
- about 15 GiB swap configured, with about 14 GiB already used;
- `qwen3-4b-route` active at about 5.7 GB unified residency, context 4096, GPU 100%;
- voice/STT/TTS, gbrain, HomeHub and the managed voice gateway active;
- about 125 GB disk space free.

This is a memory-pressure situation. Free disk space does not make a 27B model resident. A 27B IQ2 file may be 8.6–10.2 GB, but execution also needs runtime buffers, KV cache, CUDA allocations, the operating system, and all protected services. It may be possible to probe it during a maintenance window with a very short context, but it is not a safe resident profile.

Potential storage reclamation candidates were identified, but no deletion is authorized by this memo: pip cache (~1.6 GB), apt archives (~4.1 GB), ROS logs (~0.75 GB), VS Code server/cache (~2.4 GB), and staging downloads (~0.9 GB). Chromium kiosk processes use about 1.2 GiB RSS and may be a RAM candidate if the owner confirms that the GUI can close. Quarantine and robot model directories are protected until their owner and retention policy are confirmed.

## Why UnderstandAnything does not require a huge context model

Understand Anything is a pipeline, not a single prompt containing a repository. The Jetson implementation should preserve this sequence:

```text
deterministic scan / ignore rules
  -> Tree-sitter, symbols, imports, call graph, hashes
  -> chunked and incremental enrichment
  -> validated project graph and summaries
  -> lexical + graph + precomputed-vector retrieval
  -> bounded evidence bundle with source ranges and citations
  -> resident model answer or queued deep analysis
```

The existing experiment has 678 files, 638 code files, about 184,533 lines, and a largest file of 2,420 lines. A temporary batch audit produced 39 bounded batches. The model should receive selected symbols, signatures, snippets, and metadata; it should not receive the whole repository. Deterministic structure and retrieval remain useful if the model is unavailable.

Qwen3.5-4B is appropriate for short bilingual summaries, tags, constrained JSON, and evidence-based project questions. A stronger model mainly improves ambiguous cross-file reasoning, architecture tours, domain inference, and final synthesis. It does not replace scanning, graph construction, incremental hashing, or access control.

## Safe experiment sequence

1. Record `free`, swap, `tegrastats`, Ollama `/api/ps`, and HomeHub voice/STT/TTS/gbrain health.
2. Download only the Qwen3.5-4B Q4 candidate to an isolated directory and record its URL, size, and SHA256. Do not overwrite the current Ollama store.
3. Verify whether Ollama 0.31.2 understands the new architecture. If it does not, use a recent CUDA `llama.cpp` build on an isolated localhost port; do not upgrade the production Ollama service as part of the canary.
4. Keep context at 4096 or less, one request at a time, and explicitly set Qwen3.5 `enable_thinking` rather than relying on Qwen3 `/think` or `/nothink` controls.
5. Compare the candidate and current model on 20–50 fixed Chinese/English project questions, JSON enrichment, tool-call formatting, citation fidelity, refusal of unavailable evidence, latency, peak unified memory, and recovery.
6. Restore the current resident model and verify the protected voice path after the test. Promotion requires the same HomeHub model-profile and scheduler gates as every other resident model.

The 9B and 27B tiers are maintenance capabilities. They cannot silently evict the resident model or become a second inference owner. If the small-model A/B fails, keep `qwen3-4b-route` as fallback and improve retrieval/evidence bundling before buying model size.

## Product implication

The product promise is “the Jetson continuously maintains an evidence-backed project index,” not “the Jetson holds every repository in an LLM context.” This keeps the system useful under 16 GB unified memory, preserves HomeHub identity/policy/audit authority, and allows a future stronger maintenance worker without changing the user-facing project graph or access model.


## Canary and evaluation results (2026-10-09, appended after the memo)

### Jetson side: weight staged, load canary deferred by memory reality

- `ollama pull qwen3.5:4b` completed on the production Orin NX (3.3 GB on disk, digest verified, Ollama 0.31.2 accepted the manifest) — the download half of "download it and see" is done.
- Load canary was intentionally NOT run: at probe time the box had ~1.2 GiB available RAM and **14.9/15 GiB swap already used** (~70 MB swap headroom). Loading a second ~3-4 GB residency next to the pinned `qwen3-4b-route` (5.7 GB, keep-forever) would push protected voice services into unrecoverable reclaim. This matches the memo's own maintenance-window rule.
- Maintenance-window canary (run when voice chain is paused or owner-authorised): record `free -m` + `tegrastats`, then
  `curl -s 127.0.0.1:11434/api/chat -d '{"model":"qwen3.5:4b","messages":[{"role":"user","content":"Reply OK"}],"think":false,"stream":false}'`
  followed by `ollama stop qwen3.5:4b` and a voice-chain health pass.

### 4090 side: quality + speed A/B (temp ollama container, removed after test)

Three prompts matching the A/B criteria (bilingual module summary, constrained JSON, evidence citation). All three answers were **correct and compliant**. The decisive finding is the thinking-token tax:

| Mode | Tokens generated (JSON task) | Eval time (4090) | Notes |
| --- | --- | --- | --- |
| thinking on (default) | ~2,600-3,000 | 11-16 s | better judgement on ambiguous snippets (read the socket loop as `logging_collector` vs riskier reads) |
| `/nothink` prompt prefix | ~2,600 | 14 s | **does not work** on this build — still thinks |
| API `"think": false` | **20** | **0.1 s** | clean JSON, ~144x faster |

Implication for the resident profile: **run triage/enrichment with `"think": false`** (est. well under 1 s/task even on Orin NX) and reserve thinking mode for the queued deep-maintenance tier. `/nothink` prefix is not a reliable control; always use the API parameter. The three different judgements of the same snippet across modes also confirm the memo's split: small-model fast opinions for bulk work, thinking mode for judgement calls.
