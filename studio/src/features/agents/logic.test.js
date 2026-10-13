import { describe, expect, it } from "vitest";
import { authorRole, countChanges, diffShareCard, groupByCategory, handoffOrigin, makeNewItem, mergeMessages, parseThreadId, sortChats, splitContacts, visibleToAgents, } from "./logic";
const thread = (id, last, extra = {}) => ({
    thread_id: id, kind: "direct", title: id, participants: [], last_message_at: last, last_preview: "", unread: 0, ...extra,
});
describe("sortChats (thread list sorting)", () => {
    it("drops the Jarvis thread and orders by last_message_at descending", () => {
        const out = sortChats([
            thread("jarvis", "2026-10-11T12:00:00Z", { kind: "jarvis" }),
            thread("t_old", "2026-10-01T09:00:00Z"),
            thread("t_new", "2026-10-11T10:00:00Z"),
            thread("t_mid", "2026-10-05T09:00:00Z", { kind: "group" }),
        ]);
        expect(out.map((t) => t.thread_id)).toEqual(["t_new", "t_mid", "t_old"]);
    });
    it("puts threads without messages last, ties broken by title then id", () => {
        const out = sortChats([
            thread("t_empty_b", null, { title: "Beta" }),
            thread("t_x", "2026-10-02T00:00:00Z", { title: "Zed" }),
            thread("t_empty_a", null, { title: "Alpha" }),
            thread("t_y", "2026-10-02T00:00:00Z", { title: "Able" }),
            thread("t_bad", "not-a-date", { title: "Aaa" }),
        ]);
        expect(out.map((t) => t.thread_id)).toEqual(["t_y", "t_x", "t_bad", "t_empty_a", "t_empty_b"]);
    });
    it("does not mutate its input", () => {
        const input = [thread("a", "2026-01-01T00:00:00Z"), thread("b", "2026-02-01T00:00:00Z")];
        sortChats(input);
        expect(input.map((t) => t.thread_id)).toEqual(["a", "b"]);
    });
});
const item = (id, extra = {}) => ({
    item_id: id, category: "profile", label: id, value_preview: "…", ring: "R4", source: "default", enabled: true, locked: false, ...extra,
});
describe("diffShareCard (share-card edit diffing)", () => {
    const base = [
        item("profile"),
        item("calendar", { category: "calendar" }),
        item("location", { category: "location", ring: "R1", enabled: false }),
        item("health", { category: "health", ring: "R1", enabled: false, locked: true }),
        item("diet", { source: "added" }),
    ];
    it("returns null when nothing changed", () => {
        expect(diffShareCard(base, base)).toBeNull();
        expect(countChanges(null)).toBe(0);
    });
    it("emits only flipped items", () => {
        const draft = base.map((i) => (i.item_id === "calendar" ? { ...i, enabled: false } : i.item_id === "location" ? { ...i, enabled: true } : i));
        expect(diffShareCard(base, draft)).toEqual({ items: [{ item_id: "calendar", enabled: false }, { item_id: "location", enabled: true }] });
    });
    it("flipping an item back cancels the change", () => {
        const once = base.map((i) => (i.item_id === "profile" ? { ...i, enabled: false } : i));
        const twice = once.map((i) => (i.item_id === "profile" ? { ...i, enabled: true } : i));
        expect(diffShareCard(base, twice)).toBeNull();
    });
    it("never asks to enable a locked item", () => {
        const draft = base.map((i) => (i.item_id === "health" ? { ...i, enabled: true } : i));
        expect(diffShareCard(base, draft)).toBeNull();
    });
    it("collects additions with their full value and removals of added items only", () => {
        const added = makeNewItem("profile", "Allergies", "Peanuts and shellfish — please avoid");
        const draft = [...base.filter((i) => i.item_id !== "diet" && i.item_id !== "profile"), added];
        const u = diffShareCard(base, draft);
        expect(u).toEqual({
            add: [{ category: "profile", label: "Allergies", value: "Peanuts and shellfish — please avoid" }],
            remove: ["diet"],
        });
        expect(countChanges(u)).toBe(2);
        expect(added.value_preview.length).toBeLessThan(added.value.length);
    });
    it("an added-then-removed draft item produces no change", () => {
        const added = makeNewItem("calendar", "x", "y");
        const draft = [...base, added].filter((i) => i.item_id !== added.item_id);
        expect(diffShareCard(base, draft)).toBeNull();
    });
});
describe("share card helpers", () => {
    it("groups by canonical category order, unknown categories last", () => {
        const groups = groupByCategory([
            item("a", { category: "health" }), item("b", { category: "zzz_custom" }), item("c", { category: "profile" }), item("d", { category: "health" }),
        ]);
        expect(groups.map(([c, xs]) => [c, xs.length])).toEqual([["profile", 1], ["health", 2], ["zzz_custom", 1]]);
    });
    it("agents only see enabled, unlocked items", () => {
        expect(visibleToAgents([item("a"), item("b", { enabled: false }), item("c", { locked: true })]).map((i) => i.item_id)).toEqual(["a"]);
    });
});
const message = (id, at, extra = {}) => ({
    message_id: id, thread_id: "t", author: { kind: "agent", id: "c_x", display: "X" }, text: id, created_at: at, status: "delivered", meta: {}, ...extra,
});
describe("messages", () => {
    it("merges pages and polls by id, oldest first, newer copy wins", () => {
        const a = message("m1", "2026-10-11T10:00:00Z");
        const b = message("m2", "2026-10-11T10:01:00Z", { status: "sent" });
        const b2 = { ...b, status: "delivered" };
        const c = message("m0", "2026-10-11T09:00:00Z");
        const out = mergeMessages([a, b], [b2, c]);
        expect(out.map((m) => m.message_id)).toEqual(["m0", "m1", "m2"]);
        expect(out[2].status).toBe("delivered");
    });
    it("classifies authors from the viewer's perspective", () => {
        expect(authorRole({ kind: "member", id: "robin", display: "Robin" }, "robin")).toBe("me");
        expect(authorRole({ kind: "member", id: "dr_lee", display: "Dr Lee" }, "robin")).toBe("member");
        expect(authorRole({ kind: "jarvis", id: "jarvis", display: "Robin's Jarvis" }, "robin")).toBe("my-jarvis");
        expect(authorRole({ kind: "agent", id: "c_f", display: "Felix's Jarvis" }, "robin")).toBe("agent");
    });
    it("detects a Jarvis handoff origin", () => {
        expect(handoffOrigin([message("m1", "2026-10-11T10:00:00Z")])).toBeNull();
        const h = message("m2", "2026-10-11T10:00:00Z", { author: { kind: "jarvis", id: "jarvis", display: "J" } });
        expect(handoffOrigin([message("m1", "2026-10-11T09:00:00Z"), h])?.message_id).toBe("m2");
        const meta = message("m3", "2026-10-11T10:00:00Z", { meta: { handoff_thread_id: "jarvis" } });
        expect(handoffOrigin([meta])?.message_id).toBe("m3");
    });
});
describe("routing and contacts", () => {
    it("parses the thread id from the route param", () => {
        expect(parseThreadId(undefined)).toBeUndefined();
        expect(parseThreadId("")).toBeUndefined();
        expect(parseThreadId("t_abc")).toBe("t_abc");
        expect(parseThreadId("t_abc/extra")).toBe("t_abc");
        expect(parseThreadId("t%20x")).toBe("t x");
    });
    it("splits pending invites from contacts and sinks blocked ones", () => {
        const c = (id, name, status) => ({
            contact_id: id, display_name: name, urn: "urn:x:" + id, number: null, transport: "town", status, town: null, last_seen: null, note: "",
        });
        const { pending, others } = splitContacts([c("1", "Zoe", "verified"), c("2", "Abe", "blocked"), c("3", "Mia", "pending_acceptance"), c("4", "Bea", "invited")]);
        expect(pending.map((x) => x.display_name)).toEqual(["Mia"]);
        expect(others.map((x) => x.display_name)).toEqual(["Bea", "Zoe", "Abe"]);
    });
});
