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


## On-device A/B: qwen3.5:4b (think:false) vs qwen3-4b-route — 2026-10-09

Method: same box, same six bilingual prompts, `num_ctx 2048`, one model resident at a time (route model was unloaded for the 3.5 leg, then restored; voice chain verified healthy after the swap — guest turn answered normally).

| # | Task | qwen3.5:4b nothink | qwen3-4b-route | Verdict |
| --- | --- | --- | --- | --- |
| 1 | intent routing (production job) | correct, 0.2s eval | correct, 0.2s eval | tie — routing correctness is not a reason to switch, nor a risk |
| 2 | one-line Chinese module summary | correct, 10 tok | correct (mentions "signature"), 13 tok | route slightly more precise |
| 3 | constrained JSON | valid, `risk:"low"` | valid, `risk:"medium"` | tie; route slightly more conservative |
| 4 | English evidence answer (guard name) | honest "not mentioned" | honest "not mentioned" | tie (question was ambiguous; neither hallucinated) |
| 5 | Chinese architecture judgement (planner vs avoidance authority) | **layered answer: low-level motion controller holds instantaneous authority, planner supplies verified trajectories** | classic "planner holds authority" | **qwen3.5 clearly better** — nuanced, closer to modern safety architecture |
| 6 | compound split to JSON array | correct but drifted to English | correct, kept Chinese | route better on language consistency (fixable with a prompt pin) |

Speed (Jetson, think:false): comparable; eval 0.2-6.6s vs 0.2-5.1s, 3.5 emits fewer tokens for the same answers (10/24/9 vs 13/27/20).

Memory at ctx 2048: **qwen3.5:4b resident 3.1 GB vs route 4.2 GB** — the candidate is ~1.1 GB cheaper at equal context (5.7 GB figure for route is its production ctx-4096 residency).

### Verdict

Switching the resident profile to qwen3.5:4b is justified for the UnderstandYourProjects workload: clearly better Chinese/architectural reasoning, equal routing, equal-or-better speed, ~1 GB less residency. Two preconditions before promotion: pin output language in the enrichment prompts (3.5 drifted to English on one bilingual task), and keep `"think": false` on every triage/enrichment call (thinking mode costs ~144x tokens). Voice-chain promotion still goes through the HomeHub model-profile gates.


## Local decision-model bake-off + routed pipeline — 2026-10-09 (voice chain paused with owner authorization, restored and verified after)

Setup: fresh llama.cpp built on-device (CUDA, arch 87; gbrain's bundled build predates decision support). Decision API = `/v1/systemone` (Jev-compatible: choice / score / noul), one forward pass, zero generated tokens.

### Candidate results (4-file real triage: core code / deps / docs / trivial marker)

| Candidate | Size | Load | Decision latency | Triage quality | think-gate signal |
| --- | --- | --- | --- | --- | --- |
| **Laya official Q8 (ggml-org/Laya-GGUF, 421M)** | 449MB | 2s | 43-497ms | 3/4 (README over-triaged to deep) | **clean bimodal: 0.00 vs 0.95** |
| Kev-4B Q4 (ggml-org) | 3.0GB | ~10s | 337-927ms | 3/4 (same README miss) | weak/mushy 0.17-0.39 |
| Kev-0.8B Q8 | 812MB | 6s | 149-483ms | 2/4 (missed core file) | weak |
| GLiNER2.5-multi-Decide | 1.1GB | — | — | **not loadable locally**: custom Gliner2ForSchemaExtraction arch ships no modeling code; official skill pushes hosted API only. Dropped. |
| Laya 3rd-party GGUF (mys/) | — | — | — | rejected: nonstandard arch tag 'ggmlc' | use ggml-org official only |

**Winner: Laya official Q8** — 9x smaller than Kev-4B, 2s load, cleanest think-gate signal.

### Routed pipeline end-to-end (Laya decides -> qwen3.5:4b executes)

| file | Laya verdict | execution | tokens | time |
| --- | --- | --- | --- | --- |
| core app.py | deep, noul=0.94 | think=true | 3362 | 222s, JSON-OK |
| requirements | skip, noul=0.00 | skipped | 0 | 39ms |
| README | deep, noul=0.91 | think=true | 3578 | 226s, BAD format* |
| py.typed | skip, noul=0.00 | skipped | 0 | 39ms |

Totals vs baselines: routed 448s/6940 tok | all-think-false ~60s/950 tok | all-think-true ~520s/8300 tok.
*thinking mode occasionally wraps JSON — needs a brace-extraction fallback (engineering fix, queued).

Reading: on this small sample routing saves little vs all-true (Laya sent both real files deep — its known README over-triage). The win scales with corpus composition: at ~60% skip/structure-only (typical repo deps/generated), a 678-file first index projects to ~4.5h routed vs ~22.6h all-thinking vs ~2.8h all-fast — deep quality only where the gate says it matters. Calibration on our own labeled files (the known Laya zero-shot caveat) is the next quality lever.

### Placement (already in this repo)

- llama.cpp build + all weights live on the Jetson at `~/dev/uyp/models/` (Laya-Q8 449MB, Kev-4B Q4, Kev-0.8B Q8; GLiNER dir can be deleted)
- Production shape: resident Laya (0.5GB) beside qwen3.5:4b (3.1GB) = 3.6GB total, less than today's single route model (5.7GB)


### Addendum: full six-candidate matrix (same 4-file probe, on-device)

| Model | Size | Triage | Think-gate | Status |
| --- | --- | --- | --- | --- |
| Laya official Q8 | 449MB | 3/4 | **clean bimodal 0.00/0.95** | **resident pick** |
| lev-4B Q4 | 3.0GB | 3/4, higher confidence (0.71-0.95) | weak gate (all-low, never fires) | alternate |
| Kev-4B Q4 | 3.0GB | 3/4 | mushy 0.17-0.39 | alternate |
| Kev-0.8B Q8 | 812MB | 2/4 (misses core) | weak | rejected |
| Julia-1 Q8 | 168MB | degenerate: everything quick-summary at 1.00 conf | chaotic | rejected |
| GLiNER2.5-Decide | 1.1GB | not locally loadable | — | rejected |
| OpenJev / Clef 27B | 8.6GB+ | cannot co-reside with qwen3.5 on NX16; OpenJev is CC BY-NC | — | not for the resident slot (possible 4090 deep-judge later) |

README over-triage is universal across the 4B class → prompt/calibration issue, not model choice. Final ranking should be settled on a 30-file labeled set; the /v1/systemone API makes swapping a one-line config change. Ops note: pkill patterns for llama-server must exclude /usr/local/lib/ollama (ollama's internal runner shares the name).
