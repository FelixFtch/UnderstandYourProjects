const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const ROWS = [
    {
        receipt_id: "home-device-action-f10a", kind: "device_action", requested_at: "2026-10-18T12:00:02Z",
        source: "studio", principal: "owner", auth_level: null, room: null, capability: "home.light.turn_on",
        risk: "low", status: "accepted", confirmation: "ack_only",
        ack: { received: true, connector: "homehub-governed-home-assistant" }, read_back: null,
        execution_mode: "live", real_device: null, error: null,
        audit_ref: "home-device-action-f10a", request_id: "studio-home-device", remote_receipt_id: null,
        expires_at: null, detail: { event_type: "homehub.device.action", entity_domain: "switch", source_audit_id: "f10a" },
    },
    {
        receipt_id: "home-device-action-f09b", kind: "device_action", requested_at: "2026-10-18T12:00:01Z",
        source: "voice", principal: "owner", auth_level: null, room: null, capability: "test.door.lock",
        risk: "medium", status: "completed", confirmation: "simulated_read_back",
        ack: { received: true, connector: "homehub-governed-home-assistant" },
        read_back: { state: "locked", mode: "fake_execute" },
        execution_mode: "simulated", real_device: false, error: null,
        audit_ref: "home-device-action-f09b", request_id: "agent-turn-77", remote_receipt_id: null,
        expires_at: null, detail: { event_type: "homehub.device.action", entity_domain: "lock", source_audit_id: "f09b" },
    },
    {
        receipt_id: "home-device-action-f08c", kind: "device_action", requested_at: "2026-10-18T12:00:00Z",
        source: "voice", principal: "guest", auth_level: null, room: null, capability: "home.light.turn_off",
        risk: "low", status: "denied", confirmation: null,
        ack: { received: false, connector: "homehub-governed-home-assistant" }, read_back: null,
        execution_mode: "dry_run", real_device: null, error: "policy_denied",
        audit_ref: "home-device-action-f08c", request_id: "agent-turn-78", remote_receipt_id: null,
        expires_at: null, detail: { event_type: "homehub.device.action", entity_domain: "switch", source_audit_id: "f08c" },
    },
    {
        receipt_id: "uyp-audit-c", kind: "capability_lifecycle", requested_at: "2026-10-18T09:30:00Z",
        source: "studio", principal: "dr_lee", auth_level: "owner", room: null,
        capability: "homehub.group_device_grant", risk: null, status: "cancelled", confirmation: "ledger_entry",
        ack: null, read_back: null, execution_mode: null, real_device: null, error: null,
        audit_ref: "uyp-audit-c", request_id: null, remote_receipt_id: null, expires_at: null,
        detail: { event_type: "homehub.group_device_grant.revoke", epoch: 7, grant_id: "gdg-1", group_id: "grp-9", device_ids: ["dev-lamp"], action_ids: ["home.light.turn_on"] },
    },
    {
        receipt_id: "uyp-audit-b", kind: "capability_lifecycle", requested_at: "2026-10-18T09:05:00Z",
        source: "studio", principal: "dr_lee", auth_level: "member", room: null,
        capability: "homehub.group_device_context", risk: null, status: "completed", confirmation: "ledger_entry",
        ack: null, read_back: null, execution_mode: null, real_device: null, error: null,
        audit_ref: "uyp-audit-b", request_id: null, remote_receipt_id: null, expires_at: null,
        detail: { event_type: "homehub.group_device_context.verify", epoch: 7, grant_id: "gdg-1" },
    },
    {
        receipt_id: "uyp-audit-e", kind: "capability_lifecycle", requested_at: "2026-10-17T07:00:00Z",
        source: "town", principal: "robin", auth_level: "owner", room: null,
        capability: "homehub.group_message", risk: null, status: "completed", confirmation: "ledger_entry",
        ack: null, read_back: null, execution_mode: null, real_device: null, error: null,
        audit_ref: "uyp-audit-e", request_id: null, remote_receipt_id: null, expires_at: null,
        detail: { event_type: "homehub.group_message.send", epoch: 7 },
    },
    // policy-read audit: only listed when include_context_reads is on
    {
        receipt_id: "uyp-audit-f", kind: "capability_lifecycle", requested_at: "2026-10-18T10:59:00Z",
        source: "studio", principal: "robin", auth_level: "owner", room: null,
        capability: "uyp.access_context", risk: null, status: "completed", confirmation: "ledger_entry",
        ack: null, read_back: null, execution_mode: null, real_device: null, error: null,
        audit_ref: "uyp-audit-f", request_id: null, remote_receipt_id: null, expires_at: null,
        detail: { event_type: "uyp.access_context.issue", epoch: 7 },
    },
];
function list(opts) {
    let rows = ROWS.filter((r) => (opts.include_context_reads ? true : r.capability !== "uyp.access_context"));
    if (opts.before)
        rows = rows.filter((r) => r.requested_at < opts.before);
    if (opts.principal)
        rows = rows.filter((r) => r.principal.toLowerCase().includes(opts.principal.toLowerCase()));
    if (opts.capability)
        rows = rows.filter((r) => r.capability.toLowerCase().includes(opts.capability.toLowerCase()));
    if (opts.status)
        rows = rows.filter((r) => r.status === opts.status);
    if (opts.source)
        rows = rows.filter((r) => r.source === opts.source);
    rows = [...rows].sort((a, b) => (a.requested_at < b.requested_at ? 1 : -1));
    const limit = opts.limit ?? 50;
    const page = rows.slice(0, limit);
    return {
        status: "ok",
        schema_version: "studio-receipts-v1",
        read_only: true,
        sources: [
            { id: "audit_ledger", available: true, persisted: true, label: "companion-api audit ledger (uyp_audit_events)" },
            { id: "device_action_feed", available: true, persisted: false, label: "governed action route (:8869) in-memory audit" },
        ],
        receipts: page,
        count: page.length,
        next_before: rows.length > limit ? page[page.length - 1].requested_at : null,
        filters_applied: { ...opts },
    };
}
export async function receiptsList(opts = {}) {
    await wait(280);
    return list(opts);
}
