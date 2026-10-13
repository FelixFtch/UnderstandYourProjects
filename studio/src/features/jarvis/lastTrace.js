// useLastTrace — the trace of the most recent Jarvis turn (live while it streams).
//
// CROSS-FEATURE EXCEPTION (docs/STUDIO_V2.md §7: "no feature imports another feature"):
// features/flow may import `useLastTrace` from this file, and nothing else from features/jarvis.
// This module is deliberately tiny (zustand + types only) so Flow does not pull in the chat UI.
import { create } from "zustand";
function index(frames) {
    const nodes = {};
    const ms = {};
    for (const f of frames) {
        if (f.type !== "trace")
            continue;
        nodes[f.node] = f.status;
        if (typeof f.ms === "number" && (f.status === "done" || f.status === "error"))
            ms[f.node] = f.ms;
    }
    return { nodes, ms };
}
export const useLastTrace = create((set, get) => ({
    turnId: null,
    question: null,
    startedAt: null,
    live: false,
    frames: [],
    nodes: {},
    ms: {},
    begin: (turnId, question) => set({ turnId, question, startedAt: new Date().toISOString(), live: true, frames: [], nodes: {}, ms: {} }),
    push: (frame) => {
        const frames = [...get().frames, frame];
        set({ frames, ...index(frames) });
    },
    end: () => set({ live: false }),
    seed: (turnId, question, frames, at) => {
        if (get().turnId)
            return;
        set({ turnId, question, startedAt: at, live: false, frames, ...index(frames) });
    },
}));
