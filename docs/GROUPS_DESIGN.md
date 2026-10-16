# Jarvis Groups (P10) — Group Knowledge Views and Scoped Retrieval

Status: data model and scoped-retrieval engine, local conformance only.  This
file does not claim that NandaTown group transport or HomeHub group issuance
is deployed.  It extends `AGENTFLOW_ARCHITECTURE.md` (sections 2, 3, and 6)
and adds no second identity, policy, or audit authority.

Implementation: `services/indexer/src/groups.py`, pinned by
`services/indexer/tests/test_groups.py`.

## Authority boundary

A Jarvis group opens a bounded slice of this box's project knowledge to a
named set of HomeHub members — "这个群只开放这些知识".  HomeHub remains the
only authority for identity, membership decisions, policy, revocation, and
audit (AGENTS.md rule 1).  The engine in `groups.py` only:

- keeps the **local, owner-authored record** of which groups exist, who
  their members are, and which project/source slice each group opens
  (`state/groups.json` — an input to HomeHub group issuance and the local
  clamp for retrieval, never a grant store);
- **validates** a HomeHub-issued group context projection, fail-closed, the
  same discipline as `homehub_adapter.validate_context`;
- **filters** knowledge items to a group's view *before* retrieval;
- **reports** which files a proposed answer cites fall outside the view
  (input for the future scrubbing step);
- exposes the **cache invalidation hook** for membership/view changes.

It never issues a grant, widens a scope, mints a member, or decides that
two people are the same.

## The P10 chain as designed

```text
NandaTown group identity (group invite: transport + review input, never a grant)
  -> HomeHub group-issuance (owner-approved policy -> group context projection)
  -> UYP scoped retrieval (this engine: validate -> registry -> membership
       -> view intersection -> pre-retrieval filter)
  -> evidence answer (synthesis over in-view items only -> source overlap
       check -> scrub) -> HomeHub audit
```

1. **NandaTown group identity.**  A group invite travels as a
   `federation_protocol.validate_group_invite` draft: opaque capability ids
   the owner reviews; it is never itself a membership grant.  NandaTown is
   discovery and transport only (AGENTFLOW section 2, federation plane).
2. **HomeHub group-issuance.**  The owner approves the group policy
   (members, project/source view, TTL, share policy).  HomeHub resolves the
   requesting member and issues a short-lived **group context projection**
   (below) — the group-scoped analogue of the per-principal `AccessContext`
   that `homehub_adapter` validates today.
3. **UYP scoped retrieval** (`groups.scoped_retrieval`) — fail-closed:
   strict context validation; the group must exist locally; the requesting
   member must be its owner or a listed member; the effective view is the
   **intersection** of the HomeHub-issued scopes and the group's registered
   knowledge view; only then are items filtered.  Any invalid input yields
   no results — never a fallback to the unscoped store.
4. **Evidence answer.**  `knowledge_search.answer` runs over the scoped
   items only (permission filtering happens before retrieval, per
   AGENTFLOW section 3).  The proposed answer's cited files are then
   checked with `groups.source_overlap`; anything outside or unresolvable
   is reported for the scrubbing step.

## The groups file (`state/groups.json`)

Resolved from `UYP_GROUPS_FILE`, else `{UYP_STATE_ROOT:-~/dev/uyp/state}/groups.json`.
Atomic locked writes, mode `0600`, schema-versioned; a read never creates
the file.  Unknown fields — in particular tokens, grants, AccessContexts,
and filesystem paths — are dropped by design.

```json
{
  "schema_version": "uyp.groups.v1",
  "updated_at": "2026-10-10T12:00:00Z",
  "groups": [
    {
      "group_id": "group:research",
      "name": "Research group",
      "owner_member": "member:lee",
      "member_members": ["member:lee", "member:chen"],
      "knowledge_view": {"project_ids": ["project:alpha"], "source_ids": ["connector:alpha"]},
      "town_run_id": null,
      "created_at": "2026-10-10T00:00:00Z",
      "grant_epoch": "epoch-1d0b6aa5f7c2"
    }
  ]
}
```

| field             | meaning |
| ----------------- | ------- |
| `group_id`        | safe id (`[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}`); unique in the file |
| `name`            | display label (bounded text) |
| `owner_member`    | the HomeHub member who owns/defines the group |
| `member_members`  | HomeHub members of the group (deduped, ≤64; `members` is accepted as an input alias) |
| `knowledge_view`  | the slice this group opens: `{"project_ids": [...] \| "*", "source_ids": [...] \| "*"}` |
| `town_run_id`     | nullable transport routing only: which NandaTown run carries this group's messages (else `UYP_NANDATOWN_RUN_ID`, else messaging answers an honest 503).  Never an access signal — changing it does not re-issue `grant_epoch`.  Run creation stays with the town admin; this is mapping. |
| `created_at`      | set on create, preserved on every update |
| `grant_epoch`     | cache-invalidation epoch; see below |

**Epoch re-issue rules.**  `add_member` / `remove_member` / `set_view`
re-issue `grant_epoch` only on a *real* change (a no-op never invalidates
caches).  A wholesale `upsert` without an explicit epoch inherits the prior
epoch when owner+members are unchanged and re-issues when they are not.  An
explicit `grant_epoch` (e.g. a HomeHub reissue marker) always wins.

**Fail-closed load.**  A missing file is a pending state (empty document);
a corrupt, oversize, wrong-schema, or partially malformed document yields
empty or drops the malformed record — a group that cannot be fully
validated is an unknown group, and an unknown group has no results.

## The group context projection

What HomeHub group-issuance hands the box (transport TBD: HomeHub endpoint,
signed message, or request-carried projection):

```json
{
  "group_id": "group:research",
  "member_id": "member:chen",
  "jarvis_node_id": "jetson-1",
  "project_ids": ["project:alpha"],
  "source_ids": ["connector:alpha"],
  "grant_epoch": "epoch-1",
  "policy_digest": "sha256:...",
  "expires_at": "2026-10-10T23:00:00Z",
  "audit_id": "homehub-audit-id",
  "issued_at": "2026-10-10T22:00:00Z",
  "share_policy": "summary_and_evidence_refs"
}
```

`validate_group_context` mirrors `homehub_adapter.validate_context` exactly
in discipline: all nine required fields must be present; `revoked: true` or
`validation` in `{revoked, expired}` is a rejection; `expires_at` must be
ISO-8601 **with timezone** and strictly in the future (an injectable `now`
keeps this testable); scope lists are non-empty strings with duplicates
removed — `project_ids`/`source_ids` also accept the bare string `"*"`.
Optional fields are validated, never inferred: `issued_at` must be
non-empty text, `share_policy` must be one of the federation share policies.
An invalid group context is indistinguishable from no access: callers get
no results, never a fallback.

## Filter semantics

The one scope predicate (`view_allows`, used by `scoped_items`):

- **Wildcard.**  `"*"` in a dimension allows everything in it; a view
  mixing `"*"` with specific ids collapses to exactly `["*"]` (specific ids
  next to a wildcard are redundant).  An empty list is valid and means the
  group sees nothing in that dimension.
- **Spelling conventions.**  An item's project is its output-root directory
  (`_out_path`, as in `query_api.scope_allows`); a view entry matches the
  bare root (`alpha`) or the HomeHub capability spelling (`project:alpha`).
  A source matches the item's `source` field (`mac-connector`), its
  `source:` spelling, or the project-derived `connector:<root>`.  Project
  and source are ANDed.
- **Unattributable items** (no `_out_path`, no explicit project) are
  visible only under a wildcard — never under a specific view.
- **Intersection** (`intersect_views`, used by `scoped_retrieval`): the
  effective view is context ∩ registered view.  `"*"` defers to the other
  side; disjoint lists meet to the empty view.  A HomeHub wildcard grant is
  therefore clamped to what the group actually opens — the core primitive.

`scoped_retrieval(items, context, registry)` composes the whole pipeline
and is the single entry point a caller needs.  With a registry provided it
is mandatory: unknown group, or a member who is neither owner nor listed,
yields `[]`.  `registry=None` scopes by the validated context's own view
only (mirroring how non-group search trusts a HomeHub projection).

## Answer-source overlap (scrubbing input)

`source_overlap(answer_sources, group_view, items)` takes the `sources`
list of a `knowledge_search` result and resolves each cited file against
the **full candidate item set** (not just the in-view slice).  It reports
`in_view`, `out_of_view` (resolved to a project/source outside the view —
including the ambiguous case where the same relpath also exists in an
out-of-view project), `unresolved` (no indexed occurrence — a hallucinated
path), and `clean` (nothing outside, nothing unresolvable).  Fail-closed:
a citation that cannot be proven inside the view is not clean.  The future
scrubbing step (below) will rewrite or refuse answers that are not clean.

## Cache invalidation hook

Per-group result caches (when they arrive) store `membership_snapshot(group)`
next to the cached payload and revalidate on read with
`membership_stale(current_group, snapshot)`.  Staleness is epoch-first —
every registry membership or view change re-issues `grant_epoch` — with
owner/member-set/view comparison as the backstop for hand-edited files.
Fail-closed: a deleted group, an incomplete record, or a malformed snapshot
is always stale; a cache that cannot be proven fresh is never served.

## What this engine covers

- `GroupRegistry` CRUD over `state/groups.json` (atomic, locked, 0600,
  fail-closed load) with epoch re-issue on real membership/view changes.
- `validate_group_context` — strict, fail-closed group projection checks.
- `view_allows` / `scoped_items` / `intersect_views` — the pre-retrieval
  scope filter and view algebra.
- `source_overlap` — the answer-citation diff against a view.
- `membership_snapshot` / `membership_stale` — the cache invalidation hook.
- `scoped_retrieval` — the composed fail-closed engine entry point.

## What waits

- **NandaTown group transport** — group MESSAGING now exists
  (`nandatown_client.py` + the query API send/receive/history wiring in
  `docs/QUERY_API.md` "Group messaging"; pinned by
  `tests/test_nandatown_wiring.py`): per-recipient fan-out sends, a
  poll-loop receive path into `state/groups/<id>/messages.jsonl`, and a
  member-scoped history endpoint.  What still waits here: per-group run
  CREATION automation (the town admin API provisions runs and join
  tokens; the registry only maps `town_run_id`), and group
  invites/queries as `federation_protocol` envelopes (the current
  transport is chat messages, not invite drafts).
- **HomeHub group-issuance** — the endpoint that resolves a member inside a
  group and issues the projection above.  Until it exists, messaging uses
  the same pre-issuance local bridge as group search (registry record +
  requesting member), so HomeHub revocation of a messaging grant cannot be
  expressed yet.
- **Group device actions** — `POST /api/groups/{id}/device-actions` now
  validates a stronger HomeHub group projection when one is available. The
  projection must explicitly carry `device_ids` and `action_ids` capability
  scopes; a knowledge or NandaTown messaging context is insufficient. The
  UYP adapter currently returns only a provider-neutral `dry_run` plan for
  HomeHub's existing `/api/studio/home-devices/<id>/actions` route. Live
  execution stays fail-closed until HomeHub issues a group device-action
  delegation and records the corresponding audit event.
- **Voice-originated sends** — the voice chain's `group_knowledge` seam is
  read-only (list + search).  A spoken send would need a POST turn there;
  the API side already accepts the loopback `X-Agent-Member` tier.
- **Answer synthesis scrubbing** — rewriting or refusing a non-clean answer
  (`source_overlap` is the input; the canonical miss sentence from
  `knowledge_search` is the refusal shape).
- **Per-group result caches** — the snapshot/staleness hook exists; no
  cache layer stores anything yet.
- **UI** — Studio group views: the Groups workspace now shows the live
  group list, message history, and a real composer (offline demo content
  remains the fallback); a view editor and member management still wait.
- **Audit surfacing** — group queries and group messages must land in
  HomeHub audit events; the projection already carries `audit_id`.

## query_api integration

The HTTP surface landed on `feat/groups-api` (see `docs/QUERY_API.md` for
the endpoint contracts): `POST /api/groups` (owner-authored create,
optionally carrying `town_run_id`), `GET /api/groups` (owner pin sees all,
member sees own), `POST /api/groups/{id}/search`, and
`DELETE /api/groups/{id}` (dissolve, owner only).  Group messaging
(`POST /api/groups/{id}/messages` send, `GET /api/groups/{id}/messages`
history, plus the background receive loop) landed on
`feat/nandatown-messaging`.  The search handler is exactly the pipeline below, plus the
voice-chain preemptive lock (group search touches
`/tmp/uyp_interactive.lock` before synthesis so indexing yields):

```python
from groups import GroupRegistry, scoped_retrieval   # src/groups.py

# do_POST /api/groups/{id}/search - the group context arrives as a
# HomeHub-issued X-Group-Context projection, or is constructed locally
# from the registry record + the requesting member (the pre-HomeHub
# bridge; scoped_retrieval still clamps it to the registered view):
allowed_items = scoped_retrieval(
    [item for values in grouped_items().values() for item in values],
    group_context_projection,
    registry=GroupRegistry(),
)
result = search_answer(question, allowed_items)
# post-synthesis, before responding:
report = groups.source_overlap(result["sources"], effective_view, all_items)
if not report["clean"]:
    ...  # refuse: speak the canonical miss sentence instead
```

Deployment note: `query_api.py` now imports `groups`, so the Jetson copy
step must ship `groups.py` alongside it into `~/dev/uyp/indexer/`.

`/api/health` and `/api/studio/snapshot` stay principal-scoped; the group
tier is search-only initially.  The knowledge count in health remains the
principal scope, so a group query can never be observed through it.
