// Shared HTTP client for Jarvis Studio. Features call these helpers only.
// Auth: HomeHub bearer token in localStorage (pair once; it never expires). The token is
// cleared only when HomeHub's own /api/studio/me rejects it — see handleUnauthorized.
import type {
  AnalyzeJob, AnalyzeResult, CloudUsage, Contact, Device, DirectoryEntry, FlowEvent, FlowSpec, Me, Message,
  HomeDeviceActionResult, HomeDeviceProjection, LlmProvidersResult, LlmProvidersSettings, LlmProvidersUpdate,
  MarkReadRequest, ModelModeResult, ModelModeSettings, ModelModeUpdate, NotificationList,
  PairResponse, PolicyDoc, PolicyDomain, PolicyTree,
  ProjectAnswer, ProjectDigest, ProjectGraph, ProjectList, ReceiptsQuery, SendResult, SensorDeviceList,
  SensorHistory, SensorStateRow, ShareCard, ShareCardUpdate, StudioReceiptList, Thread,
  UaModeResult, UaModeSettings, UaModeUpdate, VoiceProfilesResult, VoiceProfilesSettings, VoiceProfilesUpdate,
} from "./contracts";

const TOKEN_KEY = "jarvis.studio.token";
const DEVICE_KEY = "jarvis.studio.device";

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

type AuthListener = () => void;
const authListeners = new Set<AuthListener>();
export function onAuthLost(fn: AuthListener): () => void {
  authListeners.add(fn);
  return () => authListeners.delete(fn);
}

function safeGet(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
function safeSet(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch { /* private mode: session-only auth */ }
}

let memoryToken: string | null = null;
export function getToken(): string | null { return memoryToken ?? safeGet(TOKEN_KEY); }
export function setToken(token: string | null): void { memoryToken = token; safeSet(TOKEN_KEY, token); }

function deviceId(): string {
  let id = safeGet(DEVICE_KEY);
  if (!id) {
    id = "studio-" + Math.random().toString(36).slice(2, 10);
    safeSet(DEVICE_KEY, id);
  }
  return id;
}

function apiBase(): string {
  const configured = import.meta.env.VITE_STUDIO_API_BASE as string | undefined;
  return configured ? configured.replace(/\/$/, "") : "";
}

/**
 * Pair once, stay signed in: a 401 from a feature endpoint is NOT proof that
 * the login is gone (a backend may fail for its own reasons). Only forget the
 * token after HomeHub's own identity endpoint rejects that same token.
 */
async function handleUnauthorized(path: string, token: string | null): Promise<void> {
  if (!token || getToken() !== token) return; // nothing saved, or already replaced
  let confirmed = path === "/api/studio/me";
  if (!confirmed) {
    try {
      const probe = await fetch(apiBase() + "/api/studio/me", { headers: { Authorization: `Bearer ${token}` } });
      confirmed = probe.status === 401;
    } catch {
      confirmed = false; // hub unreachable: keep the login
    }
  }
  if (confirmed && getToken() === token) {
    setToken(null);
    authListeners.forEach((fn) => fn());
  }
}

async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init.headers as Record<string, string> || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(apiBase() + path, { ...init, headers, signal });
  let body: unknown = null;
  const text = await res.text();
  if (text) { try { body = JSON.parse(text); } catch { body = text; } }
  if (res.status === 401) await handleUnauthorized(path, token);
  if (!res.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? String((body as { detail: unknown }).detail)
      : body && typeof body === "object" && "message" in body ? String((body as { message: unknown }).message)
      : `HTTP ${res.status}`;
    throw new ApiError(res.status, detail, body);
  }
  return body as T;
}

const get = <T>(p: string, s?: AbortSignal) => request<T>(p, {}, s);
const send = <T>(method: string, p: string, body?: unknown, s?: AbortSignal) =>
  request<T>(p, { method, body: body === undefined ? undefined : JSON.stringify(body) }, s);

/** POST that answers with text/event-stream; each `data:` line is one FlowEvent. */
export async function streamEvents(path: string, body: unknown, onEvent: (e: FlowEvent) => void, signal?: AbortSignal): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "text/event-stream" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(apiBase() + path, { method: "POST", headers, body: JSON.stringify(body), signal });
  if (res.status === 401) await handleUnauthorized(path, token);
  if (!res.ok || !res.body) throw new ApiError(res.status, `HTTP ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const handleLine = (raw: string) => {
    const line = raw.trim();
    if (!line.startsWith("data:")) return;
    const payload = line.slice(5).trim();
    if (!payload) return;
    try { onEvent(JSON.parse(payload) as FlowEvent); } catch { /* ignore malformed frame */ }
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n")) >= 0) {
      handleLine(buffer.slice(0, idx));
      buffer = buffer.slice(idx + 1);
    }
  }
  // flush: a last frame without a trailing newline (often the `final` frame) must not be lost
  buffer += decoder.decode();
  if (buffer) handleLine(buffer);
}

export const api = {
  // §2
  pair: (code: string) =>
    send<PairResponse>("POST", "/api/pair", { code, device_name: "Jarvis Studio", device_id: deviceId() }),
  me: (s?: AbortSignal) => get<Me>("/api/studio/me", s),
  enrollAgentBox: () => send<{ enrolled: boolean; box_id: string }>("POST", "/api/studio/agent-box/enroll", {}),

  // §3
  flows: () => get<{ flows: Array<{ name: string; description: string }> }>("/api/studio/flows"),
  flow: (name: string) => get<FlowSpec>(`/api/studio/flows/${encodeURIComponent(name)}`),

  // §4 threads
  threads: (s?: AbortSignal) => get<{ threads: Thread[] }>("/api/studio/threads", s),
  createThread: (kind: "direct" | "group", contact_ids: string[], title?: string) =>
    send<Thread>("POST", "/api/studio/threads", { kind, contact_ids, title }),
  deleteThread: (id: string) => send<{ ok: boolean }>("DELETE", `/api/studio/threads/${encodeURIComponent(id)}`),
  messages: (id: string, opts: { limit?: number; before?: string } = {}, s?: AbortSignal) => {
    const q = new URLSearchParams();
    if (opts.limit) q.set("limit", String(opts.limit));
    if (opts.before) q.set("before", opts.before);
    return get<{ messages: Message[]; has_more: boolean }>(`/api/studio/threads/${encodeURIComponent(id)}/messages?${q}`, s);
  },
  sendMessage: (id: string, text: string) =>
    send<SendResult>("POST", `/api/studio/threads/${encodeURIComponent(id)}/messages`, { text }),
  chatJarvis: (text: string, onEvent: (e: FlowEvent) => void, signal?: AbortSignal) =>
    streamEvents("/api/studio/threads/jarvis/messages", { text }, onEvent, signal),
  shareCard: (id: string) => get<ShareCard>(`/api/studio/threads/${encodeURIComponent(id)}/share-card`),
  updateShareCard: (id: string, update: ShareCardUpdate) =>
    send<ShareCard>("PUT", `/api/studio/threads/${encodeURIComponent(id)}/share-card`, update),

  // §4 contacts
  contacts: (s?: AbortSignal) => get<{ contacts: Contact[] }>("/api/studio/contacts", s),
  directory: () => get<{ entries: DirectoryEntry[] }>("/api/studio/contacts/directory"),
  addContact: (c: { urn: string; display_name: string; transport?: string; town?: DirectoryEntry["town"] }) =>
    send<Contact>("POST", "/api/studio/contacts", c),
  inviteContact: (contact_id: string) =>
    send<{ ok: boolean; delivery: { ok: boolean; error: string | null } }>("POST", "/api/studio/contacts/invite", { contact_id }),
  updateContact: (id: string, patch: Partial<Pick<Contact, "display_name" | "note" | "status">>) =>
    send<Contact>("PATCH", `/api/studio/contacts/${encodeURIComponent(id)}`, patch),
  acceptContact: (invite_code: string, card?: Record<string, unknown>) =>
    send<{ contact: Contact; delivery: { ok: boolean; error: string | null } | null }>(
      "POST", "/api/studio/contacts/accept", { invite_code, card }),
  deleteContact: (id: string) => send<{ ok: boolean }>("DELETE", `/api/studio/contacts/${encodeURIComponent(id)}`),

  // §5 policy
  policyTree: () => get<PolicyTree>("/api/studio/policy/tree"),
  policy: <T>(scope: string, domain: PolicyDomain) =>
    get<PolicyDoc<T>>(`/api/studio/policy/${encodeURIComponent(scope)}/${domain}`),
  putPolicy: <T>(scope: string, domain: PolicyDomain, values: Partial<T>) =>
    send<PolicyDoc<T>>("PUT", `/api/studio/policy/${encodeURIComponent(scope)}/${domain}`, { values }),

  // §6 devices / projects
  devices: (s?: AbortSignal) => get<{ devices: Device[] }>("/api/studio/devices", s),
  renameDevice: (id: string, label: string) => send<Device>("PATCH", `/api/studio/devices/${encodeURIComponent(id)}`, { label }),
  homeDevices: (s?: AbortSignal) => get<HomeDeviceProjection>("/api/studio/home-devices", s),
  homeDeviceAction: (homeDeviceId: string, actionId: "home.light.turn_on" | "home.light.turn_off", executionMode: "live" | "dry_run" = "live", requestId?: string) =>
    send<HomeDeviceActionResult>("POST", `/api/studio/home-devices/${encodeURIComponent(homeDeviceId)}/actions`, {
      schema_version: "homehub-device-action-request-v1",
      action_id: actionId,
      parameters: {},
      ...(requestId ? { request_id: requestId } : {}),
      execution_mode: executionMode,
    }),
  projects: (s?: AbortSignal) => get<ProjectList>("/api/studio/projects", s),
  project: (id: string, s?: AbortSignal) => get<ProjectDigest>(`/api/studio/projects/${encodeURIComponent(id)}`, s),
  projectGraph: (id: string, s?: AbortSignal) => get<ProjectGraph>(`/api/studio/projects/${encodeURIComponent(id)}/graph`, s),
  askProject: (id: string, question: string) =>
    send<ProjectAnswer>("POST", `/api/studio/projects/${encodeURIComponent(id)}/ask`, { question }),
  analyzeFolder: (path: string, device_id?: string) =>
    send<AnalyzeResult>("POST", "/api/studio/projects/analyze", { path, device_id }),
  analyzeJob: (job_id: string) => get<AnalyzeJob>(`/api/studio/projects/jobs/${encodeURIComponent(job_id)}`),

  // §6b sensors (sensor-hub behind companion-api; entity ids are hub ids)
  sensorDevices: (s?: AbortSignal) => get<SensorDeviceList>("/api/sensors/devices", s),
  sensorStates: (s?: AbortSignal) => get<SensorStateRow[]>("/api/sensors/states", s),
  sensorHistory: (entityId: string, hours = 24, s?: AbortSignal) =>
    get<SensorHistory>(`/api/sensors/entities/${encodeURIComponent(entityId)}/history?hours=${hours}`, s),

  // §6c model mode & qwen cloud usage (2026-10-14)
  modelMode: (s?: AbortSignal) => get<ModelModeSettings>("/api/settings/model-mode", s),
  putModelMode: (update: ModelModeUpdate, s?: AbortSignal) => send<ModelModeResult>("PUT", "/api/settings/model-mode", update, s),
  cloudUsage: (s?: AbortSignal) => get<CloudUsage>("/api/studio/cloud-usage", s),

  // §6d multi-vendor LLM providers & Studio notifications (2026-10-15)
  llmProviders: (s?: AbortSignal) => get<LlmProvidersSettings>("/api/settings/llm-providers", s),
  putLlmProviders: (update: LlmProvidersUpdate, s?: AbortSignal) => send<LlmProvidersResult>("PUT", "/api/settings/llm-providers", update, s),
  notifications: (limit = 20, s?: AbortSignal) => get<NotificationList>(`/api/studio/notifications?limit=${limit}`, s),
  markNotificationsRead: (req: MarkReadRequest, s?: AbortSignal) => send<{ ok: boolean }>("POST", "/api/studio/notifications/mark-read", req, s),

  // §6e voice profiles (STT/LLM/TTS chain) & UA analysis mode (2026-10-15)
  voiceProfiles: (s?: AbortSignal) => get<VoiceProfilesSettings>("/api/settings/voice-profiles", s),
  putVoiceProfiles: (update: VoiceProfilesUpdate, s?: AbortSignal) => send<VoiceProfilesResult>("PUT", "/api/settings/voice-profiles", update, s),
  uaMode: (s?: AbortSignal) => get<UaModeSettings>("/api/settings/ua-mode", s),
  putUaMode: (update: UaModeUpdate, s?: AbortSignal) => send<UaModeResult>("PUT", "/api/settings/ua-mode", update, s),

  // §6f receipts (Phase 0 Connector contract view, read-only)
  receipts: (opts: ReceiptsQuery = {}, s?: AbortSignal) => {
    const q = new URLSearchParams();
    if (opts.limit) q.set("limit", String(opts.limit));
    if (opts.before) q.set("before", opts.before);
    if (opts.principal) q.set("principal", opts.principal);
    if (opts.capability) q.set("capability", opts.capability);
    if (opts.status) q.set("status", opts.status);
    if (opts.source) q.set("source", opts.source);
    if (opts.include_context_reads) q.set("include_context_reads", "true");
    return get<StudioReceiptList>(`/api/studio/receipts?${q}`, s);
  },
};
