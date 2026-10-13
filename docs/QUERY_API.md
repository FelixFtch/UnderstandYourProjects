# Jetson Query API

`services/indexer/src/query_api.py` is the first server adapter between the
Jetson knowledge store and Studio. It wraps the existing `knowledge_search.py`
proof of concept; the browser never calls Ollama or a Connector directly.

The cross-service tool and event boundary for project automation is defined in
[`UYP_TOOL_CATALOG_AND_AUTOMATION_CONTRACT_V1.md`](UYP_TOOL_CATALOG_AND_AUTOMATION_CONTRACT_V1.md).
That contract is intentionally separate from this read-only HTTP surface:
HomeHub owns tool admission, device capabilities, automation schedules, and
audit; UYP owns the project tools and durable IndexJob events.

## Run

```bash
UYP_OUTPUT_ROOT=~/dev/uyp/output \
UYP_STATE_ROOT=~/dev/uyp/state \
UYP_ACCESS_CONTEXT_FILE=~/.config/uyp/access-context.json \
python3 services/indexer/src/query_api.py --port 8787
```

For the production Jetson service, configure HomeHub as the live policy
transport. When this URL is present it takes precedence over any copied
projection file, so a transport failure cannot accidentally keep using a
stale context after revocation:

```bash
export UYP_HOMEHUB_ACCESS_CONTEXT_URL=http://127.0.0.1:5120/api/uyp/access-context
export UYP_HOMEHUB_TOKEN_FILE=~/.config/uyp/homehub.token
```

The token is a HomeHub Companion bearer provisioned by the pairing/session
flow. It is not the Connector token. The adapter validates the returned
projection and fails closed when HomeHub is unavailable.

The default bind is `127.0.0.1`. `--lan` is an explicit deployment choice and
must sit behind the approved transport. `UYP_STUDIO_API_URL` points the web
build at this service, for example `http://127.0.0.1:8787` during a local
development session. The Studio build variable is `VITE_STUDIO_API_URL`.

## Read-only endpoints

| Endpoint | Purpose | Authority boundary |
| --- | --- | --- |
| `GET /api/health` | service, output, connector, and AccessContext presence | does not infer access |
| `GET /api/studio/snapshot` | project, source, health, evidence, and IndexJob projection | only publishes HomeHub context when supplied |
| `GET /api/knowledge-graph` | vendored Understand Anything graph projection | returns `503` until HomeHub supplies an AccessContext |
| `GET /api/sources` | source projection for the Agent Box surface | source grant is not created here |
| `GET /api/connectors` | durable multi-connector health and manifest projection | metadata-only without HomeHub; never mints pairing or grants |
| `GET /api/index/jobs` | persisted IndexJob phase/progress projection | requires HomeHub scopes; grant IDs and filesystem paths are omitted |
| `GET /api/projects/{id}/graph` | caller-scoped bounded Understand Anything graph | requires the caller's HomeHub bearer/context; structural metadata only, source-bearing content removed |
| `POST /api/knowledge/search` | bounded lexical retrieval plus Qwen synthesis | requires a HomeHub AccessContext and filters before synthesis |
| `POST /api/groups` | create a group record (owner-authored) | caller principal must be the record's `owner_member`; registry-validated |
| `GET /api/groups` | list groups | `UYP_OWNER_MEMBER` pin sees all; others see only groups they own or belong to |
| `POST /api/groups/{id}/search` | group-scoped knowledge search ("不同群看到不同知识") | `X-Group-Context` projection or registry+member; `scoped_retrieval` filters before synthesis; out-of-view citations are refused with the canonical miss sentence |
| `POST /api/groups/{id}/messages` | a member sends a group message over NandaTown | member-scoped like group search (non-member 403); per-recipient fan-out with distinct message_ids; a transport failure is an honest 503 carrying `error_code` and persists no echo — delivery is never faked |
| `GET /api/groups/{id}/messages?limit=` | a group's local message log (chat history) | member-scoped; the append-only record of this box's sends (echo) and receives (poll loop) under `UYP_STATE_ROOT/groups/<id>/messages.jsonl` |
| `DELETE /api/groups/{id}` | dissolve a group | owner only; the registry forgets the group, later searches are denied |

`POST /api/knowledge/search` accepts `{ "query": "...", "projectId": "..." }`.
Without a valid HomeHub context projection it returns `503
access_context_unavailable`; it never searches the entire output directory as a
fallback. The same redaction applies to the snapshot: without explicit
`projectScopes` and `sourceScopes`, project names, paths, counts, and evidence
are not published. Every response carries `X-UYP-Audit-Id`. Model calls remain
`think:false` through the existing search implementation.

This adapter does not implement pairing, grants, revocation, NandaTown
invites, or browser-triggered IndexJob mutation. Pairing, grants, revocation,
and NandaTown remain behind their HomeHub/connector adapters. The local
IndexJob worker described below owns only durable indexing execution after
HomeHub has supplied an AccessContext.

## Groups endpoints

The Groups endpoints (engine: `groups.py`, design: `docs/GROUPS_DESIGN.md`)
expose "这个群只开放这些知识" over HTTP.  `POST /api/groups` accepts
`{group_id, name, owner_member, member_members[], knowledge_view}` and
returns the registry record (201); the calling principal must BE the
`owner_member` — no member authors a group in someone else's name.
`POST /api/groups/{id}/search` accepts `{"query": "...", "member_id": "..."}`
and resolves the requesting member as body `member_id`, then loopback
`X-Agent-Member` (the voice-chain tier), then the caller's own principal.
A HomeHub-issued group context may instead be presented whole as the
`X-Group-Context` JSON header (strict `validate_group_context`; expired or
revoked is a 403).  Every search runs `scoped_retrieval` — context
validation, registry membership, view intersection, pre-retrieval filter —
then synthesis, then a `source_overlap` post-check: an answer citing files
outside the group's view is refused with the canonical miss sentence
(`Not in the indexed projects.`), sharing no paths.  Group search also
touches `/tmp/uyp_interactive.lock` before synthesis, so indexing yields
to group answers exactly as it yields to knowledge search.  Dissolving
(`DELETE`, owner only) forgets the registry record; later searches are
denied.  Deployment: `groups.py` must be copied alongside `query_api.py`
into `~/dev/uyp/indexer/`.

## Group messaging (NandaTown, audit A2)

Group chat that actually sends and receives between Jarvis boxes, on top
of the same authority split: `groups.py` decides WHO may speak
(registry membership, the same member tiers as group search —
`X-Group-Context` projection, body/query `member_id`, loopback
`X-Agent-Member` voice header, then the caller principal), and
`nandatown_client.py` carries the bytes.

- **Send** — `POST /api/groups/{id}/messages` with `{"text": "...",
  "member_id": "..."}` (text bounded to 4000 chars).  The message fans
  out per recipient — the town has no broadcast primitive, so every peer
  in the run directory except this box's own participant gets its own
  message with its own `message_id`; the declared `sender` in each
  envelope is the resolved member.  201 returns the local echo plus the
  per-recipient `delivery` rows.  Failures are honest: an unreachable
  town, refused join, unreadable directory, or all-per-recipient
  rejection answers 503 with the client's `error_code`
  (`nandatown_unreachable`, `nandatown_unauthorized`,
  `nandatown_unconfigured`, ...) and persists NOTHING — a message that
  did not leave the box never appears in history as if it had.  A
  non-member gets 403 `not_a_member` before anything is sent; an
  unknown/dissolved group is 404 (the message log and run mapping live
  in the registry record, so messaging requires local registration even
  when a group context is presented).
- **Receive** — a background poll thread inside `query_api`
  (`UYP_NANDATOWN_POLL_SECONDS`, default 15; `<= 0` or a missing join
  token disables it — fail-closed and quiet).  Each pass joins as the
  configured participant (`UYP_NANDATOWN_PARTICIPANT`, e.g.
  `uyp-indexer`) and claims the inbox once per locally-mapped group;
  inbound rows are appended to
  `UYP_STATE_ROOT/groups/<id>/messages.jsonl`
  (`message_id`/`group_id`/`sender`/`sent_at`/`text`/`direction`),
  deduped on `message_id` (town delivery is at-least-once).  The client
  re-offers foreign-group messages (`retryable`) instead of consuming
  them, so mail for a group this box does not map is never lost to this
  poller.  The `since_ts` watermark is derived from the group's newest
  INBOUND row only — this box's own later sends can never hide a peer's
  skewed-clock message.
- **History** — `GET /api/groups/{id}/messages?limit=` returns the
  member-scoped local log (newest `limit`, oldest first).  This is what
  a chat UI polls; the voice chain's `group_knowledge` needs only
  search, which was already live.

**Run mapping v1.**  A group's messages route to the town run named by
the registry field `town_run_id` (nullable, carried on
`POST /api/groups` create/upsert), else the deployment default
`UYP_NANDATOWN_RUN_ID`.  With neither set the messaging endpoints
answer 503 `nandatown_run_unconfigured` instead of silently guessing —
the client's hardcoded `DEFAULT_RUN_ID` stays a transport default for
directory/health, never a group-routing decision.  Per-group run
CREATION automation (town admin API) is future work; this is mapping
only — the town admin provisions runs and join tokens, the registry
records which run serves which group.

Studio: the Groups workspace loads the live group list and history
through these endpoints (plus `GET /api/groups` for the rail) and its
composer sends real messages when the query API is configured; the demo
conversations remain the offline fallback, never a stand-in for live
answers.
## MCP surface (P6)

`services/indexer/src/mcp_server.py` is the Coding Agent half of P6: a
read-only **stdio MCP server** (stdlib-only JSON-RPC 2.0, newline-delimited)
exposing exactly the six planned tools — `project.search`, `project.get`,
`project.related`, `source.locate`, `source.read_evidence`, `index.status`.
No shell, build, test, arbitrary path read, or write operation exists on the
surface, and no tool mutates output, state, or registry files.

```bash
# HTTP mode: the three route-bound tools are served by the running query API
python3 services/indexer/src/mcp_server.py \
  --api http://127.0.0.1:8787 --principal ly

# direct mode: same shared functions the routes call, no HTTP hop
UYP_MCP_PRINCIPAL=ly python3 services/indexer/src/mcp_server.py
```

A Claude Code / coding-agent registration looks like:

```json
{"mcpServers": {"uyp": {"command": "python3",
  "args": ["/path/to/services/indexer/src/mcp_server.py",
           "--api", "http://127.0.0.1:8787", "--principal", "ly"]}}}
```

### Principal story (fail closed)

The stdio server speaks for a principal it must be given; it never inherits
the box's ambient service context:

- **member tier** — `--principal` / `UYP_MCP_PRINCIPAL` names the HomeHub
  member the agent acts for. HTTP mode sends `X-Agent-Member` (the loopback
  voice tier — the API must be loopback-bound, which is the default); direct
  mode calls `homehub_adapter.load_context_for_member`, the exact function
  behind the voice handshake, which requires the projection to speak for
  exactly that member with a non-empty project scope. An unresolvable member
  is denied `member_access_denied` in her name — never the box context.
- **bearer tier** — `UYP_MCP_TOKEN_FILE` holds the agent's own HomeHub
  Companion bearer (mirroring the voice chain's token-file approach); HTTP
  mode presents `Authorization: Bearer`, direct mode calls
  `load_context_for_token`. An absent/unreadable/empty file is denied
  `principal_required`.
- **neither configured** — every tool call returns `principal_required`
  (the server still completes the MCP handshake and `tools/list`, so the
  surface is discoverable while closed).

Enforcement is the query API's own code, not a reimplementation: `search`
and the locally computed tools filter through `query_api.scoped_items`,
`project.get`'s job list through `load_persisted_index_jobs` (scope-filtered),
graph reads through `query_api.load_ua_graph` (realpath/commonpath
containment reused untouched), and the symbol tables through
`anchored_enrich`'s node filter. Out-of-scope requests get the same generic
denial as nonexistent ones — no names, paths, or counts are shared.

### Tools

| Tool | Arguments | Transport | Returns |
| --- | --- | --- | --- |
| `project.search` | `{query, project_id?}` | `POST /api/knowledge/search` (HTTP mode) / `scoped_items` + `search_answer` (direct) | cited answer plus `citations` entries carrying `projectId`, `sourceId`, `file`, `knowledgeVersion`, `evidenceLevel`, `freshness`, `producingJarvis`, `allowedToShare:false` (AGENTFLOW §5 shape) |
| `project.get` | `{project_id}` | `GET /api/studio/snapshot` (HTTP) / shared projections (direct) | project summary (counts, languages, entry points, freshness, grant epoch) + scope-filtered IndexJobs + evidence sample |
| `project.related` | `{query}` or `{project_id}` | local (no route exists) | UA-graph import relations and hub files, component tags, and other **in-scope** projects sharing tags/paths; a query with no lexical hit answers the canonical miss sentence |
| `source.locate` | `{symbol?, file_pattern?, project_id?, limit?}` | local | file/line rows from the indexed tree-sitter symbol tables (anchored enrichment data): `{projectId, file, symbol, kind, lineRange}` |
| `source.read_evidence` | `{item_id}` or `{path, lines?}` | local | the indexed bounded evidence for one item: labelled key points with snapped line ranges, components, `anchorTop`, purpose, and the verbatim `rawHead` when the indexer kept one |
| `index.status` | `{}` | `GET /api/health` (HTTP) / health functions parameterized by the principal context (direct) | scoped knowledge count, IndexJob phase summary, connector/registry health, interactive-lock state |

`source.read_evidence` serves **indexed** evidence only. Full verbatim
line-range reads of live source require the Connector `read` path
(CONNECTOR_PROTOCOL_V1 §4) and are deliberately not proxied here — the
Connector stays the only component allowed to resolve a source path.
Known tier note: in HTTP mode the three route-bound tools inherit the
query API's per-route context tiers verbatim (search resolves the member
per request; snapshot/health use the service-level projection), while
`related`/`locate`/`read_evidence` resolve the configured principal
locally with the same env (`UYP_HOMEHUB_ACCESS_CONTEXT_URL` +
`UYP_HOMEHUB_TOKEN_FILE`) — if that env is absent they deny fail-closed
even while the route-bound tools keep working.

Protocol details: MCP `initialize`/`ping`/`tools/*` over JSON-RPC 2.0;
protocol version `2025-06-18` negotiated against
`2024-11-05`/`2025-03-26`; invalid tool arguments are `-32602`; access
denials are honest `isError` tool results shaped like the HTTP API's
`{"ok": false, "error", "message"}` bodies; batch requests are rejected
(`-32600`, removed by MCP 2025-03-26); diagnostics go to stderr only.
Contracts are pinned in `services/indexer/tests/test_mcp_server.py`
(framing, the six-tool read-only surface, per-member scoping, and a
byte-identical store after a full battery of calls).

## Connector registry

The Jetson keeps a versioned registry at
`$UYP_CONNECTOR_REGISTRY_FILE`, or at
`$UYP_STATE_ROOT/connectors/registry.json` when the explicit path is omitted.
The registry stores connector and Agent Box metadata, health observations, and
bounded manifest counters. Writes are atomic and the file is mode `0600`.
Bearer tokens, source paths, full manifest entries, and HomeHub grants are
discarded at the schema boundary. A pairing or manifest adapter may call the
`connector_registry.upsert_connector`, `update_health`, and `update_manifest`
functions after its own HomeHub checks. `GET /api/connectors` only projects
those records; it cannot create or revoke a connector.

When no valid HomeHub `AccessContext` is available, the endpoint returns
opaque IDs and state only. Labels and source IDs are included only when a
validated context's `sourceScopes` authorizes the connector. This prevents a
second connector from becoming an accidental source discovery channel.

## HomeHub grant revocation and audit

- `POST /api/uyp/grants/{grant_id}/revoke` — body MUST be exactly
  `{"reason": "<opaque_identifier_no_spaces>"}` (string, non-empty, <=256
  chars, opaque-id regex; no spaces/slashes/`~`/`..`).
  - 400 `revoke fields are invalid` = extra/missing keys; 400 `reason must
    be an opaque identifier` = spaces/rejected chars.
  - 403 `owner_session_required` unless caller is owner or the grant's
    subject; 404 `grant_not_found`; re-revoke is idempotent
    (`alreadyRevoked: true`, no new audit row).
  - Success: `{status, grantId, revoked: true, grantEpoch, auditId}` — the
    grant epoch bumps (live: 2->3), invalidating outstanding AccessContexts.
- `GET /api/uyp/access-context/audit` — owner only; returns a LIST (max 200,
  newest first): `{audit_id, schema_version, event_type, actor_member_id,
  subject_member_id, grant_id, project_id, epoch, occurred_at}`; revoke rows
  carry `event_type: "uyp.grant.revoke"`.
- Live evidence: docs/P7_ACCEPTANCE_2026-10-10.md step 6 (revoke epoch 2->3
  -> search sees "0 files indexed" -> re-grant epoch 4 restores).

### Known spec deviations

- `/api/health` `knowledgeItems` was context-gated but not scope-filtered
  (still 119 after revocation) — fixed on branch `fix/p7-findings`
  (`1bc41b9`): health now shares `scoped_items()` with search.
- `sourceEpoch` echoed `analyzed_at`; now derived as sha256 over the sorted
  manifest page (`1bc41b9`), still protocol-placeholder grade until the
  Connector grows a real epoch field.
- Worker order remains transitional (semantic -> UA); UA-first anchored
  enrichment runs as a post-pass (anchored_enrich.py v3).

## Jetson Understand Anything bridge

`services/indexer/src/ua_bridge.py` is the first real UA adapter. It accepts a
Connector grant, stages bounded reads under a temporary directory in
`UYP_STATE_ROOT`, runs the vendored UA scanner, Tree-sitter extraction, batch
planner, and graph builder, then publishes only `knowledge-graph.json` and
intermediate metadata under:

```text
<state-root>/<project>/ua/
```

It never writes `.ua` or other analysis files into the authorized source. The
vendored UA source must be installed on Jetson with ARM-native dependencies;
Mac `node_modules` must not be copied to Jetson. Example smoke run after the
UA workspace is installed:

```bash
python3 services/indexer/src/ua_bridge.py \
  --host http://127.0.0.1:7121 \
  --grant g_example \
  --ua-root ~/dev/uyp/understand-anything-src-20261009 \
  --state-root ~/dev/uyp/state \
  --limit 30
```

The durable worker is implemented in `services/indexer/src/index_job.py`. It
owns the `AUTHORIZED -> QUEUED -> RUNNING -> STAGED -> PUBLISHED` transition
while HomeHub remains the authority that supplies and revokes the
AccessContext. Job records and append-only transition events live below
`UYP_STATE_ROOT/index-jobs/`; no source directory receives a job artifact.

Create and run a job on Jetson after HomeHub has written a valid context
projection (the worker does not create one):

```bash
python3 services/indexer/src/index_job.py \
  --state-root ~/dev/uyp/state \
  --output-root ~/dev/uyp/output \
  --access-context ~/.config/uyp/access-context.json \
  --connector-host http://127.0.0.1:7121 \
  --token-file ~/.config/uyp/token \
  --ua-root ~/dev/uyp/understand-anything-src \
  create --project-id jarvis-memory-live \
  --source-id connector:jarvis-memory-live \
  --grant-id g_connector_example --grant-epoch homehub-epoch-1
```

`--grant-id` is the Connector's read capability. `--grant-epoch` is the
HomeHub policy epoch from the AccessContext; they are intentionally different
values and must not be substituted for each other.

```bash
python3 services/indexer/src/index_job.py \
  --state-root ~/dev/uyp/state \
  --output-root ~/dev/uyp/output \
  --access-context ~/.config/uyp/access-context.json \
  --connector-host http://127.0.0.1:7121 \
  --token-file ~/.config/uyp/token \
  --ua-root ~/dev/uyp/understand-anything-src \
  run job-<id>
```

The worker first validates project/source scopes and the grant epoch, then
checks the live Connector manifest. It stages KnowledgeItems and the UA graph
under the job directory and publishes complete project directories with a
rollback copy. Missing, expired, or revoked HomeHub context stops the job in
`blocked` or `revoked`; it never falls back to indexing all local output.

For automatic scheduling, invoke the same worker from a systemd timer,
launchd job, or deployment controller with `run-pending`:

```bash
python3 services/indexer/src/index_job.py \
  --state-root ~/dev/uyp/state \
  --output-root ~/dev/uyp/output \
  --access-context ~/.config/uyp/access-context.json \
  --connector-host http://127.0.0.1:7121 \
  --token-file ~/.config/uyp/token \
  --ua-root ~/dev/uyp/understand-anything-src \
  run-pending --max-jobs 1
```

The scheduler is fail-closed: when HomeHub is unavailable it reports skipped
jobs and leaves their durable phase unchanged. It never turns a temporary
policy-plane outage into a grant or a permanent denial. `run-pending` is a
single bounded pass so the deployment layer controls cadence and resource
limits.

The Jetson deployment includes user-level systemd units under
`jetson/systemd/`. Install them without root after copying the indexer to
`~/dev/uyp/indexer`:

```bash
mkdir -p ~/.config/systemd/user
cp ~/dev/uyp/indexer/jetson/systemd/uyp-query-api.service ~/.config/systemd/user/
cp ~/dev/uyp/indexer/jetson/systemd/uyp-indexjob.service ~/.config/systemd/user/
cp ~/dev/uyp/indexer/jetson/systemd/uyp-indexjob.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now uyp-query-api.service uyp-indexjob.timer
```

The timer invokes one bounded pass per minute. Without a valid HomeHub
`AccessContext`, the service exits successfully with a skipped result and does
not mutate the queue; a policy-plane outage therefore cannot become an
implicit grant.

The UA bridge now feeds the staged Laya/Qwen `KnowledgeItem` summaries into the
vendored graph, retains Connector-resolved import edges, and computes
heuristic layers and a guided tour with the UA core APIs. These are published
with the graph only after the complete candidate passes the worker's atomic
publish step; no `.ua` files are written into a source repository.
