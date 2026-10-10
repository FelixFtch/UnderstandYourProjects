# HomeHub ↔ UnderstandYourProjects authority contract

HomeHub remains the sole authority for identity, device ownership, policy,
grant issuance, revocation, and audit. UnderstandYourProjects consumes a
short-lived `AccessContext`; it does not mint one, extend it, or infer access
from a Connector token.

The companion API in the HomeHub repository exposes these authenticated
routes:

| Route | Owner action | Result |
| --- | --- | --- |
| `POST /api/uyp/grants` | Create a project/source grant for a member | Opaque `grantId`, scope IDs, expiry, epoch, audit ID |
| `GET /api/uyp/grants` | Read the caller's active grants | Bounded grant projection |
| `POST /api/uyp/grants/{grantId}/revoke` | Revoke a grant | New epoch and audit ID |
| `GET /api/uyp/access-context` | Resolve the caller's current policy | Short-lived `AccessContext` |
| `GET /api/uyp/access-context/audit` | Owner-only audit view | HomeHub audit rows |

Grant `project_id` and `source_ids` are opaque capability identifiers. They
must never be filesystem paths, source roots, bearer tokens, or file contents.
The response contains no Connector secret. Revocation increments the
HomeHub-owned `grantEpoch`; a previously issued context then fails UYP's
epoch check when the worker refreshes policy.

## Jetson transport

On Jetson, the UYP worker reads the projection from HomeHub over the local
Companion API. When this URL is configured it is authoritative for every
read; a stale local projection is never used as a fallback after a transport
failure:

```ini
UYP_HOMEHUB_ACCESS_CONTEXT_URL=http://127.0.0.1:5120/api/uyp/access-context
UYP_HOMEHUB_TOKEN_FILE=%h/.config/uyp/homehub.token
```

The token file must be provisioned by the HomeHub pairing/session flow and be
readable only by the Jetson service user. Never copy the Connector token into
this file. The UYP adapter sends one authenticated GET, validates every
required field and expiry, and returns unavailable on any failure.

The IndexJob worker uses this same adapter. A timer pass with no valid
HomeHub context leaves queued jobs unchanged and reports
`homehub_access_context_unavailable`; it does not create a grant or index
unscoped files.

## First production acceptance path

1. HomeHub owner session creates one grant for one opaque project and source.
2. The Jetson service reads `/api/uyp/access-context` with that session token.
3. The authorized Connector supplies its own short-lived read capability for
   the same source. A durable UYP `IndexJob` is created with that Connector
   capability plus the HomeHub project/source scope and epoch. These are two
   deliberately separate grants: the Connector capability is never treated
   as a HomeHub identity or policy decision.
4. The worker reads the authorized Connector manifest, stages the files,
   runs Understand Anything plus the existing Laya/Qwen enrichment, and
   atomically publishes the graph and evidence projection.
5. Studio queries the UYP API and shows only the authorized project/evidence.
6. HomeHub revokes the grant. The next worker/query policy check observes the
   new epoch and stops or redacts the job; HomeHub audit contains issue and
   revoke events.

Do not call this P7 until the six steps above are demonstrated on Jetson with
real HomeHub credentials. Multiple Jetsons and NandaTown federation are a
separate acceptance stage and cannot substitute for this single-node proof.
