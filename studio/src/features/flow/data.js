// Data source for Flow: companion-api (proxy of agent-runtime /v1/agent/flows*), or fixtures.
import { api } from "../../api/client";
const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";
const fx = () => import("./fixtures");
/** The latest persisted Jarvis reply that carries a trace (used when no live turn is held). */
export function pickRecentTrace(messages) {
    for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i];
        if (m.author.kind !== "member" && m.meta?.trace?.length) {
            const q = messages.slice(0, i).reverse().find((x) => x.author.kind === "member")?.text ?? null;
            return { frames: m.meta.trace, at: m.created_at, question: q };
        }
    }
    return null;
}
export const flowData = {
    flows: () => (FIXTURES ? fx().then((f) => f.flows()) : api.flows()),
    flow: (name) => (FIXTURES ? fx().then((f) => f.flow(name)) : api.flow(name)),
    recentTrace: async (signal) => {
        const res = FIXTURES ? await fx().then((f) => f.recentMessages()) : await api.messages("jarvis", { limit: 20 }, signal);
        return pickRecentTrace(res.messages);
    },
};
