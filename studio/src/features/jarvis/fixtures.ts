// Offline fixtures for the Jarvis chat (VITE_STUDIO_FIXTURES=true only).
import type { FlowEvent, FlowSpec, Message } from "../../api/contracts";

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("Aborted", "AbortError"));
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(t); reject(new DOMException("Aborted", "AbortError")); }, { once: true });
  });

const ago = (h: number) => new Date(Date.now() - h * 3600_000).toISOString();

export function flowSpec(): FlowSpec {
  return {
    name: "studio",
    version: 1,
    description: "Studio chat: the voice chain plus project tools, trace and evidence.",
    nodes: [
      { id: "identity", type: "identity", label: "Identify speaker", group: "understand", config: {} },
      { id: "intent", type: "intent", label: "Understand intent", group: "understand", config: {} },
      { id: "policy", type: "policy", label: "Check access & policy", group: "understand", config: {} },
      { id: "memory", type: "memory", label: "Recall memory", group: "retrieve", config: {} },
      { id: "projects", type: "project_knowledge", label: "Project knowledge", group: "retrieve", config: {} },
      { id: "home", type: "home_context", label: "Home & calendar context", group: "retrieve", config: {} },
      { id: "tools", type: "tool_router", label: "Run tools", group: "act", config: {} },
      { id: "agent_ask", type: "agent_ask", label: "Ask another Jarvis", group: "act", config: {} },
      { id: "compose", type: "compose", label: "Compose reply", group: "respond", config: {} },
      { id: "stream", type: "stream", label: "Stream sentences", group: "respond", config: {} },
    ],
    edges: [
      { from: "identity", to: "intent" }, { from: "intent", to: "policy" },
      { from: "policy", to: "memory" }, { from: "policy", to: "projects" }, { from: "policy", to: "home" },
      { from: "memory", to: "tools" }, { from: "projects", to: "tools" }, { from: "home", to: "tools" },
      { from: "tools", to: "agent_ask" }, { from: "tools", to: "compose" }, { from: "agent_ask", to: "compose" },
      { from: "compose", to: "stream" },
    ],
  };
}

const robin = { kind: "member" as const, id: "robin", display: "Robin" };
const jarvis = { kind: "jarvis" as const, id: "jarvis", display: "Robin's Jarvis" };

const HISTORY: Message[] = [
  {
    message_id: "m_001", thread_id: "jarvis", author: robin, created_at: ago(26), status: "sent", meta: {},
    text: "What changed in UnderstandYourProjects this week?",
  },
  {
    message_id: "m_002", thread_id: "jarvis", author: jarvis, created_at: ago(25.99), status: "delivered",
    text:
      "Mostly the **indexer**. You added a key-file classifier and paginated the manifest:\n\n" +
      "- `services/indexer/src/key_file_classifier.py`: new, tiers files A/B/C before enrichment\n" +
      "- `services/indexer/src/knowledge_search.py`: synthesis now cites UA knowledge items\n" +
      "- `services/indexer/src/ua_bridge.py`: retry on connector read errors\n\n" +
      "Nothing changed under `studio/` until today.",
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
      evidence: [
        { kind: "project", label: "UnderstandYourProjects", ref: "UnderstandYourProjects" },
        { kind: "file", label: "key_file_classifier.py", ref: "services/indexer/src/key_file_classifier.py" },
        { kind: "file", label: "knowledge_search.py", ref: "services/indexer/src/knowledge_search.py" },
      ],
    },
  },
];

export async function messages(opts: { limit?: number; before?: string }): Promise<{ messages: Message[]; has_more: boolean }> {
  await wait(450);
  if (opts.before) return { messages: [], has_more: false };
  return { messages: HISTORY, has_more: false };
}

type Script = FlowEvent[];

function scriptFor(text: string): Script {
  const t = text.toLowerCase();
  const head: Script = [
    { type: "trace", node: "identity", status: "start", detail: "", ms: 0 },
    { type: "trace", node: "identity", status: "done", detail: "robin · owner · studio", ms: 4 },
    { type: "trace", node: "intent", status: "start", detail: "", ms: 0 },
  ];
  if (t.includes("fail") || t.includes("offline")) {
    return [
      ...head,
      { type: "trace", node: "intent", status: "error", detail: "agent-runtime timeout", ms: 8000 },
      { type: "error", message: "Agent runtime unreachable (companion-api → :8868 timed out)" },
      { type: "final", reply: "Jarvis is not reachable right now.", stats: {} },
    ];
  }
  if (t.includes("felix")) {
    return [
      ...head,
      { type: "trace", node: "intent", status: "done", detail: "agent.ask", ms: 52 },
      { type: "trace", node: "policy", status: "done", detail: "share card: calendar (free/busy) only", ms: 3 },
      { type: "trace", node: "memory", status: "skip", detail: "not needed", ms: 0 },
      { type: "trace", node: "home", status: "done", detail: "your calendar: free after 14:00 tomorrow", ms: 96 },
      { type: "trace", node: "agent_ask", status: "start", detail: "", ms: 0 },
      { type: "tool", name: "agent.ask", args: { contact: "Felix's Jarvis", transport: "town" }, ok: true, summary: "answered in 2.1 s" },
      { type: "handoff", contact: "Felix's Jarvis", question: "Is Felix free tomorrow?", answer: "Felix is free 15:00–17:00 tomorrow.", thread_id: "t_felix" },
      { type: "trace", node: "agent_ask", status: "done", detail: "verified contact · town", ms: 2140 },
      { type: "trace", node: "compose", status: "start", detail: "", ms: 0 },
      { type: "sentence", text: "I asked Felix's Jarvis." },
      { type: "sentence", text: "He is free from **15:00 to 17:00** tomorrow, and you are free after 14:00." },
      { type: "sentence", text: "Want me to propose 15:00?" },
      { type: "trace", node: "compose", status: "done", detail: "", ms: 640 },
      { type: "final", reply: "I asked Felix's Jarvis. He is free from **15:00 to 17:00** tomorrow, and you are free after 14:00. Want me to propose 15:00?", stats: { total_ms: 3020 } },
    ];
  }
  if (t.includes("light")) {
    return [
      ...head,
      { type: "trace", node: "intent", status: "done", detail: "home.lights_on", ms: 33 },
      { type: "trace", node: "policy", status: "done", detail: "clinic · light.turn_on allowed", ms: 2 },
      { type: "trace", node: "home", status: "done", detail: "clinic: 3 lights off", ms: 58 },
      { type: "trace", node: "tools", status: "start", detail: "", ms: 0 },
      { type: "tool", name: "ha.call_service", args: { domain: "light", service: "turn_on", area: "clinic" }, ok: true, summary: "3 entities on" },
      { type: "trace", node: "tools", status: "done", detail: "", ms: 410 },
      { type: "trace", node: "compose", status: "start", detail: "", ms: 0 },
      { type: "sentence", text: "Done. The three clinic lights are on." },
      { type: "trace", node: "compose", status: "done", detail: "", ms: 120 },
      { type: "final", reply: "Done. The three clinic lights are on.", stats: { total_ms: 660 } },
    ];
  }
  if (t.includes("analyze") || t.includes("analyse")) {
    return [
      ...head,
      { type: "trace", node: "intent", status: "done", detail: "project.sync", ms: 47 },
      { type: "trace", node: "policy", status: "done", detail: "owner only: allowed", ms: 2 },
      { type: "trace", node: "projects", status: "done", detail: "registry: ~/code is analyzed", ms: 64 },
      { type: "trace", node: "tools", status: "start", detail: "", ms: 0 },
      { type: "tool", name: "project.sync", args: { path: "~/code/adhd-agent", device: "Robin's MacBook Pro" }, ok: true, summary: "job j_7c1e queued" },
      { type: "trace", node: "tools", status: "done", detail: "", ms: 380 },
      { type: "evidence", items: [{ kind: "project", label: "adhd-agent", ref: "adhd-agent" }] },
      { type: "trace", node: "compose", status: "start", detail: "", ms: 0 },
      { type: "sentence", text: "Started analyzing `~/code/adhd-agent`." },
      { type: "sentence", text: "It sits inside `~/code`, so it will be analyzed as a **child of code** and get its overview as context." },
      { type: "sentence", text: "You can watch progress under Devices." },
      { type: "trace", node: "compose", status: "done", detail: "", ms: 210 },
      { type: "final", reply: "Started analyzing `~/code/adhd-agent`. It sits inside `~/code`, so it will be analyzed as a **child of code** and get its overview as context. You can watch progress under [Devices](#/devices/adhd-agent).", stats: { total_ms: 720 } },
    ];
  }
  return [
    ...head,
    { type: "trace", node: "intent", status: "done", detail: "project.status", ms: 39 },
    { type: "trace", node: "policy", status: "done", detail: "R1 allowed", ms: 2 },
    { type: "trace", node: "memory", status: "done", detail: "2 notes", ms: 71 },
    { type: "trace", node: "projects", status: "start", detail: "", ms: 0 },
    { type: "tool", name: "project.status", args: { project: "commontasks", window: "yesterday" }, ok: true, summary: "6 files changed" },
    { type: "trace", node: "projects", status: "done", detail: "digest + activity", ms: 188 },
    { type: "evidence", items: [
      { kind: "project", label: "commontasks", ref: "commontasks" },
      { kind: "file", label: "backend/app/scheduler.py", ref: "commontasks/backend/app/scheduler.py" },
      { kind: "file", label: "web/src/TaskBoard.tsx", ref: "commontasks/web/src/TaskBoard.tsx" },
      { kind: "brain", label: "note: recurring tasks", ref: "brain://robin/notes/recurring-tasks" },
    ] },
    { type: "trace", node: "tools", status: "skip", detail: "no action needed", ms: 0 },
    { type: "trace", node: "compose", status: "start", detail: "", ms: 0 },
    { type: "sentence", text: "Yesterday in **commontasks** you worked on recurring tasks:" },
    { type: "sentence", text: "\n\n- the scheduler now expands weekly rules (`backend/app/scheduler.py`)\n- the task board shows the next occurrence (`web/src/TaskBoard.tsx`)\n- 4 smaller edits in tests and fixtures\n\n" },
    { type: "sentence", text: "Your note from Tuesday says timezone handling is still open." },
    { type: "trace", node: "compose", status: "done", detail: "", ms: 870 },
    { type: "final", reply: "Yesterday in **commontasks** you worked on recurring tasks:\n\n- the scheduler now expands weekly rules (`backend/app/scheduler.py`)\n- the task board shows the next occurrence (`web/src/TaskBoard.tsx`)\n- 4 smaller edits in tests and fixtures\n\nYour note from Tuesday says timezone handling is still open.", stats: { total_ms: 1180 } },
  ];
}

export async function chat(text: string, onEvent: (e: FlowEvent) => void, signal?: AbortSignal): Promise<void> {
  await wait(250, signal);
  for (const e of scriptFor(text)) {
    const pause = e.type === "sentence" ? 380 : e.type === "trace" && e.status === "start" ? 260 : e.type === "tool" ? 520 : 140;
    await wait(pause, signal);
    if (e.type === "final") {
      const now = new Date().toISOString();
      onEvent({
        ...e,
        message: {
          message_id: `m_${Math.random().toString(36).slice(2, 8)}`, thread_id: "jarvis", author: jarvis, text: e.reply,
          created_at: now, status: "delivered", meta: { handoff_thread_id: text.toLowerCase().includes("felix") ? "t_felix" : undefined },
        },
      });
    } else onEvent(e);
  }
}
