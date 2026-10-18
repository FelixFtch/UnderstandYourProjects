const ACCEPTED_NOTE = "Accepted means the connector took the instruction - it is NOT done yet. " +
    "Only completed is a confirmed outcome.";
/** True when this receipt records a simulated execution, never a real device. */
export function isSimulated(r) {
    return r.execution_mode === "simulated" || r.real_device === false;
}
export function statusMeta(status, r) {
    const simulated = r !== undefined && isSimulated(r);
    switch (status) {
        case "completed":
            return simulated
                ? { tone: "warn", label: "completed (simulated)", note: "The execution ran against a simulated capability. No real device was touched." }
                : { tone: "ok", label: "completed", note: "Confirmed outcome with read-back evidence." };
        case "accepted":
            return { tone: "neutral", label: "accepted", note: ACCEPTED_NOTE };
        case "dispatched":
            return { tone: "neutral", label: "dispatched", note: "Released by policy to the connector; no completion evidence yet." };
        case "received":
            return { tone: "info", label: "received", note: "Request arrived; not yet scheduled." };
        case "awaiting_slot":
            return { tone: "warn", label: "awaiting slot", note: "Queued behind an occupied execution slot." };
        case "awaiting_confirmation":
            return { tone: "warn", label: "awaiting confirmation", note: "Held for an explicit confirmation before executing." };
        case "denied":
            return { tone: "err", label: "denied", note: "Refused by policy. Nothing was dispatched." };
        case "failed":
            return { tone: "err", label: "failed", note: "The connector or device reported failure." };
        case "queued":
            return { tone: "info", label: "queued", note: "Accepted by the connector as an async task; not started." };
        case "running":
            return { tone: "info", label: "running", note: "Async task in progress." };
        case "expired":
            return { tone: "neutral", label: "expired", note: "Window closed before the request completed." };
        case "cancelled":
            return { tone: "neutral", label: "cancelled", note: "Withdrawn or revoked before completion." };
        case "dry_run":
            return { tone: "neutral", label: "dry run", note: "Planned only - nothing executed." };
        default:
            return { tone: "neutral", label: status || "unknown", note: "Status not recognized by this view; shown verbatim." };
    }
}
export const STATE_MACHINE = [
    { id: "received", label: "received" },
    { id: "awaiting_slot", label: "awaiting slot" },
    { id: "awaiting_confirmation", label: "awaiting confirmation" },
    { id: "dispatched", label: "dispatched" },
    { id: "accepted", label: "accepted" },
    { id: "completed", label: "completed" },
    { id: "denied", label: "denied", terminal: true },
    { id: "failed", label: "failed", terminal: true },
    { id: "queued", label: "queued", terminal: true },
    { id: "expired", label: "expired", terminal: true },
    { id: "cancelled", label: "cancelled", terminal: true },
];
/** The happy-path order used to light the mini timeline in the detail panel. */
export const PATH_ORDER = ["received", "awaiting_slot", "awaiting_confirmation", "dispatched", "accepted", "completed"];
export function sourceMeta(source) {
    switch (source) {
        case "studio": return { label: "studio", tone: "accent" };
        case "voice": return { label: "voice", tone: "understand" };
        case "town": return { label: "town", tone: "retrieve" };
        default: return { label: source || "unknown", tone: "neutral" };
    }
}
export function kindLabel(kind) {
    switch (kind) {
        case "device_action": return "device action";
        case "capability_lifecycle": return "capability lifecycle";
        default: return kind;
    }
}
/** Ack / read-back mini-indicator text for list rows. */
export function evidenceLabel(r) {
    const ack = r.ack ? (r.ack.received ? "ack ✓" : "ack ✗") : "ack —";
    const back = r.read_back && Object.keys(r.read_back).length > 0 ? "read-back ✓" : "read-back —";
    return `${ack} · ${back}`;
}
export function sourceScopeNote(sources) {
    const ledger = sources.find((s) => s.id === "audit_ledger");
    const feed = sources.find((s) => s.id === "device_action_feed");
    const parts = [];
    if (ledger?.available)
        parts.push("persisted audit ledger (issue / verify / revoke)");
    if (feed?.available)
        parts.push("live device-action feed since the action route last restarted (volatile)");
    if (!parts.length)
        return "No receipt source is currently available.";
    return `Sources: ${parts.join(" + ")}.`;
}
