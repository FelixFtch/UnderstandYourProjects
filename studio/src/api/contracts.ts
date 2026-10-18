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

// HomeHub-owned devices are intentionally separate from Connector devices.
// HomeHub remains the authority for ownership, policy, revocation, and audit;
// Studio only renders this projection and sends governed action requests.
export type HomeDeviceCapability = "read_state" | "turn_on" | "turn_off" | string;

export interface HomeDevice {
  homeDeviceId: string;
  providerId: string;
  displayName: string;
  roomId?: string;
  kind?: string;
  capabilities: HomeDeviceCapability[];
  availability: "online" | "offline" | "unknown" | "stale" | "revoked" | string;
  projectionState?: string;
  observedAt?: string | null;
  state?: { power?: string; [key: string]: unknown } | null;
}

export interface HomeDeviceProjection {
  status: string;
  schema_version: string;
  provider?: string;
  providerDetail?: Record<string, unknown>;
  state: string;
  readOnly: boolean;
  controlEnabled: boolean;
  reason?: string;
  lastSyncedAt?: string | null;
  catalogEpoch?: string;
  devices: HomeDevice[];
}

export interface HomeDeviceActionResult {
  status: string;
  schema_version?: string;
  homeDeviceId?: string;
  allowed?: boolean;
  executed?: boolean;
  state?: Record<string, unknown> | null;
  reasonCode?: string;
  auditRef?: string | Record<string, unknown> | null;
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

/** Bounded UA structure projection returned through the authenticated Studio BFF. */
export interface ProjectGraph {
  projectId: string;
  version?: string;
  kind?: "codebase" | "knowledge" | "design" | string;
  project: Record<string, unknown>;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  layers: Array<Record<string, unknown>>;
  tour: Array<Record<string, unknown>>;
  counts: { nodes: number; edges: number; layers: number; tour: number };
  truncated: { nodes: boolean; edges: boolean; layers: boolean; tour: boolean };
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

// ─§6b Sensors (sensor-hub via companion-api /api/sensors/*) ──────────────────
// Shapes mirror the hub on the Jetson (MQTT discovery tree → HTTP :8895);
// companion-api proxies them 1:1 behind member auth.
export type SensorCategory = "air_quality" | "presence" | "checkin" | "meeting_audio" | "lighting" | "other";

export interface SensorReading {
  entity_id?: string;
  label: string;
  value: string;
  unit?: string;
  category?: SensorCategory;
}

export interface SensorDevice {
  device_id: string;
  name: string;
  manufacturer?: string;
  model?: string;
  category: SensorCategory;
  entities: string[];
  entity_count: number;
  online: boolean;
  unavailable?: number;
  stale?: number;
  last_changed?: string | null;
  readings: SensorReading[];
  /** Virtual devices (e.g. the XVF3800 poller) instead of MQTT discovery. */
  source?: string;
  status_url?: string;
  detail_note?: string;
}

export interface SensorPlaceholder {
  category: SensorCategory;
  note: string;
}

export interface SensorDeviceList {
  devices: SensorDevice[];
  count?: number;
  placeholders?: SensorPlaceholder[];
}

/** HA-isomorphic state row. `state` is always a string; "unavailable" means offline. */
export interface SensorStateRow {
  entity_id: string;
  state: string;
  attributes: {
    friendly_name?: string;
    category?: SensorCategory;
    device_id?: string;
    unit_of_measurement?: string;
    device_class?: string;
    stale?: boolean;
  };
  last_changed?: string;
}

export interface SensorHistoryPoint {
  ts: string;
  state: string;
}

export interface SensorHistory {
  entity_id: string;
  hours: number;
  count: number;
  points: SensorHistoryPoint[];
}

// ── §6c Model mode & qwen cloud usage (companion-api, added 2026-10-14) ──────
// Local-first LLM routing. In cloud mode, turns touching personal or
// household-private data still run on the local model (privacy floor), and raw
// voice audio never leaves the house; only the two text surfaces below go to qwen.
export type ModelMode = "local" | "cloud";

/** GET /api/settings/model-mode */
export interface ModelModeSettings {
  mode: ModelMode;
  cloud_model_route: string;
  cloud_model_persona: string;
  updated_at: string; // ISO
}

/** PUT /api/settings/model-mode response: the new settings plus whether the
 * change was pushed to the voice runtime (`pushed: false` = applies on next turn). */
export interface ModelModeResult extends ModelModeSettings {
  pushed: boolean;
}

/** PUT /api/settings/model-mode body: mode plus optional model-name overrides. */
export interface ModelModeUpdate {
  mode: ModelMode;
  cloud_model_route?: string;
  cloud_model_persona?: string;
}

export interface CloudUsageBucket {
  prompt_tokens: number;
  completion_tokens: number;
  cost_yuan: number;
}

/** Which text surface the tokens were spent on: routing, persona replies, or splitting. */
export type CloudUsageSurface = "route" | "persona" | "split";

/** GET /api/studio/cloud-usage */
export interface CloudUsage {
  mode: ModelMode;
  currency: string; // "CNY"
  today: CloudUsageBucket;
  month: CloudUsageBucket;
  total: CloudUsageBucket;
  by_surface: Array<CloudUsageBucket & { surface: CloudUsageSurface }>;
  updated_at: string; // ISO
}

// ── §6d LLM providers & Studio notifications (companion-api, added 2026-10-15) ──
// Cloud mode is served by one of five vendors; keys live on the Jetson and the
// API never returns them in full — only `has_key` plus a short `key_hint`.
export type LlmProviderId = "qwen" | "openai" | "claude" | "gemini" | "deepseek" | (string & {});

export interface LlmProvider {
  id: LlmProviderId;
  label: string; // "Qwen · Alibaba Bailian"
  model: string;
  has_key: boolean;
  key_hint: string | null; // "sk-…1234" when has_key, else null
}

/** GET /api/settings/llm-providers */
export interface LlmProvidersSettings {
  active: LlmProviderId;
  providers: LlmProvider[];
  updated_at: string; // ISO
}

/** PUT /api/settings/llm-providers response: the new settings plus whether the
 * change was pushed to the voice runtime (`pushed` is only true when switching
 * the active provider — a single-provider update applies on the next turn). */
export interface LlmProvidersResult extends LlmProvidersSettings {
  pushed: boolean;
}

/** PUT /api/settings/llm-providers body: either switch the active provider, or
 * update one provider's model/key (api_key omitted = keep the stored key). */
export type LlmProvidersUpdate =
  | { active: LlmProviderId }
  | { provider: LlmProviderId; model?: string; api_key?: string };

/** GET /api/studio/notifications item. `read` is 0/1 (SQLite-style flag). */
export interface StudioNotification {
  id: number;
  ts: string; // ISO
  kind: string; // "settings" | "system" | …
  title: string;
  body: string;
  read: 0 | 1;
}

/** GET /api/studio/notifications?limit=… */
export interface NotificationList {
  items: StudioNotification[];
  unread: number;
}

/** POST /api/studio/notifications/mark-read body: everything, or specific ids. */
export type MarkReadRequest = { all: true } | { ids: number[] };

// ── §6e Voice profiles & UA analysis mode (companion-api, added 2026-10-15) ──
// A voice profile bundles the STT/LLM/TTS chain; the two builtins ("local",
// "cloud-full") are fixed, custom mixes are owner-made. The *_options lists are
// what the hub can actually serve for each link: "local" plus keyed
// providers that implement that link. For example, a provider with STT but
// no TTS is excluded from tts_options instead of creating a dead profile.
export interface VoiceProfile {
  name: string; // "local" | "cloud-full" | custom slug
  label: string; // "Local (offline)"
  stt: string; // "local" or a provider id
  llm: string;
  tts: string;
  builtin: 0 | 1; // builtins cannot be renamed or re-sectioned
}

/** GET /api/settings/voice-profiles */
export interface VoiceProfilesSettings {
  active: string;
  profiles: VoiceProfile[];
  stt_options: string[];
  llm_options: string[];
  tts_options: string[];
}

/** Which chain sections were pushed to the voice runtime on a switch. */
export interface VoicePush {
  llm: boolean;
  stt: boolean;
  tts: boolean;
}

/** PUT /api/settings/voice-profiles response: settings plus the per-section
 * push result — present only when switching `active`; saving a custom mix
 * never pushes (pushed: null). */
export interface VoiceProfilesResult extends VoiceProfilesSettings {
  pushed: VoicePush | null;
}

/** PUT /api/settings/voice-profiles body: switch the active profile, or
 * create/update a custom mix (name is the identity; builtin names rejected). */
export type VoiceProfilesUpdate =
  | { active: string }
  | { name: string; stt: string; llm: string; tts: string; label?: string };

export type UaMode = "local" | "cloud";

/** GET /api/settings/ua-mode: which engine runs Understand Anything's deep
 * analysis (Laya pre-filtering always stays local). */
export interface UaModeSettings {
  mode: UaMode;
  provider: string; // qwen | openai | claude | gemini | deepseek | grok | muse
  model: string;
}

/** PUT /api/settings/ua-mode response: `written` = the indexer config file was
 * updated (false = saved on the hub but the running indexer keeps its mode). */
export interface UaModeResult extends UaModeSettings {
  written: boolean;
}

/** PUT /api/settings/ua-mode body. For mode "local" the provider/model may be
 * omitted (the stored pair is kept). */
export interface UaModeUpdate {
  mode: UaMode;
  provider?: string;
  model?: string;
}

// ── §6f Studio receipts (Phase 0 Connector contract view, 2026-10-18) ──────
// Read-only projection of the receipt picture that exists on the hub today:
// the persisted capability-lifecycle audit ledger (issue / verify / revoke)
// merged with the volatile governed-action feed.  The frozen Phase 0 rule
// shows through the shapes: `ack` without `read_back` is never `completed`,
// and simulated executions carry execution_mode "simulated" /
// real_device false so they can never read as a real device finishing.
export type ReceiptSourceKind = "studio" | "voice" | "town" | "unknown" | (string & {});

export interface ReceiptAck {
  received: boolean;
  connector?: string | null;
}

export interface StudioReceipt {
  receipt_id: string;
  kind: "capability_lifecycle" | "device_action" | (string & {});
  requested_at: string; // ISO, second-resolution UTC "…Z"
  source: ReceiptSourceKind;
  principal: string;
  auth_level: string | null; // role of the acting member, when known
  room: string | null; // not recorded by either source yet
  capability: string; // action id or capability family
  risk: string | null; // as recorded (e.g. "low"); never invented as R-levels
  status: string; // received/awaiting_*/denied/dispatched/accepted/completed/failed/queued/expired/cancelled/dry_run
  confirmation: string | null; // "ack_only" | "read_back" | "simulated_read_back" | "ledger_entry"
  ack: ReceiptAck | null;
  read_back: Record<string, unknown> | null;
  execution_mode: "live" | "dry_run" | "simulated" | (string & {}) | null;
  real_device: boolean | null;
  error: string | null;
  audit_ref: string;
  request_id: string | null;
  remote_receipt_id: string | null; // remote chain arrives with the full Connector migration
  expires_at: string | null;
  detail: Record<string, unknown>;
}

export interface ReceiptSourceInfo {
  id: "audit_ledger" | "device_action_feed" | (string & {});
  available: boolean;
  persisted: boolean;
  label: string;
}

/** GET /api/studio/receipts */
export interface StudioReceiptList {
  status: string;
  schema_version: string;
  read_only: boolean;
  sources: ReceiptSourceInfo[];
  receipts: StudioReceipt[];
  count: number;
  next_before: string | null;
  filters_applied: Record<string, unknown>;
}

export interface ReceiptsQuery {
  limit?: number;
  before?: string;
  principal?: string;
  capability?: string;
  status?: string;
  source?: string;
  include_context_reads?: boolean;
}
