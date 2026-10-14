import { jsx as _jsx } from "react/jsx-runtime";
// Model tab (2026-10-14): mode badge rendering, owner switch via PUT /api/settings/model-mode,
// pushed feedback, and the read-only state for non-owners.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ModelTab } from "./ModelTab";
import DataPage from "./DataPage";
const ME_OWNER = {
    member_id: "robin", role: "owner", display_name: "Robin", household_id: "household",
    jarvis: { node_id: "hub_1", display_name: "Robin's Jarvis", number: "J-4829-1300", urn: null, town: null },
    agent_box: { enrolled: true, box_id: "box_1" },
};
const ME_MEMBER = { ...ME_OWNER, role: "member" };
const MODE_LOCAL = {
    mode: "local",
    cloud_model_route: "qwen3.8-flash",
    cloud_model_persona: "qwen3.8-flash",
    updated_at: "2026-10-13T08:00:00Z",
};
let handler;
const calls = [];
beforeEach(() => {
    calls.length = 0;
    vi.stubGlobal("fetch", vi.fn(async (url, init = {}) => {
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
describe("ModelTab", () => {
    it("renders the current mode, both cloud model names and the privacy floor note", async () => {
        handler = (url) => (url === "/api/settings/model-mode" ? { status: 200, body: MODE_LOCAL } : undefined);
        render(_jsx(ModelTab, { me: ME_OWNER, readOnly: false }));
        expect(await screen.findByText("Local")).toBeTruthy();
        expect(screen.getAllByText("qwen3.8-flash")).toHaveLength(2); // route + persona
        expect(screen.getByText(/privacy floor/)).toBeTruthy();
        expect(screen.getByText(/raw voice audio is never uploaded/)).toBeTruthy();
        expect(screen.getByRole("switch", { name: "Cloud mode" }).getAttribute("aria-checked")).toBe("false");
        expect(calls).toEqual([{ url: "/api/settings/model-mode", method: "GET", body: undefined }]);
    });
    it("switches to cloud with a PUT and shows the pushed-to-runtime feedback", async () => {
        handler = (url, init) => {
            if (url === "/api/settings/model-mode" && init.method === "PUT") {
                return { status: 200, body: { ...MODE_LOCAL, mode: "cloud", updated_at: "2026-10-14T02:00:00Z", pushed: true } };
            }
            if (url === "/api/settings/model-mode")
                return { status: 200, body: MODE_LOCAL };
            return undefined;
        };
        render(_jsx(ModelTab, { me: ME_OWNER, readOnly: false }));
        fireEvent.click(await screen.findByRole("switch", { name: "Cloud mode" }));
        await waitFor(() => {
            expect(calls.some((c) => c.url === "/api/settings/model-mode" && c.method === "PUT")).toBe(true);
        });
        expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ mode: "cloud" });
        expect(await screen.findByText("Cloud")).toBeTruthy();
        expect(await screen.findByText(/pushed to the voice runtime/)).toBeTruthy();
        expect(screen.getByRole("switch", { name: "Cloud mode" }).getAttribute("aria-checked")).toBe("true");
    });
    it("says the runtime picks it up on the next turn when the push did not happen", async () => {
        handler = (url, init) => {
            if (url === "/api/settings/model-mode" && init.method === "PUT") {
                return { status: 200, body: { ...MODE_LOCAL, mode: "cloud", pushed: false } };
            }
            if (url === "/api/settings/model-mode")
                return { status: 200, body: MODE_LOCAL };
            return undefined;
        };
        render(_jsx(ModelTab, { me: ME_OWNER, readOnly: false }));
        fireEvent.click(await screen.findByRole("switch", { name: "Cloud mode" }));
        expect(await screen.findByText(/next turn/)).toBeTruthy();
    });
    it("is read-only for members: switch and button disabled, no PUT", async () => {
        handler = (url) => (url === "/api/settings/model-mode" ? { status: 200, body: { ...MODE_LOCAL, mode: "cloud" } } : undefined);
        render(_jsx(ModelTab, { me: ME_MEMBER, readOnly: true }));
        expect(await screen.findByText("Cloud")).toBeTruthy();
        const toggle = screen.getByRole("switch", { name: "Cloud mode" });
        const button = screen.getByRole("button", { name: /Switch to local/ });
        expect(toggle.disabled).toBe(true);
        expect(button.disabled).toBe(true);
        expect(screen.getByText(/Only the household owner can switch the model mode/)).toBeTruthy();
        fireEvent.click(toggle);
        fireEvent.click(button);
        await waitFor(() => expect(screen.getByText("Cloud")).toBeTruthy());
        expect(calls.every((c) => c.method === "GET")).toBe(true);
    });
    it("surfaces a switch error without losing the current state", async () => {
        handler = (url, init) => {
            if (url === "/api/settings/model-mode" && init.method === "PUT")
                return { status: 403, body: { detail: "only the household owner can switch the model mode" } };
            if (url === "/api/settings/model-mode")
                return { status: 200, body: MODE_LOCAL };
            return undefined;
        };
        render(_jsx(ModelTab, { me: ME_OWNER, readOnly: false }));
        fireEvent.click(await screen.findByRole("switch", { name: "Cloud mode" }));
        expect(await screen.findByRole("alert")).toBeTruthy();
        expect(screen.getByText("Only the household owner can switch the model mode.")).toBeTruthy();
        expect(screen.getByText("Local")).toBeTruthy(); // badge unchanged
    });
});
describe("DataPage Model tab", () => {
    it("offers a Model tab next to the policy domains and renders the switch at #/data/<scope>/model", async () => {
        handler = (url) => {
            if (url === "/api/studio/me")
                return { status: 200, body: ME_OWNER };
            if (url === "/api/studio/policy/tree") {
                return { status: 200, body: { scopes: [{ scope: "household", label: "Household", parent: null, kind: "household" }], domains: ["privacy", "ha", "schedule"] } };
            }
            if (url === "/api/settings/model-mode")
                return { status: 200, body: MODE_LOCAL };
            return undefined;
        };
        render(_jsx(DataPage, { param: "household/model", navigate: vi.fn() }));
        // the tab sits next to Privacy rings / Home Assistant / Scheduling
        const tablist = await screen.findByRole("tablist", { name: "Domain" });
        expect(tablist.textContent).toContain("Model");
        expect(tablist.textContent).toContain("Privacy rings");
        // the model panel renders without touching the policy endpoints
        expect(await screen.findByRole("heading", { name: /Model mode/ })).toBeTruthy();
        expect(screen.getByRole("tab", { name: "Model" }).getAttribute("aria-selected")).toBe("true");
        expect(calls.some((c) => c.url.startsWith("/api/studio/policy/household"))).toBe(false);
    });
});
