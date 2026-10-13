# Nugget `chat` task interface (coordination draft)

**Status:** draft interface reservation. This document does not claim that the
Robin Jetson poller, Nugget, iMessage, or a HomeHub session is deployed or
connected.

This is the smallest contract that lets the course poller add an owner-chat
task without changing the HomeHub task model. The `chat` discriminator belongs
to the external adapter envelope. The canonical HomeHub `TaskRequest` remains
unchanged until a separate ADR and implementation are reviewed.

## Ownership and boundary

| Component | Responsibility | Boundary |
| --- | --- | --- |
| Nugget | Message/forum transport and reply delivery | It queues a request and delivers the returned answer; it is not an authority for identity or grants. |
| `adhd-agent` poller | Robin's course/Jetson-side worker | It polls Nugget over outbound HTTPS, reads the two approved local read-only sources, and calls the configured Jarvis text endpoint. |
| HomeHub | Identity, device ownership, policy, grant, revocation, and audit | A plain `owner=true` flag or a `Jarvis:` prefix is never sufficient authorization. |
| Jarvis/HomeHub text endpoint | Conversation execution | It receives a signed/delegated identity context and returns an answer with evidence metadata. |
| clinic-agent and satellite gateway | Read-only source systems | They remain local sources; neither is exposed as a public webhook. |

The intended route is:

```text
iMessage or course forum
  -> Nugget queue
  -> Robin Jetson poller (outbound HTTPS)
  -> local Jarvis text endpoint
  -> poller
  -> Nugget
  -> original channel
```

The poller must not open an inbound Jetson port for this feature. Existing
local services such as the satellite gateway (`8766`) and demo clinic-agent
(`127.0.0.1:8895`) are read-only inputs, not public transport endpoints.

## Request envelope

The adapter reserves `task_type: "chat"` at the Nugget/poller boundary. The
inner fields map to the existing HomeHub `TaskRequest` and `ReplyBinding`
contracts. This keeps current task persistence and state transitions reusable.

```json
{
  "task_type": "chat",
  "capability_id": "chat",
  "task_request": {
    "task_id": "nugget-chat-01J...",
    "goal": "Answer the owner's question about the clinic room",
    "completion_condition": "one answer returned or an explicit failure",
    "input_refs": [],
    "delegation_ref": "homehub-delegation-01J...",
    "budget": { "rounds": 1, "timeout_seconds": 60 },
    "deadline": "2026-10-13T23:59:00Z",
    "reply_binding": {
      "channel": "nugget-imessage",
      "session": "nugget-session-01J...",
      "turn": "turn-01J..."
    }
  },
  "input": {
    "text": "ask Jarvis: what is the current clinic occupancy?",
    "requested_by": "owner-channel-assertion"
  },
  "metadata": {
    "source": "nugget",
    "correlation_id": "corr-01J...",
    "issued_at": "2026-10-13T20:00:00Z",
    "expires_at": "2026-10-13T20:02:00Z",
    "idempotency_key": "nugget-chat-01J..."
  }
}
```

`requested_by` is an assertion reference, not a free-form role. HomeHub must
validate the delegation/session before the poller can ask Jarvis for private
information. The adapter must reject missing, expired, revoked, or
audience-mismatched assertions.

HomeHub's existing contracts client already accepts `capability_id: "chat"`
and maps the capability input to a `question`. The poller may therefore use
that existing task path (including its wake/cancel operations), or the
configured local Jarvis text endpoint, but the exact URL is deployment
configuration. This document deliberately does not invent a new public
endpoint or a second chat router.

## Response envelope

Every successful answer must preserve provenance and freshness so Nugget can
display what kind of answer it received. `records` from a demo service must be
marked synthetic; a later human-answer path is a separate `human` source.

```json
{
  "task_id": "nugget-chat-01J...",
  "correlation_id": "corr-01J...",
  "status": "done",
  "answer": "The room is currently available.",
  "source_kind": "measured",
  "synthetic": false,
  "observed_at": "2026-10-13T20:00:08Z",
  "fresh_until": "2026-10-13T20:01:08Z",
  "sources": [
    { "system": "satellite-gateway", "ref": "occupancy", "kind": "measured" }
  ],
  "missing": [],
  "verification_level": "verified"
}
```

Allowed `source_kind` values are:

- `measured`: current device or gateway observation;
- `records`: stored schedule/appointment data; set `synthetic: true` for the
  course demo records;
- `human`: a later queued question answered by an identified person through
  Jarvis. The answer must carry the voice/identity evidence that HomeHub
  authorizes; it is not part of the first poller delivery.

## Polling, retry, and duplicate rules

1. The poller claims one task using `task_id`/`idempotency_key`.
2. It validates expiry and HomeHub delegation before reading local sources.
3. It calls Jarvis once for the current attempt and records the correlation ID.
4. A retry reuses the same task ID and must not send a second user-visible
   reply after a committed `done` result.
5. Terminal states are `done`, `failed`, `expired`, `revoked`, and `cancelled`.
   A missing local source is reported in `missing`; it is not silently replaced
   with a made-up answer.

The poller should use a bounded polling interval and an explicit timeout. The
15–30 second latency described for the course workflow is an expected property
of polling plus Jarvis execution, not an availability guarantee.

## What this draft does not implement

- No `adhd-agent` or Nugget code is present in this repository.
- No iMessage history reader is added. Existing phone capability rules do not
  expose arbitrary SMS/iMessage history to HomeHub.
- No HomeHub grant, revocation, audit, or session token is fabricated.
- No clinic-agent or satellite gateway is made publicly reachable.
- No new `task_type` field is added to the frozen HomeHub `TaskRequest`; that
  requires an ADR, compatibility review, and tests.

Robin can implement the adapter in her own repository against this envelope.
To review or coordinate that implementation, we need the private repository URL
and a collaborator grant or a commit/PR link; a name alone is not enough to
infer visibility.

## Acceptance checklist for a future implementation

- [ ] A signed HomeHub delegation is required and audience-checked.
- [ ] A real Nugget task can be created, claimed, retried, and cancelled.
- [ ] The poller only makes outbound HTTPS calls and reads approved local ports.
- [ ] The Jarvis response includes `source_kind`, provenance, freshness, and
      missing-source information.
- [ ] Revocation prevents a queued task from being executed or delivered.
- [ ] Duplicate polling produces at most one user-visible reply.
- [ ] A Jetson log and HomeHub audit record cover creation, execution, reply,
      failure, and revocation.

