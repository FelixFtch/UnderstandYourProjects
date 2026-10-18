// The Receipts page: renders /api/studio/receipts read-only — the
// accepted≠completed distinction stays visible, SIMULATED rows are badged,
// and nothing on the page ever issues a non-GET request.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ReceiptsPage from "./ReceiptsPage";

const RECEIPTS = {
  status: "ok", schema_version: "studio-receipts-v1", read_only: true,
  sources: [
    { id: "audit_ledger", available: true, persisted: true, label: "companion-api audit ledger (uyp_audit_events)" },
    { id: "device_action_feed", available: true, persisted: false, label: "governed action route (:8869) in-memory audit" },
  ],
  receipts: [
    {
      receipt_id: "home-device-action-f1", kind: "device_action", requested_at: new Date(Date.now() - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"),
      source: "studio", principal: "owner", auth_level: null, room: null, capability: "home.light.turn_on",
      risk: "low", status: "accepted", confirmation: "ack_only",
      ack: { received: true, connector: "homehub-governed-home-assistant" }, read_back: null,
      execution_mode: "live", real_device: null, error: null,
      audit_ref: "home-device-action-f1", request_id: "studio-home-device", remote_receipt_id: null,
      expires_at: null, detail: { event_type: "homehub.device.action" },
    },
    {
      receipt_id: "home-device-action-f2", kind: "device_action", requested_at: new Date(Date.now() - 120_000).toISOString().replace(/\.\d{3}Z$/, "Z"),
      source: "voice", principal: "owner", auth_level: null, room: null, capability: "test.door.lock",
      risk: "medium", status: "completed", confirmation: "simulated_read_back",
      ack: { received: true, connector: "homehub-governed-home-assistant" }, read_back: { state: "locked" },
      execution_mode: "simulated", real_device: false, error: null,
      audit_ref: "home-device-action-f2", request_id: "agent-turn-77", remote_receipt_id: null,
      expires_at: null, detail: { event_type: "homehub.device.action" },
    },
    {
      receipt_id: "uyp-audit-1", kind: "capability_lifecycle", requested_at: new Date(Date.now() - 3_600_000).toISOString().replace(/\.\d{3}Z$/, "Z"),
      source: "studio", principal: "dr_lee", auth_level: "owner", room: null,
      capability: "homehub.group_device_grant", risk: null, status: "cancelled", confirmation: "ledger_entry",
      ack: null, read_back: null, execution_mode: null, real_device: null, error: null,
      audit_ref: "uyp-audit-1", request_id: null, remote_receipt_id: null, expires_at: null,
      detail: { event_type: "homehub.group_device_grant.revoke", device_ids: ["dev-lamp"] },
    },
  ],
  count: 3, next_before: null, filters_applied: {},
};

type Handler = (url: string) => { status: number; body?: unknown };
let handler: Handler;
const calls: Array<{ url: string; method: string }> = [];

beforeEach(() => {
  calls.length = 0;
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET" });
    const r = handler(String(url));
    return new Response(JSON.stringify(r.body ?? {}), { status: r.status, headers: { "Content-Type": "application/json" } });
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderPage() {
  render(<ReceiptsPage param={undefined} navigate={vi.fn()} />);
}

describe("ReceiptsPage", () => {
  it("renders the merged timeline with sources and per-row fields", async () => {
    handler = () => ({ status: 200, body: RECEIPTS });
    renderPage();
    expect(await screen.findByText("home.light.turn_on")).toBeTruthy();
    expect(screen.getByText("test.door.lock")).toBeTruthy();
    expect(screen.getByText("homehub.group_device_grant")).toBeTruthy();
    expect(screen.getByText(/persisted audit ledger/)).toBeTruthy();
    expect(screen.getByText(/home-device-action-f1/)).toBeTruthy();
    expect(screen.getByText("dr_lee")).toBeTruthy();
  });

  it("keeps accepted visually neutral with the explanation, completed simulated off-green", async () => {
    handler = () => ({ status: 200, body: RECEIPTS });
    renderPage();
    // the legend teaches the rule permanently, not only on hover
    expect(await screen.findByText(/It is not done yet/)).toBeTruthy();
    expect(screen.getAllByText(/only.*completed.*confirmed outcome|completed.*confirmed outcome/i).length).toBeGreaterThan(0);
    const accepted = screen.getAllByText("accepted").at(-1)!;
    expect(accepted.className).not.toMatch(/ok-soft/); // never the green confirmation chip
    const simulatedBadge = screen.getAllByText("SIMULATED");
    expect(simulatedBadge.length).toBeGreaterThan(0);
    expect(simulatedBadge.some((el) => (el.parentElement?.className ?? "").includes("warn"))).toBe(true);
    // the simulated row's completed badge says so out loud
    expect(screen.getByText("completed (simulated)")).toBeTruthy();
  });

  it("opens the read-only detail for a row with the full field set", async () => {
    handler = () => ({ status: 200, body: RECEIPTS });
    renderPage();
    fireEvent.click(await screen.findByText("test.door.lock"));
    expect(await screen.findByText(/No physical device was touched/)).toBeTruthy();
    expect(screen.getAllByText(/studio-home-device|agent-turn-77/).length).toBeGreaterThan(0); // request id present for device rows
    expect(screen.getAllByText(/—/).length).toBeGreaterThan(0); // honest blanks (room, remote receipt)
    expect(screen.getByText("Audit detail")).toBeTruthy();
  });

  it("is strictly read-only: every request is a GET and no action buttons exist", async () => {
    handler = () => ({ status: 200, body: RECEIPTS });
    renderPage();
    await screen.findByText("home.light.turn_on");
    expect(calls.length).toBeGreaterThan(0);
    expect(calls.every((c) => c.method === "GET")).toBe(true);
    // selecting rows and filtering never turns into a write
    fireEvent.click(screen.getByText("home.light.turn_on"));
    fireEvent.click(screen.getByRole("tab", { name: "Voice" }));
    await waitFor(() => expect(calls.filter((c) => c.url.includes("source=voice")).length).toBe(1));
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("filters server-side by source and shows the empty state honestly", async () => {
    handler = (url) => {
      if (url.includes("source=town")) {
        return { status: 200, body: { ...RECEIPTS, receipts: [], count: 0, next_before: null } };
      }
      return { status: 200, body: RECEIPTS };
    };
    renderPage();
    await screen.findByText("home.light.turn_on");
    fireEvent.click(screen.getByRole("tab", { name: "Town" }));
    expect(await screen.findByText("No receipts match")).toBeTruthy();
    expect(screen.getByText(/hidden by default/)).toBeTruthy();
  });

  it("pages back in time with the cursor when the hub has more", async () => {
    let paged = false;
    handler = (url) => {
      if (url.includes("before=")) {
        paged = true;
        return { status: 200, body: { ...RECEIPTS, receipts: [RECEIPTS.receipts[2]], count: 1, next_before: null } };
      }
      return { status: 200, body: { ...RECEIPTS, next_before: "2026-10-18T09:30:00Z" } };
    };
    renderPage();
    fireEvent.click(await screen.findByText("Load older"));
    await waitFor(() => expect(paged).toBe(true));
    await waitFor(() => expect(screen.getAllByText("uyp-audit-1").length).toBe(2)); // kept + older page
  });

  it("keeps the page usable when the volatile feed is down", async () => {
    handler = () => ({
      status: 200,
      body: { ...RECEIPTS, sources: [
        RECEIPTS.sources[0],
        { id: "device_action_feed", available: false, persisted: false, label: "governed action route (:8869) unreachable" },
      ], receipts: RECEIPTS.receipts.slice(2) },
    });
    renderPage();
    expect(await screen.findByText(/Live device-action feed unavailable/)).toBeTruthy();
    expect(await screen.findByText("homehub.group_device_grant")).toBeTruthy();
  });

  it("shows the hub error without inventing data", async () => {
    handler = () => ({ status: 403, body: { detail: "owner_session_required" } });
    renderPage();
    expect(await screen.findByText(/Couldn't load receipts|Not allowed/)).toBeTruthy();
    expect(screen.queryByText("home.light.turn_on")).toBeNull();
  });
});
