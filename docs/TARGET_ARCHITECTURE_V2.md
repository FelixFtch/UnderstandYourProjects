# UnderstandYourProjects target architecture

**Status:** Accepted product target, implementation in progress  
**Date:** 2026-10-15

This document records the target agreed for the Jarvis/UnderstandYourProjects
system. It describes the product boundary and the intended execution model; it
does not claim that every adapter or federation endpoint is already deployed.

## 1. One Jarvis, several presentation surfaces

Voice, iPhone, Studio, Coding Agent clients, and Jarvis Groups are different
input/output surfaces over one permission-aware Jarvis core:

```text
Voice / iPhone / Studio / Coding Agent / Group message
                         |
                         v
             HomeHub identity and AccessContext
                         |
                         v
                  Intent Gate / routing
                         |
       +-----------------+------------------+----------------+
       |                 |                  |                |
  Device action     UA / project       Memory query      Normal chat
  HomeHub route     UYP + UA            gbrain            Persona
       |                 |                  |                |
       +-----------------+------------------+----------------+
                         |
                         v
       receipt / evidence / handoff / audit result
                         |
          TTS / Studio / iPhone / Agent Group
```

HomeHub remains the only authority for principal identity, voice identity
evidence, device ownership, policy, grants, revocation, and audit. UYP adds the
project knowledge plane. A Connector, UA worker, gbrain adapter, NandaTown, or
Studio cannot issue or widen a permission.

## 2. Langflow, Studio, and live execution

Langflow is the visual inspection and replay surface. It is not a second Jarvis
runtime and it is not an authorization boundary. The live execution source of
truth remains the HomeHub `agent-runtime` flow specification and registered node
implementation.

The Langflow canvas should show these stages and their branch outcomes:

1. **Understand:** split the request, project the authenticated identity, apply
   HomeHub policy, and assemble context.
2. **Intent Gate:** classify the request as an action, folder/project
   understanding, memory query, agent query, ordinary chat, or clarification.
3. **Retrieve/Act:** show the selected domain, skipped domains, tool arguments,
   evidence, latency, and errors.
4. **Respond:** show the code receipt, evidence-backed answer, remote handoff,
   chat response, and audit reference.

The canvas head makes one live request and downstream visual components inspect
the same turn bundle. Editing a canvas wire must not create a second execution
path or allow the browser to read source files, gbrain tables, or Connector
credentials.

Studio is the user-facing Jarvis surface. Its direct Jarvis conversation uses
the same runtime and policy as voice, but displays text, trace, evidence,
HomeHub status, and handoff state. The Studio should make the following visible
as separate states:

- ordinary conversation;
- a HomeHub device action and its real read-back receipt;
- a UYP/UA project answer and its source evidence;
- a gbrain memory answer and its permitted sources;
- a request sent to another Agent and the attributed remote reply;
- denied, revoked, stale, offline, or partial results.

## 3. Jarvis-to-Jarvis and Group communication

NandaTown is a discovery and transport layer. It is not the final permission
authority and it must never receive a complete gbrain, vector store, or source
tree.

For a remote Agent request, the local Jarvis must:

1. resolve the human and local Jarvis node through HomeHub;
2. check the local group/contact policy and share card;
3. send only a bounded question and approved evidence scope;
4. route the envelope through the Agent Gateway/NandaTown transport;
5. let the receiving Jarvis perform its own local authorization and retrieval;
6. return an attributed answer or evidence reference with expiry and audit data.

Studio Groups can display both forms of interaction:

- **Group knowledge query:** search the authorized group's existing indexed
  history through the UYP Groups API;
- **Agent handoff:** send a new `agent.ask` request to another Jarvis through
  the outbound gateway.

These can share one conversation UI, but the trace must distinguish retrieval
from a live remote handoff. A remote Agent never receives private project files
merely because it is discoverable in NandaTown.

## 4. Intent Gate and fast paths

The target flow keeps HomeHub identity and policy first, then uses a small local
Intent Gate. The gate should return a typed decision such as:

```json
{
  "kind": "device_action | understand | project_query | memory_query | agent_query | chat | clarify",
  "target": "kitchen_light",
  "scope": "current_project",
  "confidence": 0.96
}
```

The gate does not read unauthorized data and does not execute tools. It only
selects the next bounded domain. High-confidence deterministic phrases remain
the fastest path for lights, sensors, scenes, and other simple operations.

Recommended routing:

- `device_action` -> HomeHub governed action -> code receipt -> TTS/Studio;
- `understand` -> Connector grant check -> UA incremental analysis;
- `project_query` -> UYP/UA retrieval with evidence and freshness;
- `memory_query` -> identity-filtered gbrain retrieval and synthesis;
- `agent_query` -> share-card and contact checks -> Agent Gateway/NandaTown;
- `chat` -> Persona directly, without a gbrain preflight;
- `clarify` -> ask one bounded follow-up question.

Laya is the resident implementation of the local Intent Gate on Jetson. The
production `voice-agent-runtime.service` calls the local `/v1/systemone`
endpoint with a bounded score question and maps the returned legend to these
eight domains in one forward pass. It must not manufacture identities, bypass
HomeHub, or call arbitrary tools. High-confidence deterministic phrases still
use the explicit fast lane; every other request fails closed with a retry
message when Laya is unavailable or below the confidence threshold. The
adapter and service wiring are tracked in `jarvis-homehub` commit `3a02969`.

## 5. RAG and project understanding decision

The `skills/*/SKILL.md` and language/framework references inside Understand
Anything are **analysis instructions**, not the project's RAG database. They
tell UA how to parse files, extract symbols, resolve imports, build layers,
generate tours, and enrich bounded items. They are useful during indexing but
are not a replacement for retrieval.

The target knowledge path is hybrid:

```text
Connector grant
  -> Laya triage
  -> UA structure/import/layer/graph analysis
  -> KnowledgeItems + source evidence
  -> UYP scoped retrieval
  -> optional project_knowledge gbrain mirror
  -> gbrain/Persona synthesis over the allowed evidence
```

Use UYP/UA as the project boundary and evidence source. Use gbrain for
identity-filtered memory retrieval, cross-source questions, timelines, and
natural-language synthesis. A project question must never bypass UYP scope,
source epoch, freshness, or revocation checks just because it is mirrored into
gbrain.

This is better than choosing either mechanism alone:

- reference-driven UA analysis gives deterministic structure and precise file,
  symbol, and line evidence;
- UYP provides Connector, project, grant, freshness, and evidence boundaries;
- gbrain provides semantic, temporal, graph-aware retrieval and synthesis;
- HomeHub remains the permission authority before retrieval and before sharing.

The current repository already has the pieces: UA skills and KnowledgeItems,
the UYP Query API, and a bounded `project_knowledge` gbrain publisher. The
durable UYP-to-gbrain publication and invalidation path must remain explicit
and observable rather than being inferred from a successful UI response.

### 5.1 Canonical artifacts and the gbrain mirror

The Agent Box keeps one canonical project-knowledge model under its state
root:

```text
Connector manifest
  -> <state>/<project>/ua/knowledge-graph.json
  -> <output>/<project>/*.knowledge.json
  -> UYP project registry/cache
  -> scoped Query API, Studio, and MCP projections
```

The artifacts have different jobs:

- `knowledge-graph.json` contains files, symbols, logical relationships,
  layers, and guided-tour data;
- each `KnowledgeItem` contains a bounded file-level summary, purpose, key
  points, components, verdict, source version, and optional evidence anchor;
- the Connector manifest records the source-relative path, size, mtime, and
  source epoch;
- the project registry records device, authorized folder path, project ID,
  parent/child relations, IndexJob status, and freshness.

The `project_knowledge` gbrain pages are a **secondary semantic mirror**. A
successful local publish must remain useful when gbrain is unavailable. A
gbrain hit must therefore carry the project, relative path, KnowledgeVersion,
source epoch, and HomeHub grant epoch, then be checked against the current
AccessContext before it is used. Exact file, symbol, line, and source evidence
is hydrated from UYP, never trusted solely from a Markdown mirror.

The desired publication contract is:

```text
IndexJob PUBLISHED
  -> async/idempotent project_knowledge mirror job
  -> write item pages
  -> write complete-version manifest last
  -> expose mirror state and errors

HomeHub revoke / grant epoch change
  -> revoke or tombstone that epoch's pages
  -> invalidate mirror and answer caches
```

The mirror must use a dedicated project brain and namespace. It must never
write project pages into the family brain, expose raw source bytes, or become
the source of folder hierarchy, ACL, revocation, or audit decisions. A failed
mirror job is visible as a degraded semantic index; it does not invalidate a
successfully published UYP/UA version.

## 6. Shared Agent Identity and communication skill

Miku, Felix's Jarvis, Robin's Jarvis, and other participating Agents should use
one protocol skill, provisionally named **HomeHub Agent Identity & Messaging**.
It is a shared protocol/adapter, not a prompt that invents IDs.

HomeHub issues and revokes the identity card. The skill exposes it to clients:

```text
principal_id       human account resolved by HomeHub
jarvis_node_id     one enrolled Agent Box
agent_urn          stable communication identity for that node
jarvis_number      human-friendly display number derived from node identity
group_id           collaboration group
contact_id         verified HomeHub contact record
session_id         one interaction session
request_id         one request and audit unit
```

The human-friendly `J-1234-5678` number and NandaTown participant name are
discovery/display values. They are not permission keys. Email addresses, IP
addresses, hostnames, and model names must not be used as Agent identity.

The reusable skill should provide these bounded operations:

```text
identity.describe()              -> public node card, capabilities, key fingerprint
identity.verify(peer_card)       -> HomeHub signature, expiry, revocation, audience
directory.discover()             -> public NandaTown/Gateway metadata
contact.invite(contact)          -> one-time HomeHub-reviewed invitation
contact.accept(invite)           -> verified contact record
message.send(question, scope)    -> bounded, expiring, attributed envelope
message.receive(envelope)        -> verify, authorize locally, then dispatch
group.list/create/invite         -> HomeHub membership and share policy
audit.reference(request_id)      -> HomeHub audit projection, never a secret
```

Every message envelope should include sender node, receiver node, request ID,
nonce, issued time, expiry, group/contact ID, requested scope, share policy,
and an authorization/delegation reference. Secrets, bearer tokens, full source
paths, and private gbrain contents are never returned by the skill.

Other AI Agents can implement the same skill through MCP or a small HTTP/OpenAPI
adapter. They still need HomeHub enrollment or a verified invitation; a shared
skill alone cannot make an unregistered Agent trusted.

## 7. Implementation order

1. Add the Intent Gate contract and latency trace without changing HomeHub
   authority or existing voice receipts.
2. Move ordinary chat before the gbrain preflight; query gbrain only for an
   explicit memory/cross-source request.
3. Keep UA/UYP project retrieval separate from family-memory retrieval and make
   project-to-gbrain publication/revocation observable.
4. Make the Langflow Studio canvas display the same branch decisions, evidence,
   handoffs, and skipped nodes as the live runtime.
5. Expose Studio Jarvis threads and Group threads through the same identity and
   share-card contracts.
6. Implement the shared HomeHub Agent Identity & Messaging skill for Miku and
   Jarvis, then add NandaTown federation after local authorization and revoke
   behavior are verified.

## 8. Unified Understanding surface

The product target includes one discoverable **Understanding** workspace that
combines the existing UA graph and UYP project projections. It is not a new
analysis engine and it is not a second authorization surface.

The workspace should present:

```text
left:   project and authorized-folder tree
center: UA structure graph, layers, relations, and guided tour
right:  selected KnowledgeItem / file / symbol / evidence inspector
bottom: IndexJob, source freshness, KnowledgeVersion, source epoch,
        Git commit (when available), grant epoch, and gbrain mirror state
```

The first screen should make these states obvious: current, analyzing,
queued, stale, failed, offline, revoked, partial, and graph-only preview. A
user must be able to move from a project to a file, symbol, line range, source
version, and then to the Jarvis answer that cited it without searching for a
different app or route.

The existing ProjectStudio and classic UA graph are the initial implementation
of this target. They currently live behind the vendored dashboard's **Studio**
button and graph view; `#/understanding` is a product route to add, not a
currently registered route. Studio API calls must resolve the caller's
HomeHub bearer/AccessContext rather than relying on one process-wide context
file, so multiple users and expired sessions cannot see the wrong projection.

## 9. Folder hierarchy and incremental understanding

An authorized Connector root and a separately authorized nested folder are
different cases:

1. A new file or subfolder inside an existing grant keeps its relative path in
   the Connector manifest. Events create a deterministic incremental IndexJob;
   unchanged staged bytes are reused by size/mtime, and the next atomic
   project version removes deleted items during a full reconciliation.
2. A separately analyzed nested folder receives its own project ID. On the
   same device, the registry links it to the deepest registered ancestor using
   `parent_id` and `children`. Parent/child summaries and existing items may
   seed the new job, but each project retains its own grant and evidence
   boundary.

The UA graph is a logical code graph and does not itself replace the folder
tree. Directory nodes and parent/child navigation belong in the UYP registry
projection. Cross-device paths do not become parent/child relations, and two
folders with the same name receive distinct opaque project IDs.

## 10. Completion gates

The target is complete only when all of these are demonstrated with live
evidence:

1. Voice, iPhone, Studio, Coding Agent, and Group messages enter the same
   identity -> policy -> Intent Gate -> domain route.
2. A simple device action uses the governed HomeHub route and returns a real
   read-back receipt; a denied or revoked action is rejected by the same route.
3. An authorized folder produces a UA graph, KnowledgeItems, evidence
   anchors, source/version metadata, and a visible project hierarchy.
4. A file addition, modification, and deletion produce the expected
   incremental IndexJob and updated project version.
5. A project query combines exact UYP/UA evidence with optional gbrain
   semantic recall, while ordinary chat skips an unnecessary gbrain preflight.
6. A published KnowledgeVersion can be mirrored to the dedicated gbrain brain,
   searched under the same HomeHub scope, and revoked by grant epoch without
   leaking a page or citation.
7. Langflow shows the same live branch decisions and results as the runtime;
   its canvas is inspectable but cannot create a second execution or auth path.
8. A Jarvis-to-Jarvis group query returns an attributed, bounded answer and
   audit reference without exposing another owner's source tree or database.

