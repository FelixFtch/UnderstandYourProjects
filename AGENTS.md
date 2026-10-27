# UnderstandYourProjects — development rules

## Current product direction (accepted 2026-10-27)

The user approved the Pi native-home architecture. Start with
`docs/PI_NATIVE_HOME_TRANSITION_20261027.md`; the canonical architecture and
execution plan live in `jarvis-homehub/docs/plan/PI_NATIVE_HOME_*`.
For this work, those documents supersede the older UA/Jetson/Studio product
target. HomeHub remains the only authority. OpenClaw owns the new Pi assistant
and scheduler; gBrain owns long-term retrieval. Do not add UA analysis loops,
global semantic routing, another agent runtime, or another permission system.
The product has native iPhone and macOS Apps; Studio and Connector contribute
reusable functionality, not additional permanent product surfaces.
Jetson and XVF3800 are out of scope and must not be changed. Parallel agents
may edit assigned local files; only the Integrator may deploy to live devices.
Unavailable/stale devices are excluded from migration. Build success never
substitutes for actual App playback, device read-back, or deployment evidence.

1. HomeHub (jarvis-homehub) stays the ONLY authority for identity, device
   ownership, policy, revocation, and audit. This repo adds project knowledge,
   indexing, retrieval, and evidence — nothing else.
2. Red lines from docs/EXECUTION_PLAN.md section 8 apply to every change.
3. For maintenance of the retained historical implementation, Understand
   Anything is vendored under services/indexer/vendor/ — patch it
   there, never write analysis outputs into source projects (.ua stays inside
   state_root).
4. Models: enrichment calls always use "think": false; language is pinned in
   prompts; see docs/JETSON_MODEL_STRATEGY.md before changing resident models.
5. Git: explicit file adds only; no secrets in repo; push with the proxy rule.
