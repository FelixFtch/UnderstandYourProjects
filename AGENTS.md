# UnderstandYourProjects — development rules

1. HomeHub (jarvis-homehub) stays the ONLY authority for identity, device
   ownership, policy, revocation, and audit. This repo adds project knowledge,
   indexing, retrieval, and evidence — nothing else.
2. Red lines from docs/EXECUTION_PLAN.md section 8 apply to every change.
3. Understand Anything is vendored under services/indexer/vendor/ — patch it
   there, never write analysis outputs into source projects (.ua stays inside
   state_root).
4. Models: enrichment calls always use "think": false; language is pinned in
   prompts; see docs/JETSON_MODEL_STRATEGY.md before changing resident models.
5. Git: explicit file adds only; no secrets in repo; push with the proxy rule.
