// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { FlowEvent, FlowSpec, Message } from "../../api/contracts";
import { applyEvent, buildSteps, formatArgs, fromMessage, groupForNode, groupTotals, joinSentence, newBubble, totalMs, type TraceFrame } from "./turn";

const spec: FlowSpec = {
  name: "studio", version: 1, edges: [],
  nodes: [
    { id: "identity", type: "identity", label: "Identify speaker", group: "understand", config: {} },
    { id: "projects", type: "project_knowledge", label: "Project knowledge", group: "retrieve", config: {} },
  ],
};

describe("applyEvent", () => {
  it("folds a full stream into one reply", () => {
    const frames: FlowEvent[] = [
      { type: "trace", node: "identity", status: "start", detail: "", ms: 0 },
      { type: "trace", node: "identity", status: "done", detail: "robin", ms: 4 },
      { type: "tool", name: "project.status", args: { project: "commontasks" }, ok: true, summary: "6 files" },
      { type: "evidence", items: [{ kind: "file", label: "a.py", ref: "x/a.py" }] },
      { type: "evidence", items: [{ kind: "file", label: "a.py", ref: "x/a.py" }, { kind: "project", label: "x", ref: "x" }] },
      { type: "sentence", text: "Hello." },
      { type: "sentence", text: "World." },
      { type: "handoff", contact: "Felix's Jarvis", question: "free?", answer: "yes", thread_id: "t_felix" },
      { type: "error", message: "minor" },
    ];
    let b = newBubble({ id: "local-1", role: "jarvis", status: "streaming" });
    for (const f of frames) b = applyEvent(b, f);
    expect(b.text).toBe("Hello. World.");
    expect(b.frames).toHaveLength(3);
    expect(b.evidence).toHaveLength(2);
    expect(b.handoffs[0]).toMatchObject({ contact: "Felix's Jarvis", thread_id: "t_felix" });
    expect(b.errors).toEqual(["minor"]);
    expect(b.status).toBe("streaming");

    const final = applyEvent(b, {
      type: "final", reply: "Hello, world.", stats: { total_ms: 900 },
      message: { message_id: "m_9", thread_id: "jarvis", author: { kind: "jarvis", id: "j", display: "J" }, text: "Hello, world.", created_at: "2026-10-11T10:00:00Z", status: "delivered", meta: {} },
    });
    expect(final).toMatchObject({ id: "m_9", text: "Hello, world.", status: "done", persisted: true });
    expect(final.stats).toEqual({ total_ms: 900 });
  });

  it("ignores unknown frames and keeps streamed text when final.reply is empty", () => {
    let b = newBubble({ id: "x", role: "jarvis", status: "streaming", text: "partial" });
    b = applyEvent(b, { type: "mystery" } as unknown as FlowEvent);
    b = applyEvent(b, { type: "final", reply: "" });
    expect(b.text).toBe("partial");
    expect(b.status).toBe("done");
  });

  it("joins sentences without doubling whitespace", () => {
    expect(joinSentence("", "  Hi.")).toBe("Hi.");
    expect(joinSentence("Hi.", "There.")).toBe("Hi. There.");
    expect(joinSentence("List:", "\n\n- a")).toBe("List:\n\n- a");
  });
});

describe("buildSteps", () => {
  it("merges start/done, attributes tools to the running node, maps groups", () => {
    const frames: TraceFrame[] = [
      { type: "trace", node: "identity", status: "start", detail: "", ms: 0 },
      { type: "trace", node: "identity", status: "done", detail: "robin", ms: 4 },
      { type: "trace", node: "projects", status: "start", detail: "", ms: 0 },
      { type: "tool", name: "project.status", args: { project: "x", window: "yesterday" }, ok: true, summary: "ok" },
      { type: "trace", node: "projects", status: "done", detail: "digest", ms: 200 },
      { type: "trace", node: "ha_lights", status: "skip", detail: "", ms: 0 },
      { type: "trace", node: "compose", status: "done", detail: "", ms: 800 },
    ];
    const steps = buildSteps(frames, spec);
    expect(steps.map((s) => [s.node, s.label, s.group, s.status, s.ms])).toEqual([
      ["identity", "Identify speaker", "understand", "done", 4],
      ["projects", "Project knowledge", "retrieve", "done", 200],
      ["ha_lights", "Ha lights", "act", "skip", null],
      ["compose", "Compose", "respond", "done", 800],
    ]);
    expect(steps[1].tools.map((t) => t.name)).toEqual(["project.status"]);
    expect(groupTotals(steps)).toEqual({ understand: 4, retrieve: 200, act: 0, respond: 800 });
    expect(totalMs(steps)).toBe(1004);
    expect(totalMs(steps, { total_ms: 1500 })).toBe(1500);
  });

  it("a repeated node after it finished becomes a new step; orphan tools get a host", () => {
    const steps = buildSteps([
      { type: "tool", name: "x.y", args: {}, ok: false, summary: "" },
      { type: "trace", node: "tools", status: "start", detail: "", ms: 0 },
      { type: "trace", node: "tools", status: "done", detail: "", ms: 5 },
      { type: "trace", node: "tools", status: "start", detail: "", ms: 0 },
    ]);
    expect(steps).toHaveLength(3);
    expect(steps[0].tools).toHaveLength(1);
    expect(steps[2].status).toBe("start");
  });

  it("falls back to name heuristics without a spec", () => {
    expect(groupForNode("intent")).toBe("understand");
    expect(groupForNode("memory_recall")).toBe("retrieve");
    expect(groupForNode("compose")).toBe("respond");
    expect(groupForNode("ha.call_service")).toBe("act");
    expect(groupForNode("projects", spec)).toBe("retrieve");
  });

  it("formats tool args compactly", () => {
    expect(formatArgs({ project: "commontasks", window: "yesterday", n: 3 })).toBe("project=commontasks window=yesterday n=3");
    expect(formatArgs({ long: "x".repeat(200) }, 20)).toHaveLength(20);
  });
});

describe("fromMessage", () => {
  it("maps history messages, including the handoff thread", () => {
    const m: Message = {
      message_id: "m_1", thread_id: "jarvis", author: { kind: "jarvis", id: "j", display: "J" }, text: "Asked.", created_at: "2026-10-10T08:00:00Z", status: "delivered",
      meta: { trace: [{ type: "tool", name: "agent.ask", args: { contact: "Felix's Jarvis" }, ok: true, summary: "" }], handoff_thread_id: "t_felix" },
    };
    const b = fromMessage(m);
    expect(b).toMatchObject({ id: "m_1", role: "jarvis", status: "done", persisted: true });
    expect(b.handoffs).toEqual([{ contact: "Felix's Jarvis", question: "", answer: null, thread_id: "t_felix" }]);
    expect(fromMessage({ ...m, author: { kind: "member", id: "robin", display: "Robin" }, meta: {} }).role).toBe("me");
  });
});
