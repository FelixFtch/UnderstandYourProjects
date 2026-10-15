// UA analysis mode card (2026-10-15): local/cloud rendering, cloud save PUT body
// with provider+model, `written` feedback (both ways), local PUT omits the pair,
// read-only for non-owners.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Me, UaModeSettings } from "../../api/contracts";
import { UaModeCard } from "./UaModeCard";

const ME_OWNER: Me = {
  member_id: "robin", role: "owner", display_name: "Robin", household_id: "household",
  jarvis: { node_id: "hub_1", display_name: "Robin's Jarvis", number: "J-4829-1300", urn: null, town: null },
  agent_box: { enrolled: true, box_id: "box_1" },
};
const ME_MEMBER: Me = { ...ME_OWNER, role: "member" };

const UA_LOCAL: UaModeSettings = { mode: "local", provider: "qwen", model: "qwen3.8-flash" };
const UA_CLOUD: UaModeSettings = { mode: "cloud", provider: "claude", model: "claude-sonnet-4-6" };

type Handler = (url: string, init: RequestInit) => { status: number; body?: unknown } | undefined;
let handler: Handler;
const calls: Array<{ url: string; method: string; body?: unknown }> = [];

const GET_URL = "/api/settings/ua-mode";

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

describe("UaModeCard (Data → Model)", () => {
  it("renders the local default with the badge, segmented switch and the Laya note", async () => {
    handler = (url) => (url === GET_URL ? { status: 200, body: UA_LOCAL } : undefined);
    render(<UaModeCard me={ME_OWNER} readOnly={false} />);

    expect(await screen.findByRole("heading", { name: /UA analysis mode/ })).toBeTruthy();
    // the badge sits inside the heading (the radio carries the same label)
    expect(screen.getByRole("heading", { name: /UA analysis mode/ }).textContent).toContain("Local analysis");
    expect(calls).toEqual([{ url: GET_URL, method: "GET", body: undefined }]);

    const local = screen.getByRole("radio", { name: "Local analysis" });
    expect(local.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: "Cloud analysis" }).getAttribute("aria-checked")).toBe("false");
    expect(screen.queryByLabelText("Provider")).toBeNull(); // cloud-only form
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true); // nothing dirty
    expect(screen.getByText(/Laya pre-filtering always stays local/)).toBeTruthy();
  });

  it("saves cloud mode with PUT {mode, provider, model} and confirms the config write", async () => {
    handler = (url, init) => {
      if (url === GET_URL && init.method === "PUT") {
        const body = JSON.parse(String(init.body));
        return { status: 200, body: { mode: body.mode, provider: body.provider, model: body.model, written: true } };
      }
      if (url === GET_URL) return { status: 200, body: UA_LOCAL };
      return undefined;
    };
    render(<UaModeCard me={ME_OWNER} readOnly={false} />);

    fireEvent.click(await screen.findByRole("radio", { name: "Cloud analysis" }));

    // the provider dropdown lists all seven vendors
    const provider = screen.getByLabelText("Provider") as HTMLSelectElement;
    expect(provider.querySelectorAll("option")).toHaveLength(7);
    for (const label of ["Qwen · Alibaba Bailian", "OpenAI", "Claude · Anthropic", "Gemini · Google", "DeepSeek", "Grok · xAI", "Muse · Meta"]) {
      expect(withinSelect(provider, label)).toBe(true);
    }
    fireEvent.change(provider, { target: { value: "claude" } });
    const model = screen.getByLabelText("Model") as HTMLInputElement;
    fireEvent.change(model, { target: { value: "claude-sonnet-4-6" } });

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ mode: "cloud", provider: "claude", model: "claude-sonnet-4-6" });
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.getByText(/cloud analysis via claude \(claude-sonnet-4-6\)/)).toBeTruthy();
    expect(screen.getByText(/written to the indexer config/)).toBeTruthy();
    // badge flips to cloud
    expect(screen.getByRole("heading", { name: /UA analysis mode/ }).textContent).toContain("Cloud analysis");
  });

  it("warns when the hub saved but could not write the indexer config", async () => {
    handler = (url, init) => {
      if (url === GET_URL && init.method === "PUT") {
        return { status: 200, body: { mode: "cloud", provider: "qwen", model: "qwen3.8-flash", written: false } };
      }
      if (url === GET_URL) return { status: 200, body: UA_LOCAL };
      return undefined;
    };
    render(<UaModeCard me={ME_OWNER} readOnly={false} />);

    fireEvent.click(await screen.findByRole("radio", { name: "Cloud analysis" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" })); // provider/model unchanged, still valid

    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.getByText(/indexer config was not written/)).toBeTruthy();
  });

  it("switches back to local with PUT {mode:'local'} only", async () => {
    handler = (url, init) => {
      if (url === GET_URL && init.method === "PUT") return { status: 200, body: { ...UA_LOCAL, written: true } };
      if (url === GET_URL) return { status: 200, body: UA_CLOUD };
      return undefined;
    };
    render(<UaModeCard me={ME_OWNER} readOnly={false} />);

    expect((await screen.findByRole("radio", { name: "Cloud analysis" })).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("radio", { name: "Local analysis" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const body = calls.find((c) => c.method === "PUT")?.body;
    expect(body).toEqual({ mode: "local" });
    expect(body).not.toHaveProperty("provider");
    expect(await screen.findByText(/local analysis; written to the indexer config/)).toBeTruthy();
  });

  it("is read-only for members: radios and inputs disabled, no PUT", async () => {
    handler = (url) => (url === GET_URL ? { status: 200, body: UA_CLOUD } : undefined);
    render(<UaModeCard me={ME_MEMBER} readOnly />);

    expect((await screen.findByRole("radio", { name: "Local analysis" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("radio", { name: "Cloud analysis" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("Provider") as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByLabelText("Model") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Only the household owner can change the analysis mode/)).toBeTruthy();
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });
});

/** Does the select carry an option with this label? */
function withinSelect(select: HTMLSelectElement, label: string): boolean {
  return Array.from(select.options).some((o) => o.text === label);
}
