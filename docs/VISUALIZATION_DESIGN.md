# UnderstandYourProjects visualization design

Status: first product design pass, 2026-10-09

## Design read

Reading this as a local product console for heavy AI developers, NAS users, researchers, and small engineering teams whose job is to locate, understand, verify, and reuse project knowledge. The interface uses an editorial operations workspace: calm mineral surfaces for orientation, a dark graph map for deep inspection, and evidence cards that make every answer traceable.

The first screen is a **Project Cockpit**. The existing ReactFlow dashboard becomes the **Project Map** detail view. This changes the reading order from “open a graph and decode it” to “understand project state, choose a question, inspect evidence, then open the graph when structure matters.”

## Reference translation

The design study used Langflow's official visual-editor documentation and OpenCode's official product/docs pages as pattern references. Langflow demonstrates a canvas where relationships are manipulated directly, with zoom-to-fit, smart guides, notes, a playground, and logs available around the workspace. OpenCode demonstrates a keyboard-first agent surface with primary/subagent modes, multi-session work, shareable sessions, and an explicit plan/build distinction. We borrow those interaction principles while keeping this product read-only and evidence-oriented: the canvas explains project knowledge, the command bar scopes retrieval, and the inspector explains provenance.

- [Langflow visual editor](https://docs.langflow.org/concepts-overview) — study canvas navigation, relationship edges, zoom, notes, playground, and logs.
- [OpenCode agents](https://docs.opencode.ai/docs/agents/) — study visible agent modes, primary/subagent hierarchy, keyboard switching, and agent-specific appearance.
- [OpenCode product surface](https://opencode.ai/) — study multi-session, share links, privacy-first positioning, and a direct developer workflow.

The product should not copy their branding or layout. It should apply the same clarity principles to project facts, source ranges, graph relations, index jobs, and Jarvis scopes.

## Research translation: graph, conversation, and privacy

Understand Anything already has the right deep inspection primitives: a structural code graph, domain and flow views, plain-language node summaries, guided tours, semantic search, impact paths, and layer visualization. The Studio keeps those views inside `Map`, while the workspace adds the missing project-level reading order: `Today → Projects → Ask Jarvis → Evidence → Activity → Groups → Privacy & audit`. This prevents a large force-directed graph from becoming the first and only explanation of a codebase.

- [Understand Anything on GitHub](https://github.com/alexhraber/understand-anything) — graph nodes, relationships, tours, summaries, semantic search, and impact exploration.
- [Understand Anything knowledge design](https://github.com/Egonex-AI/Understand-Anything/blob/main/docs/superpowers/specs/2026-04-09-understand-knowledge-design.md) — typed code/knowledge graphs and the vertical knowledge-reading model.

The graph conversion is deliberate: `GraphView` remains the structural map, `DomainGraphView` becomes a domain/flow layer, and `KnowledgeGraphView` becomes the reading layer for articles, entities, topics, claims, and source references. A project card and an answer can link to the same node, bounded source range, commit anchor, knowledge epoch, and freshness state. Graph JSON remains a read-only result of the indexer; the Studio does not write `.ua` output into source projects.

`Ask Jarvis` and `Groups` are first-class navigation surfaces rather than secondary actions. The conversation view keeps the question, current audience, producing Jarvis, evidence chips, and the composer together. A group view uses a connection card, a live attributed transcript, and a HomeHub approval preview. It shares summaries and evidence references by contract; it never exposes a remote Jarvis's raw source or vector store.

Privacy is visible at three levels: a global trust bar below the command bar, a scope chip on each answer/evidence/group card, and the full `Privacy & audit` trace page. The UI can display `Private project`, `Owner group`, and `External group` as HomeHub projections with grant epoch, expiry, and audit trace. It cannot create, infer, or revoke a permission. The iPhone Jarvis patterns we reuse are the central Jarvis entry point, left/right chat bubbles, voice/identity status, a bottom composer, privacy rings, sync/device status, and `Will see / Won't see` approval cards from the existing HomeHub designs.

### Visual hierarchy for trust-sensitive actions

The three trust-sensitive surfaces intentionally use different visual treatments:

- **Ask Jarvis** is a dark, high-contrast conversation stage. The transcript, producing Jarvis, scope lock, evidence chips, and composer read as one focused room instead of another dashboard card.
- **Groups** begins with a dark boundary rail, then a three-step group builder: invite Jarvis, set the visibility window, and review the HomeHub approval. The form is a draft until HomeHub returns a grant.
- **Privacy & audit** uses three permission cards with explicit content rows: project summaries, evidence references, and raw source ranges. Each row has an allowed/grant/hidden/never state, so the user can understand what will be shared before reading the epoch and audit trace.

The surface hierarchy is part of the product contract. A user should recognize the action type from the visual treatment before reading every label, while the actual authority and decision remain in HomeHub.

## Product information architecture

### Global workspace

These surfaces describe the workspace and are not permission authorities. They consume HomeHub `AccessContext` and connector health.

| Surface | User question | Primary visualization | Required data |
| --- | --- | --- | --- |
| Projects | What do I have and what should I open? | project list/cards, freshness, source badges, reuse signals | `ProjectSummary`, `KnowledgeHealth`, `SourceRef[]` |
| Search | Where is the answer and why should I trust it? | evidence result cards with source ranges | `RetrievalResult`, `EvidenceRef[]`, `AccessContext` |
| Sources & devices | What is connected and what is allowed? | connector table, manifest preview, grant state | HomeHub source/grant status; connector manifest |
| Jobs & updates | What is being indexed? | queue, staged/running/failed timeline | `IndexJob`, queue events, knowledge epoch |
| Jarvis groups | Which Jarvis can share which context? | member list, scope chips, TTL/epoch, provenance | group membership and remote query grants |
| Privacy & audit | Why did this result appear? | access trace and revocation state | HomeHub audit/trace projection |

### Project detail

| Tab | Purpose | Existing component to evolve |
| --- | --- | --- |
| Summary | goal, stack, current health, key entry points, related projects | `ProjectOverview` |
| Map | structural, domain, and knowledge graph exploration | `GraphView`, `DomainGraphView`, `KnowledgeGraphView` |
| Evidence | cited snippets, source ranges, fact/inference labels | `NodeInfo`, `CodeViewer` |
| Files | authorized source tree and file-level status | `FileExplorer` |
| Changes | source commit versus knowledge epoch, affected nodes | `DiffToggle`, `StalenessBanner` |
| Reuse | related projects and candidate modules | new retrieval surface |

The current dashboard has most of the Project Map primitives already. They should remain focused on one project. Cross-project concerns belong in the global workspace so the graph never has to become a permission or navigation system.

## Project Cockpit layout

The desktop cockpit uses a 248 px workspace rail, a 70 px command bar, and a 12-column content canvas capped at 1,440 px. The first viewport contains:

1. Project identity, purpose, source/commit anchor, last analysis, and a clear `Explore graph` / `Ask Jarvis` action.
2. Four compact state cards: indexed files, relationships, logical layers, and project health derived from actual graph data.
3. An orientation map showing the project center and its highest-level layers. This is a navigation preview, not a second graph engine.
4. Composition bars that explain code share, layer coverage, and complexity to review.
5. High-signal entry points ranked by relationship count, each opening the existing node inspector.
6. An evidence trail showing what is known, when it was analyzed, and whether collaboration data is connected.
7. A Coding Agent handoff card that promises bounded, cited evidence rather than an unbounded repository dump.

The mobile layout collapses the rail into a horizontal navigation strip, keeps search reachable, uses two-column state cards, and moves the graph preview below the project identity. Graph exploration remains a secondary action on small screens.

## Visual system

The system deliberately has two related surfaces:

- **Studio surface:** `#F4F4F0` background, paper panels, deep green-black ink, teal for active retrieval, lime for healthy sync, coral for review risk, and muted purple for domain concepts. Use 12–14 px panel radii, 1 px borders, and restrained shadows.
- **Map surface:** the existing dark graph theme with its gold accent and node-type colors. Keep it for high-density structural inspection; do not use it for the default workspace landing page.

Typography uses the existing DM Serif Display for project names and Inter/JetBrains Mono for operational labels, commit hashes, paths, counts, and timestamps. The cockpit has a 10 px uppercase kicker, 11–14 px body text, and a 32–54 px project title. Chinese and English labels must wrap without changing the card height unexpectedly.

The interface avoids decorative AI gradients, fake metrics, generic three-card marketing layouts, and unlabelled demo content. Every metric comes from an indexed graph or is shown as `Not connected`, `Partial`, `Unknown`, or `Revoked`.

## Evidence visual language

Every answer, node, and search result needs a visible evidence ladder:

```text
Conclusion
  -> evidence type: fact | structural | inference | unavailable
  -> source project / device / connector
  -> path + line range or symbol
  -> source commit/hash and knowledge epoch
  -> freshness and access/grant status
```

Use a compact evidence strip on result cards. A result is not complete if it only gives a score or node name. `Why this result` should show the matched symbol, path, graph relationship, or semantic field that caused the hit. The UI must never imply that an answer is current when the connector is stale, offline, partially indexed, or revoked.

## Interaction rules

- `Ask Jarvis` opens project-scoped retrieval with the current HomeHub access context. It does not change identity or ACL state.
- `Explore graph` enters the existing map. The map is read-only and can only reveal nodes that have already passed the server-side access filter.
- A result card opens a bounded `CodeViewer` range with path, line numbers, commit/hash, evidence type, and freshness. A raw file jump requires a new HomeHub grant.
- `Reindex`, `Retry`, `Reconcile`, and `Export` are server operations. The UI must show disabled, queued, running, failed, succeeded, offline, and revoked states with a reason and a retry path.
- Any loading surface must show the last known state and the job/epoch that produced it; a spinner alone is insufficient.
- Motion is reserved for state changes: a new index job enters the queue, a graph layer expands, a result opens its evidence drawer, or a source transitions to stale. Reduced-motion mode removes transforms and keeps the same hierarchy.

## HomeHub boundary

UnderstandYourProjects displays identity and authorization results; it does not own them. HomeHub remains the only authority for principal, device ownership, policy, revocation, and audit. The visualization receives a signed or server-validated access projection containing the principal, source/project scope, grant epoch, policy digest, freshness, and audit/trace id. It should display those fields where they help trust, but it must not persist a replacement ACL or infer permission from a visual persona selector.

Jarvis Groups show the producing Jarvis, allowed project/source scope, grant TTL/epoch, and provenance. Sharing sends a bounded retrieval request or evidence/summary result. It does not expose another Jarvis's raw vector store, source database, or arbitrary files.

## State matrix

The visual layer needs a shared state vocabulary:

| State | Meaning | UI treatment |
| --- | --- | --- |
| `current` | source and knowledge epoch agree | healthy dot, timestamp, normal actions |
| `stale` | source changed after last successful analysis | amber/coral banner, changed count, reconcile action |
| `partial` | deterministic structure exists but semantic enrichment is incomplete | partial badge, explain missing fields |
| `offline` | connector unavailable | offline badge, last successful sync, retry |
| `failed` | job or connector failed | error reason, logs/evidence id, retry |
| `revoked` | HomeHub withdrew access | lock state, no source contents, request access action |
| `unsupported` | file/source type is outside the current indexer | clear reason, no false completeness |

The graph being renderable is not the same as the project being synchronized. The cockpit must show those as separate facts.

## Implementation sequence

1. Ship the Project Studio shell and `/projects/:id` navigation using the current graph as the only real data source.
2. Add typed `ProjectSummary`, `KnowledgeHealth`, and `EvidenceRef` payloads to the connector/indexer boundary.
3. Upgrade global search from the current five-node fuzzy view to ACL-filtered evidence results with source/version/freshness fields.
4. Add sources/devices and jobs surfaces, including manifest dry-run and incremental index epochs.
5. Add owner-group plus one external Jarvis vertical slice. Keep NandaTown federation and multi-Jarvis management behind the same grant/provenance model.
6. Add the privacy/audit trace projection and Coding Agent handoff endpoint.

This order lets collaborators review a useful project cockpit while the backend contracts are still being hardened. It also keeps the existing graph viewer valuable during the migration.

## Data boundary and install target

The Studio now has a typed adapter boundary in
`packages/dashboard/src/studio-contracts.ts`. It defines `ProjectSummary`,
`KnowledgeHealth`, `EvidenceRef`, `IndexJob`, `SourceSummary`, and the
server-projected HomeHub `AccessContextProjection`. Until the read-only
knowledge API exists, `createStudioSnapshotFromGraph` maps the existing
`KnowledgeGraph` into a clearly labelled `partial` snapshot. This fallback is
useful for review, but it must never be called synchronized source truth.

The build and the appliance runtime are separate steps:

| Environment | Responsibility | Command or artifact |
| --- | --- | --- |
| Mac or CI | install dashboard dependencies, build, run browser review | `pnpm install --frozen-lockfile`; `pnpm --filter @understand-anything/core build`; `pnpm --filter @understand-anything/dashboard build` |
| Jetson Agent Box | run indexer, retrieval API, model services, state, and logs | `~/dev/uyp/indexer/`, `~/dev/uyp/state/`, `~/dev/uyp/output/` |
| Jetson Studio serving | serve the prebuilt static dashboard through the controlled knowledge service | release artifact from the Mac/CI build; a dedicated `jetson/deploy` unit is still pending |

The vendored workspace root's plain `pnpm build` only compiles the skill
package. The dashboard build is the filtered command shown in the table.
These are Mac/CI development and release steps, not model installation
commands. The Jetson can run the same Node toolchain later if an
all-in-one appliance is chosen, but the first deployment should copy a tested
static artifact and keep indexing/inference resource ownership explicit. The
Mac connector remains on each source computer; the browser can be on the Mac,
another workstation, or a NAS client while the Jetson serves the project
knowledge API.

## Readability gate before backend wiring

The Studio uses progressive disclosure: one decision per page, three or four
summary metrics, one primary visualization, then evidence or job details in
cards. Evidence starts with five result cards and keeps path, line range,
knowledge version, and freshness in a readable secondary row. Raw JSON, model
logs, and full manifests do not belong in the first viewport. The current
implementation uses explicit partial/unsupported/awaiting states and an
indeterminate scheduler card rather than a fabricated progress percentage.

Before calling the UI production-ready, capture desktop 1440 px, laptop 1280
px, and mobile 390 px screenshots on a networked Mac after dependencies are
available. Check line wrapping, contrast, focus rings, card clipping, evidence
path readability, and the mobile project table. The source-level transpile
check can pass while browser-level visual QA is still outstanding.

## Verification checklist

- Desktop and mobile screenshots show the project purpose, state, and next action within the first viewport.
- The Studio renders from real graph data and labels unconnected surfaces honestly.
- Long project names, Chinese descriptions, paths, hashes, and bilingual evidence snippets wrap without overflow at 320, 375, 414, 768, and desktop widths.
- Every graph/search/evidence action is read-only unless an explicit server operation is present and HomeHub has authorized it.
- Build and tests pass for the vendored dashboard; the dashboard does not write `.ua` output into source projects.
- A map load, an index synchronization, an evidence answer, and a HomeHub authorization are shown as separate states in the UI.

## Personal timeline and conversation sharing

The Today surface includes a personal project timeline inspired by the mobile
Jarvis experience. It is a readable digest, not a second event ledger. Each
entry is derived from the latest KnowledgeGraph/StudioSnapshot and links back
to the project map or evidence view. The first card answers ‘what did I learn
yesterday?’ with the project name, indexed entity count, layer count,
knowledge health, and the snapshot date. Follow-up rows show structure
availability, connector health, and the next high-signal entry point. When the
timeline has no connector-backed event, it says ‘Snapshot signal’ or
‘Suggested from graph’ instead of inventing a commit or conversation event.

Privacy is modelled as a data inventory before it is modelled as an audience.
The global Your privacy map uses three concentric layers:

| Layer | Purpose | Default meaning |
| --- | --- | --- |
| vault | sensitive working material, private notes, identity implementation | excluded from direct and group defaults |
| trusted | material suitable for a known collaborator or owner circle | opt in through the global draft |
| shareable | prepared summaries, onboarding, and selected examples | inherited by new direct and group drafts |

An audience (this Jarvis, direct chat, or group) is a separate choice.
Every conversation shows Inherited items from its default layers, Added items
selected for that conversation, and Excluded items removed locally. Reset to
default only clears the local draft. The UI never calls those states a HomeHub
grant: the browser surface says Draft only, Demo policy preview, or HomeHub
reviews any real grant until an AccessContextProjection is returned.

The concentric map and the per-conversation scope panel are deliberately the
same vocabulary. The map stays visually large and uncluttered: the ring
receives drops, while three responsive layer trays show every item by name,
type, and source. A user can drag a tray card into the ring to move it between
layers, click it for its project/source detail, or use the selector as a
keyboard-friendly fallback. A user can classify an item once in the global
map, then fine-tune a specific group or one-to-one conversation without
silently changing other conversations. HomeHub remains the only authority for
identity, ownership, policy, revocation, and audit.

The rings are intentionally unfilled dashed outlines. The three yellow tones
identify the vault, trusted, and shareable boundaries without turning the
center into a solid color block.
