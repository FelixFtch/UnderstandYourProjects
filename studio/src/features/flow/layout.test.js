// @vitest-environment node
import { describe, expect, it } from "vitest";
import { pickRecentTrace } from "./data";
import { columns, edgePath, nodeRuns, traversed } from "./layout";
const spec = {
    name: "studio", version: 1,
    nodes: [
        { id: "identity", type: "identity", label: "Identify", group: "understand", config: {} },
        { id: "projects", type: "pk", label: "Projects", group: "retrieve", config: {} },
        { id: "tools", type: "tools", label: "Tools", group: "act", config: {} },
        { id: "compose", type: "compose", label: "Compose", group: "respond", config: {} },
    ],
    edges: [{ from: "identity", to: "projects" }, { from: "projects", to: "tools" }, { from: "tools", to: "compose" }, { from: "projects", to: "compose" }],
};
describe("flow layout", () => {
    it("groups nodes into the four columns in order", () => {
        expect(columns(spec).map((c) => [c.group, c.nodes.map((n) => n.id)])).toEqual([
            ["understand", ["identity"]], ["retrieve", ["projects"]], ["act", ["tools"]], ["respond", ["compose"]],
        ]);
    });
    it("summarizes runs and lights only edges whose ends ran", () => {
        const frames = [
            { type: "trace", node: "identity", status: "done", detail: "robin", ms: 3 },
            { type: "trace", node: "projects", status: "start", detail: "", ms: 0 },
            { type: "tool", name: "project.status", args: {}, ok: true, summary: "6 files" },
            { type: "trace", node: "projects", status: "done", detail: "digest", ms: 120 },
            { type: "trace", node: "tools", status: "skip", detail: "", ms: 0 },
            { type: "trace", node: "compose", status: "done", detail: "", ms: 700 },
        ];
        const runs = nodeRuns(frames);
        expect(runs.projects).toMatchObject({ status: "done", ms: 120, detail: "digest" });
        expect(runs.projects.tools).toHaveLength(1);
        expect([...traversed(spec.edges, runs)].sort()).toEqual(["identity->projects", "projects->compose"]);
    });
    it("draws forward, same-column and backward edges", () => {
        const a = { x: 0, y: 0, w: 100, h: 40 };
        expect(edgePath(a, { x: 200, y: 0, w: 100, h: 40 })).toMatch(/^M 100 20 C/);
        expect(edgePath(a, { x: 0, y: 60, w: 100, h: 40 })).toBe("M 50 40 L 50 60");
        expect(edgePath(a, { x: 0, y: 300, w: 100, h: 40 })).toMatch(/^M 100 20 C/);
        expect(edgePath({ x: 200, y: 0, w: 100, h: 40 }, a)).toMatch(/^M 250 40 C/);
    });
    it("picks the latest traced reply from history", () => {
        const r = pickRecentTrace([
            { message_id: "1", thread_id: "jarvis", author: { kind: "member", id: "r", display: "R" }, text: "q1", created_at: "2026-10-10T00:00:00Z", status: "sent", meta: {} },
            { message_id: "2", thread_id: "jarvis", author: { kind: "jarvis", id: "j", display: "J" }, text: "a1", created_at: "2026-10-10T00:00:01Z", status: "delivered", meta: { trace: [{ type: "trace", node: "x", status: "done", detail: "", ms: 1 }] } },
            { message_id: "3", thread_id: "jarvis", author: { kind: "member", id: "r", display: "R" }, text: "q2", created_at: "2026-10-10T00:00:02Z", status: "sent", meta: {} },
            { message_id: "4", thread_id: "jarvis", author: { kind: "jarvis", id: "j", display: "J" }, text: "a2", created_at: "2026-10-10T00:00:03Z", status: "delivered", meta: {} },
        ]);
        expect(r).toMatchObject({ question: "q1", at: "2026-10-10T00:00:01Z" });
        expect(pickRecentTrace([])).toBeNull();
    });
});
