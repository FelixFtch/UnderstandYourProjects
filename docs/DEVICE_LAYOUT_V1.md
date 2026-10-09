# Device layout V1 — where everything lives (2026-10-09)

Follows jarvis-homehub device discipline: dev/staging in `~/dev/<name>/`,
production only via release process; secrets in `~/.config` (0600), never in
repos; logs in the platform convention.

## Mac (owner's computer — source host + dev machine)
| Path | Role |
| --- | --- |
| `~/Documents/ChatGPT/UnderstandAnyProjects_MIT` | main repo (this repo) |
| `~/.config/uyp/connector.json` | connector config: grants, paired jetson ids, token (0600) |
| `~/.config/uyp/pairing.key` | device key material (0600, never in repo) |
| `~/Library/LaunchAgents/com.mofang.uyp.connector.plist` | LaunchAgent (per jarvis-memory-live convention) |
| `~/Library/Logs/uyp/connector.log` | logs |
| authorized dirs | ONLY owner-granted paths recorded in connector.json grants |

## Jetson home (jetson-us-cf — the Jarvis Agent Box)
| Path | Role |
| --- | --- |
| `~/dev/uyp/` | UYP dev+staging root (voice-p1 pattern) |
| `~/dev/uyp/models/` | weights: Laya-Q8, Kev-4B/0.8B, (qwen3.5 via ollama store) |
| `~/dev/uyp/llama.cpp-build/` | decision-serving llama.cpp (CUDA arch 87) |
| `~/dev/uyp/venv-gliner/` | python env (gliner experiments; safe to delete) |
| `~/dev/uyp/indexer/` | indexer service dev copy (upcoming) |
| `~/dev/uyp/state/` | analysis state root (`.ua` equivalent) — NEVER inside a source project |
| `~/dev/uyp/output/` | derived knowledge (summaries/graphs) before publish to gbrain |
| `~/jarvis/gbrain/` | knowledge store (existing; UYP publishes into it via :8790) |
| voice chain `/home/jetson/dev/voice-p1/` | UNTOUCHED production |

## 4090 (i9-cf)
| Path | Role |
| --- | --- |
| `/data/langfuse/` | observability stack (running; feeds Studio task views later) |
| (reserved) | deep 27B judge if ever needed — not resident now |

## robin / aurora
No UYP role. Clinic and read-only legs unchanged.

## Data-flow rules (red-line enforcement points)
1. Source bytes enter Jetson memory only via Connector `/read` (range-capped,
   audited); never persisted whole (state/output carry derived knowledge only).
2. Nothing is ever written back into an authorized source directory.
3. Revocation in connector.json stops `/manifest`+`/read`+`/events` immediately.
