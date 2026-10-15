import { jsx as _jsx } from "react/jsx-runtime";
// Voice profile card (2026-10-15): rendering with the active badge and builtin
// switches, switching PUT body + per-section push feedback, custom-mix save
// (slugified name, no push), activating a saved mix, read-only for non-owners.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VoiceProfileCard } from "./VoiceProfileCard";
const ME_OWNER = {
    member_id: "robin", role: "owner", display_name: "Robin", household_id: "household",
    jarvis: { node_id: "hub_1", display_name: "Robin's Jarvis", number: "J-4829-1300", urn: null, town: null },
    agent_box: { enrolled: true, box_id: "box_1" },
};
const ME_MEMBER = { ...ME_OWNER, role: "member" };
const VOICE = {
    active: "local",
    profiles: [
        { name: "local", label: "Local (offline)", stt: "local", llm: "local", tts: "local", builtin: 1 },
        { name: "cloud-full", label: "Cloud full chain", stt: "qwen", llm: "qwen", tts: "qwen", builtin: 1 },
    ],
    stt_options: ["local", "qwen", "claude"],
    llm_options: ["local", "qwen", "claude"],
    tts_options: ["local", "qwen", "claude"],
};
const VOICE_WITH_CUSTOM = {
    ...VOICE,
    profiles: [
        ...VOICE.profiles,
        { name: "my-mix", label: "My mix", stt: "local", llm: "claude", tts: "qwen", builtin: 0 },
    ],
};
let handler;
const calls = [];
const GET_URL = "/api/settings/voice-profiles";
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
describe("VoiceProfileCard (Data → Model)", () => {
    it("renders the active profile badge, builtin switches, mix editor and the keep-warm note", async () => {
        handler = (url) => (url === GET_URL ? { status: 200, body: VOICE } : undefined);
        render(_jsx(VoiceProfileCard, { me: ME_OWNER, readOnly: false }));
        expect(await screen.findByRole("heading", { name: /Voice profiles/ })).toBeTruthy();
        // the active badge sits inside the heading (the builtin button carries the same label)
        expect(screen.getByRole("heading", { name: /Voice profiles/ }).textContent).toContain("Local (offline)");
        expect(calls).toEqual([{ url: GET_URL, method: "GET", body: undefined }]);
        // builtins: the active one is disabled, the other is a one-tap switch
        expect(screen.getByRole("button", { name: /Local \(offline\)/ }).disabled).toBe(true);
        expect(screen.getByRole("button", { name: /Cloud full chain/ }).disabled).toBe(false);
        // mix editor: three segment selects fed from the *_options lists
        for (const seg of ["STT", "LLM", "TTS"]) {
            const select = screen.getByLabelText(seg);
            expect(select.tagName).toBe("SELECT");
            expect(select.querySelectorAll("option")).toHaveLength(3);
        }
        expect(screen.getByLabelText("Label")).toBeTruthy();
        expect(screen.getByText(/Switching never unloads the local models - switching back is instant\./)).toBeTruthy();
    });
    it("switches to a builtin with PUT {active} and shows the per-section push feedback", async () => {
        handler = (url, init) => {
            if (url === GET_URL && init.method === "PUT") {
                return { status: 200, body: { ...VOICE, active: "cloud-full", pushed: { llm: true, stt: true, tts: false } } };
            }
            if (url === GET_URL)
                return { status: 200, body: VOICE };
            return undefined;
        };
        render(_jsx(VoiceProfileCard, { me: ME_OWNER, readOnly: false }));
        fireEvent.click(await screen.findByRole("button", { name: /Cloud full chain/ }));
        await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
        expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ active: "cloud-full" });
        expect(await screen.findByRole("status")).toBeTruthy();
        expect(screen.getByText(/Active profile: Cloud full chain/)).toBeTruthy();
        expect(screen.getByText(/LLM: pushed to the voice runtime/)).toBeTruthy();
        expect(screen.getByText(/STT: pushed to the voice runtime/)).toBeTruthy();
        expect(screen.getByText(/TTS: applies on the next turn/)).toBeTruthy();
        // the badge follows the response
        expect(screen.getByRole("heading", { name: /Voice profiles/ }).textContent).toContain("Cloud full chain");
    });
    it("saves a custom mix with a slugified name and no push", async () => {
        handler = (url, init) => {
            if (url === GET_URL && init.method === "PUT") {
                const body = JSON.parse(String(init.body));
                const profiles = [...VOICE.profiles, { name: body.name, label: body.label, stt: body.stt, llm: body.llm, tts: body.tts, builtin: 0 }];
                return { status: 200, body: { ...VOICE, profiles, pushed: null } };
            }
            if (url === GET_URL)
                return { status: 200, body: VOICE };
            return undefined;
        };
        render(_jsx(VoiceProfileCard, { me: ME_OWNER, readOnly: false }));
        // fresh install: the editor starts on a new mix with the first options preselected
        const llm = (await screen.findByLabelText("LLM"));
        expect(llm.value).toBe("local");
        fireEvent.change(screen.getByLabelText("Label"), { target: { value: "My mix" } });
        fireEvent.change(llm, { target: { value: "claude" } });
        fireEvent.change(screen.getByLabelText("TTS"), { target: { value: "qwen" } });
        fireEvent.click(screen.getByRole("button", { name: "Save custom" }));
        await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
        expect(calls.find((c) => c.method === "PUT")?.body)
            .toEqual({ name: "my-mix", stt: "local", llm: "claude", tts: "qwen", label: "My mix" });
        expect(await screen.findByRole("status")).toBeTruthy();
        expect(screen.getByText(/Saved "My mix" — stored on the hub, not pushed to the voice runtime/)).toBeTruthy();
        // the saved mix becomes the edited one — Activate is now offered
        expect(screen.getByLabelText("Mix to edit").value).toBe("my-mix");
        expect(screen.getByRole("button", { name: "Activate" }).disabled).toBe(false);
    });
    it("activates a saved custom mix with PUT {active}", async () => {
        handler = (url, init) => {
            if (url === GET_URL && init.method === "PUT") {
                return { status: 200, body: { ...VOICE_WITH_CUSTOM, active: "my-mix", pushed: { llm: true, stt: true, tts: true } } };
            }
            if (url === GET_URL)
                return { status: 200, body: VOICE_WITH_CUSTOM };
            return undefined;
        };
        render(_jsx(VoiceProfileCard, { me: ME_OWNER, readOnly: false }));
        // the existing custom mix is preselected for editing, drafts match → Activate is enabled
        expect((await screen.findByLabelText("Mix to edit"))).toBeTruthy();
        const activate = screen.getByRole("button", { name: "Activate" });
        expect(activate.disabled).toBe(false);
        fireEvent.click(activate);
        await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
        expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ active: "my-mix" });
        expect(await screen.findByText(/Active profile: My mix/)).toBeTruthy();
        expect(screen.getByText(/TTS: pushed to the voice runtime/)).toBeTruthy();
    });
    it("is read-only for members: switches, selects and buttons disabled, no PUT", async () => {
        handler = (url) => (url === GET_URL ? { status: 200, body: VOICE_WITH_CUSTOM } : undefined);
        render(_jsx(VoiceProfileCard, { me: ME_MEMBER, readOnly: true }));
        expect(await screen.findByRole("heading", { name: /Voice profiles/ })).toBeTruthy();
        expect(screen.getByRole("button", { name: /Cloud full chain/ }).disabled).toBe(true);
        for (const seg of ["STT", "LLM", "TTS"]) {
            expect(screen.getByLabelText(seg).disabled).toBe(true);
        }
        expect(screen.getByLabelText("Label").disabled).toBe(true);
        expect(screen.getByRole("button", { name: "Save custom" }).disabled).toBe(true);
        expect(screen.getByRole("button", { name: "Activate" }).disabled).toBe(true);
        expect(screen.getByText(/Only the household owner can change voice profiles/)).toBeTruthy();
        expect(calls.every((c) => c.method === "GET")).toBe(true);
    });
});
