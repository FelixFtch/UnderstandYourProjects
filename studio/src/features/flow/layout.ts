// Flow graph layout (pure): columns by group, node run summaries, SVG edge paths.
import type { FlowGroup, FlowNodeSpec, FlowSpec } from "../../api/contracts";
import type { TraceFrame } from "./data";

export const GROUPS: FlowGroup[] = ["understand", "retrieve", "act", "respond"];

export const GROUP_INFO: Record<FlowGroup, { title: string; body: string }> = {
  understand: { title: "Understand", body: "Who is speaking, what they want, and what they may do." },
  retrieve: { title: "Retrieve", body: "Gather context: memory, project knowledge, home and calendar." },
  act: { title: "Act", body: "Use tools, control the home, ask other Jarvises." },
  respond: { title: "Respond", body: "Compose the reply and stream it back." },
};

export function columns(spec: FlowSpec | null | undefined): Array<{ group: FlowGroup; nodes: FlowNodeSpec[] }> {
  const by = new Map<FlowGroup, FlowNodeSpec[]>(GROUPS.map((g) => [g, []]));
  for (const n of spec?.nodes ?? []) (by.get(n.group) ?? by.get("act")!).push(n);
  return GROUPS.map((g) => ({ group: g, nodes: by.get(g)! }));
}

export interface NodeRun {
  status: "start" | "done" | "skip" | "error";
  ms: number | null;
  detail: string;
  tools: Array<Extract<TraceFrame, { type: "tool" }>>;
}

/** Latest run per node, with tool calls attributed to the node that was running. */
export function nodeRuns(frames: TraceFrame[]): Record<string, NodeRun> {
  const runs: Record<string, NodeRun> = {};
  const running: string[] = [];
  let last: string | null = null;
  for (const f of frames) {
    if (f.type === "trace") {
      const prev = runs[f.node];
      const fresh = !prev || (f.status === "start" && prev.status !== "start");
      const r: NodeRun = fresh ? { status: f.status, ms: null, detail: "", tools: [] } : prev;
      r.status = f.status;
      if (f.detail) r.detail = f.detail;
      if (typeof f.ms === "number" && (f.status === "done" || f.status === "error")) r.ms = f.ms;
      runs[f.node] = r;
      last = f.node;
      if (f.status === "start") running.push(f.node);
      else { const i = running.lastIndexOf(f.node); if (i >= 0) running.splice(i, 1); }
    } else {
      const host = running[running.length - 1] ?? last;
      if (host && runs[host]) runs[host].tools.push(f);
    }
  }
  return runs;
}

export const edgeKey = (e: { from: string; to: string }) => `${e.from}->${e.to}`;

/** An edge was traversed when both ends ran (not skipped) in the last turn. */
export function traversed(edges: FlowSpec["edges"], runs: Record<string, NodeRun>): Set<string> {
  const ok = (id: string) => !!runs[id] && runs[id].status !== "skip";
  return new Set(edges.filter((e) => ok(e.from) && ok(e.to)).map(edgeKey));
}

export interface Rect { x: number; y: number; w: number; h: number }

/** Cubic path between two node rects (container coordinates). */
export function edgePath(a: Rect, b: Rect): string {
  const acx = a.x + a.w / 2;
  const bcx = b.x + b.w / 2;
  const sameColumn = Math.abs(acx - bcx) < Math.min(a.w, b.w) / 2;
  if (sameColumn) {
    const gap = b.y - (a.y + a.h);
    if (gap >= 0 && gap <= 48) return `M ${acx} ${a.y + a.h} L ${bcx} ${b.y}`;
    const sx = a.x + a.w, sy = a.y + a.h / 2, ex = b.x + b.w, ey = b.y + b.h / 2;
    const bulge = 26 + Math.min(40, Math.abs(ey - sy) / 6);
    return `M ${sx} ${sy} C ${sx + bulge} ${sy}, ${ex + bulge} ${ey}, ${ex} ${ey}`;
  }
  if (bcx > acx) {
    const sx = a.x + a.w, sy = a.y + a.h / 2, ex = b.x, ey = b.y + b.h / 2;
    const dx = Math.max(18, (ex - sx) / 2);
    return `M ${sx} ${sy} C ${sx + dx} ${sy}, ${ex - dx} ${ey}, ${ex} ${ey}`;
  }
  // backwards edge: loop underneath
  const sx = a.x + a.w / 2, sy = a.y + a.h, ex = b.x + b.w / 2, ey = b.y + b.h;
  const drop = Math.max(sy, ey) + 36;
  return `M ${sx} ${sy} C ${sx} ${drop}, ${ex} ${drop}, ${ex} ${ey}`;
}
