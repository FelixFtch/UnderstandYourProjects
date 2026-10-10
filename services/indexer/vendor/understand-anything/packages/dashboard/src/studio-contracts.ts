import type { KnowledgeGraph } from "@understand-anything/core/types";

/**
 * These are read-only projections for Studio. Identity, ownership, grants,
 * revocation, and audit decisions remain owned by HomeHub.
 */
export type ConnectionState =
  | "current"
  | "stale"
  | "partial"
  | "offline"
  | "failed"
  | "revoked"
  | "unsupported";

export type EvidenceKind = "fact" | "structure" | "inference" | "unavailable";

export type IndexJobPhase =
  | "discovered"
  | "authorized"
  | "queued"
  | "running"
  | "staged"
  | "published"
  | "blocked"
  | "retry_wait"
  | "offline"
  | "revoked"
  | "failed";

export interface ProjectCounts {
  files: number;
  nodes: number;
  relations: number;
  layers: number;
}

export interface ProjectSummary {
  projectId: string;
  sourceId?: string;
  name: string;
  description: string;
  languages: string[];
  frameworks: string[];
  counts: ProjectCounts;
  entryPoints: string[];
  /** Server-published knowledge epoch/version. The graph schema version is separate. */
  knowledgeVersion?: string;
  schemaVersion?: string;
  sourceEpoch?: string;
  freshness: ConnectionState;
  updatedAt: string;
  /** Server-projected visibility; this is never a client-side permission check. */
  visibility?: "private" | "group" | "shared";
  grantEpoch?: string;
  policyDigest?: string;
  auditId?: string;
}

export interface KnowledgeHealth {
  state: ConnectionState;
  knowledgeVersion?: string;
  sourceEpoch?: string;
  coverage: {
    filesIndexed: number;
    filesAuthorized?: number;
    parseFailures?: number;
  };
  lastSuccessfulAt?: string;
  connectorStatus: ConnectionState;
  reason?: string;
}

export interface EvidenceRef {
  evidenceId: string;
  projectId: string;
  sourceId?: string;
  knowledgeVersion?: string;
  sourceEpoch?: string;
  locator: {
    path?: string;
    lineStart?: number;
    lineEnd?: number;
    symbol?: string;
  };
  kind: EvidenceKind;
  summary: string;
  score?: number;
  freshness: ConnectionState;
  visibility?: "private" | "group" | "shared";
  producingJarvis?: string;
  auditId?: string;
}

export interface IndexJob {
  jobId: string;
  projectId: string;
  sourceId?: string;
  phase: IndexJobPhase;
  /** The query service always publishes `processed`; `total` is null when unbounded/unknown. */
  progress?: { processed: number; total?: number | null };
  knowledgeVersion?: string;
  error?: string;
  startedAt?: string;
  finishedAt?: string;
  /** Persisted-job timestamps published by the index service (query_api._job_projection). */
  createdAt?: string;
  updatedAt?: string;
  publishedAt?: string;
  reason?: string;
  sourceEpoch?: string;
  auditId?: string;
}

/** A server-projected HomeHub context. Studio can display it, but cannot mint or widen it. */
export interface AccessContextProjection {
  principalId: string;
  sessionId: string;
  jarvisNodeId: string;
  displayLabel?: string;
  audience?: "private" | "owner_group" | "external_group" | "shared";
  groupId?: string;
  groupLabel?: string;
  projectScopes: string[];
  sourceScopes: string[];
  allowedOperations?: Array<"retrieve" | "cite" | "handoff">;
  redactionReason?: string;
  issuedAt?: string;
  grantEpoch: string;
  policyDigest: string;
  expiresAt: string;
  auditId: string;
  revoked: boolean;
  /** Optional HomeHub validation result. Studio must not infer authorization from UI state. */
  validation?: "active" | "expired" | "revoked" | "unknown";
}

export interface SourceSummary {
  sourceId: string;
  label: string;
  kind: "local" | "nas" | "github" | "device" | "graph";
  state: ConnectionState;
  detail: string;
  lastSyncAt?: string;
  /** Optional counts; the current query service embeds grants in `detail` text only. */
  grantsActive?: number;
  knowledgeItems?: number;
}

/** Read-only projections for the Agent Box and multi-connector surfaces. */
export type PairingState = "discovered" | "pairing" | "paired" | "offline" | "revoked";

export interface AgentNodeSummary {
  nodeId: string;
  label: string;
  transport: "lan" | "cloudflare" | "local" | "unknown";
  pairing: PairingState;
  lastSeen?: string;
  capabilities: string[];
  connectorIds: string[];
  grantEpoch?: string;
  auditId?: string;
}

export interface ConnectorSummary {
  connectorId: string;
  nodeId: string;
  kind: "local" | "nas" | "github" | "device";
  label: string;
  state: ConnectionState;
  manifestState: "ready" | "pending" | "unavailable";
  sourceIds: string[];
  sourceEpoch?: string;
  grantEpoch?: string;
  auditId?: string;
}

/** Public NandaTown metadata; it is not a HomeHub grant or a source listing. */
export interface PeerJarvisSummary {
  peerId: string;
  nodeId: string;
  displayLabel: string;
  handle?: string;
  transport: "nandatown";
  trust: "advertised" | "invited" | "verified" | "revoked";
  status: "available" | "recent" | "offline";
  lastSeen?: string;
  capabilities: string[];
  advertisedProjectCount?: number;
}

export interface GroupMemberProjection {
  memberId: string;
  nodeId: string;
  displayLabel: string;
  status: "pending" | "active" | "offline" | "revoked";
  projectScopes: string[];
  sourceScopes: string[];
  grantEpoch?: string;
  expiresAt?: string;
  auditId?: string;
}

export interface StudioSnapshot {
  project: ProjectSummary;
  health: KnowledgeHealth;
  evidence: EvidenceRef[];
  jobs: IndexJob[];
  sources: SourceSummary[];
  /** Optional server projections. Empty means the adapter has not published them. */
  agentNodes?: AgentNodeSummary[];
  connectors?: ConnectorSummary[];
  peers?: PeerJarvisSummary[];
  access?: AccessContextProjection;
  /** Identifies whether evidence came from the service or the graph-only fallback. */
  evidenceOrigin: "service" | "graph-fallback";
}

/**
 * Keeps the current static graph viewer useful while the read-only Studio API
 * is being implemented. The resulting state is deliberately `partial` so a
 * loaded graph is never presented as synchronized source truth.
 */
export function createStudioSnapshotFromGraph(graph: KnowledgeGraph): StudioSnapshot {
  const files = graph.nodes.filter((node) => node.type === "file").length;
  const entryPoints = graph.nodes
    .filter((node) => node.domainMeta?.entryPoint)
    .map((node) => node.name)
    .slice(0, 4);
  const projectId = `graph:${graph.project.name}`;
  return {
    project: {
      projectId,
      name: graph.project.name,
      description: graph.project.description,
      languages: graph.project.languages,
      frameworks: graph.project.frameworks,
      counts: { files, nodes: graph.nodes.length, relations: graph.edges.length, layers: graph.layers.length },
      entryPoints,
      schemaVersion: graph.version,
      freshness: "partial",
      updatedAt: graph.project.analyzedAt,
      // A graph snapshot has no HomeHub audience decision. Keep visibility
      // unknown until the access projection supplies it.
    },
    health: {
      state: "partial",
      coverage: { filesIndexed: files },
      lastSuccessfulAt: graph.project.analyzedAt,
      connectorStatus: "unsupported",
      reason: "The current viewer has a graph snapshot; connector freshness and HomeHub context are not attached yet.",
    },
    evidence: [],
    evidenceOrigin: "graph-fallback",
    // A graph file is not an IndexJob record. Leave job history unavailable
    // until the index service publishes real phases and progress.
    jobs: [],
    sources: [
      { sourceId: "graph-snapshot", label: "Current graph snapshot", kind: "graph", state: "partial", detail: `${graph.nodes.length} nodes · schema ${graph.version} · commit ${graph.project.gitCommitHash || "unavailable"}` },
      { sourceId: "nas", label: "NAS connector", kind: "nas", state: "unsupported", detail: "Waiting for a HomeHub-owned source grant" },
      { sourceId: "github", label: "GitHub connector", kind: "github", state: "unsupported", detail: "Waiting for repository manifest and source scope" },
    ],
  };
}
