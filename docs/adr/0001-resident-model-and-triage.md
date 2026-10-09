# ADR-0001: Resident model profile and local decision triage

Date: 2026-10-09
Status: Accepted (owner decision, end of on-device bake-off)

## Decision

1. The Jetson resident model profile for UnderstandYourProjects is
   **qwen3.5:4b** (Q4, staged on-device). All bulk enrichment calls run with
   `"think": false`. Thinking mode is reserved for the maintenance-tier
   judgement tasks (measured ~11x token/time cost; only mode that answered
   the central-architecture synthesis question correctly).
2. File/question triage is decided locally by **Laya official Q8**
   (ggml-org/Laya-GGUF, 421M, 449MB) served via llama.cpp `/v1/systemone`
   (Jev-compatible choice/score/noul). Runner-up lev-4B kept as alternate
   (higher triage confidence but a dead think-gate). Julia-1, Kev-0.8B,
   GLiNER2.5-Decide rejected (degenerate / weak / not locally loadable).
3. Combined residency: Laya (~0.5GB) + qwen3.5 (3.1GB @2048) = 3.6GB —
   fits beside the voice chain with ~2GB more headroom than today's single
   qwen3-4b-route (5.7GB).
4. Promotion of qwen3.5 into the voice runtime still passes the HomeHub
   model-profile gates; voice chain was paused/restored safely during tests
   (six voice-* units, verified active after).

## Known follow-ups

- Laya calibration on a 30-file labeled set (README over-triage is universal
  across 4B-class: prompt/calibration issue, not model choice).
- JSON brace-extraction fallback for thinking-mode outputs (observed wrap).
- Red lines from docs/EXECUTION_PLAN.md section 8 apply unchanged.
