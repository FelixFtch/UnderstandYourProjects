// @vitest-environment node
import { describe, expect, it } from "vitest";
import { ancestors, buildForest, descendantIds, predictRelation, relationSentence, treemapCells, visibleRows } from "./tree";
function p(id, path, extra = {}) {
    return {
        project_id: id, device_id: "d1", root_name: id, path, parent_id: null, children: [], status: "analyzed", analyzed_at: null,
        stats: { files: 10, summarized: 0, nodes: 0, edges: 0, languages: [] }, tiers: { A: 0, B: 0, C: 0, gate: 0 }, embedded_roots: [], ...extra,
    };
}
const projects = [
    p("code", "/Users/r/code", { stats: { files: 100, summarized: 0, nodes: 0, edges: 0, languages: [] } }),
    p("ct", "/Users/r/code/commontasks", { parent_id: "code", stats: { files: 40, summarized: 0, nodes: 0, edges: 0, languages: [] } }),
    p("ctb", "/Users/r/code/commontasks/backend", { parent_id: "ct", stats: { files: 15, summarized: 0, nodes: 0, edges: 0, languages: [] } }),
    p("uyp", "/Users/r/code/UYP", { parent_id: "code", device_id: "d2", stats: { files: 30, summarized: 0, nodes: 0, edges: 0, languages: [] } }),
    p("docs", "/Users/r/Documents"),
];
describe("buildForest", () => {
    it("uses the server tree and drops unknown ids, lifting their children", () => {
        const f = buildForest({
            projects,
            tree: [{ project_id: "code", children: [{ project_id: "ghost", children: [{ project_id: "ct", children: [{ project_id: "ctb", children: [] }] }] }, { project_id: "uyp", children: [] }] }],
        });
        expect(f.roots).toEqual(["code", "docs"]); // docs was not in the tree → placed as a root
        expect(f.children.get("code")).toEqual(["ct", "uyp"]);
        expect(f.parent.get("ctb")).toBe("ct");
        expect(ancestors(f, "ctb").map((x) => x.project_id)).toEqual(["code", "ct"]);
        expect(descendantIds(f, "code").sort()).toEqual(["ct", "ctb", "uyp"]);
    });
    it("falls back to parent_id (any order) and breaks cycles", () => {
        const f = buildForest({ projects: [...projects].reverse(), tree: [] });
        expect(new Set(f.roots)).toEqual(new Set(["code", "docs"]));
        expect(f.parent.get("ctb")).toBe("ct");
        const cyc = buildForest({ projects: [p("a", "/a", { parent_id: "b" }), p("b", "/b", { parent_id: "a" })], tree: [] });
        expect(cyc.roots).toHaveLength(1);
        expect(cyc.byId.size).toBe(2);
        expect([...cyc.parent.values()].filter((x) => x === null)).toHaveLength(1);
    });
    it("handles empty / missing input", () => {
        expect(buildForest(undefined).roots).toEqual([]);
    });
});
describe("visibleRows", () => {
    const f = buildForest({ projects, tree: [] });
    it("respects expansion with depth", () => {
        expect(visibleRows(f, new Set()).map((r) => r.project.project_id)).toEqual(["code", "docs"]);
        const rows = visibleRows(f, new Set(["code", "ct"]));
        expect(rows.map((r) => [r.project.project_id, r.depth])).toEqual([["code", 0], ["ct", 1], ["ctb", 2], ["uyp", 1], ["docs", 0]]);
        expect(rows[0]).toMatchObject({ childCount: 2, expanded: true });
    });
    it("filters by device but keeps ancestors as context", () => {
        const rows = visibleRows(f, new Set(), (x) => x.device_id === "d2");
        expect(rows.map((r) => [r.project.project_id, r.match])).toEqual([["code", false], ["uyp", true]]);
    });
});
describe("predictRelation", () => {
    it("finds the deepest parent and top-most children", () => {
        const child = predictRelation("/Users/r/code/commontasks/web/", projects);
        expect(child.parent?.project_id).toBe("ct");
        expect(relationSentence(child)).toMatch(/child of ct/);
        const parent = predictRelation("/Users/r", projects);
        expect(parent.parent).toBeNull();
        expect(parent.children.map((x) => x.project_id).sort()).toEqual(["code", "docs"]);
        expect(relationSentence(parent)).toMatch(/parent of/);
        expect(predictRelation("/Users/r/code", projects).existing?.project_id).toBe("code");
        expect(relationSentence(predictRelation("/tmp/new", projects))).toBe("Will be a new top-level folder.");
    });
    it("understands ~ paths and device scoping", () => {
        expect(predictRelation("~/code/adhd-agent", projects).parent?.project_id).toBe("code");
        expect(predictRelation("/Users/r/code/UYP/sub", projects, "d1").parent?.project_id).toBe("code");
        expect(predictRelation("/Users/r/code/UYP/sub", projects, "d2").parent?.project_id).toBe("uyp");
    });
    it("does not treat a name prefix as containment", () => {
        expect(predictRelation("/Users/r/code-old", projects).parent).toBeNull();
    });
});
describe("treemapCells", () => {
    it("nests two levels and computes uncovered files", () => {
        const f = buildForest({ projects, tree: [] });
        const cells = treemapCells(f, f.roots);
        expect(cells.map((c) => c.id)).toEqual(["code", "docs"]);
        const code = cells[0];
        expect(code.children.map((c) => [c.id, c.files])).toEqual([["ct", 40], ["uyp", 30]]);
        expect(code.own).toBe(30);
        expect(code.children[0].children).toEqual([]); // depth capped at 2
    });
});
