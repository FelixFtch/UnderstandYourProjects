// Notification bell (2026-10-15): bell rendering + unread badge, dropdown list with
// relative time and kind chips, mark-all-read / mark-one-read POSTs, empty state.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { NotificationList } from "../api/contracts";
import { NotificationBell } from "./NotificationBell";

const NOTES: NotificationList = {
  items: [
    { id: 2, ts: new Date(Date.now() - 30 * 60_000).toISOString(), kind: "settings", title: "Model mode switched to cloud", body: "qwen3.8-flash now serves route and persona.", read: 0 },
    { id: 1, ts: new Date(Date.now() - 25 * 3600_000).toISOString(), kind: "system", title: "Agent box enrolled", body: "box_q8Zt1fKx enrolled with HomeHub.", read: 1 },
  ],
  unread: 1,
};

type Handler = (url: string, init: RequestInit) => { status: number; body?: unknown } | undefined;
let handler: Handler;
const calls: Array<{ url: string; method: string; body?: unknown }> = [];

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, method: init.method ?? "GET", body: init.body ? JSON.parse(String(init.body)) : undefined });
    const r = handler(url, init);
    const status = r?.status ?? 404;
    const body = r?.body ?? { detail: "not in this test" };
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("NotificationBell", () => {
  it("polls the notifications endpoint and shows the unread count on the bell", async () => {
    handler = (url) => (url === "/api/studio/notifications?limit=20" ? { status: 200, body: NOTES } : undefined);
    render(<NotificationBell />);

    const bell = await screen.findByRole("button", { name: "Notifications, 1 unread" });
    expect(bell.textContent).toContain("1");
    expect(calls).toEqual([{ url: "/api/studio/notifications?limit=20", method: "GET", body: undefined }]);
  });

  it("opens a dropdown with relative time, kind chips and titles; read rows are inert", async () => {
    handler = (url) => (url === "/api/studio/notifications?limit=20" ? { status: 200, body: NOTES } : undefined);
    render(<NotificationBell />);

    fireEvent.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));

    const panel = await screen.findByRole("dialog", { name: "Notifications" });
    expect(panel.textContent).toContain("1 unread");
    expect(screen.getByText("Model mode switched to cloud")).toBeTruthy();
    expect(screen.getByText("qwen3.8-flash now serves route and persona.")).toBeTruthy();
    expect(screen.getByText("30 min ago")).toBeTruthy(); // relative time
    expect(screen.getByText("settings")).toBeTruthy(); // kind chip
    expect(screen.getByText("system")).toBeTruthy();
    // exactly one unread row offers click-to-mark-read
    expect(screen.getAllByTitle("Mark read")).toHaveLength(1);
  });

  it("marks all read: POSTs {all:true} and clears the badge", async () => {
    handler = (url, init) => {
      if (url === "/api/studio/notifications/mark-read" && init.method === "POST") return { status: 200, body: { ok: true } };
      if (url === "/api/studio/notifications?limit=20") return { status: 200, body: NOTES };
      return undefined;
    };
    render(<NotificationBell />);

    fireEvent.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));
    fireEvent.click(await screen.findByRole("button", { name: "Mark all read" }));

    await waitFor(() => expect(calls.some((c) => c.url === "/api/studio/notifications/mark-read" && c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ all: true });
    // badge cleared and the panel header flips to "All read"
    expect(await screen.findByRole("button", { name: "Notifications" })).toBeTruthy();
    expect(await screen.findByText("All read")).toBeTruthy();
    expect(screen.queryByTitle("Mark read")).toBeNull(); // no unread rows left
  });

  it("marks a single notification read from its row with {ids:[…]}", async () => {
    handler = (url, init) => {
      if (url === "/api/studio/notifications/mark-read" && init.method === "POST") return { status: 200, body: { ok: true } };
      if (url === "/api/studio/notifications?limit=20") return { status: 200, body: NOTES };
      return undefined;
    };
    render(<NotificationBell />);

    fireEvent.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));
    fireEvent.click(await screen.findByTitle("Mark read"));

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ ids: [2] });
    expect(await screen.findByRole("button", { name: "Notifications" })).toBeTruthy(); // badge gone
  });

  it("shows a friendly empty state when there is nothing to report", async () => {
    handler = (url) => (url === "/api/studio/notifications?limit=20" ? { status: 200, body: { items: [], unread: 0 } } : undefined);
    render(<NotificationBell />);

    fireEvent.click(await screen.findByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("All caught up")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Mark all read" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("surfaces a load error inside the panel and recovers via Retry", async () => {
    let down = true;
    handler = (url) => {
      if (url === "/api/studio/notifications?limit=20") return down ? { status: 503, body: { detail: "hub starting" } } : { status: 200, body: NOTES };
      return undefined;
    };
    render(<NotificationBell />);

    fireEvent.click(await screen.findByRole("button", { name: "Notifications" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("hub starting")).toBeTruthy();

    down = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Model mode switched to cloud")).toBeTruthy();
  });
});
