import type { IndexJob, PeerJarvisSummary, SourceSummary, StudioSnapshot } from "./studio-contracts";

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

export async function searchProjectKnowledge(query: string, projectId: string, signal?: AbortSignal): Promise<KnowledgeSearchResult> {
  return request<KnowledgeSearchResult>("/api/knowledge/search", { method: "POST", body: JSON.stringify({ query, projectId }) }, signal);
}

export function studioApiConfigured(): boolean {
  return apiBase() !== null;
}
