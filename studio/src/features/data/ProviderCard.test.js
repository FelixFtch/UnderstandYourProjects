import { jsx as _jsx } from "react/jsx-runtime";
// Cloud provider card (2026-10-15): provider dropdown rendering, save PUT body
// (api_key omitted unless replaced), active-switch PUT body + pushed feedback,
// read-only for non-owners, load-error retry.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProviderCard } from "./ProviderCard";
const ME_OWNER = {
    member_id: "robin", role: "owner", display_name: "Robin", household_id: "household",
    jarvis: { node_id: "hub_1", display_name: "Robin's Jarvis", number: "J-4829-1300", urn: null, town: null },
    agent_box: { enrolled: true, box_id: "box_1" },
};
const ME_MEMBER = { ...ME_OWNER, role: "member" };
const PROVIDERS = {
    active: "qwen",
    providers: [
        { id: "qwen", label: "Qwen · Alibaba Bailian", model: "qwen3.8-flash", has_key: true, key_hint: "sk-…1234" },
        { id: "openai", label: "OpenAI", model: "gpt-5.2", has_key: false, key_hint: null },
        { id: "claude", label: "Claude · Anthropic", model: "claude-sonnet-4-6", has_key: false, key_hint: null },
        { id: "gemini", label: "Gemini · Google", model: "gemini-3-flash", has_key: false, key_hint: null },
        { id: "deepseek", label: "DeepSeek", model: "deepseek-v4-flash", has_key: true, key_hint: "sk-…abcd" },
        // 2026-10-15: the hub catalog grew to seven vendors (grok + muse)
        { id: "grok", label: "Grok · xAI", model: "grok-4.7", has_key: false, key_hint: null },
        { id: "muse", label: "Muse · Meta", model: "muse-spark-1.3", has_key: false, key_hint: null },
    ],
    updated_at: "2026-10-14T08:00:00Z",
};
let handler;
const calls = [];
const GET_URL = "/api/settings/llm-providers";
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
function putProviders(body) {
    return { status: 200, body: typeof body === "object" && body !== null && "pushed" in body ? body : { ...body, pushed: false } };
}
describe("ProviderCard (Data → Model)", () => {
    it("renders all seven providers with model + key status, preselecting the active one", async () => {
        handler = (url) => (url === GET_URL ? { status: 200, body: PROVIDERS } : undefined);
        render(_jsx(ProviderCard, { me: ME_OWNER, readOnly: false }));
        // card header names the active provider; the picker is preselected on it
        expect(await screen.findByRole("heading", { name: /Cloud provider/ })).toBeTruthy();
        const picker = screen.getByRole("button", { name: "Provider" });
        expect(picker.textContent).toContain("Qwen · Alibaba Bailian");
        expect(picker.textContent).toContain("qwen3.8-flash");
        expect(calls.filter((c) => c.url === GET_URL)).toEqual([{ url: GET_URL, method: "GET", body: undefined }]);
        // the dropdown is server-driven: all seven vendors with their model and a key-status dot
        fireEvent.click(picker);
        const listbox = await screen.findByRole("listbox", { name: "Cloud providers" });
        expect(within(listbox).getAllByRole("option")).toHaveLength(7);
        for (const label of ["Qwen · Alibaba Bailian", "OpenAI", "Claude · Anthropic", "Gemini · Google", "DeepSeek", "Grok · xAI", "Muse · Meta"]) {
            expect(within(listbox).getByText(label)).toBeTruthy();
        }
        expect(within(listbox).getAllByTitle(/Key stored/)).toHaveLength(2); // qwen + deepseek
        expect(within(listbox).getAllByTitle("No key stored")).toHaveLength(5);
        expect(within(listbox).getByText("deepseek-v4-flash")).toBeTruthy();
        expect(within(listbox).getByText("grok-4.7")).toBeTruthy();
        expect(within(listbox).getByText("muse-spark-1.3")).toBeTruthy();
        fireEvent.keyDown(document, { key: "Escape" });
        // selected provider detail: model prefilled (with datalist suggestions), stored-key hint + Replace key
        const model = screen.getByLabelText("Model");
        expect(model.value).toBe("qwen3.8-flash");
        expect(model.getAttribute("list")).toBeTruthy();
        expect(document.querySelectorAll("datalist option").length).toBeGreaterThanOrEqual(3);
        expect(screen.getByLabelText("API key").placeholder).toBe("Stored key sk-…1234");
        expect(screen.getByRole("button", { name: "Replace key" })).toBeTruthy();
        expect(screen.getByText("Keys are stored server-side and never returned in full.")).toBeTruthy();
    });
    it("saves a provider with PUT {provider, model, api_key} and shows next-turn feedback", async () => {
        handler = (url, init) => {
            if (url === GET_URL && init.method === "PUT") {
                const body = JSON.parse(String(init.body));
                const providers = PROVIDERS.providers.map((p) => p.id === body.provider ? { ...p, model: body.model, has_key: true, key_hint: `sk-…${String(body.api_key).slice(-4)}` } : p);
                return putProviders({ ...PROVIDERS, providers, updated_at: "2026-10-15T01:00:00Z" });
            }
            if (url === GET_URL)
                return { status: 200, body: PROVIDERS };
            return undefined;
        };
        render(_jsx(ProviderCard, { me: ME_OWNER, readOnly: false }));
        fireEvent.click(await screen.findByRole("button", { name: "Provider" }));
        fireEvent.click(await screen.findByRole("option", { name: /OpenAI/ }));
        // openai has no stored key: the password field is shown straight away
        const model = screen.getByLabelText("Model");
        expect(model.value).toBe("gpt-5.2");
        fireEvent.change(model, { target: { value: "gpt-5.2-pro" } });
        const key = screen.getByPlaceholderText(/Paste the key - stored on the Jetson/);
        fireEvent.change(key, { target: { value: "sk-live-9999" } });
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
        expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ provider: "openai", model: "gpt-5.2-pro", api_key: "sk-live-9999" });
        expect(await screen.findByRole("status")).toBeTruthy();
        expect(screen.getByText(/Saved OpenAI — the voice runtime picks it up on its next turn/)).toBeTruthy();
        // form reflects the response: model updated, key field back to the stored-hint state
        expect(screen.getByLabelText("Model").value).toBe("gpt-5.2-pro");
        expect(screen.getByLabelText("API key").placeholder).toBe("Stored key sk-…9999");
    });
    it("omits api_key from the PUT body when the stored key was not replaced", async () => {
        handler = (url, init) => {
            if (url === GET_URL && init.method === "PUT") {
                const body = JSON.parse(String(init.body));
                const providers = PROVIDERS.providers.map((p) => (p.id === body.provider ? { ...p, model: body.model } : p));
                return putProviders({ ...PROVIDERS, providers });
            }
            if (url === GET_URL)
                return { status: 200, body: PROVIDERS };
            return undefined;
        };
        render(_jsx(ProviderCard, { me: ME_OWNER, readOnly: false }));
        const model = (await screen.findByLabelText("Model"));
        await screen.findByRole("button", { name: "Replace key" }); // qwen's stored key shown, not the password field
        fireEvent.change(model, { target: { value: "qwen3.8-plus" } });
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
        const body = calls.find((c) => c.method === "PUT")?.body;
        expect(body).toEqual({ provider: "qwen", model: "qwen3.8-plus" });
        expect(body).not.toHaveProperty("api_key");
    });
    it("expands the key field via Replace key and collapses it with Cancel", async () => {
        handler = (url) => (url === GET_URL ? { status: 200, body: PROVIDERS } : undefined);
        render(_jsx(ProviderCard, { me: ME_OWNER, readOnly: false }));
        fireEvent.click(await screen.findByRole("button", { name: "Replace key" }));
        const key = screen.getByPlaceholderText("Paste the key - stored on the Jetson, never shown in full");
        expect(key.type).toBe("password");
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
        expect(screen.getByLabelText("API key").placeholder).toBe("Stored key sk-…1234");
        expect(screen.queryByPlaceholderText("Paste the key - stored on the Jetson, never shown in full")).toBeNull();
    });
    it("switches the active provider with PUT {active} and shows pushed-to-runtime feedback", async () => {
        handler = (url, init) => {
            if (url === GET_URL && init.method === "PUT")
                return { status: 200, body: { ...PROVIDERS, active: "claude", updated_at: "2026-10-15T01:00:00Z", pushed: true } };
            if (url === GET_URL)
                return { status: 200, body: PROVIDERS };
            return undefined;
        };
        render(_jsx(ProviderCard, { me: ME_OWNER, readOnly: false }));
        fireEvent.click(await screen.findByRole("button", { name: "Provider" }));
        fireEvent.click(await screen.findByRole("option", { name: /Claude · Anthropic/ }));
        fireEvent.click(screen.getByRole("button", { name: "Use this provider" }));
        await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
        expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ active: "claude" });
        expect(await screen.findByRole("status")).toBeTruthy();
        expect(screen.getByText(/Now using Claude · Anthropic — pushed to the voice runtime, effective immediately/)).toBeTruthy();
        // the header badge follows the response, and the use-button disables on the active provider
        expect(screen.getByRole("heading", { name: /Cloud provider/ }).textContent).toContain("Claude · Anthropic");
        expect(screen.getByRole("button", { name: "Use this provider" }).disabled).toBe(true);
    });
    it("is read-only for members: inputs and buttons disabled, no PUT", async () => {
        handler = (url) => (url === GET_URL ? { status: 200, body: PROVIDERS } : undefined);
        render(_jsx(ProviderCard, { me: ME_MEMBER, readOnly: true }));
        const model = (await screen.findByLabelText("Model"));
        expect(model.disabled).toBe(true);
        expect(screen.getByLabelText("API key").disabled).toBe(true);
        expect(screen.getByRole("button", { name: "Save" }).disabled).toBe(true);
        expect(screen.queryByRole("button", { name: "Replace key" })).toBeNull(); // members never reach the key field
        expect(screen.getByText(/Only the household owner can change cloud provider settings/)).toBeTruthy();
        // picking another provider is allowed for inspection, but the actions stay disabled
        fireEvent.click(screen.getByRole("button", { name: "Provider" }));
        fireEvent.click(await screen.findByRole("option", { name: /DeepSeek/ }));
        expect(screen.getByRole("button", { name: "Use this provider" }).disabled).toBe(true);
        expect(screen.getByRole("button", { name: "Save" }).disabled).toBe(true);
        expect(calls.every((c) => c.method === "GET")).toBe(true);
    });
    it("surfaces a save rejection as an inline alert", async () => {
        handler = (url, init) => {
            if (url === GET_URL && init.method === "PUT")
                return { status: 403, body: { detail: "owner only" } };
            if (url === GET_URL)
                return { status: 200, body: PROVIDERS };
            return undefined;
        };
        render(_jsx(ProviderCard, { me: ME_OWNER, readOnly: false }));
        const model = (await screen.findByLabelText("Model"));
        fireEvent.change(model, { target: { value: "qwen3-max" } });
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        expect(await screen.findByRole("alert")).toBeTruthy();
        expect(screen.getByText("Only the household owner can change cloud provider settings.")).toBeTruthy();
        expect(screen.getByLabelText("Model").value).toBe("qwen3-max"); // draft kept
    });
    it("offers a retry when the providers cannot be loaded", async () => {
        let down = true;
        handler = (url) => {
            if (url === GET_URL)
                return down ? { status: 503, body: { detail: "runtime unreachable" } } : { status: 200, body: PROVIDERS };
            return undefined;
        };
        render(_jsx(ProviderCard, { me: ME_OWNER, readOnly: false }));
        expect(await screen.findByText("runtime unreachable")).toBeTruthy();
        down = false;
        fireEvent.click(screen.getByRole("button", { name: "Retry" }));
        expect(await screen.findByRole("heading", { name: /Cloud provider/ })).toBeTruthy();
        expect(screen.getByRole("button", { name: "Provider" }).textContent).toContain("Qwen · Alibaba Bailian");
    });
});
