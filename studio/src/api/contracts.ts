// Typed mirror of docs/STUDIO_V2.md. Change both together.
// All endpoints live on companion-api (HomeHub) under /api/studio/* (plus /api/pair).

export type Role = "owner" | "member" | "guest";
export type Ring = "R1" | "R2" | "R3" | "R4";

// ── §2 Auth / me ────────────────────────────────────────────────────────────
export interface PairResponse {
  token: string;
  member_id: string;
  role: Role;
  display_name: string;
  device_kind?: string;
}

export interface JarvisIdentity {
  node_id: string;
  display_name: string;
  number: string; // "J-4829-1300"
  urn: string | null;
  town: { run_id: string; participant: string } | null;
}

export interface Me {
  member_id: string;
  role: Role;
  display_name: string;
  household_id: string;
  jarvis: JarvisIdentity;
  agent_box: { enrolled: boolean; box_id: string | null };
}

// ── §3 Agent flow ───────────────────────────────────────────────────────────
export type FlowGroup = "understand" | "retrieve" | "act" | "respond";

export interface FlowNodeSpec {
  id: string;
  type: string;
  label: string;
  group: FlowGroup;
  config: Record<string, unknown>;
}

export interface FlowSpec {
  name: string;
  version: number;
  description?: string;
  nodes: FlowNodeSpec[];
  edges: Array<{ from: string; to: string }>;
}

export interface EvidenceItem {
  kind: "file" | "brain" | "project";
  label: string;
  ref: string;
}

export type FlowEvent =
  | { type: "trace"; node: string; status: "start" | "done" | "skip" | "error"; detail: string; ms: number }
  | { type: "tool"; name: string; args: Record<string, unknown>; ok: boolean; summary: string }
  | { type: "evidence"; items: EvidenceItem[] }
  | { type: "handoff"; contact: string; question: string; answer: string | null; thread_id?: string }
  | { type: "sentence"; text: string }
  | { type: "final"; reply: string; stats?: Record<string, unknown>; message?: Message }
  | { type: "error"; message: string };

// ── §4 Contacts, threads, share cards ───────────────────────────────────────
export type ContactStatus = "verified" | "unverified" | "invited" | "pending_acceptance" | "blocked";
export type Transport = "town" | "a2a" | "contracts-v1";

export interface Contact {
  contact_id: string;
  display_name: string;
  urn: string;
  number: string | null;
  transport: Transport;
  status: ContactStatus;
  town: { run_id: string; participant: string } | null;
  last_seen: string | null;
  note: string;
  /** Present while status is "pending_acceptance": their invite, accepted via POST /contacts/accept. */
  invite?: { invite_code: string; card: Record<string, unknown>; expires_at: string };
}

export interface DirectoryEntry {
  urn: string;
  display_name: string;
  transport: Transport;
  town: { run_id: string; participant: string } | null;
  source: "gateway" | "town";
}

export type ThreadKind = "jarvis" | "direct" | "group";
export type AuthorKind = "member" | "jarvis" | "agent";

export interface Participant {
  kind: AuthorKind;
  id: string;
  display: string;
}

export interface Thread {
  thread_id: string; // "jarvis" for the 1:1 Jarvis chat
  kind: ThreadKind;
  title: string;
  participants: Participant[];
  last_message_at: string | null;
  last_preview: string;
  unread: number;
}

export interface Message {
  message_id: string;
  thread_id: string;
  author: Participant;
  text: string;
  created_at: string;
  status: "sent" | "delivered" | "failed" | "pending";
  meta: {
    trace?: Array<Extract<FlowEvent, { type: "trace" | "tool" }>>;
    evidence?: EvidenceItem[];
    handoff_thread_id?: string;
    shared_items?: string[];
  };
}

export interface SendResult {
  message: Message;
  replies: Message[];
  delivery: Array<{ contact_id: string; ok: boolean; error: string | null }>;
}

export interface ShareCardItem {
  item_id: string;
  category: PrivacyCategory | string;
  label: string;
  value_preview: string;
  ring: Ring;
  source: "default" | "added";
  enabled: boolean;
  locked: boolean;
}

export interface ShareCard {
  thread_id: string;
  items: ShareCardItem[];
  updated_at: string;
}

export interface ShareCardUpdate {
  items?: Array<{ item_id: string; enabled: boolean }>;
  add?: Array<{ category: string; label: string; value: string }>;
  remove?: string[];
}

// ── §5 Policy hierarchy ─────────────────────────────────────────────────────
export type PolicyDomain = "privacy" | "ha" | "schedule";
export type PrivacyCategory =
  | "profile" | "calendar" | "reminders" | "shopping" | "family_messages"
  | "projects" | "location" | "health" | "contacts";

export interface PolicyScope {
  scope: string; // "town_default" | "household" | "guest" | "member:<id>"
  label: string;
  parent: string | null;
  kind: "town" | "household" | "member" | "guest";
}

export interface PolicyTree {
  scopes: PolicyScope[];
  domains: PolicyDomain[];
}

export interface PrivacyPolicy {
  categories: Partial<Record<PrivacyCategory, { ring: Ring; share_with_agents: boolean }>>;
}

export interface HaPolicy {
  live: boolean;
  rooms: Record<string, { entities: string[]; allowed_actions: string[] }>;
  guest_actions: string[];
}

export interface SchedulePolicy {
  calendar_visibility: "private" | "household";
  agents_can_propose: boolean;
  agents_can_book: boolean;
  quiet_hours: { start: string; end: string } | null;
  reminder_lead_minutes: number;
}

export interface PolicyDoc<T = Record<string, unknown>> {
  scope: string;
  domain: PolicyDomain;
  values: Partial<T>;
  inherited: Partial<T>;
  effective: T;
  updated_at: string | null;
  updated_by: string | null;
}

// ── §6 Devices and projects ─────────────────────────────────────────────────
export interface Device {
  device_id: string;
  kind: "computer" | "nas" | "jetson" | "phone";
  label: string;
  hostname: string;
  os: string;
  connector: {
    state: "online" | "offline" | "unknown";
    watcher: string | null;
    grants: number;
    last_seen: string | null;
  } | null;
  paired_at: string | null;
  project_count: number;
}

export type ProjectStatus = "analyzed" | "analyzing" | "queued" | "stale" | "failed" | "not_analyzed";

export interface ProjectSummary {
  project_id: string;
  device_id: string | null;
  root_name: string;
  path: string;
  parent_id: string | null;
  children: string[];
  status: ProjectStatus;
  analyzed_at: string | null;
  stats: { files: number; summarized: number; nodes: number; edges: number; languages: string[] };
  tiers: { A: number; B: number; C: number; gate: number };
  embedded_roots: string[];
}

export interface ProjectTreeNode {
  project_id: string;
  children: ProjectTreeNode[];
}

export interface ProjectList {
  projects: ProjectSummary[];
  tree: ProjectTreeNode[];
}

export interface ProjectDigest {
  project: ProjectSummary;
  overview: string;
  key_files: Array<{ file: string; tier: string; purpose: string; key_points: string[] }>;
  // `embedded`: a bundled third-party project folder (e.g. a vendored upstream repo); listed last.
  areas: Array<{ folder: string; files: number; summary: string; embedded?: boolean }>;
  activity: {
    window: string;
    changed: Array<{ file: string; mtime: string; purpose: string }>;
    by_day: Array<{ date: string; count: number }>;
  };
  graph: {
    layers: Array<{ name: string; files: number }>;
    top_nodes: Array<{ name: string; type: string; file: string }>;
  };
  related: { parent: ProjectSummary | null; children: ProjectSummary[]; siblings: ProjectSummary[] };
  generated_at: string;
}

export interface ProjectAnswer {
  answer: string;
  sources: Array<{ file: string }>;
  confidence: "high" | "medium" | "low" | "none" | "unavailable";
}

export interface AnalyzeResult {
  job_id: string;
  project_id: string;
  relation: { parent_id: string | null; children: string[] };
  status: "queued";
}

export interface AnalyzeJob {
  job_id: string;
  project_id: string;
  status: "queued" | "running" | "done" | "failed";
  phase: string;
  progress: { done: number; total: number };
  log_tail: string[];
}
