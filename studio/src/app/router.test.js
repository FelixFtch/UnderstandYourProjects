// @vitest-environment node
import { describe, expect, it } from "vitest";
import { normalizeHash, parseHash, toHash } from "./router";
import { isValidInviteCode, normalizeInviteCode } from "./session";
describe("hash routes", () => {
    it("parses section and param", () => {
        expect(parseHash("")).toEqual({ section: "" });
        expect(parseHash("#/jarvis")).toEqual({ section: "jarvis" });
        expect(parseHash("#/Devices/")).toEqual({ section: "devices" });
        expect(parseHash("#/agents/t_felix")).toEqual({ section: "agents", param: "t_felix" });
    });
    it("keeps slashes inside the param and decodes it", () => {
        expect(parseHash("#/devices/commontasks%2Fbackend")).toEqual({ section: "devices", param: "commontasks/backend" });
        expect(parseHash("#/devices/a/b")).toEqual({ section: "devices", param: "a/b" });
        expect(parseHash("#/devices/%E0%A4")).toEqual({ section: "devices", param: "%E0%A4" }); // malformed stays raw
    });
    it("round-trips through toHash", () => {
        const h = toHash("devices", "GSD Works/notes");
        expect(parseHash(h)).toEqual({ section: "devices", param: "GSD Works/notes" });
        expect(normalizeHash("/flow")).toBe("#/flow");
        expect(normalizeHash("flow")).toBe("#/flow");
        expect(normalizeHash("#/flow")).toBe("#/flow");
    });
});
describe("invite codes", () => {
    it("normalizes spaces, dashes and case", () => {
        expect(normalizeInviteCode(" ab12-cd34 ")).toBe("AB12CD34");
        expect(isValidInviteCode("AB12CD34")).toBe(true);
        expect(isValidInviteCode("AB12CD3")).toBe(false);
        expect(isValidInviteCode("AB12CD34X")).toBe(false);
    });
});
