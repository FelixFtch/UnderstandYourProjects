# Jetson Query API

`services/indexer/src/query_api.py` is the first server adapter between the
Jetson knowledge store and Studio. It wraps the existing `knowledge_search.py`
proof of concept; the browser never calls Ollama or a Connector directly.

## Run

```bash
UYP_OUTPUT_ROOT=~/dev/uyp/output \
UYP_ACCESS_CONTEXT_FILE=~/.config/uyp/access-context.json \
python3 services/indexer/src/query_api.py --port 8787
```

The default bind is `127.0.0.1`. `--lan` is an explicit deployment choice and
must sit behind the approved transport. `UYP_STUDIO_API_URL` points the web
build at this service, for example `http://127.0.0.1:8787` during a local
development session.

## Read-only endpoints

| Endpoint | Purpose | Authority boundary |
| --- | --- | --- |
| `GET /api/health` | service, output, connector, and AccessContext presence | does not infer access |
| `GET /api/studio/snapshot` | project, source, health, evidence, and IndexJob projection | only publishes HomeHub context when supplied |
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
