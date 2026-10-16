# UnderstandYourProjects current state

Date: 2026-10-15  
Canonical repository: `FelixFtch/UnderstandYourProjects`  
Canonical UYP commit: `58bd41a docs: record deployed laya intent gate`  
Related HomeHub commit observed: `3a02969 fix(agent-runtime): use laya score domain contract`

This is the short status page for contributors. Start here before reading
older acceptance reports or changing a live route.

## The product target

UnderstandYourProjects is the project-knowledge plane for Jarvis: authorized
computers, NAS folders, GitHub repositories, and development devices are
understood by a Jetson Agent Box and exposed through visual project maps,
evidence-backed retrieval, coding-agent APIs, and controlled Jarvis-to-Jarvis
groups. HomeHub remains the only authority for identity, device ownership,
policy, grants, revocation, and audit. NandaTown is discovery and transport,
not a permission authority.

The accepted architecture is in
[`TARGET_ARCHITECTURE_V2.md`](TARGET_ARCHITECTURE_V2.md). The shared agent
protocol is described in
[`AGENT_IDENTITY_MESSAGING_SKILL_V1.md`](AGENT_IDENTITY_MESSAGING_SKILL_V1.md).

## What is real today

| Area | Current state | Source of truth |
|---|---|---|
| HomeHub/Laya intent gate | Deployed on Jetson; Laya is the resident local gate | HomeHub commits `a9da75b`, `4063c28`, `3a02969` |
| Voice/device route | Existing governed light route has been tested with state read-back | HomeHub agent runtime and action receipts |
| UYP Query API | Scoped search, project/source/job/evidence projections, groups routes | `services/indexer/src/query_api.py` |
| Understand Anything | UA graph snapshots and tours are readable; outputs stay under the UYP state root | `services/indexer/vendor/understand-anything/` |
| KnowledgeItems | Published for the current indexed jobs; evidence carries source/version context | UYP output/state roots on Jetson |
| gBrain mirror | Secondary mirror worker exists; queue is not fully drained | `docs/runbooks/GBRAIN_MIRROR_WORKER.md` |
| Studio | Project, sources, evidence, privacy, Jarvis, and group UI/API slices exist | `services/indexer/vendor/understand-anything/packages/dashboard/` and HomeHub companion |
| NandaTown | Discovery/mailbox transport and clinic-home messaging wiring exist | `services/indexer/src/nandatown_client.py` |
| Shared federation validators | Offline card/message/invite shape checks exist | `services/indexer/src/federation_protocol.py` |
| Group device action | Fail-closed dry-run plan only; live is deliberately rejected | `services/indexer/src/group_device_actions.py` |
| Miku | Existing ADR-0028 signed HMAC delegation works for task contracts; it is not yet on the new identity-card skill | `docs/HANDOFF_GROUP_DEVICE_ACTION_P7_20261015.md` |

Observed UA graph snapshots (not a promise of current freshness) were 645
nodes/843 edges for `jarvis-memory-live` and 23,175 nodes/29,210 edges for
`jarvis-homehub`. The graph is larger than the current KnowledgeItem/gBrain
projection; a graph hit therefore does not prove that a gBrain page exists.

## What is not complete

These are explicit blockers, not UI placeholders that can be marked passed:

1. HomeHub does not yet issue or verify a live `uyp-agent-identity-v1` signed
   card. `/api/studio/me`, `/internal/studio/card`, and `contacts.my_card()`
   still return the legacy unsigned display/number/urn/town card.
2. Miku is not yet a verified skill-card participant in a HomeHub-approved
   group/Town session. Its current auth is ADR-0028 HMAC delegation.
3. HomeHub has not issued a group device delegation containing explicit device
   and action scopes. UYP cannot execute a group live action or mint that grant.
4. NandaTown P7 (two independently authorized Jarvis nodes, attributed query,
   bounded device action, revocation denial, and audit chain) is not accepted.
5. UA graph coverage is broader than searchable KnowledgeItems; the gBrain
   mirror queue still needs durable drain/retry/invalidations.

The complete handoff, with the exact order of work and acceptance commands,
is [`HANDOFF_GROUP_DEVICE_ACTION_P7_20261015.md`](HANDOFF_GROUP_DEVICE_ACTION_P7_20261015.md).

## Canonical files for new work

- Product/flow target: [`TARGET_ARCHITECTURE_V2.md`](TARGET_ARCHITECTURE_V2.md)
- Execution gates and red lines: [`EXECUTION_PLAN_V2.md`](EXECUTION_PLAN_V2.md)
- Shared identity/message contract: [`AGENT_IDENTITY_MESSAGING_SKILL_V1.md`](AGENT_IDENTITY_MESSAGING_SKILL_V1.md)
- Group semantics: [`GROUPS_DESIGN.md`](GROUPS_DESIGN.md)
- Query API contract: [`QUERY_API.md`](QUERY_API.md)
- Device provider boundary: [`DEVICE_PROVIDER_CONTRACT_V1.md`](DEVICE_PROVIDER_CONTRACT_V1.md)
- Live handoff and P7 blockers: [`HANDOFF_GROUP_DEVICE_ACTION_P7_20261015.md`](HANDOFF_GROUP_DEVICE_ACTION_P7_20261015.md)
- Historical evidence (read as dated evidence, not current status):
  [`P7_ACCEPTANCE_2026-10-10.md`](P7_ACCEPTANCE_2026-10-10.md),
  [`GBRAIN_PROVISIONING_EVIDENCE_20261010.md`](GBRAIN_PROVISIONING_EVIDENCE_20261010.md),
  [`QA_AUDIT_2026-10-10.md`](QA_AUDIT_2026-10-10.md).

## Contributor rules

- Do not create a second identity, grant, device-action, or audit authority in
  UYP, Studio, Langflow, NandaTown, Miku, or a Connector.
- Do not call a legacy card “verified” and do not call a Town participant a
  HomeHub member without the HomeHub projection and audit reference.
- Do not change the existing voice/action route while implementing the group
  adapter. Group actions must eventually forward through that same governed
  HomeHub action route.
- Do not put tokens, delegation keys, source bytes, unrestricted paths, or
  AccessContext objects in GitHub, logs, envelopes, or screenshots.
- Treat SSH/DNS failures from a restricted development shell as a reachability
  limitation until a normal terminal probe confirms the Jetson state; never
  convert that failure into a claim that the Jetson service is deleted.
