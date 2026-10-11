// Jarvis chat state. Module-level (zustand) so a streaming turn survives navigating away:
// switch to Flow mid-turn and the nodes keep lighting up.
import { create } from "zustand";
import { ApiError } from "../../api/client";
import type { FlowSpec } from "../../api/contracts";
import { describeError } from "../../design/format";
import { jarvisData } from "./data";
import { useLastTrace } from "./lastTrace";
import { applyEvent, fromMessage, newBubble, type Bubble } from "./turn";

type LoadState = "idle" | "loading" | "ready" | "error";

interface ChatState {
  bubbles: Bubble[];
  history: LoadState;
  historyError: unknown;
  hasMore: boolean;
  loadingEarlier: boolean;
  streaming: boolean;
  draft: string;
  spec: FlowSpec | null;
  setDraft: (d: string) => void;
  loadHistory: (force?: boolean) => Promise<void>;
  loadEarlier: () => Promise<void>;
  loadSpec: () => Promise<void>;
  send: (text: string) => Promise<void>;
  stop: () => void;
  retry: (jarvisBubbleId: string) => void;
}

let seq = 0;
let controller: AbortController | null = null;
let specRequested = false;

function seedLastTrace(bubbles: Bubble[]) {
  for (let i = bubbles.length - 1; i >= 0; i--) {
    const b = bubbles[i];
    if (b.role === "jarvis" && b.frames.length) {
      const q = bubbles.slice(0, i).reverse().find((x) => x.role === "me")?.text ?? null;
      useLastTrace.getState().seed(b.id, q, b.frames, b.createdAt);
      return;
    }
  }
}

export const useChat = create<ChatState>((set, get) => {
  const update = (id: string, fn: (b: Bubble) => Bubble) =>
    set((s) => ({ bubbles: s.bubbles.map((b) => (b.id === id ? fn(b) : b)) }));

  return {
    bubbles: [],
    history: "idle",
    historyError: null,
    hasMore: false,
    loadingEarlier: false,
    streaming: false,
    draft: "",
    spec: null,

    setDraft: (draft) => set({ draft }),

    loadHistory: async (force) => {
      const st = get().history;
      if (!force && (st === "loading" || st === "ready")) return;
      set({ history: "loading", historyError: null });
      try {
        const res = await jarvisData.messages({ limit: 50 });
        const fetched = res.messages.map(fromMessage);
        const known = new Set(fetched.map((b) => b.id));
        // keep anything sent locally while history was loading
        const local = get().bubbles.filter((b) => !known.has(b.id) && !b.persisted);
        const bubbles = [...fetched, ...local];
        set({ bubbles, hasMore: res.has_more, history: "ready" });
        seedLastTrace(bubbles);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return;
        set({ history: "error", historyError: err });
      }
    },

    loadEarlier: async () => {
      const first = get().bubbles.find((b) => b.persisted);
      if (!first || get().loadingEarlier) return;
      set({ loadingEarlier: true });
      try {
        const res = await jarvisData.messages({ limit: 50, before: first.id });
        const known = new Set(get().bubbles.map((b) => b.id));
        const older = res.messages.map(fromMessage).filter((b) => !known.has(b.id));
        set((s) => ({ bubbles: [...older, ...s.bubbles], hasMore: res.has_more, loadingEarlier: false }));
      } catch (err) {
        set({ loadingEarlier: false, historyError: err });
      }
    },

    loadSpec: async () => {
      if (specRequested) return;
      specRequested = true;
      try {
        set({ spec: await jarvisData.flow() });
      } catch {
        specRequested = false; // labels fall back to heuristics; try again next visit
      }
    },

    send: async (raw) => {
      const text = raw.trim();
      if (!text || get().streaming) return;
      const n = ++seq;
      const meId = `local-me-${n}`;
      const jId = `local-jarvis-${n}`;
      const now = new Date().toISOString();
      set((s) => ({
        draft: "",
        streaming: true,
        bubbles: [
          ...s.bubbles,
          newBubble({ id: meId, role: "me", text, createdAt: now, status: "pending" }),
          newBubble({ id: jId, role: "jarvis", createdAt: now, status: "streaming", question: text }),
        ],
      }));
      const trace = useLastTrace.getState();
      trace.begin(jId, text);
      controller = new AbortController();
      let currentId = jId;
      let finished = false;
      let accepted = false;
      try {
        await jarvisData.chat(
          text,
          (e) => {
            if (!accepted) { accepted = true; update(meId, (b) => ({ ...b, status: "sent" })); }
            if (e.type === "trace" || e.type === "tool") useLastTrace.getState().push(e);
            if (e.type === "final") finished = true;
            let nextId = currentId;
            update(currentId, (b) => {
              const nb = applyEvent(b, e);
              nextId = nb.id;
              return nb;
            });
            currentId = nextId;
          },
          controller.signal,
        );
        update(meId, (b) => ({ ...b, status: "sent" }));
        if (!finished) {
          update(currentId, (b) => ({
            ...b,
            status: b.text ? "done" : "failed",
            errors: [...b.errors, "The stream ended before Jarvis finished its reply."],
          }));
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          update(meId, (b) => ({ ...b, status: "sent" }));
          update(currentId, (b) => ({ ...b, status: "stopped" }));
        } else if (err instanceof ApiError && err.status === 401) {
          /* the shell returns to the login screen */
        } else {
          const d = describeError(err, "Agent runtime");
          update(meId, (b) => ({ ...b, status: "failed" }));
          update(currentId, (b) => ({ ...b, status: "failed", errors: [...b.errors, d.detail ? `${d.title}: ${d.detail}` : d.title] }));
        }
      } finally {
        controller = null;
        set({ streaming: false });
        useLastTrace.getState().end();
      }
    },

    stop: () => controller?.abort(),

    retry: (jarvisBubbleId) => {
      const s = get();
      if (s.streaming) return;
      const idx = s.bubbles.findIndex((b) => b.id === jarvisBubbleId);
      const b = s.bubbles[idx];
      if (!b?.question) return;
      // drop the failed pair, then resend
      const prev = s.bubbles[idx - 1];
      const drop = new Set([b.id, prev?.role === "me" && !prev.persisted ? prev.id : ""]);
      set({ bubbles: s.bubbles.filter((x) => !drop.has(x.id)) });
      void get().send(b.question);
    },
  };
});
