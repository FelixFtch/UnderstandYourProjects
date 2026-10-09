# Understand Anything — vendored copy provenance

- Version: 2.9.7 (plugin cache layout, official release channel)
- Imported: 2026-10-09 from local Claude plugin cache
  ~/.claude/plugins/cache/understand-anything/understand-anything/2.9.7/
- Scope: source only; node_modules excluded (reinstall with pnpm/bun on target)
- Planned adaptation (see docs/FILETREE_V1.md + strategy docs):
  - three-root split: source_root (read-only remote), state_root, output_root
    on the Jetson — never write .ua into the analyzed project
  - structure extraction (deterministic) stays as-is; LLM enrichment goes
    through the Ollama adapter with "think": false and pinned language
  - graph/dashboard components feed the Studio via knowledge/ APIs, not direct
