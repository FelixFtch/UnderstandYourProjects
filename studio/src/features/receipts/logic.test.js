// Receipt logic: the accepted≠completed rule, simulated marking, state machine.
import { describe, expect, it } from "vitest";
import { PATH_ORDER, STATE_MACHINE, evidenceLabel, isSimulated, sourceMeta, sourceScopeNote, statusMeta } from "./logic";
const simulated = (over = {}) => ({
    receipt_id: "r", kind: "device_action", requested_at: "2026-10-18T12:00:00Z", source: "voice",
    principal: "owner", auth_level: null, room: null, capability: "test.door.lock", risk: "medium",
    status: "completed", confirmation: "simulated_read_back", ack: { received: true, connector: "c" },
    read_back: { state: "locked" }, execution_mode: "simulated", real_device: false, error: null,
    audit_ref: "a", request_id: null, remote_receipt_id: null, expires_at: null, detail: {},
    ...over,
});
describe("statusMeta: accepted is never a confirmation", () => {
    it("keeps accepted neutral and completed green", () => {
        expect(statusMeta("accepted").tone).toBe("neutral");
        expect(statusMeta("accepted").note).toMatch(/not.*done yet/i);
        expect(statusMeta("completed").tone).toBe("ok");
    });
    it("flips a completed SIMULATED receipt off the green confirmation", () => {
        const sim = simulated();
        expect(statusMeta("completed", sim).tone).toBe("warn");
        expect(statusMeta("completed", sim).label).toContain("simulated");
        expect(statusMeta("completed", simulated({ execution_mode: "live", real_device: true })).tone).toBe("ok");
    });
    it("maps the rest of the vocabulary deterministically", () => {
        expect(statusMeta("denied").tone).toBe("err");
        expect(statusMeta("failed").tone).toBe("err");
        expect(statusMeta("awaiting_confirmation").tone).toBe("warn");
        expect(statusMeta("queued").tone).toBe("info");
        expect(statusMeta("cancelled").tone).toBe("neutral");
        expect(statusMeta("dry_run").note).toMatch(/nothing executed/i);
        expect(statusMeta("something-new").label).toBe("something-new"); // verbatim, never guessed
    });
});
describe("isSimulated", () => {
    it("detects either marker", () => {
        expect(isSimulated({ execution_mode: "simulated", real_device: null })).toBe(true);
        expect(isSimulated({ execution_mode: "live", real_device: false })).toBe(true);
        expect(isSimulated({ execution_mode: "live", real_device: true })).toBe(false);
        expect(isSimulated({ execution_mode: null, real_device: null })).toBe(false);
    });
});
describe("state machine", () => {
    it("lists every stop exactly once, path before terminals", () => {
        const ids = STATE_MACHINE.map((s) => s.id);
        expect(new Set(ids).size).toBe(ids.length);
        const terminals = ids.filter((id) => STATE_MACHINE.find((s) => s.id === id)?.terminal);
        expect(ids.indexOf("accepted")).toBeLessThan(ids.indexOf("completed"));
        expect(terminals).toEqual(["denied", "failed", "queued", "expired", "cancelled"]);
        expect(PATH_ORDER[PATH_ORDER.length - 1]).toBe("completed");
        expect(PATH_ORDER).not.toContain("denied");
    });
});
describe("presentation helpers", () => {
    it("labels ack and read-back evidence", () => {
        expect(evidenceLabel(simulated())).toBe("ack ✓ · read-back ✓");
        expect(evidenceLabel(simulated({ ack: { received: false }, read_back: null, status: "accepted" }))).toBe("ack ✗ · read-back —");
        expect(evidenceLabel(simulated({ ack: null, read_back: null }))).toBe("ack — · read-back —");
    });
    it("scopes source labels and notes", () => {
        expect(sourceMeta("voice").label).toBe("voice");
        expect(sourceMeta("weird").label).toBe("weird");
        expect(sourceScopeNote([
            { id: "audit_ledger", available: true, persisted: true, label: "l" },
            { id: "device_action_feed", available: false, persisted: false, label: "f" },
        ])).toContain("persisted audit ledger");
        expect(sourceScopeNote([
            { id: "audit_ledger", available: false, persisted: true, label: "l" },
            { id: "device_action_feed", available: false, persisted: false, label: "f" },
        ])).toContain("No receipt source");
    });
});
