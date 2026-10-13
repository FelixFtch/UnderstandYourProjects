// Offline fixtures for Flow (VITE_STUDIO_FIXTURES=true only).
import { ApiError } from "../../api/client";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const STUDIO = {
    name: "studio",
    version: 1,
    description: "Studio chat: the voice chain plus project tools, trace and evidence.",
    nodes: [
        { id: "identity", type: "identity", label: "Identify speaker", group: "understand", config: { source: "bearer token" } },
        { id: "intent", type: "intent", label: "Understand intent", group: "understand", config: { model: "qwen2.5-7b", catalog: "studio" } },
        { id: "policy", type: "policy", label: "Check access & policy", group: "understand", config: { rings: ["R1", "R2", "R3"] } },
        { id: "memory", type: "memory", label: "Recall memory", group: "retrieve", config: { store: "gbrain" } },
        { id: "projects", type: "project_knowledge", label: "Project knowledge", group: "retrieve", config: { tools: ["project.list", "project.status", "project.ask"] } },
        { id: "home", type: "home_context", label: "Home & calendar context", group: "retrieve", config: {} },
        { id: "tools", type: "tool_router", label: "Run tools", group: "act", config: { port: "HomeHubPort (composite)" } },
        { id: "agent_ask", type: "agent_ask", label: "Ask another Jarvis", group: "act", config: { transport: "agent-gateway" } },
        { id: "compose", type: "compose", label: "Compose reply", group: "respond", config: {} },
        { id: "stream", type: "stream", label: "Stream sentences", group: "respond", config: { frames: ["sentence", "evidence", "final"] } },
    ],
    edges: [
        { from: "identity", to: "intent" }, { from: "intent", to: "policy" },
        { from: "policy", to: "memory" }, { from: "policy", to: "projects" }, { from: "policy", to: "home" },
        { from: "memory", to: "tools" }, { from: "projects", to: "tools" }, { from: "home", to: "tools" },
        { from: "tools", to: "agent_ask" }, { from: "tools", to: "compose" }, { from: "agent_ask", to: "compose" },
        { from: "compose", to: "stream" },
    ],
};
const VOICE = {
    name: "voice",
    version: 1,
    description: "The live voice path (ADR-0027 parity).",
    nodes: [
        { id: "identity", type: "identity", label: "Identify speaker", group: "understand", config: { source: "voiceprint" } },
        { id: "intent", type: "intent", label: "Understand intent", group: "understand", config: {} },
        { id: "route", type: "router", label: "Route action", group: "understand", config: {} },
        { id: "memory", type: "memory", label: "Recall memory", group: "retrieve", config: {} },
        { id: "home", type: "home_context", label: "Home & calendar context", group: "retrieve", config: {} },
        { id: "tools", type: "tool_router", label: "Run tools", group: "act", config: {} },
        { id: "compose", type: "compose", label: "Compose reply", group: "respond", config: {} },
        { id: "tts", type: "tts", label: "Speak", group: "respond", config: { voice: "jarvis-en" } },
    ],
    edges: [
        { from: "identity", to: "intent" }, { from: "intent", to: "route" }, { from: "route", to: "memory" }, { from: "route", to: "home" },
        { from: "memory", to: "tools" }, { from: "home", to: "tools" }, { from: "tools", to: "compose" }, { from: "compose", to: "tts" },
    ],
};
export async function flows() {
    await wait(250);
    return { flows: [{ name: "studio", description: STUDIO.description ?? "" }, { name: "voice", description: VOICE.description ?? "" }] };
}
export async function flow(name) {
    await wait(380);
    if (name === "studio")
        return STUDIO;
    if (name === "voice")
        return VOICE;
    throw new ApiError(404, `Unknown flow ${name}`);
}
export async function recentMessages() {
    await wait(300);
    const at = new Date(Date.now() - 26 * 3600_000).toISOString();
    return {
        has_more: false,
        messages: [
            { message_id: "m_001", thread_id: "jarvis", author: { kind: "member", id: "robin", display: "Robin" }, text: "What changed in UnderstandYourProjects this week?", created_at: at, status: "sent", meta: {} },
            {
                message_id: "m_002", thread_id: "jarvis", author: { kind: "jarvis", id: "jarvis", display: "Robin's Jarvis" }, text: "Mostly the indexer…", created_at: at, status: "delivered",
                meta: {
                    trace: [
                        { type: "trace", node: "identity", status: "done", detail: "robin · owner", ms: 3 },
                        { type: "trace", node: "intent", status: "done", detail: "project.status", ms: 41 },
                        { type: "trace", node: "policy", status: "done", detail: "R1 allowed", ms: 2 },
                        { type: "trace", node: "projects", status: "start", detail: "", ms: 0 },
                        { type: "tool", name: "project.status", args: { project: "UnderstandYourProjects", window: "this_week" }, ok: true, summary: "14 files changed in 5 days" },
                        { type: "trace", node: "projects", status: "done", detail: "digest + activity", ms: 212 },
                        { type: "trace", node: "compose", status: "done", detail: "", ms: 980 },
                    ],
                },
            },
        ],
    };
}
