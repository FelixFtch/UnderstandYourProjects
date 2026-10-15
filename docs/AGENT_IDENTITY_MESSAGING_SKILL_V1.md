# HomeHub Agent Identity & Messaging Skill v1

**Status:** protocol contract and offline conformance checks only  
**Authority:** `jarvis-homehub` (HomeHub)  
**Consumers:** Felix's Jarvis, Miku, Robin's Jarvis, UYP, and NandaTown adapters

This document records the smallest shared seam for Jarvis-to-Jarvis discovery
and messaging. It is intentionally not a new identity service, directory, or
permission store. HomeHub continues to issue and revoke identity cards,
resolve the principal, approve contacts/groups, issue grants and delegations,
and write the audit record. UYP only validates transport shape before handing
an envelope to a HomeHub-aware receiver.

## What already exists

The audit of the current codebases found useful pieces that should be reused:

| Existing piece | Current role | Boundary |
| --- | --- | --- |
| HomeHub `AccessContext` (`homehub_adapter.py`) | Principal, Agent Box node, grant/source scopes, epoch, expiry, audit projection | Issued and revoked by HomeHub; UYP validates only |
| HomeHub `contacts.my_card()` and `/api/studio/me` | Public display card: `display`, deterministic `J-####-####`, `urn`, optional Town participant | Discovery/display metadata; the current card has no signature and is not proof of trust |
| HomeHub `agent_contracts` ADR-0028 | `Capability`, `Delegation`, `TaskRequest`, `TaskEvent`, `TaskResult`, `ActionReceipt` | Canonical task/delegation contracts; no new copy belongs in UYP |
| HomeHub `agent-gateway` Directory | Allowlisted URNs, protocol and verified flag, outbound Gatehouse | HomeHub gateway decides whether a remote send is callable |
| UYP `federation_protocol.py` | Peer/query/invite/response shape validation | No network I/O, grant, signature, or revocation decision |
| UYP `nandatown_client.py` | Town join/session, public participants, mailbox claim/ack | Discovery and delivery only; a Town participant is not automatically trusted |
| HomeHub Miku bridge envelopes | Legacy `contact.*` and `group.*` JSON-over-contracts-v1 interception | Compatibility transport; it does not carry a HomeHub AccessContext |

The important gap is that these pieces do not yet expose one common
`identity.describe/verify` and message envelope. The new contract below makes
the gap explicit without replacing any of the working HomeHub or Miku paths.

## Identity card

`identity.describe()` is a public, non-secret card returned by a HomeHub-aware
adapter. The stable identifiers are:

```json
{
  "schemaVersion": "uyp-agent-identity-v1",
  "cardId": "card:opaque",
  "principalId": "optional HomeHub projection, not public by default",
  "jarvisNodeId": "jetson-1",
  "agentUrn": "urn:jarvis:felix",
  "jarvisNumber": "J-1234-5678",
  "displayLabel": "Felix's Jarvis",
  "capabilities": ["project.search", "group.message"],
  "issuer": "homehub",
  "audience": "nanda-town",
  "issuedAt": "2026-10-15T12:00:00Z",
  "expiresAt": "2026-10-15T12:15:00Z",
  "revocationRef": "homehub:card:opaque",
  "keyFingerprint": "sha256:…",
  "signature": "opaque HomeHub signature"
}
```

`principalId` is kept in the private HomeHub `AccessContext` unless the
HomeHub policy explicitly permits it in a contact card. `agentUrn` and the
human-friendly Jarvis number are names for display/routing; neither is a
permission key. IP addresses, hostnames, e-mail addresses, model names, and
Town participant names are never identity substitutes.

`identity.verify(peer_card)` has two stages:

1. HomeHub verifies the issuer signature, audience, expiry, and revocation
   state, and resolves the peer node/contact/group policy.
2. The receiving Jarvis/UYP validator checks the envelope shape and refuses a
   missing, expired, revoked, or audience-mismatched projection.

The pure UYP validator in `src/federation_protocol.py` implements stage 2. It
does **not** hold an issuer key or turn a valid-looking card into trust. The
legacy HomeHub `my_card()` shape (`display/number/urn/town`) remains useful for
NandaTown discovery and invite UI, but deliberately fails the verified-card
validator until a HomeHub adapter adds the signed fields.

## Shared message envelope

All direct, group, and invite messages use the following outer envelope. The
legacy `type` field may be duplicated as `kind` while Miku and HomeHub are
migrated; new code should emit `kind`.

```json
{
  "schemaVersion": "uyp-agent-identity-v1",
  "messageId": "msg:opaque",
  "kind": "agent.ask",
  "requestId": "req:opaque",
  "senderNodeId": "jetson-1",
  "receiverNodeId": "robin-jetson",
  "contactId": "contact:opaque",
  "groupId": null,
  "sessionId": "session:opaque",
  "nonce": "one-time-opaque",
  "issuedAt": "2026-10-15T12:00:00Z",
  "expiresAt": "2026-10-15T12:01:00Z",
  "audience": "robin-jetson",
  "authorizationRef": "homehub:delegation:opaque",
  "scope": {
    "sharePolicy": "summary_only",
    "projectScopes": ["project:alpha"],
    "sourceScopes": ["connector:mac"]
  },
  "body": {"question": "Which project has the parser?"}
}
```

`groupId` is required for `group.*` messages. `contactId` is required for
`contact.*` and direct `agent.*` messages; a group `agent.*` request uses
`groupId` instead. `authorizationRef` is an opaque HomeHub delegation/grant
reference, never a bearer or AccessContext. The receiver must resolve it
locally before retrieval or dispatch.

Supported kinds are `agent.ask`, `agent.reply`, `contact.invite`,
`contact.accept`, `group.invite`, `group.accept`, and `group.message`.
`scope.sharePolicy` is either `summary_only` or
`summary_and_evidence_refs`; project/source scopes are opaque capability IDs.
The body is bounded to 64 KiB and cannot contain raw source bytes, arbitrary
filesystem paths, vector stores, databases, bearer tokens, grants, or an
AccessContext. Answers may contain a bounded summary and evidence references;
the receiving Jarvis obtains exact evidence from its own UYP/UA store.

The UYP validator accepts no operation that mutates a remote device or grants
permission. A remote action, if ever introduced, must use a HomeHub action
route and `ActionReceipt`; it must not be smuggled into `agent.ask`.

## Adapter mapping

### Felix/Robin Jarvis

The HomeHub companion `/api/studio/me` remains the source for the local card.
The companion creates contacts and groups, obtains HomeHub delegation/grant
references, and sends through the existing agent-gateway. UYP receives only a
validated projection or an opaque `authorizationRef`.

### Miku

The Miku bridge may continue to send contracts-v1 tasks and JSON-over-question
compatibility envelopes while migration is in progress. Its
`MIKU_BRIDGE_PEER_URN` and display name are routing defaults, not proof of
identity. The bridge should obtain the signed card from its HomeHub companion
hook before emitting a verified `agent.*` message. Existing
`contact.invite/accept` and `group.message` kinds map directly to the shared
kind set.

### NandaTown

NandaTown continues to carry discovery metadata and mailbox delivery. Its
`participants` response is an advertised directory entry only. Joining a run
creates a Town session for delivery; it does not issue a HomeHub contact,
group membership, grant, or identity card. The receiver performs
`identity.verify` and local policy checks after claiming a message.

## Offline contract checks

`services/indexer/src/federation_protocol.py` exposes:

- `validate_agent_card(card, audience=...)` for the non-authoritative shape,
  expiry, revocation marker, and audience checks;
- `validate_agent_message(envelope)` for required routing identifiers,
  conversation binding, share policy, expiry, size, and forbidden-field
  checks.

Tests in `services/indexer/tests/test_homehub_federation_contracts.py` cover
legacy discovery cards, wrong audiences, revocation, missing conversation
bindings, expiry, and attempts to put credentials or private source material
on the wire. These are offline tests; they do not claim a live HomeHub
signature, NandaTown delivery, or cross-Jarvis federation.

## Rollout order

1. Keep current HomeHub contacts, Miku contracts-v1, and NandaTown transport
   running unchanged.
2. Add a HomeHub adapter that returns the signed card and verifies the
   `authorizationRef`; do not duplicate that authority in UYP.
3. Add dual-read/dual-write compatibility (`type` + `kind`) at the Miku and
   Town edges, with a request ID and audit reference on every new message.
4. Route Studio direct/group messages and UYP federation through the same
   verified envelope, then remove the legacy fields only after both HomeHub and
   Miku conformance suites pass.
5. Validate revocation and offline behavior with a real HomeHub session before
   calling the Agent Groups/P7 gate complete.

