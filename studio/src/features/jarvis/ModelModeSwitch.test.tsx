// Jarvis header model-mode switch (2026-10-14): badge rendering, confirm dialog with the
// privacy-floor copy, PUT + pushed feedback, read-only for non-owners, load-error retry.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Me } from "../../api/contracts";
import { useSession } from "../../app/session";
import { ModelModeSwitch } from "./ModelModeSwitch";

const ME_OWNER: Me = {
  member_id: "robin", role: "owner", display_name: "Robin", household_id: "household",
  jarvis: { node_id: "hub_1", display_name: "Robin's Jarvis", number: "J-4829-1300", urn: null, town: null },
  agent_box: { enrolled: true, box_id: "box_1" },
};
const ME_MEMBER: Me = { ...ME_OWNER, role: "member" };

const MODE_LOCAL = {
  mode: "local",
  cloud_model_route: "qwen3.8-flash",
  cloud_model_persona: "qwen3.8-flash",
  updated_at: "2026-10-13T08:00:00Z",
};

type Handler = (url: string, init: RequestInit) => { status: number; body?: unknown } | undefined;
let handler: Handler;
const calls: Array<{ url: string; method: string; body?: unknown }> = [];

beforeEach(() => {
  calls.length = 0;
  useSession.setState({ me: ME_OWNER });
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
  useSession.setState({ me: null });
});

describe("ModelModeSwitch (Jarvis header)", () => {
  it("shows the current mode as a labelled badge", async () => {
    handler = (url) => (url === "/api/settings/model-mode" ? { status: 200, body: MODE_LOCAL } : undefined);
    render(<ModelModeSwitch />);

    const badge = await screen.findByRole("button", { name: /Model mode: local/ });
    expect(badge.textContent).toContain("Local");
    expect(calls).toEqual([{ url: "/api/settings/model-mode", method: "GET", body: undefined }]);
  });

  it("asks for confirmation (with the privacy floor note), PUTs, and updates the badge", async () => {
    handler = (url, init) => {
      if (url === "/api/settings/model-mode" && init.method === "PUT") {
        return { status: 200, body: { ...MODE_LOCAL, mode: "cloud", updated_at: "2026-10-14T02:00:00Z", pushed: true } };
      }
      if (url === "/api/settings/model-mode") return { status: 200, body: MODE_LOCAL };
      return undefined;
    };
    render(<ModelModeSwitch />);

    fireEvent.click(await screen.findByRole("button", { name: /Model mode: local/ }));

    // the dialog carries the model names and the mandatory privacy copy
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(screen.getByText(/privacy floor/)).toBeTruthy();
    expect(screen.getByText(/raw voice audio is never uploaded/)).toBeTruthy();
    expect(screen.getAllByText("qwen3.8-flash")).toHaveLength(2);
    expect(screen.getByText(/Data → Model/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Switch to cloud" }));

    expect(await screen.findByText(/pushed to the voice runtime, effective immediately/)).toBeTruthy();
    const put = calls.find((c) => c.method === "PUT");
    expect(put).toMatchObject({ url: "/api/settings/model-mode", body: { mode: "cloud" } });
    // badge flipped immediately, even before dismissing the dialog
    expect(screen.getByRole("button", { name: /Model mode: cloud/ }).textContent).toContain("Cloud");

    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the pushed=false semantics: saved, applies on the next turn", async () => {
    handler = (url, init) => {
      if (url === "/api/settings/model-mode" && init.method === "PUT") return { status: 200, body: { ...MODE_LOCAL, mode: "cloud", pushed: false } };
      if (url === "/api/settings/model-mode") return { status: 200, body: { ...MODE_LOCAL, mode: "cloud" } };
      return undefined;
    };
    render(<ModelModeSwitch />);

    fireEvent.click(await screen.findByRole("button", { name: /Model mode: cloud/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Switch to local" }));

    expect(await screen.findByText(/picks it up on its next turn/)).toBeTruthy();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ mode: "local" });
  });

  it("is read-only for non-owners: badge disabled, no dialog, no PUT", async () => {
    useSession.setState({ me: ME_MEMBER });
    handler = (url) => (url === "/api/settings/model-mode" ? { status: 200, body: { ...MODE_LOCAL, mode: "cloud" } } : undefined);
    render(<ModelModeSwitch />);

    const badge = (await screen.findByText("Cloud")).closest("button") as HTMLButtonElement;
    expect(badge.disabled).toBe(true);
    expect(badge.title).toMatch(/Only the household owner/);
    fireEvent.click(badge);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("shows an inline error in the dialog when the PUT is rejected", async () => {
    handler = (url, init) => {
      if (url === "/api/settings/model-mode" && init.method === "PUT") return { status: 403, body: { detail: "owner only" } };
      if (url === "/api/settings/model-mode") return { status: 200, body: MODE_LOCAL };
      return undefined;
    };
    render(<ModelModeSwitch />);

    fireEvent.click(await screen.findByRole("button", { name: /Model mode: local/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Switch to cloud" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("Only the household owner can switch the model mode.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Model mode: local/ })).toBeTruthy(); // badge unchanged
  });

  it("offers a retry chip when the mode cannot be loaded", async () => {
    let down = true;
    handler = (url) => {
      if (url === "/api/settings/model-mode") return down ? { status: 503, body: { detail: "runtime unreachable" } } : { status: 200, body: MODE_LOCAL };
      return undefined;
    };
    render(<ModelModeSwitch />);

    const retry = await screen.findByRole("button", { name: /Model mode\?/ });
    down = false;
    fireEvent.click(retry);
    expect(await screen.findByRole("button", { name: /Model mode: local/ })).toBeTruthy();
  });
});
