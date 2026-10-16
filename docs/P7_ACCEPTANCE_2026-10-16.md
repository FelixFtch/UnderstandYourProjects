# NandaTown P7 acceptance evidence — 2026-10-16

**Status:** live run on the real two-node mesh (Jetson `yahboom` + Mac `felix.miku`), single session.
**Baseline snapshot:** homehub `1fedcc2`, UYP `dea9abb`, nandatown local `ed99ca4`; grant epoch 66 at start;
group `t_4f4bca886db3f3bc`; Town run `run-4a76172d8ed6`; companion PID 2931615, listener 2878845, coordinator 2878866.

## The seven P7 items

### 1. Two independent node cards, both issued/verified by HomeHub

| node | cardId | key fingerprint | issue audit | verify |
|---|---|---|---|---|
| home (`yahboom-uyp`) | `card:2fe5952027f08991129724e4b5d91061` | sha256:f3f70c6f… | uyp-audit-188a9414ba6441bdbe9803805cef275f | ok (uyp-audit-1cf161c56c6b4272b686b875f6f93d11) |
| miku (`felix.miku`) | `card:fde222f97ab3edf1cfcfe9cd4ae388b7` | sha256:15e707bb… | uyp-audit-82ff1df8d5904a6898d5cf4ec35c2572 | ok (uyp-audit-90078f75939b47eea79354676618f8d4) |

Distinct keys, distinct issuers' ledgers (Jetson companion :5120 / Mac companion :7105), both schema `uyp-agent-identity-v1`.

### 2. HomeHub-approved group + bounded scope

Group `t_4f4bca886db3f3bc` created through the HomeHub Studio threads API (owner bearer). UYP
local registry view bounded to `project_ids: [jarvis-homehub, jarvis-memory-live]`, `source_ids: ["*"]`;
device scope issued separately as signed grant `hhgdg-7a051e604fb04fed9fdadf11fbd98331`
(device `home-device-kitchen-light`, actions `turn_on/turn_off/read_state`).

### 3. Bidirectional Town delivery with attribution and request ids

| direction | Town message id | requestId | landed as |
|---|---|---|---|
| home → miku | `msg-p7-home-001` | req-p7-001 | poller claim + companion inbound |
| miku → home | `msg-p7-miku-001` | req-p7-002 | listener → Jetson thread `m_eb9ffd12d7919704` |

Miku's autonomous reply also rode back (`m_acc3a8ac40ddd37e`). Sender attribution via Town
participant names (`home`/`miku`) and envelope `senderNodeId`.

### 4. Scoped project question answered with evidence refs

`POST /api/groups/t_4f4bca886db3f3bc/search` — "how does XVF3800 detect end of speech" answered
with high confidence citing `voice-satellite/firmware-xvf3800/tools/phase_b_gateway/endpoint.py`
(plus two corroborating sources with match scores). Group-scoped auditId `6a78d6c3-b877-4b31-8938-22d284b1aab3`.
(Form used: group knowledge query per TARGET_ARCHITECTURE_V2 §3; the group's knowledge view
bounded the retrieval.)

### 5. Group device dry_run → live → read-back → revoke → denied (same governed route)

| step | result | evidence |
|---|---|---|
| issue grant | 201, epoch 66→67 | audit uyp-audit-f743adf5779a41 |
| dry_run | 200, `status: dry_run`, executed false | req-p7-dry |
| live turn_on | 200, `executed: true`, state `{power: on}` | req-p7-live-on |
| live turn_off + readback | 200, `executed: true`, state `{power: off}` (state restored) | req-p7-live-off |
| revoke | 200, epoch 67→68 | audit uyp-audit-2b97d8bb885842 |
| replay same request | **403 `group_context_invalid: revoked`** | req-p7-replay |

### 6. Offline/expired/revoked behavior is fail-closed

- revoked grant: live replay denied (item 5);
- revoked card: Mac companion verify → `{ok: false, reason: revoked}` (live, this run);
- expired card: covered by unit negatives (`test_studio_identity.py`); a live expiry run needs a
  service-env TTL change and is left as a scripted follow-up;
- offline/unknown peer: Town accepted `msg-p7-ghost` to a non-existent participant as **queued
  mailbox state (202)** — delivery is never fabricated; no claim/ack exists for it.

### 7. Audit trail

Jetson `uyp_audit_events` (this run): `homehub.group_device_grant.issue` (epoch 67) →
`homehub.group_device_context.verify` ×3 → `homehub.group_device_grant.revoke` (epoch 68);
identity card issue/verify rows for both cards (item 1); `homehub.group_message.send/receive`
rows from the P1a wiring (same day). Town coordinator events carry `participant_added` (miku)
and the message deliveries. **Honest gaps:** the group invite/accept pair predates this run and
is not in the HomeHub audit stream (group-message auditing was added today); the device action
`auditRef` on the governed local fallback is empty — the production route session bridge reports
`homehub_session_bridge_unavailable`, so receipt anchoring currently comes from the grant
verify/revoke audits instead of per-action persisted receipts.

## Verdict

P7 acceptance criteria are evidenced in one run with the deviations listed above (expired-card
covered by tests; offline peer = honest mailbox queue; per-action auditRef pending on the
production bridge fix). Prior status line "NandaTown transport works; P7 pending" is superseded
by this document for the two-node home↔miku mesh.
