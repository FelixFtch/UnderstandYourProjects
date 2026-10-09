# UnderstandYourProjects File Tree V1 (2026-10-09)

Same discipline as jarvis-homehub ENTERPRISE_FILETREE: repo top level = delivery
manifest; every runnable unit self-contained under src/; contracts before
implementation; docs classified by reader intent.

```
UnderstandYourProjects/
├── README.md              product direction (EN)
├── AGENTS.md              dev rules: HomeHub is the ONLY identity/policy/audit
│                          authority; UYP adds knowledge only; red lines apply
├── docs/
│   ├── FILETREE_V1.md     this file
│   ├── adr/               decision history (0001: Project Knowledge Domain)
│   ├── EXECUTION_PLAN.md  P0-P11 stages, G0-G9 gates        (exists)
│   ├── AGENTFLOW_ARCHITECTURE.md                            (exists)
│   ├── REFERENCE_ARCHITECTURES.md                           (exists)
│   ├── INVESTIGATION_REPORT_2026-10-09.md                   (exists)
│   └── JETSON_MODEL_STRATEGY.md                             (exists)
├── services/
│   ├── connector-mac/     computer-side Connector: pairing, dir grants,
│   │                      manifest, controlled read, change notify (Tauri/py)
│   ├── indexer/           Jetson-side analysis pipeline
│   │   ├── src/           triage rules -> local classifier -> UA-adapted
│   │   │                  enrichment -> KnowledgeItem staging -> atomic publish
│   │   └── vendor/
│   │       └── understand-anything/   UA v2.9.7 vendored (code only,
│   │                                    node_modules gitignored; adapted via
│   │                                    three-root split: source(RO)/state/output)
│   └── knowledge/         ProjectKnowledge layer in front of knowledge-service
│                          :8790/gbrain - signed identity, ProjectGrant,
│                          evidence/freshness/epoch, project.search/related/
│                          locate/status
├── studio/                Jarvis Studio frontend (assistant-ui + React Flow
│                          + Monaco); calls controlled APIs only
├── jetson/                deployment: systemd units, env, runbooks, canary
│   └── deploy/
├── benchmarks/            model A/B sets (six-prompt set formalized) + triage
│                          eval corpora
└── tools/                 scripts
```

Placement decision for Understand Anything: vendored under
`services/indexer/vendor/understand-anything/` (jarvis-homehub vendoring
discipline + PROVENANCE.md), NOT a submodule (upstream moves fast, we patch
the analyzer contract), NOT at repo root (it is one engine inside indexer).
A deployed copy lives on the Jetson at `~/dev/uyp/` per device discipline.
