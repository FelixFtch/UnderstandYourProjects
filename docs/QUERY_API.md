# Jetson Query API

`services/indexer/src/query_api.py` is the first server adapter between the
Jetson knowledge store and Studio. It wraps the existing `knowledge_search.py`
proof of concept; the browser never calls Ollama or a Connector directly.

## Run

```bash
UYP_OUTPUT_ROOT=~/dev/uyp/output \
UYP_STATE_ROOT=~/dev/uyp/state \
UYP_ACCESS_CONTEXT_FILE=~/.config/uyp/access-context.json \
python3 services/indexer/src/query_api.py --port 8787
```

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
| `POST /api/knowledge/search` | bounded lexical retrieval plus Qwen synthesis | requires a HomeHub AccessContext and filters before synthesis |

`POST /api/knowledge/search` accepts `{ "query": "...", "projectId": "..." }`.
Without a valid HomeHub context projection it returns `503
access_context_unavailable`; it never searches the entire output directory as a
fallback. The same redaction applies to the snapshot: without explicit
`projectScopes` and `sourceScopes`, project names, paths, counts, and evidence
are not published. Every response carries `X-UYP-Audit-Id`. Model calls remain
`think:false` through the existing search implementation.

This adapter does not implement pairing, grants, revocation, NandaTown
invites, or IndexJob mutation. Those operations belong behind the HomeHub and
connector adapters described in `docs/EXECUTION_PLAN.md` and must be added with
their own durable state and audit contracts.

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
  --grant-id g_example --grant-epoch homehub-epoch-1

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
