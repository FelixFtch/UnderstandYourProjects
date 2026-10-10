# HomeHub and Jarvis Federation Adapter V1

Status: protocol contract and local conformance implementation.  This file
does not claim that HomeHub, Cloudflare, or NandaTown is deployed.

## Authority boundary

UnderstandYourProjects consumes a HomeHub-issued `AccessContext` projection.
`services/indexer/src/homehub_adapter.py` validates that projection and fails
closed when it is missing, malformed, revoked, or expired.  The knowledge
plane cannot create a principal, widen a project/source scope, issue a grant,
pair a device, revoke a grant, or write an audit event.  HomeHub remains the
only authority for those operations.

The projection must contain:

```json
{
  "principalId": "homehub-principal",
  "sessionId": "session",
  "jarvisNodeId": "jetson-1",
  "projectScopes": ["project:alpha"],
  "sourceScopes": ["connector:mac"],
  "grantEpoch": "epoch-42",
  "policyDigest": "sha256:...",
  "expiresAt": "2026-10-09T23:00:00Z",
  "auditId": "homehub-audit-id"
}
```

The local file used by the current Jetson proof is a deployment transport, not
an authority.  A production adapter must replace it with a HomeHub local IPC
or authenticated endpoint and retain the same validation contract.

## Connector registry

`connector_registry.py` stores non-sensitive observations needed by Studio and
the IndexJob scheduler: connector/node identifiers, reachability transport,
manifest state, capabilities, source capability IDs, and HomeHub review
references.  It refuses tokens, secrets, passwords, source paths, and root
directories.  It cannot mark a connector paired unless a HomeHub projection
has first reported that state.  Atomic writes and mode `0600` prevent a
partially-written registry from being treated as current.

The registry is not a replacement for HomeHub's device registry.  It is a
restart-safe cache that may be discarded and rebuilt from HomeHub and the
Connector status endpoint.

## Pairing and Cloudflare transport

The safe production sequence is:

```text
HomeHub device ownership review
  -> one-time pairing approval / nonce
  -> Connector pair exchange
  -> HomeHub records the node and grant epoch
  -> Connector manifest dry-run
  -> HomeHub approves a source grant
  -> durable IndexJob
```

mDNS or a Cloudflare endpoint can report transport reachability.  They cannot
establish ownership, issue a grant, or revoke access.  The current
`connector-mac` `/pair` route is still a local V1 draft that accepts the
one-time code and records the supplied Jetson identifier.  Before P7 it must
consume a HomeHub pairing approval reference and reject a client-supplied node
identity that HomeHub has not registered.  Cloudflare tunnel setup is an
operator/deployment concern and is not implemented by this repository.

`pairing_protocol.py` validates the transport-neutral approval metadata that
such an adapter must consume. It requires a HomeHub approval ID, both
device/node identifiers, a nonce, grant epoch, expiry, audit reference, and
an origin-only endpoint. It rejects credentials and requires HTTPS for a
Cloudflare transport. Passing this validator is not a pairing operation; the
HomeHub adapter still has to redeem the approval, rotate the Connector token,
and record the resulting audit event.

## NandaTown and Agent Groups

`federation_protocol.py` defines the transport-neutral envelope:

- requests carry protocol version, request/group IDs, sender/recipient nodes,
  a read-only operation, bounded query, nonce, audience, and expiry;
- responses carry the producing Jarvis, knowledge version, visibility,
  evidence references, and audit ID;
- raw source bytes, arbitrary filesystem paths, vector stores, and full
  databases are rejected by the response validator.

NandaTown directory metadata is public discovery only.  It may contain a
peer/node label, transport, status, and capabilities.  It must not contain
project names, source paths, grants, tokens, or private knowledge counts.
The receiving Jarvis performs its own HomeHub validation before searching and
returns an attributed summary or evidence references.  A revoked or expired
context invalidates new requests and cached remote results.

`validate_group_invite` and `validate_group_invite_result` cover the missing
directory-to-group seam. An invite is a draft carrying node IDs, audience,
expiry, nonce, audit reference, share policy, and optional *requested* opaque
scope IDs. It does not carry a grant or `AccessContext`, and an acknowledgement
only says `pending`, `accepted`, `declined`, `expired`, or `revoked`. HomeHub
must make the membership and scope decision before either Jarvis may search.
NandaTown should deliver these envelopes and presence metadata, then leave
authorization and evidence retrieval to the two HomeHub-aware Jarvis nodes.

The remaining production work is external integration:

1. HomeHub adapter endpoint with signed or locally authenticated projections;
2. HomeHub-owned pairing approval and revocation callbacks;
3. Cloudflare tunnel lifecycle and endpoint identity pinning;
4. NandaTown directory/invite/group transport;
5. deploy the durable worker scheduler and complete P7 end-to-end evidence.

Until those are present, Studio must display `pending`, `offline`, or
`access_context_unavailable`; a local protocol test or HTTP 200 is not a live
pairing, grant, federation, or P7 acceptance.
