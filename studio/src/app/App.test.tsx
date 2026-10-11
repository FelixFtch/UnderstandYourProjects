// Auth lifecycle against a fake companion-api: 401 → login, pair → shell, enroll, hub down.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ME = {
  member_id: "robin", role: "owner", display_name: "Robin", household_id: "household",
  jarvis: { node_id: "hub_1", display_name: "Robin's Jarvis", number: "J-4829-1300", urn: null, town: null },
  agent_box: { enrolled: false, box_id: null },
};

type Handler = (url: string, init: RequestInit) => { status: number; body?: unknown };
let handler: Handler;
const calls: Array<{ url: string; method: string; auth?: string; body?: unknown }> = [];

function json(status: number, body?: unknown) {
  return new Response(body === undefined ? "" : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  vi.resetModules();
  calls.length = 0;
  window.localStorage.clear();
  window.location.hash = "";
  window.matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }) as unknown as typeof window.matchMedia;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const headers = (init.headers ?? {}) as Record<string, string>;
    calls.push({ url, method: init.method ?? "GET", auth: headers.Authorization, body: init.body ? JSON.parse(String(init.body)) : undefined });
    const r = handler(url, init);
    return json(r.status, r.body);
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function renderApp() {
  const { default: App } = await import("./App");
  render(<App />);
}

describe("App auth", () => {
  it("drops to the login screen with an explanation when the hub answers 401", async () => {
    window.localStorage.setItem("jarvis.studio.token", "cat_stale");
    handler = () => ({ status: 401, body: { detail: "Invalid token" } });
    await renderApp();
    expect(await screen.findByText("Sign in to Jarvis Studio")).toBeTruthy();
    expect(screen.getByText(/Your session ended/)).toBeTruthy();
    expect(window.localStorage.getItem("jarvis.studio.token")).toBeNull();
    expect(calls[0]).toMatchObject({ url: "/api/studio/me", auth: "Bearer cat_stale" });
  });

  it("pairs with an invite code, loads /me and can enroll the agent box", async () => {
    let enrolled = false;
    handler = (url, init) => {
      if (url === "/api/pair") return { status: 200, body: { token: "cat_new", member_id: "robin", role: "owner", display_name: "Robin" } };
      if (url === "/api/studio/me") return { status: 200, body: { ...ME, agent_box: enrolled ? { enrolled: true, box_id: "box_1" } : ME.agent_box } };
      if (url === "/api/studio/agent-box/enroll" && init.method === "POST") { enrolled = true; return { status: 200, body: { enrolled: true, box_id: "box_1" } }; }
      if (url.startsWith("/api/studio/threads/jarvis/messages")) return { status: 200, body: { messages: [], has_more: false } };
      return { status: 404, body: { detail: "not in this test" } };
    };
    await renderApp();
    const input = await screen.findByLabelText("Invite code");
    fireEvent.change(input, { target: { value: "ab12 cd34" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Pair this browser/ })); });

    await waitFor(() => expect(screen.getAllByText("J-4829-1300").length).toBeGreaterThan(0));
    expect(calls.find((c) => c.url === "/api/pair")?.body).toMatchObject({ code: "AB12CD34", device_name: "Jarvis Studio" });
    expect(window.localStorage.getItem("jarvis.studio.token")).toBe("cat_new");
    expect(calls.find((c) => c.url === "/api/studio/me")?.auth).toBe("Bearer cat_new");

    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Enroll" })[0]); });
    await waitFor(() => expect(screen.getByText("Agent box enrolled")).toBeTruthy());
  });

  it("shows the pairing error from the hub", async () => {
    handler = () => ({ status: 400, body: { detail: "Unknown or already-used pairing code" } });
    await renderApp();
    fireEvent.change(await screen.findByLabelText("Invite code"), { target: { value: "DEADBEEF" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Pair this browser/ })); });
    expect(await screen.findByText("Unknown or already-used pairing code")).toBeTruthy();
  });

  it("keeps the token and offers Retry when the hub is down", async () => {
    window.localStorage.setItem("jarvis.studio.token", "cat_ok");
    handler = () => ({ status: 503, body: { detail: "companion-api starting" } });
    await renderApp();
    expect(await screen.findByText("companion-api unreachable")).toBeTruthy();
    expect(window.localStorage.getItem("jarvis.studio.token")).toBe("cat_ok");
    expect(screen.getByRole("button", { name: /Try again/ })).toBeTruthy();
  });
});
