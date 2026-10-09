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

The bridge is intentionally a separate command until the durable `IndexJob`
worker owns the `AUTHORIZED -> QUEUED -> RUNNING -> STAGED -> PUBLISHED`
transition. A worker may call the same function once HomeHub has supplied the
grant and audit context.
