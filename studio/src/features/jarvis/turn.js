export const GROUP_ORDER = ["understand", "retrieve", "act", "respond"];
export const GROUP_LABEL = {
    understand: "Understand",
    retrieve: "Retrieve",
    act: "Act",
    respond: "Respond",
};
export function newBubble(partial) {
    return {
        text: "",
        createdAt: new Date().toISOString(),
        status: "done",
        frames: [],
        evidence: [],
        handoffs: [],
        errors: [],
        persisted: false,
        ...partial,
    };
}
function handoffContact(frames) {
    for (const f of frames) {
        if (f.type !== "tool" || !/agent\.ask|ask_agent|handoff/i.test(f.name))
            continue;
        const a = f.args ?? {};
        const v = a.contact ?? a.to ?? a.agent ?? a.display_name;
        if (typeof v === "string" && v)
            return v;
    }
    return null;
}
export function fromMessage(m) {
    const frames = (m.meta?.trace ?? []);
    const handoffs = m.meta?.handoff_thread_id
        ? [{ contact: handoffContact(frames) ?? "another Jarvis", question: "", answer: null, thread_id: m.meta.handoff_thread_id }]
        : [];
    return newBubble({
        id: m.message_id,
        role: m.author.kind === "member" ? "me" : "jarvis",
        text: m.text,
        createdAt: m.created_at,
        status: m.status === "failed" ? "failed" : m.author.kind === "member" ? "sent" : "done",
        frames,
        evidence: m.meta?.evidence ?? [],
        handoffs,
        persisted: true,
    });
}
/** Join streamed sentence frames into readable text. */
export function joinSentence(prev, next) {
    if (!prev)
        return next.replace(/^\s+/, "");
    if (!next)
        return prev;
    if (/\s$/.test(prev) || /^\s/.test(next))
        return prev + next;
    return `${prev} ${next}`;
}
function mergeEvidence(a, b) {
    const seen = new Set(a.map((e) => `${e.kind}|${e.ref}`));
    const out = [...a];
    for (const e of b) {
        const k = `${e.kind}|${e.ref}`;
        if (!seen.has(k)) {
            seen.add(k);
            out.push(e);
        }
    }
    return out;
}
/** Fold one SSE frame into the in-flight Jarvis reply. Never throws on odd frames. */
export function applyEvent(b, e) {
    switch (e?.type) {
        case "trace":
        case "tool":
            return { ...b, frames: [...b.frames, e] };
        case "evidence":
            return { ...b, evidence: mergeEvidence(b.evidence, Array.isArray(e.items) ? e.items : []) };
        case "handoff":
            return { ...b, handoffs: [...b.handoffs, { contact: e.contact, question: e.question, answer: e.answer ?? null, thread_id: e.thread_id }] };
        case "sentence":
            return { ...b, text: joinSentence(b.text, String(e.text ?? "")) };
        case "error":
            return { ...b, errors: [...b.errors, String(e.message || "Unknown error")] };
        case "final": {
            const msg = e.message;
            let handoffs = b.handoffs;
            const threadId = msg?.meta?.handoff_thread_id;
            if (threadId) {
                handoffs = handoffs.length
                    ? handoffs.map((h) => (h.thread_id ? h : { ...h, thread_id: threadId }))
                    : [{ contact: handoffContact(b.frames) ?? "another Jarvis", question: "", answer: null, thread_id: threadId }];
            }
            return {
                ...b,
                id: msg?.message_id ?? b.id,
                createdAt: msg?.created_at ?? b.createdAt,
                text: e.reply || msg?.text || b.text,
                status: "done",
                stats: e.stats ?? b.stats,
                frames: b.frames.length ? b.frames : (msg?.meta?.trace ?? []),
                evidence: mergeEvidence(b.evidence, msg?.meta?.evidence ?? []),
                handoffs,
                persisted: !!msg || b.persisted,
            };
        }
        default:
            return b;
    }
}
const UNDERSTAND = /(identity|speaker|intent|classif|policy|access|guard|route|router|parse|understand|lang|safety)/i;
const RETRIEVE = /(retriev|memory|knowledge|brain|project|search|recall|context|lookup|fetch|rag|calendar|home_state|state)/i;
const RESPOND = /(reply|respond|compose|answer|speak|tts|stream|final|format|render|persist|deliver)/i;
export function groupForNode(node, spec) {
    const hit = spec?.nodes.find((n) => n.id === node);
    if (hit)
        return hit.group;
    if (UNDERSTAND.test(node))
        return "understand";
    if (RESPOND.test(node))
        return "respond";
    if (RETRIEVE.test(node))
        return "retrieve";
    return "act";
}
export function humanize(id) {
    const s = id.replace(/[_.-]+/g, " ").trim();
    return s ? s[0].toUpperCase() + s.slice(1) : id;
}
export function labelForNode(node, spec) {
    return spec?.nodes.find((n) => n.id === node)?.label ?? humanize(node);
}
export function buildSteps(frames, spec) {
    const steps = [];
    const open = new Map();
    for (const f of frames) {
        if (f.type === "trace") {
            let st = open.get(f.node);
            if (!st || (f.status === "start" && st.status !== "start")) {
                st = {
                    key: `${f.node}#${steps.length}`,
                    node: f.node,
                    label: labelForNode(f.node, spec),
                    group: groupForNode(f.node, spec),
                    status: f.status,
                    detail: "",
                    ms: null,
                    tools: [],
                };
                steps.push(st);
                open.set(f.node, st);
            }
            st.status = f.status;
            if (f.detail)
                st.detail = f.detail;
            if (typeof f.ms === "number" && (f.status === "done" || f.status === "error"))
                st.ms = f.ms;
        }
        else if (f.type === "tool") {
            let host;
            for (let i = steps.length - 1; i >= 0; i--)
                if (steps[i].status === "start") {
                    host = steps[i];
                    break;
                }
            host ??= steps[steps.length - 1];
            if (!host) {
                host = { key: `tools#${steps.length}`, node: "tools", label: "Tools", group: "act", status: "done", detail: "", ms: null, tools: [] };
                steps.push(host);
            }
            host.tools.push(f);
        }
    }
    return steps;
}
export function groupTotals(steps) {
    const t = { understand: 0, retrieve: 0, act: 0, respond: 0 };
    for (const s of steps)
        if (s.ms)
            t[s.group] += s.ms;
    return t;
}
export function totalMs(steps, stats) {
    for (const k of ["total_ms", "ms", "elapsed_ms", "latency_ms"]) {
        const v = stats?.[k];
        if (typeof v === "number" && v > 0)
            return v;
    }
    const sum = steps.reduce((acc, s) => acc + (s.ms ?? 0), 0);
    return sum > 0 ? sum : null;
}
export function toolCount(steps) {
    return steps.reduce((n, s) => n + s.tools.length, 0);
}
/** Compact one-line rendering of tool args: `project=commontasks window=yesterday`. */
export function formatArgs(args, max = 90) {
    if (!args)
        return "";
    const parts = Object.entries(args).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
    const s = parts.join(" ");
    return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}
