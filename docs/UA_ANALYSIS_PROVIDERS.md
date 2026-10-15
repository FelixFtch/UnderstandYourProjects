# Understand Anything analysis providers

UnderstandYourProjects keeps the **Laya triage stage local**. Laya decides
which files need deep enrichment before any model-provider choice is applied.
The provider choice only affects the bounded Qwen-style enrichment and the
optional project-digest synthesis. Understand Anything still performs the
same scan, structure extraction, import graph, layers, tours, and evidence
publication in both modes.

This preserves the Jetson operating profile:

```
Connector grant -> Laya (local) -> UA structure/graph ->
  local resident Qwen OR owner-selected OpenAI-compatible/Claude API ->
  KnowledgeItem + evidence -> HomeHub-scoped Studio/Jarvis
```

## Local mode

The absence of `~/dev/uyp/state/ua-cloud.json`, or a config with
`"mode": "local"`, keeps the existing Ollama route. Local weights stay
resident; switching back does not require downloading or loading a model.

## Cloud mode

The owner-facing HomeHub settings adapter writes a `0600` JSON file at
`~/dev/uyp/state/ua-cloud.json`. The indexer reads it and reads the API key
from a separate `0600` file. Keys never appear in the config JSON, logs, UA
artifacts, or exception text.

```json
{
  "mode": "cloud",
  "provider": "qwen",
  "model": "qwen3.8-plus",
  "api_key_file": "~/.config/homehub/qwen.key"
}
```

When the mode is selected in Studio, HomeHub writes the selected provider key
to `~/.config/homehub/<provider>.key` with a 0700 directory and 0600 file
before the next index pass. UYP only reads that local file; no companion HTTP
endpoint returns the full secret. A manually managed deployment may set an
explicit `api_key_file` instead.

Supported OpenAI-compatible providers and their default base URLs are:

| provider | default base URL | example model |
| --- | --- | --- |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3.8-plus` |
| `openai` | `https://api.openai.com/v1` | operator-selected model |
| `deepseek` | `https://api.deepseek.com/v1` | operator-selected model |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai` | operator-selected model |
| `grok` | `https://api.x.ai/v1` | `grok-4.7` |
| `muse` | `https://api.meta.ai/v1` | `muse-spark-1.3` |

`claude` uses the native Anthropic Messages envelope at
`https://api.anthropic.com/v1/messages`. It is kept as a separate dialect so
the system prompt and typed text blocks are not silently sent in an
OpenAI-shaped request.

For a user's existing Miku/Bailian gateway, or an OpenAI-compatible reverse
proxy, set `base_url` explicitly. The path must stop at the API base; the
client appends `/chat/completions`.

```json
{
  "mode": "cloud",
  "provider": "custom",
  "model": "my-qwen-route",
  "base_url": "http://127.0.0.1:9000/v1",
  "api_key_file": "~/.config/homehub/miku.key"
}
```

`custom` is intentionally a configuration-only profile. The Studio catalog
does not advertise an arbitrary endpoint until HomeHub has allow-listed it.
This avoids turning a browser setting into an SSRF or secret-forwarding path.

The documented vendor bases are references, not proof of access. A provider
is only usable after its owner key, model entitlement, network route, and
response contract have been verified. Muse's official Model API documents an
OpenAI-compatible base at `https://api.meta.ai/v1`; xAI documents its
OpenAI-compatible inference API at `https://api.x.ai`.

## Failure and rollback behavior

- One cloud error marks only the current file as `structure-only` and retains
  the UA graph and source provenance.
- Five consecutive cloud failures trip a per-job breaker. Remaining files
  remain structure-only and the run state records `cloud_enrich_broken`.
- A later file success resets the consecutive-failure count before the breaker
  trips.
- Local mode remains the fallback for a missing or invalid cloud config. A
  broken cloud profile is visible in worker output; it does not silently claim
  that cloud enrichment completed.

The implementation is deliberately provider-neutral and stdlib-only in
`services/indexer/src/ua_llm_client.py`; it does not add a second resident
model beside Laya/Qwen or change HomeHub's identity, policy, revocation, or
audit authority.

Qwen requests explicitly send `enable_thinking: false` for bounded enrichment;
this is the cloud equivalent of the local route's `think: false` requirement.
