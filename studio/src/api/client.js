const TOKEN_KEY = "jarvis.studio.token";
const DEVICE_KEY = "jarvis.studio.device";
export class ApiError extends Error {
    status;
    body;
    constructor(status, message, body) {
        super(message);
        this.status = status;
        this.body = body;
    }
}
const authListeners = new Set();
export function onAuthLost(fn) {
    authListeners.add(fn);
    return () => authListeners.delete(fn);
}
function safeGet(key) {
    try {
        return window.localStorage.getItem(key);
    }
    catch {
        return null;
    }
}
function safeSet(key, value) {
    try {
        if (value === null)
            window.localStorage.removeItem(key);
        else
            window.localStorage.setItem(key, value);
    }
    catch { /* private mode: session-only auth */ }
}
let memoryToken = null;
export function getToken() { return memoryToken ?? safeGet(TOKEN_KEY); }
export function setToken(token) { memoryToken = token; safeSet(TOKEN_KEY, token); }
function deviceId() {
    let id = safeGet(DEVICE_KEY);
    if (!id) {
        id = "studio-" + Math.random().toString(36).slice(2, 10);
        safeSet(DEVICE_KEY, id);
    }
    return id;
}
function apiBase() {
    const configured = import.meta.env.VITE_STUDIO_API_BASE;
    return configured ? configured.replace(/\/$/, "") : "";
}
/**
 * Pair once, stay signed in: a 401 from a feature endpoint is NOT proof that
 * the login is gone (a backend may fail for its own reasons). Only forget the
 * token after HomeHub's own identity endpoint rejects that same token.
 */
async function handleUnauthorized(path, token) {
    if (!token || getToken() !== token)
        return; // nothing saved, or already replaced
    let confirmed = path === "/api/studio/me";
    if (!confirmed) {
        try {
            const probe = await fetch(apiBase() + "/api/studio/me", { headers: { Authorization: `Bearer ${token}` } });
            confirmed = probe.status === 401;
        }
        catch {
            confirmed = false; // hub unreachable: keep the login
        }
    }
    if (confirmed && getToken() === token) {
        setToken(null);
        authListeners.forEach((fn) => fn());
    }
}
async function request(path, init = {}, signal) {
    const headers = { "Content-Type": "application/json", ...(init.headers || {}) };
    const token = getToken();
    if (token)
        headers.Authorization = `Bearer ${token}`;
    const res = await fetch(apiBase() + path, { ...init, headers, signal });
    let body = null;
    const text = await res.text();
    if (text) {
        try {
            body = JSON.parse(text);
        }
        catch {
            body = text;
        }
    }
    if (res.status === 401)
        await handleUnauthorized(path, token);
    if (!res.ok) {
        const detail = body && typeof body === "object" && "detail" in body ? String(body.detail)
            : body && typeof body === "object" && "message" in body ? String(body.message)
                : `HTTP ${res.status}`;
        throw new ApiError(res.status, detail, body);
    }
    return body;
}
const get = (p, s) => request(p, {}, s);
const send = (method, p, body, s) => request(p, { method, body: body === undefined ? undefined : JSON.stringify(body) }, s);
/** POST that answers with text/event-stream; each `data:` line is one FlowEvent. */
export async function streamEvents(path, body, onEvent, signal) {
    const headers = { "Content-Type": "application/json", Accept: "text/event-stream" };
    const token = getToken();
    if (token)
        headers.Authorization = `Bearer ${token}`;
    const res = await fetch(apiBase() + path, { method: "POST", headers, body: JSON.stringify(body), signal });
    if (res.status === 401)
        await handleUnauthorized(path, token);
    if (!res.ok || !res.body)
        throw new ApiError(res.status, `HTTP ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const handleLine = (raw) => {
        const line = raw.trim();
        if (!line.startsWith("data:"))
            return;
        const payload = line.slice(5).trim();
        if (!payload)
            return;
        try {
            onEvent(JSON.parse(payload));
        }
        catch { /* ignore malformed frame */ }
    };
    for (;;) {
        const { value, done } = await reader.read();
        if (done)
            break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n")) >= 0) {
            handleLine(buffer.slice(0, idx));
            buffer = buffer.slice(idx + 1);
        }
    }
    // flush: a last frame without a trailing newline (often the `final` frame) must not be lost
    buffer += decoder.decode();
    if (buffer)
        handleLine(buffer);
}
export const api = {
    // §2
    pair: (code) => send("POST", "/api/pair", { code, device_name: "Jarvis Studio", device_id: deviceId() }),
    me: (s) => get("/api/studio/me", s),
    enrollAgentBox: () => send("POST", "/api/studio/agent-box/enroll", {}),
    // §3
    flows: () => get("/api/studio/flows"),
    flow: (name) => get(`/api/studio/flows/${encodeURIComponent(name)}`),
    // §4 threads
    threads: (s) => get("/api/studio/threads", s),
    createThread: (kind, contact_ids, title) => send("POST", "/api/studio/threads", { kind, contact_ids, title }),
    deleteThread: (id) => send("DELETE", `/api/studio/threads/${encodeURIComponent(id)}`),
    messages: (id, opts = {}, s) => {
        const q = new URLSearchParams();
        if (opts.limit)
            q.set("limit", String(opts.limit));
        if (opts.before)
            q.set("before", opts.before);
        return get(`/api/studio/threads/${encodeURIComponent(id)}/messages?${q}`, s);
    },
    sendMessage: (id, text) => send("POST", `/api/studio/threads/${encodeURIComponent(id)}/messages`, { text }),
    chatJarvis: (text, onEvent, signal) => streamEvents("/api/studio/threads/jarvis/messages", { text }, onEvent, signal),
    shareCard: (id) => get(`/api/studio/threads/${encodeURIComponent(id)}/share-card`),
    updateShareCard: (id, update) => send("PUT", `/api/studio/threads/${encodeURIComponent(id)}/share-card`, update),
    // §4 contacts
    contacts: (s) => get("/api/studio/contacts", s),
    directory: () => get("/api/studio/contacts/directory"),
    addContact: (c) => send("POST", "/api/studio/contacts", c),
    inviteContact: (contact_id) => send("POST", "/api/studio/contacts/invite", { contact_id }),
    updateContact: (id, patch) => send("PATCH", `/api/studio/contacts/${encodeURIComponent(id)}`, patch),
    acceptContact: (invite_code, card) => send("POST", "/api/studio/contacts/accept", { invite_code, card }),
    deleteContact: (id) => send("DELETE", `/api/studio/contacts/${encodeURIComponent(id)}`),
    // §5 policy
    policyTree: () => get("/api/studio/policy/tree"),
    policy: (scope, domain) => get(`/api/studio/policy/${encodeURIComponent(scope)}/${domain}`),
    putPolicy: (scope, domain, values) => send("PUT", `/api/studio/policy/${encodeURIComponent(scope)}/${domain}`, { values }),
    // §6 devices / projects
    devices: (s) => get("/api/studio/devices", s),
    renameDevice: (id, label) => send("PATCH", `/api/studio/devices/${encodeURIComponent(id)}`, { label }),
    homeDevices: (s) => get("/api/studio/home-devices", s),
    homeDeviceAction: (homeDeviceId, actionId, executionMode = "live", requestId) => send("POST", `/api/studio/home-devices/${encodeURIComponent(homeDeviceId)}/actions`, {
        schema_version: "homehub-device-action-request-v1",
        action_id: actionId,
        parameters: {},
        ...(requestId ? { request_id: requestId } : {}),
        execution_mode: executionMode,
    }),
    projects: (s) => get("/api/studio/projects", s),
    project: (id, s) => get(`/api/studio/projects/${encodeURIComponent(id)}`, s),
    projectGraph: (id, s) => get(`/api/studio/projects/${encodeURIComponent(id)}/graph`, s),
    askProject: (id, question) => send("POST", `/api/studio/projects/${encodeURIComponent(id)}/ask`, { question }),
    analyzeFolder: (path, device_id) => send("POST", "/api/studio/projects/analyze", { path, device_id }),
    analyzeJob: (job_id) => get(`/api/studio/projects/jobs/${encodeURIComponent(job_id)}`),
    // §6b sensors (sensor-hub behind companion-api; entity ids are hub ids)
    sensorDevices: (s) => get("/api/sensors/devices", s),
    sensorStates: (s) => get("/api/sensors/states", s),
    sensorHistory: (entityId, hours = 24, s) => get(`/api/sensors/entities/${encodeURIComponent(entityId)}/history?hours=${hours}`, s),
    // §6c model mode & qwen cloud usage (2026-10-14)
    modelMode: (s) => get("/api/settings/model-mode", s),
    putModelMode: (update, s) => send("PUT", "/api/settings/model-mode", update, s),
    cloudUsage: (s) => get("/api/studio/cloud-usage", s),
    // §6d multi-vendor LLM providers & Studio notifications (2026-10-15)
    llmProviders: (s) => get("/api/settings/llm-providers", s),
    putLlmProviders: (update, s) => send("PUT", "/api/settings/llm-providers", update, s),
    notifications: (limit = 20, s) => get(`/api/studio/notifications?limit=${limit}`, s),
    markNotificationsRead: (req, s) => send("POST", "/api/studio/notifications/mark-read", req, s),
    // §6e voice profiles (STT/LLM/TTS chain) & UA analysis mode (2026-10-15)
    voiceProfiles: (s) => get("/api/settings/voice-profiles", s),
    putVoiceProfiles: (update, s) => send("PUT", "/api/settings/voice-profiles", update, s),
    uaMode: (s) => get("/api/settings/ua-mode", s),
    putUaMode: (update, s) => send("PUT", "/api/settings/ua-mode", update, s),
    // §6f receipts (Phase 0 Connector contract view, read-only)
    receipts: (opts = {}, s) => {
        const q = new URLSearchParams();
        if (opts.limit)
            q.set("limit", String(opts.limit));
        if (opts.before)
            q.set("before", opts.before);
        if (opts.principal)
            q.set("principal", opts.principal);
        if (opts.capability)
            q.set("capability", opts.capability);
        if (opts.status)
            q.set("status", opts.status);
        if (opts.source)
            q.set("source", opts.source);
        if (opts.include_context_reads)
            q.set("include_context_reads", "true");
        return get(`/api/studio/receipts?${q}`, s);
    },
};
