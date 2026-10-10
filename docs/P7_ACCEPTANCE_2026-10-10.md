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
