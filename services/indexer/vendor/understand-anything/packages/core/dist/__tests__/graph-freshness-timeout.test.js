import { describe, expect, it, vi } from "vitest";
const { execFileMock } = vi.hoisted(() => ({
    execFileMock: vi.fn(),
}));
vi.mock("child_process", async () => {
    const actual = await vi.importActual("child_process");
    return {
        ...actual,
        execFile: execFileMock,
    };
});
import { getGraphFreshness } from "../staleness.js";
describe("getGraphFreshness timeout handling", () => {
    it("returns an explicit unknown result when Git times out", async () => {
        execFileMock.mockImplementation((_file, _args, _options, callback) => {
            callback(Object.assign(new Error("timed out"), {
                code: null,
                killed: true,
                signal: "SIGTERM",
            }), Buffer.alloc(0), Buffer.alloc(0));
        });
        await expect(getGraphFreshness("/project", { graphCommitHash: "abc123" })).resolves.toEqual({
            status: "unknown",
            reason: "git-command-timeout",
            graphCommitHash: "abc123",
        });
    });
});
//# sourceMappingURL=graph-freshness-timeout.test.js.map