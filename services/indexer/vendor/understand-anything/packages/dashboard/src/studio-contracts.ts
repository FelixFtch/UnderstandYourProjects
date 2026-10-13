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
  /** v3.2 anchored enrichment primary actor, e.g. "route_fast L97-L215". */
  anchorTop?: string;
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

/**
 * A deliberately small Home Assistant projection.  The Studio never receives
 * an HA token, raw service name, or an arbitrary entity id.  HomeHub maps the
 * stable `homeDeviceId` to the current HA entity and decides which actions
 * may be exposed to this audience.
 */
export type HomeAssistantProviderState = "current" | "stale" | "partial" | "offline" | "revoked" | "unsupported" | "contract_pending" | "failed";

export type HomeEntityDomain = "light" | "switch" | "sensor" | "binary_sensor" | "climate" | "media_player" | "other";

export type CuratedHomeAction =
  | "home.light.turn_on"
  | "home.light.turn_off"
  | "home.light.set_brightness"
  | "home.switch.turn_on"
  | "home.switch.turn_off";

export interface HomeDeviceCapability {
  homeDeviceId: string;
  uniqueId?: string;
  /** HomeHub-owned display label; it is never an authorization key. */
  displayName: string;
  roomId?: string;
  domain: HomeEntityDomain;
  state: string;
  availability: "online" | "offline" | "unknown";
  freshness: ConnectionState;
  lastSeenAt?: string;
  capabilities: string[];
  /** Actions are an allowlisted projection, never raw HA service calls. */
  actions?: CuratedHomeAction[];
  source: { kind: "home_assistant"; uniqueId?: string };
  projectionEpoch?: string;
  auditId?: string;
}

export interface HomeAssistantProjection {
  provider: "home_assistant";
  state: HomeAssistantProviderState;
  readOnly: boolean;
  controlEnabled: boolean;
  version?: string;
  lastSyncedAt?: string;
  reason?: string;
  devices: HomeDeviceCapability[];
  auditId?: string;
}

export type AutomationState = "enabled" | "disabled" | "paused" | "failed" | "unsupported";

export type AutomationTriggerKind = "schedule" | "event" | "project_sync" | "manual";

export interface AutomationTriggerSummary {
  kind: AutomationTriggerKind;
  label: string;
  nextRunAt?: string;
  recurrence?: string;
}

export interface HomeAutomationSummary {
  automationId: string;
  name: string;
  description?: string;
  state: AutomationState;
  trigger: AutomationTriggerSummary;
  actionLabels: string[];
  lastRunAt?: string;
  lastRunState?: "succeeded" | "failed" | "skipped" | "not_run";
  source: "homehub";
  readOnly: boolean;
  auditId?: string;
}

export interface HomeAutomationProjection {
  provider: "homehub";
  state: HomeAssistantProviderState;
  readOnly: boolean;
  reason?: string;
  updatedAt?: string;
  automations: HomeAutomationSummary[];
}

export type ToolOwner = "homehub" | "uyp" | "approved_adapter";
export type ToolKind = "knowledge" | "home" | "communication" | "system";
export type ToolOperation = "query" | "command";
export type ToolConfirmation = "none" | "owner_or_policy" | "explicit_owner";

/** Normalized capability descriptor shared by Studio, phone, and Jetson. */
export interface ToolDescriptor {
  toolId: string;
  version: string;
  displayName: string;
  description: string;
  owner: ToolOwner;
  kind: ToolKind;
  operation: ToolOperation;
  requiredScopes: string[];
  confirmation: ToolConfirmation;
  idempotency: "none" | "optional" | "required";
  freshness?: { maxAgeSeconds: number };
  availability: { state: HomeAssistantProviderState; checkedAt?: string; reason?: string };
}

export interface ToolCatalogProjection {
  catalogEpoch?: string;
  state: HomeAssistantProviderState;
  tools: ToolDescriptor[];
  updatedAt?: string;
  reason?: string;
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
  /** Optional Home Assistant capability projection supplied by HomeHub. */
  homeAssistant?: HomeAssistantProjection;
  /** Optional HomeHub-owned automation projection. */
  automations?: HomeAutomationProjection;
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
