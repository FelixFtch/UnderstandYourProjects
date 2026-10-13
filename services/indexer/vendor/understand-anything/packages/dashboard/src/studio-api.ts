import type {
  HomeAssistantProjection,
  HomeAutomationProjection,
  ToolCatalogProjection,
  IndexJob,
  PeerJarvisSummary,
  SourceSummary,
  StudioSnapshot,
} from "./studio-contracts";

export interface KnowledgeSearchResult {
  ok?: boolean;
  answer: string;
  sources: Array<{ file: string; match: number }>;
  confidence: "high" | "medium" | "none" | "unavailable";
  auditId?: string;
  error?: string;
  message?: string;
}

/** GET /api/sources — the Agent Box source projection for this session. */
export interface SourcesProjection {
  sources: SourceSummary[];
}

/** GET /api/index/jobs — persisted IndexJob records, already HomeHub scope-filtered. */
export interface IndexJobsProjection {
  jobs: IndexJob[];
  /** False means no HomeHub AccessContext was supplied, so an empty job list is expected. */
  accessContext?: boolean;
}

/** GET /api/nandatown/peers — public directory metadata; never a HomeHub grant. */
export interface NandatownPeersProjection {
  peers: PeerJarvisSummary[];
  metadataOnly?: boolean;
}

/** A registry group record (GET /api/groups); membership/view authority stays server-side. */
export interface GroupRecordProjection {
  group_id: string;
  name: string;
  owner_member: string;
  member_members: string[];
  knowledge_view: { project_ids: string[] | "*"; source_ids: string[] | "*" };
  town_run_id?: string | null;
  created_at?: string | null;
  grant_epoch?: string | null;
}

/** GET /api/groups — the caller's visible slice of the registry. */
export interface GroupsProjection {
  ok?: boolean;
  groups: GroupRecordProjection[];
  ownerView?: boolean;
}

/** One row of a group's local message log (send echoes + received mail). */
export interface GroupMessageRow {
  message_id: string | null;
  group_id: string;
  sender: string;
  sent_at: string | null;
  received_at?: string | null;
  text: string;
  direction: "in" | "out";
  delivery?: Array<{ to: string; ok: boolean; error?: string }>;
}

/** GET /api/groups/{id}/messages — the member-scoped local log a chat UI polls. */
export interface GroupMessagesProjection {
  ok?: boolean;
  groupId: string;
  memberId?: string;
  total?: number;
  messages: GroupMessageRow[];
}

/** POST /api/groups/{id}/messages — per-recipient fan-out results, honestly reported. */
export interface SendGroupMessageResult {
  ok?: boolean;
  groupId?: string;
  memberId?: string;
  sent?: GroupMessageRow;
  delivery?: Array<{ to: string; ok: boolean; message_id?: string; error?: string }>;
  deliveredTo?: string[];
  error?: string;
  message?: string;
}

/** Read-only Home Assistant capability projection from the HomeHub BFF. */
export type HomeAssistantProjectionResponse = HomeAssistantProjection | { homeAssistant: HomeAssistantProjection };

/** HomeHub-owned automation projection; mutation endpoints are intentionally not exposed here yet. */
export type HomeAutomationProjectionResponse = HomeAutomationProjection | { automations: HomeAutomationProjection };

export type ToolCatalogProjectionResponse = ToolCatalogProjection | { catalog: ToolCatalogProjection };

/**
 * The web client only talks to this adapter. It never calls Ollama, a
 * Connector, or HomeHub directly. In the static demo the adapter is absent and
 * the graph-only fallback remains visible as `partial`.
 */
function apiBase(): string | null {
  const configured = import.meta.env.VITE_STUDIO_API_URL as string | undefined;
  if (configured?.trim()) return configured.replace(/\/$/, "");
  if (import.meta.env.VITE_DEMO_MODE === "true") return null;
  return "";
}

async function request<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const base = apiBase();
  if (base === null) throw new Error("studio_api_not_configured");
  const response = await fetch(`${base}${path}`, { ...init, signal, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
  let body: unknown = null;
  try { body = await response.json(); } catch { /* preserve the HTTP error below */ }
  if (!response.ok) {
    const detail = body && typeof body === "object" && "message" in body ? String(body.message) : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return body as T;
}

export async function fetchStudioSnapshot(signal?: AbortSignal): Promise<StudioSnapshot | null> {
  if (apiBase() === null) return null;
  return request<StudioSnapshot>("/api/studio/snapshot", undefined, signal);
}

export async function fetchSources(signal?: AbortSignal): Promise<SourceSummary[] | null> {
  if (apiBase() === null) return null;
  const projection = await request<SourcesProjection>("/api/sources", undefined, signal);
  return Array.isArray(projection?.sources) ? projection.sources : [];
}

export async function fetchIndexJobs(signal?: AbortSignal): Promise<IndexJobsProjection | null> {
  if (apiBase() === null) return null;
  return request<IndexJobsProjection>("/api/index/jobs", undefined, signal);
}

export async function fetchNandatownPeers(signal?: AbortSignal): Promise<PeerJarvisSummary[] | null> {
  if (apiBase() === null) return null;
  const projection = await request<NandatownPeersProjection>("/api/nandatown/peers", undefined, signal);
  return Array.isArray(projection?.peers) ? projection.peers : [];
}

function unwrapHomeAssistantProjection(body: HomeAssistantProjectionResponse): HomeAssistantProjection {
  return "homeAssistant" in body ? body.homeAssistant : body;
}

function unwrapAutomationProjection(body: HomeAutomationProjectionResponse): HomeAutomationProjection {
  return "automations" in body && !Array.isArray(body.automations)
    ? body.automations
    : body as HomeAutomationProjection;
}

function unwrapToolCatalog(body: ToolCatalogProjectionResponse): ToolCatalogProjection {
  return "catalog" in body ? body.catalog : body;
}

/**
 * GET /api/studio/home-devices — curated Home Assistant entities. The route
 * belongs to HomeHub; a missing route is rendered as an unavailable provider,
 * never as a fake device list.
 */
export async function fetchHomeAssistantProjection(signal?: AbortSignal): Promise<HomeAssistantProjection | null> {
  if (apiBase() === null) return null;
  const projection = await request<HomeAssistantProjectionResponse>("/api/studio/home-devices", undefined, signal);
  return unwrapHomeAssistantProjection(projection);
}

/** GET /api/studio/automations — HomeHub scheduler summaries, read-only for now. */
export async function fetchAutomationProjection(signal?: AbortSignal): Promise<HomeAutomationProjection | null> {
  if (apiBase() === null) return null;
  const projection = await request<HomeAutomationProjectionResponse>("/api/studio/automations", undefined, signal);
  return unwrapAutomationProjection(projection);
}

/** GET /api/studio/tool-catalog — HomeHub-filtered descriptors for Studio/phone/Jetson. */
export async function fetchToolCatalog(signal?: AbortSignal): Promise<ToolCatalogProjection | null> {
  if (apiBase() === null) return null;
  const projection = await request<ToolCatalogProjectionResponse>("/api/studio/tool-catalog", undefined, signal);
  return unwrapToolCatalog(projection);
}

export async function fetchGroups(signal?: AbortSignal): Promise<GroupRecordProjection[] | null> {
  if (apiBase() === null) return null;
  const projection = await request<GroupsProjection>("/api/groups", undefined, signal);
  return Array.isArray(projection?.groups) ? projection.groups : [];
}

export async function fetchGroupMessages(groupId: string, limit = 200, signal?: AbortSignal): Promise<GroupMessagesProjection | null> {
  if (apiBase() === null) return null;
  const path = `/api/groups/${encodeURIComponent(groupId)}/messages?limit=${limit}`;
  return request<GroupMessagesProjection>(path, undefined, signal);
}

export async function sendGroupMessage(groupId: string, text: string, signal?: AbortSignal): Promise<SendGroupMessageResult> {
  const path = `/api/groups/${encodeURIComponent(groupId)}/messages`;
  return request<SendGroupMessageResult>(path, { method: "POST", body: JSON.stringify({ text }) }, signal);
}

export async function searchProjectKnowledge(query: string, projectId: string, signal?: AbortSignal): Promise<KnowledgeSearchResult> {
  return request<KnowledgeSearchResult>("/api/knowledge/search", { method: "POST", body: JSON.stringify({ query, projectId }) }, signal);
}

export function studioApiConfigured(): boolean {
  return apiBase() !== null;
}
