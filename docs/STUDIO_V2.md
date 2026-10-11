# Jarvis Studio v2 — architecture and API contracts

## Handoff status (2026-10-11, Robin)

- **This repo (branch `robin/studio-revamp`)**: Studio SPA (`studio/`), indexer
  key-file classifier, manifest paging, `/api/projects*` (registry, hierarchy,
  digests, ask, analyze jobs), deploy/hotfix scripts in `tools/`.
- **HomeHub side lives in `FelixFtch/jarvis-homehub`, branch `robin/studio-revamp`**:
  companion-api `/api/studio/*` (me/enroll, policy, devices, threads, contacts, share
  cards, projects proxy, `studio_admin` CLI, tokens `device_name` migration),
  agent-runtime `flow/` package (voice + studio flows, project tools, ADR-0031),
  agent-gateway Town routing (`town://<participant>`) and the town_listener inbound hook.
- **Deployed** on the clinic Jetson (2026-10-11) with `tools/deploy_studio_v2.sh` +
  `tools/hotfix_studio_auth.sh`; Studio at `http://<jetson>:5120/studio/`. Login code:
  `cd ~/jetson/services/companion-api && PYTHONPATH=src venv/bin/python -m companion_api.studio_admin invite`.
  companion-api needs `ROBOTDESK_HOMEHUB_HUB_ID` (systemd drop-in) or project access fails.
- **Tests**: companion-api 175, agent-runtime 199, UYP indexer 377 (1 known timing flake),
  agent-gateway 176 (+2 pre-existing failures), studio 71.
- **Open**: `project.ask` ranks embedded third-party folders too high; Town inbound depends
  on the (hand-started) town_listener on each box; the old UA graph explorer is not linked
  from the new Studio yet; a Town join token is committed in `jarvis-homehub`
  `deploy/systemd/town-bridge.service` and should be rotated.

## Contract

Status: build contract, 2026-10-11. Owner: Robin (clinic Jarvis, member `robin`, role `owner`).
Shared by both repos: `UnderstandYourProjects` (UYP) and `jarvis-homehub` (HomeHub).
Every build agent implements exactly the endpoints and shapes in this file. If a shape
must change, change this file in the same edit and say so in your report.

## 0. Principles (non-negotiable)

1. **HomeHub is the only authority** for identity, membership, contacts/trust, policy,
   privacy share cards, devices, grants and audit (AGENTS.md rule 1 in both repos). UYP
   stores derived project knowledge only. The Studio is a client; it never decides policy.
2. **Identity comes from a HomeHub bearer token**, never from a request body or a header the
   browser can set. Machine-to-machine calls on loopback use the existing
   `X-Task-Source: <service>` + `X-Agent-*` header pattern (as `/internal/deep-pref` does).
3. **The live voice path must not change behaviour.** New harness code is additive; the
   existing parity/contract tests in `jetson/services/agent-runtime/tests` stay green.
4. **No secrets in repos or responses.** HA tokens, Town join tokens, device tokens are
   referenced, never returned.
5. Every new module ships with tests that run offline (fakes for HTTP/LLM).

## 1. Topology

```
Browser (Studio SPA)  ──HTTPS/HTTP──►  companion-api :5120  (HomeHub; Studio BFF; serves /studio/)
                                          │  identity, policy, contacts, threads, share cards, devices
                                          ├──► agent-runtime :8868   /v1/agent/flow/*   (Harness flows, SSE)
                                          ├──► UYP query_api :8787    /api/projects/*    (knowledge; Bearer forwarded)
                                          ├──► agent-gateway :8891    /ask, /api/agents  (A2A / NANDA Town transport)
                                          └──► knowledge-service :8790 (gbrain; via harness)
agent-runtime ──► hub stub :8869 (HA, calendar, reminders, family) ; ──► UYP :8787 (X-Agent-* + UYP service token)
UYP ──► Mac connector via ssh -R 127.0.0.1:7121 ; ──► companion /api/uyp/access-context
```

All Studio HTTP endpoints live under companion-api `/api/studio/*` and require
`Authorization: Bearer <companion token>`. The SPA is served by companion-api at `/studio/`
(static `dist/` copied to `~/jetson/services/companion-api/studio_dist`, path from env
`COMPANION_STUDIO_DIST`). Dev: Vite on :4173 proxies `/api` to companion.

## 2. Auth and session

- Login: the owner gets an invite code (phone app "Invite", or on the Jetson:
  `PYTHONPATH=src venv/bin/python -m companion_api.studio_admin invite --ttl 900` (run in ~/jetson/services/companion-api), prints an 8-hex code).
  The Studio posts `POST /api/pair {code, device_name:"Jarvis Studio", device_id:"studio-<uuid>"}`
  (existing route) and keeps the returned `token` in `localStorage["jarvis.studio.token"]`.
- `GET /api/studio/me` →
  ```json
  {"member_id":"robin","role":"owner","display_name":"Robin","household_id":"household",
   "jarvis":{"node_id":"hub_…","display_name":"Robin's Jarvis","number":"J-4829-1300",
             "urn":"urn:ai:domain:…","town":{"run_id":"run-…","participant":"clinic"}|null},
   "agent_box":{"enrolled":true|false,"box_id":"box_…"|null}}
  ```
  `number` = deterministic "Jarvis number": `J-` + 8 decimal digits from sha256(node_id), grouped 4-4.
- `POST /api/studio/agent-box/enroll` (owner) → enrolls *this* Jetson's UYP worker: creates an
  agent-box invite, redeems it locally, writes `~/.config/uyp/homehub.token` (0600, path from env
  `UYP_HOMEHUB_TOKEN_FILE`, default that path). Returns `{"enrolled":true,"box_id":"…"}`. Never
  returns the token.

## 3. Jarvis chat and the agent flow (Harness)

### 3.1 agent-runtime endpoints (HARNESS)
- `GET /v1/agent/flows` → `{"flows":[{"name":"voice","description":"…"},{"name":"studio",…}]}`
- `GET /v1/agent/flows/{name}` → flow spec (for visualization):
  ```json
  {"name":"studio","version":1,"nodes":[{"id":"identity","type":"identity","label":"Identify speaker",
    "group":"understand","config":{}}],"edges":[{"from":"identity","to":"intent"}]}
  ```
  Node `group` ∈ `understand | retrieve | act | respond`.
- `POST /v1/agent/flow/turn` body `{"text":str,"flow":"studio","thread_id":str}` with headers
  `X-Agent-Member/Role/Household/Room/Session` (+ `X-Agent-Channel: studio`). Response
  `text/event-stream`, one JSON object per `data:` line:
  - `{"type":"trace","node":"intent","status":"start"|"done"|"skip"|"error","detail":str,"ms":int}`
  - `{"type":"tool","name":"project.status","args":{…},"ok":bool,"summary":str}`
  - `{"type":"evidence","items":[{"kind":"file"|"brain"|"project","label":str,"ref":str}]}`
  - `{"type":"handoff","contact":str,"question":str,"answer":str|null}` (agent.ask happened)
  - `{"type":"sentence","text":str}`
  - `{"type":"final","reply":str,"stats":{…}}` (always last)
- The `voice` flow reproduces today's `_turn_events` order exactly; `/v1/agent/turn` and
  `/turn/stream` keep their current behaviour (ADR-0027 parity). The `studio` flow = the same
  node chain + project tools + trace/evidence emission. Document this in a new
  `docs/adr/ADR-0031-modular-flows.md` (HomeHub repo).

### 3.2 Flow framework (HARNESS, `agent_runtime/flow/`)
- `flow/core.py`: `TurnContext`, `Node` protocol (`id`, `type`, `label`, `group`,
  `run(ctx) -> Iterator[Event] | None`; returning None = fall through), `FlowSpec`,
  `FlowRunner` (runs nodes in order, emits trace events, stops at the first node that completes the turn).
- `flow/nodes/*.py`: one module per node family. `flow/registry.py`: type → class.
- `flow/specs/voice.json`, `flow/specs/studio.json`: declarative node lists (LangFlow-like,
  editable). Loading a spec validates node types against the registry.
- New **local tools** (studio flow; executed by a composite `HomeHubPort` that dispatches
  `project.*` locally and everything else to the hub stub):
  - `project.list` (R1) — list analyzed projects/folders.
  - `project.status` (R1) `{project, window: "today"|"yesterday"|"this_week"}` — recent activity + digest.
  - `project.ask` (R1) `{project?, question}` — UA knowledge + gbrain synthesis.
  - `project.sync` (R1, owner only) `{path, device?}` — start Understand Anything on a folder.
  These call UYP `:8787` with `X-Agent-*` headers (same pattern as `project_knowledge.py`).
  They must not be added to the voice catalog set pinned by
  `test_visible_route_actions_matches_catalog`; studio adds them via its own catalog list.
- Identity → access: owner/member → R1–R3; guest → R3; local tools enforce owner/member and
  (for `project.sync`) owner.

### 3.3 companion-api Jarvis thread (AGENTCHAT)
- The Jarvis thread is a singleton per member: `thread_id = "jarvis"`.
- `POST /api/studio/threads/jarvis/messages {text}` → proxies to `/v1/agent/flow/turn`
  (flow `studio`, headers from the token's member/role, `X-Agent-Room: studio`,
  `X-Agent-Session: studio-<member>`), streams the same SSE frames to the browser, and persists
  the user message + final reply (+ trace summary in `meta`) in `studio_messages`.
  A `handoff` frame also appends the exchange to the direct thread with that contact
  (creating it if needed) and adds `meta.handoff_thread_id` to the Jarvis reply.
- `GET /api/studio/flows` and `GET /api/studio/flows/{name}` → proxies of the agent-runtime
  `/v1/agent/flows*` endpoints (any authenticated member).
- If agent-runtime is unreachable, the Jarvis POST still answers with SSE: one
  `{"type":"error","message":…}` frame then `{"type":"final","reply":"Jarvis is not reachable right now."}`.

## 4. Contacts, agent threads, share cards (AGENTCHAT, companion-api + agent-gateway)

### 4.1 Contacts
`GET /api/studio/contacts` →
```json
{"contacts":[{"contact_id":"c_…","display_name":"Felix's Jarvis","urn":"urn:ai:domain:…",
  "number":"J-1234-5678","transport":"town"|"a2a"|"contracts-v1","status":"verified"|"unverified"|"invited"|"pending_acceptance"|"blocked",
  "town":{"run_id":"…","participant":"home"}|null,"last_seen":"ISO"|null,"note":""}]}
```
- `GET /api/studio/contacts/directory` → discoverable agents not yet contacts (from agent-gateway
  `/api/agents` and UYP `/api/nandatown/peers`): `{"entries":[{"urn","display_name","transport","town","source":"gateway"|"town"}]}`.
- `POST /api/studio/contacts {urn, display_name, transport?, town?}` → 201 contact (status `unverified`).
- `POST /api/studio/contacts/invite` `{contact_id}` → sends a `contact.invite` envelope with my
  card (`me.jarvis` + a one-time `invite_code`) via agent-gateway; status → `invited`. →
  `{"ok":true,"delivery":{"ok":bool,"error":str|null}}`.
- `POST /api/studio/contacts/accept {invite_code, card}` → creates/marks contact `verified`
  (used when another Jarvis's invite arrives; also callable by the inbound hook).
- `PATCH /api/studio/contacts/{id} {display_name?, note?, status?:"blocked"|"verified"}`;
  `DELETE /api/studio/contacts/{id}`.

### 4.2 Threads and messages
```json
Thread  {"thread_id":"t_…"|"jarvis","kind":"jarvis"|"direct"|"group","title":str,
         "participants":[{"kind":"member"|"jarvis"|"agent","id":str,"display":str}],
         "last_message_at":"ISO"|null,"last_preview":str,"unread":int}
Message {"message_id":"m_…","thread_id":str,"author":{"kind":"member"|"jarvis"|"agent","id":str,"display":str},
         "text":str,"created_at":"ISO","status":"sent"|"delivered"|"failed"|"pending",
         "meta":{"trace":[…]?,"evidence":[…]?,"handoff_thread_id":str?,"shared_items":[item_id…]?}}
```
- `GET /api/studio/threads` → `{"threads":[Thread…]}` (Jarvis first, then by last_message_at desc).
- `POST /api/studio/threads {kind:"direct"|"group", contact_ids:[…], title?}` → 201 Thread
  (a direct thread is unique per contact; return the existing one).
- `GET /api/studio/threads/{id}/messages?limit=50&before=<message_id>` → `{"messages":[Message…],"has_more":bool}` (oldest→newest).
- `POST /api/studio/threads/{id}/messages {text}` (direct/group) → 201
  `{"message":Message,"replies":[Message…],"delivery":[{"contact_id","ok","error"}]}`.
  Outbound = agent-gateway `POST /ask` per contact with a HomeHub-issued delegation
  (`POST /api/delegations` internally) and a context block built **only** from the thread's
  enabled share-card items. Replies are appended as `agent` messages.
- `DELETE /api/studio/threads/{id}` (not `jarvis`).
- Inbound: agent-gateway `town_listener` posts each inbound question + its reply to
  `POST /internal/studio/inbound` (loopback, `X-Task-Source: agent-gateway`) →
  appended to the direct thread with that contact (created as `unverified` if unknown).
  Inbound `contact.invite` envelopes → stored as contact status `pending_acceptance`.
- Fix the Town participant clash: UYP's poller and agent-gateway must use different
  participant names (UYP default becomes `uyp-indexer`); document env.
- As built: the Jarvis `final` frame also carries `message_id` (+ `handoff_thread_id`);
  delegation scopes are `memory:read, calendar:read, agent:read, projects:read`; inbound hook
  env `TOWN_STUDIO_HOOK=0` disables it. **Known gap:** agent-gateway `/ask` routes Town traffic
  only to `target="clinic"`/directory entries, so sends to other Town contacts report failed
  delivery until the gateway learns per-participant Town routing (follow-up).

### 4.3 Share cards (per-thread privacy card)
```json
ShareCard {"thread_id":str,"items":[{"item_id":str,"category":str,"label":str,"value_preview":str,
           "ring":"R1"|"R2"|"R3"|"R4","source":"default"|"added","enabled":bool,"locked":bool}],
           "updated_at":"ISO"}
```
- `GET /api/studio/threads/{id}/share-card` → ShareCard. Defaults are computed from the
  member's **effective privacy policy** (§5): every category whose `share_with_agents` is true
  becomes an enabled item; categories whose ring is R1 are offered but disabled; `locked` items
  (policy says never share) cannot be enabled.
- `PUT /api/studio/threads/{id}/share-card {items:[{item_id,enabled}], add:[{category,label,value}], remove:[item_id]}` → ShareCard.
- Item values are resolved server-side at send time (e.g. `calendar` → next 3 free slots), never
  sent to the browser in full; `value_preview` is a short redacted preview.

## 5. Data management: principal hierarchy and policy (POLICY, companion-api)

Scopes (a tree; child inherits then overrides per leaf key):
```
town_default            NANDA Town defaults (what any external Jarvis may get)
└─ household            the household baseline
   ├─ member:<id>       an individual (robin, dr_lee, …)
   └─ guest             unregistered speakers; may never exceed household, never write
```
Domains and value schemas:
- `privacy`: `{"categories":{"<cat>":{"ring":"R1"|"R2"|"R3"|"R4","share_with_agents":bool}}}`
  categories: `profile, calendar, reminders, shopping, family_messages, projects, location, health, contacts`.
  Rings: R1 personal, R2 family, R3 household, R4 external (NANDA). `share_with_agents` true
  requires ring R4.
- `ha`: `{"live":bool,"rooms":{"<room>":{"entities":[str],"allowed_actions":[str]}},"guest_actions":[str]}`
  (HA URL/token are env secret refs, never in this document).
- `schedule`: `{"calendar_visibility":"private"|"household","agents_can_propose":bool,
  "agents_can_book":bool,"quiet_hours":{"start":"HH:MM","end":"HH:MM"}|null,"reminder_lead_minutes":int}`

Endpoints:
- `GET /api/studio/policy/tree` → `{"scopes":[{"scope":"household","label":"Household","parent":"town_default","kind":"household"}…],"domains":["privacy","ha","schedule"]}`
  (member scopes come from the `members` table).
- `GET /api/studio/policy/{scope}/{domain}` → `{"scope","domain","values":{…own},"inherited":{…},"effective":{…},"updated_at","updated_by"}`
- `PUT /api/studio/policy/{scope}/{domain} {values}` (owner only; schema-validated; guest
  clamped; audit row) → same shape.
- `GET /api/studio/policy/effective?member=<id>` → `{"member","privacy":{…},"ha":{…},"schedule":{…}}`
- Python API for other modules: `companion_api.policy.effective(member_id) -> dict`.

## 6. Devices and projects

### 6.1 Devices (POLICY, companion-api)
`GET /api/studio/devices` →
```json
{"devices":[{"device_id":"d_…","kind":"computer"|"nas"|"jetson"|"phone","label":"Robin's MacBook Pro",
  "hostname":str,"os":str,"connector":{"state":"online"|"offline"|"unknown","watcher":str|null,
  "grants":int,"last_seen":"ISO"|null}|null,"paired_at":"ISO"|null,"project_count":int}]}
```
`PATCH /api/studio/devices/{id} {label}`. The Jetson itself (`d_jetson`, env
`STUDIO_JETSON_DEVICE_ID`) and paired phones appear as devices (Studio sessions and Agent Box
tokens do not); computers come from connector pairings (connector `/status` via
`UYP_CONNECTOR_HOST`, default `http://127.0.0.1:7121`); the Mac connector's device id is
`d_mac` (env `UYP_CONNECTOR_DEVICE_ID`) and UYP project records use the same id.
As built: member scopes in the policy tree also carry `member_id`/`role`; PUT responses add
`clamped`; members with role guest resolve to the `guest` scope.

### 6.2 Projects / analyzed folders (KNOWLEDGE: UYP query_api + thin companion proxy)
UYP endpoints (accept `Authorization: Bearer <companion token>` → AccessContext path (a), or
loopback `X-Agent-Member` path (b)); companion proxies `/api/studio/projects*` →
`:8787/api/projects*`, forwarding the caller's bearer.
- `GET /api/projects` →
  ```json
  {"projects":[{"project_id":"commontasks","device_id":"d_…"|null,"root_name":"commontasks",
    "path":"/Users/…/code/commontasks","parent_id":null,"children":["…"],
    "status":"analyzed"|"analyzing"|"queued"|"stale"|"failed"|"not_analyzed",
    "analyzed_at":"ISO"|null,"stats":{"files":int,"summarized":int,"nodes":int,"edges":int,"languages":[str]},
    "tiers":{"A":int,"B":int,"C":int,"gate":int},"embedded_roots":[str]}],
   "tree":[{"project_id":…,"children":[…]}]}
  ```
  `path` is owner-visible metadata from the project registry; never a source read.
- `GET /api/projects/{id}` → digest:
  ```json
  {"project":{…as above},"overview":str,"key_files":[{"file","tier","purpose","key_points":[str]}],
   "areas":[{"folder":str,"files":int,"summary":str,"embedded":bool}],
   "activity":{"window":"7d","changed":[{"file","mtime","purpose"}],"by_day":[{"date","count"}]},
   "graph":{"layers":[{"name","files"}],"top_nodes":[{"name","type","file"}]},
   "related":{"parent":…|null,"children":[…],"siblings":[…]},"generated_at":"ISO"}
  ```
- `GET /api/projects/{id}/activity?since=ISO&until=ISO` → `{"changed":[{"file","mtime","purpose"}]}`
- `POST /api/projects/{id}/ask {question}` → `{"answer","sources":[{"file"}],"confidence"}`
  (UA knowledge items + gbrain synthesis; same model env as knowledge_search).
- `POST /api/projects/analyze {path, device_id?}` (owner) → 202
  `{"job_id","project_id","relation":{"parent_id":…|null,"children":[…]},"status":"queued"}`.
  Creates the connector grant, registers the project with its hierarchy relation, and launches
  the run (`systemd-run --user` or detached subprocess) with parent/children context.
- `GET /api/projects/jobs/{job_id}` → `{"job_id","project_id","status","phase","progress":{"done","total"},"log_tail":[str]}`
  (`status` ∈ `queued|running|done|failed`; readable by the owner or anyone granted the project).
- `GET /api/projects/ids` (owner) → `{"project_ids":[str]}` — every registered project id, so the
  companion can grant them to the owner (added 2026-10-11, KNOWLEDGE).
- Errors are `{"ok":false,"error":code,"message"}`: no credential / unresolvable bearer → 401,
  member without grants or non-owner on owner routes → 403, unknown or out-of-scope project → 404,
  HomeHub transport unconfigured or connector unreachable → 503. There is no service-context
  fallback on `/api/projects*`. `areas[].embedded` marks a bundled third-party root (listed last).
- `device_id` of every project = the Mac connector device (`UYP_CONNECTOR_DEVICE_ID`, default
  `d_mac`, same as §6.1); `analyze` with another `device_id` → 400 `unsupported_device`.
- **Hierarchy**: a new folder whose path is an ancestor of analyzed folders becomes their
  parent (children are linked and not re-enriched; their outputs are reused); a descendant of
  an analyzed folder becomes its child and receives the parent's overview as prompt context.
  Siblings = same parent. The registry lives at `<UYP_STATE_ROOT>/projects/registry.json`.
- companion-side, `POST /api/studio/projects/analyze` also creates the HomeHub `uyp_grants`
  row for the owner (project + `connector:<root>`), before calling UYP (and grants the id UYP
  returns if it differs; a fresh pre-grant is revoked when UYP refuses the folder).
  `POST /api/studio/projects/sync-grants` (owner) → `{"ok","project_ids","granted","existing","skipped"}`
  grants every registered project to the owner (24 h, renewed when < 1 h left); an owner's
  `GET /api/studio/projects` runs it at most every 10 min. Companion env for the UYP base:
  `UYP_QUERY_URL` or `COMPANION_UYP_QUERY_URL` (default `http://127.0.0.1:8787`).

## 7. Studio frontend (FRONTEND)

New app at `UnderstandYourProjects/studio/` (Vite + React 19 + TypeScript + Tailwind 4 +
zustand), reusing design tokens from the existing dashboard. Navigation:
1. **Jarvis** — 1:1 chat (streaming, trace drawer showing the flow nodes, evidence chips, handoff chips).
2. **Agents** — contacts list + directory + invite; direct and group threads with full history;
   right-side **Share card** panel per thread.
3. **Devices** — device cards → folder hierarchy (tree + treemap) → project digest
   (overview, key files, areas, activity timeline, ask box, "Analyze a folder", link to the graph explorer).
4. **Data** — principal tree (Town default → Household → Robin / members, Guest) × domain tabs
   (Privacy rings, Home Assistant, Scheduling) with inherited-vs-own values.
5. **Flow** — read-only visualization of the agent flow spec (nodes grouped understand/retrieve/act/respond),
   highlighting the last turn's trace.
Shared typed client: `studio/src/api/contracts.ts` (types mirroring this file) and
`studio/src/api/client.ts` (fetch + SSE helper, bearer from localStorage, 401 → login screen).
Feature code lives in `studio/src/features/<area>/`; no feature imports another feature.

## 8. Ownership map (parallel build)

| Agent | Repo / paths (exclusive) |
|---|---|
| HARNESS | homehub `jetson/services/agent-runtime/src/agent_runtime/flow/**`, `…/project_tools.py`, edits to `app.py` limited to new endpoints + composite port wiring; `…/tests/test_flow_*.py`; `docs/adr/ADR-0031-modular-flows.md` |
| POLICY | homehub `companion-api/src/companion_api/{policy.py,studio_admin.py,tables_studio_policy.py}`, `routes/{studio_me.py,studio_policy.py,studio_devices.py}`; `tests/test_studio_policy*.py`, `tests/test_studio_devices*.py` |
| AGENTCHAT | homehub `companion-api/src/companion_api/{tables_studio_chat.py,threads.py,share_cards.py}`, `routes/{studio_threads.py,studio_contacts.py,studio_internal.py}`; `agent-gateway/src/agent_gateway/town_listener.py` (inbound hook only); `tests/test_studio_threads*.py`, `tests/test_studio_contacts*.py` |
| KNOWLEDGE | UYP `services/indexer/src/{projects.py,project_digest.py,project_jobs.py}`, new route handlers in `query_api.py` (only the `/api/projects*` block + Bearer support for them + the group `member_id` fix); `services/indexer/tests/test_projects*.py`; homehub `companion-api/routes/studio_projects.py` |
| FRONTEND-A | UYP `studio/` scaffold, `studio/src/{app,api,shell,features/jarvis,features/devices,features/flow}/**` |
| FRONTEND-B | UYP `studio/src/features/{agents,data}/**` |

Shared files touched only by the lead (pre-wired before agents start): companion `app.py`
(router includes), `tables.py` (`init()` calls `tables_studio_policy.init(conn)` and
`tables_studio_chat.init(conn)`), `studio/src/api/contracts.ts`, `studio/src/api/client.ts`.
