import { describe, expect, it } from "vitest";
import { deepMerge, explainPrivacy, fieldView, flattenScopes, parseDataRoute, privacyRows, scopeChain, setPath, setPrivacy, unsetPath, validatePrivacy, validateSchedule, } from "./inherit";
const inherited = {
    categories: {
        profile: { ring: "R4", share_with_agents: true },
        calendar: { ring: "R3", share_with_agents: false },
        health: { ring: "R1", share_with_agents: false },
    },
};
describe("fieldView (inherited vs own display)", () => {
    it("shows the inherited value when nothing is set at this level", () => {
        const v = fieldView(undefined, { live: true }, { live: true }, ["live"]);
        expect(v).toMatchObject({ source: "inherited", value: true, own: undefined, inherited: true, overrides: false });
    });
    it("an own value overrides and is flagged as such", () => {
        const v = fieldView({ live: false }, { live: true }, { live: false }, ["live"]);
        expect(v).toMatchObject({ source: "own", value: false, inherited: true, overrides: true, redundant: false });
    });
    it("an own value equal to the inherited one is redundant, not an override", () => {
        const v = fieldView({ live: true }, { live: true }, { live: true }, ["live"]);
        expect(v).toMatchObject({ source: "own", overrides: false, redundant: true });
    });
    it("unset everywhere", () => {
        expect(fieldView({}, {}, {}, ["quiet_hours"]).source).toBe("unset");
    });
    it("null is a real own value (e.g. quiet hours switched off)", () => {
        const v = fieldView({ quiet_hours: null }, { quiet_hours: { start: "22:00", end: "07:00" } }, {}, ["quiet_hours"]);
        expect(v).toMatchObject({ source: "own", value: null, overrides: true });
    });
});
describe("privacyRows", () => {
    it("covers all nine categories, merges per leaf and completes with safe defaults", () => {
        const own = { categories: { calendar: { ring: "R4", share_with_agents: true }, health: { ring: "R2" } } };
        const rows = privacyRows(own, inherited, deepMerge(inherited, own));
        expect(rows).toHaveLength(9);
        const by = Object.fromEntries(rows.map((r) => [r.category, r]));
        expect(by.profile).toMatchObject({ source: "inherited", local: { ring: "R4", share_with_agents: true } });
        expect(by.calendar).toMatchObject({ source: "own", overrides: true, partial: false, local: { ring: "R4", share_with_agents: true } });
        // Only `ring` set here: share flag still inherited.
        expect(by.health).toMatchObject({ source: "own", partial: true, local: { ring: "R2", share_with_agents: false } });
        expect(by.location).toMatchObject({ source: "unset", local: { ring: "R1", share_with_agents: false } });
    });
});
describe("setPrivacy / reset", () => {
    it("writes a complete pair and forces share off below R4", () => {
        const own = setPrivacy({}, inherited, "profile", { ring: "R3" });
        expect(own).toEqual({ categories: { profile: { ring: "R3", share_with_agents: false } } });
    });
    it("toggling share keeps the inherited R4 ring", () => {
        const own = setPrivacy({}, inherited, "profile", { share_with_agents: false });
        expect(own).toEqual({ categories: { profile: { ring: "R4", share_with_agents: false } } });
    });
    it("does not touch other categories and is immutable", () => {
        const before = { categories: { calendar: { ring: "R2", share_with_agents: false } } };
        const after = setPrivacy(before, inherited, "health", { ring: "R2" });
        expect(before).toEqual({ categories: { calendar: { ring: "R2", share_with_agents: false } } });
        expect(after).toEqual({ categories: { calendar: { ring: "R2", share_with_agents: false }, health: { ring: "R2", share_with_agents: false } } });
    });
    it("reset to inherited removes the key and prunes empty parents", () => {
        const own = { categories: { calendar: { ring: "R4", share_with_agents: true } } };
        expect(unsetPath(own, ["categories", "calendar"])).toEqual({});
        expect(unsetPath({ a: 1, b: { c: 2 } }, ["b", "c"])).toEqual({ a: 1 });
        expect(setPath({ a: { b: 1 } }, ["a", "c"], 2)).toEqual({ a: { b: 1, c: 2 } });
    });
});
describe("validation and explanations", () => {
    it("rejects share_with_agents below R4", () => {
        expect(validatePrivacy({ categories: { health: { ring: "R2", share_with_agents: true } } })).toHaveLength(1);
        expect(validatePrivacy({ categories: { profile: { ring: "R4", share_with_agents: true } } })).toEqual([]);
    });
    it("validates schedule values", () => {
        expect(validateSchedule({ reminder_lead_minutes: 15, quiet_hours: { start: "22:00", end: "07:00" } })).toEqual([]);
        expect(validateSchedule({ reminder_lead_minutes: -5 })).toHaveLength(1);
        expect(validateSchedule({ quiet_hours: { start: "25:00", end: "07:00" } })).toHaveLength(1);
    });
    it("explains the effective result", () => {
        expect(explainPrivacy({ ring: "R4", share_with_agents: true }).headline).toBe("R4 External · shared with agents");
        expect(explainPrivacy({ ring: "R4", share_with_agents: false }).headline).toBe("R4 External · not on share cards");
        expect(explainPrivacy({ ring: "R2", share_with_agents: false }).headline).toBe("R2 Family");
        expect(explainPrivacy(undefined).headline).toBe("Not set anywhere");
    });
});
describe("deepMerge", () => {
    it("merges objects per key, replaces arrays and null", () => {
        expect(deepMerge({ a: { x: 1, y: 2 }, list: [1, 2], q: { s: "1" } }, { a: { y: 3 }, list: [9], q: null }))
            .toEqual({ a: { x: 1, y: 3 }, list: [9], q: null });
    });
});
describe("scope tree and routing", () => {
    const scopes = [
        { scope: "guest", label: "Guest", parent: "household", kind: "guest" },
        { scope: "member:robin", label: "Robin", parent: "household", kind: "member" },
        { scope: "household", label: "Household", parent: "town_default", kind: "household" },
        { scope: "member:ana", label: "Ana", parent: "household", kind: "member" },
        { scope: "town_default", label: "Town default", parent: null, kind: "town" },
    ];
    it("orders Town → Household → members (alpha) → Guest with depths", () => {
        expect(flattenScopes(scopes).map((n) => `${n.depth}:${n.scope.scope}`)).toEqual([
            "0:town_default", "1:household", "2:member:ana", "2:member:robin", "2:guest",
        ]);
    });
    it("builds the inheritance chain root-first", () => {
        expect(scopeChain(scopes, "member:robin").map((s) => s.scope)).toEqual(["town_default", "household", "member:robin"]);
        expect(scopeChain(scopes, "nope")).toEqual([]);
    });
    it("parses #/data/<scope>/<domain?>", () => {
        expect(parseDataRoute("member:robin/privacy")).toEqual({ scope: "member:robin", domain: "privacy" });
        expect(parseDataRoute("household")).toEqual({ scope: "household", domain: undefined });
        expect(parseDataRoute("member%3Arobin/ha")).toEqual({ scope: "member:robin", domain: "ha" });
        expect(parseDataRoute("guest/bogus")).toEqual({ scope: "guest", domain: undefined });
        expect(parseDataRoute(undefined)).toEqual({});
    });
});
