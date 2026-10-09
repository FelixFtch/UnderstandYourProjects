# UnderstandYourProjects visualization design

Status: first product design pass, 2026-10-09

## Design read

Reading this as a local product console for heavy AI developers, NAS users, researchers, and small engineering teams whose job is to locate, understand, verify, and reuse project knowledge. The interface uses an editorial operations workspace: calm mineral surfaces for orientation, a dark graph map for deep inspection, and evidence cards that make every answer traceable.

The first screen is a **Project Cockpit**. The existing ReactFlow dashboard becomes the **Project Map** detail view. This changes the reading order from “open a graph and decode it” to “understand project state, choose a question, inspect evidence, then open the graph when structure matters.”

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

## Verification checklist

- Desktop and mobile screenshots show the project purpose, state, and next action within the first viewport.
- The Studio renders from real graph data and labels unconnected surfaces honestly.
- Long project names, Chinese descriptions, paths, hashes, and bilingual evidence snippets wrap without overflow at 320, 375, 414, 768, and desktop widths.
- Every graph/search/evidence action is read-only unless an explicit server operation is present and HomeHub has authorized it.
- Build and tests pass for the vendored dashboard; the dashboard does not write `.ua` output into source projects.
- A map load, an index synchronization, an evidence answer, and a HomeHub authorization are shown as separate states in the UI.
