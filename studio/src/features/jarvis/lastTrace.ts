// useLastTrace — the trace of the most recent Jarvis turn (live while it streams).
//
// CROSS-FEATURE EXCEPTION (docs/STUDIO_V2.md §7: "no feature imports another feature"):
// features/flow may import `useLastTrace` from this file, and nothing else from features/jarvis.
// This module is deliberately tiny (zustand + types only) so Flow does not pull in the chat UI.
import { create } from "zustand";
import type { FlowEvent } from "../../api/contracts";

type TraceOrTool = Extract<FlowEvent, { type: "trace" | "tool" }>;
type NodeStatus = "start" | "done" | "skip" | "error";

interface LastTraceState {
  /** id of the Jarvis reply this trace belongs to */
  turnId: string | null;
  /** the user's message that started the turn */
  question: string | null;
  startedAt: string | null;
  /** true while the turn is still streaming */
  live: boolean;
  /** raw trace/tool frames in arrival order */
  frames: TraceOrTool[];
  /** latest status per node id */
  nodes: Record<string, NodeStatus>;
  /** reported duration per node id (from done frames) */
  ms: Record<string, number>;
  begin: (turnId: string, question: string) => void;
  push: (frame: TraceOrTool) => void;
  end: () => void;
  /** seed from history (only if nothing newer is held) */
  seed: (turnId: string, question: string | null, frames: TraceOrTool[], at: string) => void;
}

function index(frames: TraceOrTool[]) {
  const nodes: Record<string, NodeStatus> = {};
  const ms: Record<string, number> = {};
  for (const f of frames) {
    if (f.type !== "trace") continue;
    nodes[f.node] = f.status;
    if (typeof f.ms === "number" && (f.status === "done" || f.status === "error")) ms[f.node] = f.ms;
  }
  return { nodes, ms };
}

export const useLastTrace = create<LastTraceState>((set, get) => ({
  turnId: null,
  question: null,
  startedAt: null,
  live: false,
  frames: [],
  nodes: {},
  ms: {},
  begin: (turnId, question) =>
    set({ turnId, question, startedAt: new Date().toISOString(), live: true, frames: [], nodes: {}, ms: {} }),
  push: (frame) => {
    const frames = [...get().frames, frame];
    set({ frames, ...index(frames) });
  },
  end: () => set({ live: false }),
  seed: (turnId, question, frames, at) => {
    if (get().turnId) return;
    set({ turnId, question, startedAt: at, live: false, frames, ...index(frames) });
  },
}));
