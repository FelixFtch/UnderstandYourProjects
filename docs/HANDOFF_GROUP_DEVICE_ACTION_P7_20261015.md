# Group device-action / Miku / NandaTown handoff

Date: 2026-10-15
Repository: `FelixFtch/UnderstandYourProjects`
UYP HEAD at handoff: `58bd41a docs: record deployed laya intent gate`
HomeHub HEAD observed: `3a02969 fix(agent-runtime): use laya score domain contract`

This document is the handoff boundary for the next agent. It records what is
real, what is only a local contract or dry-run, and the exact work still needed
for the Group device-action and NandaTown P7 acceptance. It deliberately does
not treat a legacy Studio card, a NandaTown participant, or a local UYP group
record as HomeHub authorization.

## What is already implemented and verified

### HomeHub/Jarvis runtime

- HomeHub remains the authority for identity, device ownership, policy, grants,
  revocation, and audit.
- The Jetson runtime has a local Laya intent gate on `:8901`; the gate is
  enabled and the HomeHub agent runtime on `:8868` requires it for ambiguous
  turns. The deployed HomeHub commits are `a9da75b`, `4063c28`, and `3a02969`.
- The existing voice/chat device route is live. Kitchen light on, state
  read-back, and off were tested through the governed HomeHub route; the final
  state was off. This is separate from Studio's device projection.
- The Miku bridge already uses HomeHub ADR-0028 HMAC delegations. It asks the
  companion for a short-lived delegation and sends a signed
  `X-Jarvis-Delegation` header to Miku. Miku's endpoint is local at
  `127.0.0.1:7102`, exposes eight capabilities, and accepts task contracts.

### UnderstandYourProjects / UYP

- Query API, scoped retrieval, evidence projection, graph snapshots, and the
  UYP Studio bridge are implemented. The deployed Jetson query API has returned
  a valid HomeHub access context and owner-scoped evidence in earlier checks.
- UA graph snapshots are readable. The observed graph sizes were:
  - `jarvis-memory-live`: 645 nodes, 843 edges, 4 layers, 6 tour steps;
  - `jarvis-homehub`: 23,175 nodes, 29,210 edges, 8 layers, 10 tour steps.
- Evidence responses include HomeHub-related audit data (`auditId`, grant epoch,
  expiry/visibility projections, and producing Jarvis) when the caller is
  authorized.
- Index jobs and KnowledgeItems are published. The last observed mirror state
  still had 86 gBrain jobs queued, so “UA graph exists” must not be reported as
  “every graph node is searchable in gBrain.”
- Laya intent routing is documented in `docs/TARGET_ARCHITECTURE_V2.md` and
  deployed to HomeHub; do not add a second intent authority in UYP.

### Existing federation contract

- `docs/AGENT_IDENTITY_MESSAGING_SKILL_V1.md` defines the shared
  `uyp-agent-identity-v1` card and message envelope.
- `services/indexer/src/federation_protocol.py` validates card/message/invite
  shape, expiry, audience, forbidden fields, and `kind`/`type` compatibility.
- The validators are intentionally offline. They do not verify a HomeHub
  signature, issue a card, mint a grant, or authorize a device action.
- `services/indexer/src/nandatown_client.py` is a transport adapter for Town
  discovery and mailbox delivery. It is not an identity or permission store.
- `services/indexer/src/group_device_actions.py` is fail-closed. With a
  HomeHub-issued group context containing explicit `device_ids` and
  `action_ids`, it can return a provider-neutral `dry_run` plan. `live` always
  returns `group_device_action_pending` until HomeHub provides a group device
  delegation.
- UYP group routes and group retrieval are implemented, but the local group
  registry is only an input to HomeHub issuance. It cannot widen access.

## Current Miku and Town reality

The next agent must begin from these facts, not from the UI label “authenticated”:

- Miku is currently authenticated by the existing HomeHub ADR-0028 delegation
  path, not by the new `uyp-agent-identity-v1` card. Its default peer URN and
  display name are routing values, not proof of identity.
- HomeHub `/api/studio/me`, `/internal/studio/card`, and
  `contacts.my_card()` currently return the legacy unsigned card
  `{display/number/urn/town}`. They do **not** return `cardId`, issuer,
  expiry, revocation reference, key fingerprint, or signature.
- HomeHub has no live `identity.describe/verify` endpoint for the new card yet.
  The static `/a2a/card` is a public probe card and is not a HomeHub identity
  proof.
- Miku's Studio group handling is legacy JSON-over-contracts-v1
  (`group.invite`, `group.accept`, `group.message`). It does not carry a
  verified skill card or group device grant.
- The current Jetson Town run observed was `run-4a76172d8ed6` with participants
  `clinic`, `home`, and `uyp-indexer`. Miku was not a Town participant.
- The Jetson companion database had a verified `felix.miku` contact, but no
  durable Studio group row. A direct contact is therefore not evidence that
  Miku has joined a group.
- Group device action is not production-ready: no HomeHub-issued group
  `device_ids`/`action_ids` context or group delegation was observed.

## What remains to do

### P0 — add the HomeHub adapter for the shared skill

Implement this in HomeHub first; UYP must remain a verifier/consumer:

1. Add a HomeHub-authenticated `identity.describe` projection for Miku and
   each Jarvis node. It must return the fields required by
   `validate_agent_card`, with an actual HomeHub signature, expiry, audience,
   key fingerprint, and revocation reference.
2. Add a HomeHub verification path for `identity.verify` that checks issuer,
   audience, expiry, revocation, contact/group policy, and the current grant
   epoch. Do not make UYP or NandaTown hold the issuer key.
3. Make the Miku bridge obtain that projection before emitting a verified
   `agent.*` or `group.*` envelope. Keep ADR-0028 task delegations for the
   existing `/tasks` endpoint during migration; do not remove the working path
   until dual-read/dual-write tests pass.
4. Dual-write `kind` and legacy `type`, add `messageId`, `requestId`, nonce,
   expiry, audience, and opaque `authorizationRef` to Miku group envelopes.
   Never put a bearer, AccessContext, grant body, source bytes, or filesystem
   path in an envelope.

### P1 — put Miku in a real HomeHub/Town group

1. Use the existing HomeHub contact/group UI/API; do not create a second local
   group authority in UYP.
2. Create or reuse a dedicated test group with Jetson Jarvis and Miku as two
   independent members. The group membership and its sharing scope must be
   issued by HomeHub, not inferred from a Town run.
3. Add a dedicated Town participant/session for Miku. Check the participant
   directory and mailbox claim/ack on both sides. A Town join alone is not
   sufficient; record the corresponding HomeHub contact/group authorization.
4. Send a harmless `group.message` (“identity handshake”) in both directions
   and capture sender node, receiver node, group id, request id, authorization
   reference, and HomeHub audit id.

### P1 — add the HomeHub group device delegation

HomeHub must issue a group context containing, at minimum:

```json
{
  "group_id": "...",
  "member_id": "...",
  "jarvis_node_id": "...",
  "grant_epoch": "...",
  "policy_digest": "...",
  "expires_at": "...",
  "audit_id": "...",
  "device_ids": ["home-device-kitchen-light", "home-device-living-room-light"],
  "action_ids": ["home.light.turn_on", "home.light.turn_off", "home.light.read_state"]
}
```

The actual wire may use camelCase, but HomeHub must be the issuer and UYP must
only validate/intersect the scopes. The adapter then needs to:

1. prove `dry_run` for one allowed light action;
2. execute one harmless live action through the same HomeHub action route used
   by voice, Studio, and iPhone;
3. read the device state back and match the receipt;
4. revoke the group delegation or advance the grant epoch;
5. prove the same request returns `denied` after revocation.

No provider-specific entity id or ESP-NOW details may cross the group envelope.

### P2 — NandaTown P7 acceptance

P7 is complete only when all of the following are evidenced in one run:

- two independent Jarvis node cards, both issued/verified by HomeHub;
- a HomeHub-approved group membership and bounded knowledge/device scope;
- bidirectional Town delivery with attribution and request ids;
- a scoped project question answered by the receiving Jarvis with evidence refs;
- one group device `dry_run`, one live action/read-back, and post-revocation
  denial through the same HomeHub action route;
- offline/expired/revoked peer behavior is fail-closed;
- the audit trail contains the group invite/accept, message, action receipt,
  and revocation event.

Until those artifacts exist, report “NandaTown transport works; P7 pending” and
“group device-action dry-run contract exists; production delegation pending.”

## Acceptance commands for the next agent

Use the existing SSH config/Cloudflare route and redact all secrets. If the
host alias cannot be resolved in the current shell, record it as an execution
environment limitation and retry from the normal Mac terminal; do not infer
Jetson health from that one failure.

```bash
# HomeHub and Town health (Jetson loopback)
ssh jetson-us-cf 'curl -fsS http://127.0.0.1:5120/a2a/card'
ssh jetson-us-cf 'curl -fsS http://127.0.0.1:8477/health'

# Miku bridge and contract catalog (Mac)
curl -fsS http://127.0.0.1:7102/health
curl -fsS http://127.0.0.1:7102/capabilities

# UYP contract and fail-closed checks
python3 -m unittest discover -s services/indexer/tests -p 'test_homehub_federation_contracts.py'
python3 -m unittest discover -s services/indexer/tests -p 'test_group_device_actions.py'
python3 -m unittest discover -s services/indexer/tests -p 'test_nandatown_wiring.py'
```

Before touching a live group, snapshot the current HomeHub/UYP state and save
the exact commit, service PIDs, grant epoch, group id, Town run id, and audit
ids. Never paste `homehub.token`, Town join tokens, delegation keys, or signed
wire values into GitHub, logs, or this document.

## Handoff conclusion

The project has real progress: local Laya-gated Jarvis routing, governed light
control, UYP graph/evidence/search, the shared identity/message contract, Town
transport, and a fail-closed group device-action dry-run seam are present. The
remaining work is a narrow integration gap in HomeHub: issue and verify the
shared signed identity card, issue group membership/device delegation, then
run the two-node Town/action/revocation acceptance. Do not replace the working
voice or Studio route, do not add a new pairing ceremony, and do not declare
P7 from the current unsigned Miku card or NandaTown directory metadata.
