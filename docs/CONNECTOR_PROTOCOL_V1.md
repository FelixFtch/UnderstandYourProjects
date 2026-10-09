# Jarvis Connector Protocol V1 (Mac side) — 2026-10-09

Status: draft for implementation (P0). Loopback+LAN only; no cloud relay in V1.

## Roles

The Connector is a thin, local, read-only file service on the owner's
computer. It does NO analysis, runs NO models, and holds NO knowledge. All
AI work happens on the Jetson. The Connector exists because a browser or an
API key cannot and should not grant whole-disk access.

```
Jetson (knowledge agent)  <---- HTTP + bearer token, LAN/loopback ----> Connector (this spec)
                                                              |
                                                    owner-granted directories
```

## Identity & transport

- Connector binds `127.0.0.1` + LAN interface; never 0.0.0.0 without owner opt-in.
- Auth: `Authorization: Bearer <device-token>`; token issued at pairing, stored
  0600 at `~/.config/uyp/connector.json` on both ends. Rotate = re-pair.
- All responses carry `X-UYP-Audit-Id` (UUID) logged locally on both machines.

## 1. Pairing — `POST /pair`

Run once per Jetson, from the Studio "add device" flow (QR/6-digit code).

```json
// request (Jetson -> Connector)
{ "pairing_code": "482913",             // shown in Studio, typed/QR'd by owner
  "jetson_id": "jarvis-home-01",        // stable node id (from HomeHub device registry)
  "jetson_pubkey_fp": "sha256:..." }    // for future mTLS upgrade; V1 records it
// response
{ "ok": true, "device_token": "uyp_t_...", "connector_version": "1.0.0",
  "hostname": "Felixs-MacBook", "os": "macos 26.4" }
```

Rules: code expires in 10 min, single use; pairing does NOT grant any
directory. Directories are granted separately, explicitly, revocable.

## 2. Directory grants — `GET /grants` / `POST /grants` / `DELETE /grants/{id}`

```json
// GET /grants -> what the Jetson may see
{ "grants": [ { "id": "g_01", "path": "/Users/felixfang/projects/jarvis-memory-live",
                "granted_at": "2026-10-09T12:00:00Z", "mode": "ro" } ] }
```

- Grant = one directory subtree, mode always `ro` in V1.
- Hard deny-list (never grantable, enforced in code): `~/.ssh`, `~/.config`,
  `~/Library/Keychains`, anything matching `*.env*`, `*key*`, `*token*`,
  `*credential*` at grant time and at read time (belt and braces).
- DELETE stops `/manifest`, `/read`, `/events` for that subtree immediately.

## 3. Manifest — `GET /manifest?grant=g_01&cursor=<cursor>`

Incremental file inventory. Cursor = opaque token (mtime+path checkpoint).

```json
{ "grant": "g_01",
  "files": [ { "id": "f_...",             // stable: sha256(relpath) — survives moves? no: renames emit events
               "relpath": "services/chat-bridge/chat_bridge.py",
               "size": 41234, "mtime": "2026-10-07T...", 
               "content_sha256": null,    // lazily filled on first read
               "kind": "file" } ],
  "deleted": ["f_..."],
  "next_cursor": "c_...", "has_more": false }
```

- Page cap 2000 entries; Jetson polls on startup, then relies on /events plus
  a periodic manifest reconciliation (network watchers are not trusted —
  Node.js docs warning applies to fsevents-over-network too).
- Excluded by rules (never listed): `.git/`, `node_modules/`, `__pycache__/`,
  `.venv*/`, `venv/`, `dist/`, `build/`, binaries >64MB (listed as kind:"blob"
  with size only), and the deny-list above.

## 4. Controlled read — `GET /read?grant=g_01&relpath=...&offset=0&length=8192`

- Range read, max `length` 1 MiB per call; total per-file cap 16 MiB without
  explicit owner bump (big-file policy: structure-only triage).
- Response: raw bytes, `Content-Type: application/octet-stream`,
  `X-UYP-Content-Sha256` when the full file was served across calls.
- Deny-list re-checked at read time. Every read logged with audit id, path,
  range. No directory listing outside grants, no symlink escape (realpath
  must stay inside the granted root).

## 5. Change events — `GET /events?since=<event_id>` (poll; SSE upgrade later)

```json
{ "events": [ { "id": "e_...", "ts": "...", "grant": "g_01",
                "relpath": "src/app.py", "kind": "modified" } ] }
```
kinds: `created | modified | deleted | renamed` (renamed carries `from`).
Source of truth is the local filesystem watcher (FSEvents on macOS) plus the
periodic manifest reconciliation as safety net.

## 6. Status — `GET /status`

`{ "state": "online", "grants_active": 1, "watcher_ok": true,
   "connector_version": "1.0.0", "last_event_id": "e_..." }`
Jetson surfaces this in Studio's Devices page; "source offline" answers must
say so honestly (freshness label), never fake freshness.

## Non-goals (V1)
No write-back. No shell/exec. No sudo. No cloud relay. No auto-discovery
beyond LAN mDNS (optional, off by default). Multi-user auth is out (single
owner principal; HomeHub stays the identity authority for queries).
