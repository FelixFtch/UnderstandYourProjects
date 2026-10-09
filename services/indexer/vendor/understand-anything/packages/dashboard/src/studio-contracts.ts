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
  knowledgeVersion: string;
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
  progress?: { processed: number; total?: number };
  knowledgeVersion?: string;
  error?: string;
  startedAt?: string;
  finishedAt?: string;
}

/** A server-projected HomeHub context. Studio can display it, but cannot mint or widen it. */
export interface AccessContextProjection {
  principalId: string;
  sessionId: string;
  jarvisNodeId: string;
  projectScopes: string[];
  sourceScopes: string[];
  grantEpoch: string;
  policyDigest: string;
  expiresAt: string;
  auditId: string;
  revoked: boolean;
}

export interface SourceSummary {
  sourceId: string;
  label: string;
  kind: "local" | "nas" | "github" | "device" | "graph";
  state: ConnectionState;
  detail: string;
  lastSyncAt?: string;
}

export interface StudioSnapshot {
  project: ProjectSummary;
  health: KnowledgeHealth;
  evidence: EvidenceRef[];
  jobs: IndexJob[];
  sources: SourceSummary[];
  access?: AccessContextProjection;
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
  const evidence = graph.nodes.slice(0, 8).map((node): EvidenceRef => ({
    evidenceId: `graph-node:${node.id}`,
    projectId,
    knowledgeVersion: graph.version,
    locator: { path: node.filePath, lineStart: node.lineRange?.[0], lineEnd: node.lineRange?.[1], symbol: node.name },
    kind: node.filePath ? "structure" : "unavailable",
    summary: node.summary || "No semantic summary has been published for this graph node.",
    freshness: "partial",
  }));

  return {
    project: {
      projectId,
      name: graph.project.name,
      description: graph.project.description,
      languages: graph.project.languages,
      frameworks: graph.project.frameworks,
      counts: { files, nodes: graph.nodes.length, relations: graph.edges.length, layers: graph.layers.length },
      entryPoints,
      knowledgeVersion: graph.version,
      freshness: "partial",
      updatedAt: graph.project.analyzedAt,
      visibility: "private",
    },
    health: {
      state: "partial",
      knowledgeVersion: graph.version,
      coverage: { filesIndexed: files },
      lastSuccessfulAt: graph.project.analyzedAt,
      connectorStatus: "unsupported",
      reason: "The current viewer has a graph snapshot; connector freshness and HomeHub context are not attached yet.",
    },
    evidence,
    jobs: [{
      jobId: `graph-publish:${graph.version}`,
      projectId,
      phase: "published",
      progress: { processed: graph.nodes.length, total: graph.nodes.length },
      knowledgeVersion: graph.version,
      finishedAt: graph.project.analyzedAt,
    }],
    sources: [
      { sourceId: "graph-snapshot", label: "Current graph snapshot", kind: "graph", state: "partial", detail: `${graph.nodes.length} nodes · commit ${graph.project.gitCommitHash || "unavailable"}` },
      { sourceId: "nas", label: "NAS connector", kind: "nas", state: "unsupported", detail: "Waiting for a HomeHub-owned source grant" },
      { sourceId: "github", label: "GitHub connector", kind: "github", state: "unsupported", detail: "Waiting for repository manifest and source scope" },
    ],
  };
}
