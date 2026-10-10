# P7 Single-Node Acceptance — PASSED (2026-10-10)

Executor: Claude (ground-truth session); Laya service + job run + six-step acceptance.

| Step | Result | Evidence |
|---|---|---|
| 1. Laya triage service | ✅ | uyp-laya.service (systemd user, Restart=always, enabled); /v1/systemone live |
| 2. Durable IndexJob | ✅ | job-2a1f2742d9: discovered→authorized→queued→running→staged→**published**; 118/120 processed; atomic publish; knowledgeVersion 2026-10-10T08:05:32Z; grantEpoch recorded |
| 3. UA structure graph | ✅ | knowledge-graph.json regenerated fresh: **766 nodes / 963 edges** (vs 40/25 smoke); .glb correctly skipped as too-large |
| 4. Artifact reconciliation | ✅ | staged 120 items → published; sourceEpoch null (noted gap) |
| 5. Query acceptance | ✅ | "where is delegation signing implemented" → correct chain (delegation_sig.py → signing.py → tests), inline citations |
| 6. Revocation lockdown | ✅ | POST grants/{id}/revoke (epoch 2→3) → search immediately returns "0 files indexed, no match" → audit trail → re-grant (epoch 4) → knowledge restored |

## Findings (honest)
1. **health endpoint leaks unscoped count**: after revocation /api/health still reported knowledgeItems:119 while search correctly saw 0 — the count should be scope-filtered (spec: no counts without context).
2. sourceEpoch not captured (None) — version lineage gap for incremental updates.
3. Worker order is transitional (semantic→UA); final state (UA-first anchored enrichment) is the next refactor — see QA_AUDIT fix #2.
4. Revoke body requires opaque identifier reason (no spaces) — document in QUERY_API.md.

Reproduce: tools/p7_acceptance_run.sh (correct --ua-root ~/dev/uyp/understand-anything-src-20261009).

## Second project (jarvis-homehub) — 2026-10-10

Grants: connector **g_1393b498** (Mac `~/projects/jarvis-homehub`); HomeHub **uyp-grant-3b73f433130b4390b861e54d213a9f05** (felix, epoch 5, 24 h). Manifest **3136** (excludes verified: jetson/ 19808→881 after .git/node_modules/.venv; `.env`/`secret`/`credential` names absent from manifest **and** 403 `denied_pattern` on direct read).

Jobs: full-scope job-018ea9f6 (`--limit 0`) crashed twice (10:06Z ollama restart → empty reply; 10:27Z tunnel blip → ConnectionReset); bounded job-33cd3880 (`--limit 150`) ran discovered 10:17:29Z → authorized/queued/running 10:32:15Z → **published 11:31:09Z**: 150 items, UA graph 709 nodes/790 edges, anchored_enrich DONE anchored=5. `/api/health` knowledgeItems **269** (119 jarvis-memory-live + 150 jarvis-homehub). Search "where is the voice router implemented" → ok, cites ios/JarvisHub Tests + audit-2026-09-22 jetson tests (answer quotes a `file:///Users/ben/...` URL found inside source content).

Findings: (1) `failed`/`offline` are TERMINAL — run-pending never resumes a crashed job, and each resume re-creates `staged/` so all prior progress is lost; (2) `qwen_enrich` had no transport retry — one empty ollama reply (shared with live voice router, restart 06:06 EDT) killed the job; hotfixed on the jetson deployment only (retry+warm, same for connector `api()` after a tunnel reset) — port to repo; (3) full scope ≈ 2394 LLM files × ~27 s serial ≈ 18 h+ — infeasible same-day, bounded 150 used for acceptance, full job resumed via babysitter `/tmp/run_second_full_loop.sh` (attempt loop, log /tmp/second_full_job.log), still running at commit; (4) access-context session TTL ~30 min then rolling +5 min — long jobs authorize once and are unaffected; (5) concurrent actor on jetson ran anchored v3.2 09:53–10:11Z and /tmp/second_job.log was deleted ~11:24Z (unidentified).

