import { jsx as _jsx } from "react/jsx-runtime";
// Cloud usage (qwen) card (2026-10-14): ¥/token formatting helpers, card rendering
// from /api/studio/cloud-usage, and its placement on the Devices page.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CloudUsageCard, tokenPair, yuan } from "./CloudUsageCard";
import DevicesPage from "./DevicesPage";
const USAGE = {
    mode: "cloud",
    currency: "CNY",
    today: { prompt_tokens: 48_210, completion_tokens: 12_980, cost_yuan: 0.42 },
    month: { prompt_tokens: 913_400, completion_tokens: 246_010, cost_yuan: 7.83 },
    total: { prompt_tokens: 2_411_500, completion_tokens: 688_420, cost_yuan: 21.06 },
    by_surface: [
        { surface: "route", prompt_tokens: 1_502_300, completion_tokens: 402_100, cost_yuan: 12.41 },
        { surface: "persona", prompt_tokens: 812_400, completion_tokens: 256_320, cost_yuan: 7.69 },
        { surface: "split", prompt_tokens: 96_800, completion_tokens: 30_000, cost_yuan: 0.96 },
    ],
    updated_at: new Date().toISOString(),
};
let handler;
beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (url) => {
        const r = handler(url);
        const status = r?.status ?? 404;
        const body = r?.body ?? { detail: "not in this test" };
        return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    }));
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});
describe("cloud usage formatting", () => {
    it("formats CNY with two decimals and compact token pairs", () => {
        expect(yuan(7.83)).toBe("¥7.83");
        expect(yuan(0.4)).toBe("¥0.40");
        expect(yuan(0)).toBe("¥0.00");
        expect(tokenPair({ prompt_tokens: 913_400, completion_tokens: 246_010, cost_yuan: 7.83 })).toBe("913k in · 246k out");
        expect(tokenPair({ prompt_tokens: 980, completion_tokens: 12, cost_yuan: 0 })).toBe("980 in · 12 out");
    });
});
describe("CloudUsageCard", () => {
    it("renders mode badge, ¥ totals, compact tokens and the by-surface table", () => {
        render(_jsx(CloudUsageCard, { usage: USAGE }));
        expect(screen.getByText("Cloud usage (qwen)")).toBeTruthy();
        expect(screen.getByText("Cloud")).toBeTruthy(); // mode badge
        expect(screen.getByText("¥0.42")).toBeTruthy(); // today
        expect(screen.getByText("¥7.83")).toBeTruthy(); // month
        expect(screen.getByText("¥21.06")).toBeTruthy(); // total
        expect(screen.getByText("913k in · 246k out tokens")).toBeTruthy();
        expect(screen.getByText("Route")).toBeTruthy();
        expect(screen.getByText("Persona")).toBeTruthy();
        expect(screen.getByText("Split")).toBeTruthy();
        expect(screen.getByText("¥12.41")).toBeTruthy();
    });
    it("shows the Local badge when the household is in local mode", () => {
        render(_jsx(CloudUsageCard, { usage: { ...USAGE, mode: "local" } }));
        expect(screen.getByText("Local")).toBeTruthy();
        expect(screen.queryByText("Cloud")).toBeNull();
    });
});
describe("DevicesPage cloud usage section", () => {
    it("loads /api/studio/cloud-usage and shows the card between home devices and sensors", async () => {
        handler = (url) => {
            if (url === "/api/studio/devices")
                return { status: 200, body: { devices: [] } };
            if (url === "/api/studio/projects")
                return { status: 200, body: { projects: [], tree: [] } };
            if (url === "/api/studio/home-devices")
                return { status: 200, body: { status: "ok", schema_version: "homehub-home-devices-v1", state: "ok", readOnly: true, controlEnabled: false, devices: [] } };
            if (url === "/api/sensors/devices")
                return { status: 200, body: { count: 0, devices: [], placeholders: [] } };
            if (url === "/api/sensors/states")
                return { status: 200, body: [] };
            if (url === "/api/studio/cloud-usage")
                return { status: 200, body: USAGE };
            return undefined;
        };
        const navigate = vi.fn();
        render(_jsx(DevicesPage, { param: undefined, navigate: navigate }));
        expect(await screen.findByText("Cloud usage (qwen)")).toBeTruthy();
        expect(screen.getByText("Cloud mode")).toBeTruthy(); // section status line
        expect(screen.getByText("¥7.83")).toBeTruthy();
        expect(screen.getByText("Route")).toBeTruthy();
    });
    it("shows a compact error when the usage meter is unreachable", async () => {
        handler = (url) => {
            if (url === "/api/studio/devices")
                return { status: 200, body: { devices: [] } };
            if (url === "/api/studio/projects")
                return { status: 200, body: { projects: [], tree: [] } };
            if (url === "/api/studio/home-devices")
                return { status: 200, body: { status: "ok", schema_version: "homehub-home-devices-v1", state: "ok", readOnly: true, controlEnabled: false, devices: [] } };
            if (url === "/api/sensors/devices")
                return { status: 200, body: { count: 0, devices: [], placeholders: [] } };
            if (url === "/api/sensors/states")
                return { status: 200, body: [] };
            if (url === "/api/studio/cloud-usage")
                return { status: 503, body: { detail: "meter unavailable" } };
            return undefined;
        };
        render(_jsx(DevicesPage, { param: undefined, navigate: vi.fn() }));
        expect(await screen.findByText("Cloud usage meter unreachable")).toBeTruthy();
    });
});
