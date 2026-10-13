import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { AgentNodeSummary, ConnectionState, ConnectorSummary, IndexJob, SourceSummary } from "../studio-contracts";
import { fetchIndexJobs, fetchSources, studioApiConfigured } from "../studio-api";
import { DEVICE_ADAPTER_OPTIONS } from "../device-adapters";
import "./sources-workspace.css";

type PairingState = "discovered" | "pairing" | "paired" | "offline";
type ConnectorKind = "Folder / NAS" | "GitHub repository" | "Jetson device" | "Workstation" | "ESP-NOW device adapter" | "Govee LAN device adapter" | "Matter device adapter";

/** Which data this surface is rendering right now. */
type ProjectionMode = "pending" | "live" | "stale" | "demo";

type ConnectorRecord = {
  id: string;
  label: string;
  kind: ConnectorKind;
  detail: string;
  state: ConnectionState;
  manifest: "ready" | "pending" | "unavailable";
  /** True when the record came from a server projection (live or last known). */
  projected: boolean;
  /** Server projection fields; demo records leave them unset. */
  sourceIds?: string[];
  grantEpoch?: string;
  grantsActive?: number;
  lastSyncAt?: string;
  knowledgeItems?: number;
  latestJob?: IndexJob;
};

type DeviceRecord = {
  id: string;
  label: string;
  detail: string;
  pairing: PairingState;
  lastSeen: string;
  capabilities: string[];
  connectors: ConnectorRecord[];
  transport?: string;
};

const pairingLabel: Record<PairingState, string> = {
  discovered: "Discovered · pair required",
  pairing: "HomeHub review pending",
  paired: "Paired projection",
  offline: "Offline · last seen recorded",
};

const pairingClass: Record<PairingState, string> = {
  discovered: "sw-state-discovered",
  pairing: "sw-state-pairing",
  paired: "sw-state-paired",
  offline: "sw-state-offline",
};

const modeTagClass: Record<ProjectionMode, string> = {
  pending: "sw-mode-tag sw-mode-tag-pending",
  live: "sw-mode-tag sw-mode-tag-live",
  stale: "sw-mode-tag sw-mode-tag-stale",
  demo: "sw-mode-tag sw-mode-tag-demo",
};

const modeTagText: Record<ProjectionMode, string> = {
  pending: "Contacting query API",
  live: "Live query API",
  stale: "Offline · last server projection",
  demo: "Demo fallback",
};

function SourceGlyph({ kind }: { kind: string }) {
  const mark = kind.toLowerCase().includes("github") ? "⌘" : kind.toLowerCase().includes("nas") || kind.toLowerCase().includes("folder") ? "▤" : kind.toLowerCase().includes("jetson") ? "▣" : "◈";
  return <span className="sw-source-glyph" aria-hidden="true">{mark}</span>;
}

function formatTimestamp(value: string | undefined): string {
  if (!value) return "not published";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "not published";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function stateText(state: ConnectionState | undefined): string {
  return state ? state.charAt(0).toUpperCase() + state.slice(1) : "Unknown";
}

function connectorKindLabel(kind: string): ConnectorKind {
  return kind === "github" ? "GitHub repository" : kind === "nas" ? "Folder / NAS" : kind === "device" ? "Jetson device" : "Workstation";
}

function jobPhaseLabel(job: IndexJob): string {
  return job.phase === "retry_wait" ? "Retry waiting" : job.phase.replace(/_/g, " ").replace(/^./, (value) => value.toUpperCase());
}

/** The query service currently embeds the connector's active-grant count in the source detail text. */
function grantsFromDetail(detail: string): number | undefined {
  const match = /(\d+)\s+active\s+grants?/i.exec(detail);
  return match ? Number(match[1]) : undefined;
}

function latestJobBySource(jobs: IndexJob[]): Map<string, IndexJob> {
  const map = new Map<string, IndexJob>();
  for (const job of jobs) {
    if (!job.sourceId) continue;
    const current = map.get(job.sourceId);
    if (!current || (job.updatedAt ?? job.createdAt ?? "") > (current.updatedAt ?? current.createdAt ?? "")) map.set(job.sourceId, job);
  }
  return map;
}

function knowledgeCount(source: SourceSummary, job: IndexJob | undefined, knowledgeItemsBySource: Record<string, number> | undefined): number | undefined {
  if (typeof source.knowledgeItems === "number") return source.knowledgeItems;
  const fromEvidence = knowledgeItemsBySource?.[source.sourceId];
  if (typeof fromEvidence === "number") return fromEvidence;
  if (job?.phase === "published" && typeof job.progress?.processed === "number") return job.progress.processed;
  return undefined;
}

/**
 * Offline fallback only. These cards are demo content and every surface that
 * renders them labels them as such; they never imply a HomeHub grant.
 */
function demoDevices(sources: SourceSummary[]): DeviceRecord[] {
  const nas = sources.find((source) => source.kind === "nas");
  const github = sources.find((source) => source.kind === "github");
  return [
    {
      id: "jetson-us-cf",
      label: "Jetson Agent Box",
      detail: "jetson-us-cf · Agent Box target",
      pairing: "discovered",
      lastSeen: "Discovery metadata only",
      capabilities: ["Incremental index", "GBrain route", "Evidence cache"],
      connectors: [],
    },
    {
      id: "local-graph",
      label: "Current graph viewer",
      detail: "Understand Anything · local snapshot",
      pairing: "paired",
      lastSeen: "Snapshot 2026-03-14",
      capabilities: ["Graph map", "Read-only evidence", "Project Studio"],
      connectors: [{ id: "graph-snapshot", label: "Graph snapshot", kind: "Workstation", detail: "97 nodes · local fallback", state: "partial", manifest: "ready", projected: false }],
    },
    {
      id: "source-host",
      label: "Source connector host",
      detail: "Mac / NAS / GitHub connector family",
      pairing: "pairing",
      lastSeen: "AccessContext unavailable",
      capabilities: ["Manifest preview", "Range read", "Change events"],
      connectors: [
        { id: nas?.sourceId ?? "nas", label: nas?.label ?? "NAS connector", kind: "Folder / NAS", detail: nas?.detail ?? "Waiting for source grant", state: nas?.state ?? "unsupported", manifest: "pending", projected: false },
        { id: github?.sourceId ?? "github", label: github?.label ?? "GitHub connector", kind: "GitHub repository", detail: github?.detail ?? "Waiting for repository scope", state: github?.state ?? "unsupported", manifest: "pending", projected: false },
      ],
    },
  ];
}

/** Build devices from server projections: Agent Box nodes plus their connectors, enriched by the live source list. */
function serverDevices(sources: SourceSummary[], agentNodes: AgentNodeSummary[], connectors: ConnectorSummary[], jobs: IndexJob[], knowledgeItemsBySource: Record<string, number> | undefined): DeviceRecord[] {
  const jobBySource = latestJobBySource(jobs);
  const nodes: AgentNodeSummary[] = agentNodes.length > 0
    ? agentNodes
    : [{ nodeId: "query-api-agent-box", label: "Jetson Agent Box", transport: "unknown", pairing: "discovered", capabilities: ["Incremental index", "Knowledge search", "Evidence citations"], connectorIds: [] }];
  const consumed = new Set<string>();
  const devices: DeviceRecord[] = nodes.map((node) => ({
    id: node.nodeId,
    label: node.label,
    detail: `${node.nodeId} · server projection`,
    pairing: node.pairing === "revoked" ? "offline" : node.pairing,
    lastSeen: node.lastSeen ?? "Not supplied",
    capabilities: node.capabilities,
    transport: node.transport,
    connectors: connectors
      .filter((connector) => connector.nodeId === node.nodeId)
      .map((connector) => {
        const ids = new Set<string>([connector.connectorId, ...connector.sourceIds]);
        const source = sources.find((candidate) => ids.has(candidate.sourceId));
        if (source) consumed.add(source.sourceId);
        const job = [...connector.sourceIds, connector.connectorId].map((id) => jobBySource.get(id)).find((entry) => entry !== undefined);
        return {
          id: connector.connectorId,
          label: connector.label,
          kind: connectorKindLabel(connector.kind),
          detail: `${connector.state} · ${connector.sourceIds.length} source${connector.sourceIds.length === 1 ? "" : "s"}`,
          state: connector.state,
          manifest: connector.manifestState,
          projected: true,
          sourceIds: connector.sourceIds,
          grantEpoch: connector.grantEpoch,
          grantsActive: source ? source.grantsActive ?? grantsFromDetail(source.detail) : undefined,
          lastSyncAt: source?.lastSyncAt,
          knowledgeItems: source ? knowledgeCount(source, job, knowledgeItemsBySource) : undefined,
          latestJob: job,
        };
      }),
  }));
  // Sources without a registry connector card still belong to the primary Agent Box.
  const primary = devices[0];
  for (const source of sources) {
    if (consumed.has(source.sourceId) || !primary) continue;
    primary.connectors.push({
      id: source.sourceId,
      label: source.label,
      kind: connectorKindLabel(source.kind),
      detail: source.detail,
      state: source.state,
      manifest: "pending",
      projected: true,
      sourceIds: [source.sourceId],
      grantsActive: source.grantsActive ?? grantsFromDetail(source.detail),
      lastSyncAt: source.lastSyncAt,
      knowledgeItems: knowledgeCount(source, jobBySource.get(source.sourceId), knowledgeItemsBySource),
      latestJob: jobBySource.get(source.sourceId),
    });
  }
  return devices;
}

export default function SourcesWorkspace({ sources, agentNodes, connectors, knowledgeItemsBySource, live = false }: {
  sources: SourceSummary[];
  agentNodes?: AgentNodeSummary[];
  connectors?: ConnectorSummary[];
  /** Live per-source knowledge item counts derived from the service snapshot's evidence list. */
  knowledgeItemsBySource?: Record<string, number>;
  /** True when the snapshot's evidence came from the knowledge service rather than the graph fallback. */
  live?: boolean;
}) {
  const [mode, setMode] = useState<ProjectionMode>(studioApiConfigured() ? "pending" : "demo");
  const [liveSources, setLiveSources] = useState<SourceSummary[]>([]);
  const [liveJobs, setLiveJobs] = useState<IndexJob[]>([]);
  const [jobsAccessContext, setJobsAccessContext] = useState<boolean | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [scanState, setScanState] = useState<"idle" | "scanned">("idle");
  const [connectorOpen, setConnectorOpen] = useState(false);
  const [connectorKind, setConnectorKind] = useState<ConnectorKind>("Folder / NAS");
  const [connectorLabel, setConnectorLabel] = useState("");
  const [manifestId, setManifestId] = useState<string | null>(null);
  const [draftConnectors, setDraftConnectors] = useState<Record<string, ConnectorRecord[]>>({});
  const [pairingDrafts, setPairingDrafts] = useState<Record<string, boolean>>({});
  const [notice, setNotice] = useState(studioApiConfigured() ? "Contacting the Jetson query API for live source projections…" : "No HomeHub ownership or grant has been issued in this demo.");
  const hadLiveFetch = useRef(false);

  const serverProjectionAvailable = (agentNodes?.length ?? 0) > 0 || (connectors?.length ?? 0) > 0;

  useEffect(() => {
    if (!studioApiConfigured()) return;
    const controller = new AbortController();
    let cancelled = false;
    const applyOffline = () => {
      if (cancelled) return;
      setMode(hadLiveFetch.current || serverProjectionAvailable ? "stale" : "demo");
      setNotice(`Jetson query API offline — showing ${hadLiveFetch.current || serverProjectionAvailable ? "the last known server projection" : "explicitly labeled demo content"}. No live HomeHub grant is active.`);
    };
    fetchSources(controller.signal)
      .then((result) => {
        if (cancelled) return;
        if (result) {
          hadLiveFetch.current = true;
          setLiveSources(result);
          setMode("live");
          setScanState("scanned");
          setNotice(`Live source projection loaded from the Jetson query API${live ? "" : "; knowledge evidence stays graph-derived until HomeHub supplies an AccessContext"}. Pairing and source grants still require HomeHub.`);
        } else {
          applyOffline();
        }
      })
      .catch((error) => {
        if (cancelled || (error instanceof DOMException && error.name === "AbortError")) return;
        applyOffline();
      });
    fetchIndexJobs(controller.signal)
      .then((result) => {
        if (cancelled) return;
        if (result) {
          setLiveJobs(result.jobs);
          setJobsAccessContext(result.accessContext ?? null);
        }
      })
      .catch((error) => {
        if (cancelled || (error instanceof DOMException && error.name === "AbortError")) return;
        setJobsAccessContext(null);
      });
    return () => { cancelled = true; controller.abort(); };
  }, [refreshToken, serverProjectionAvailable, live]);

  const devices = useMemo<DeviceRecord[]>(() => {
    if (mode === "demo") return demoDevices(sources);
    return serverDevices(liveSources, agentNodes ?? [], connectors ?? [], liveJobs, knowledgeItemsBySource);
  }, [mode, liveSources, liveJobs, agentNodes, connectors, knowledgeItemsBySource, sources]);

  const devicesWithDrafts = useMemo<DeviceRecord[]>(() => devices.map((device) => ({
    ...device,
    pairing: pairingDrafts[device.id] ? "pairing" : device.pairing,
    connectors: [...device.connectors, ...(draftConnectors[device.id] ?? [])],
  })), [devices, draftConnectors, pairingDrafts]);

  const selectedDevice = devicesWithDrafts.find((device) => device.id === selectedDeviceId) ?? devicesWithDrafts[0];
  const connectorCount = useMemo(() => devicesWithDrafts.reduce((total, device) => total + device.connectors.length, 0), [devicesWithDrafts]);
  const activeJobCount = useMemo(() => liveJobs.filter((job) => !["published", "blocked", "offline", "revoked", "failed"].includes(job.phase)).length, [liveJobs]);

  const scan = () => {
    if (mode !== "demo") {
      setRefreshToken((token) => token + 1);
      setNotice("Re-querying the Jetson query API for sources and IndexJob records…");
      return;
    }
    setScanState("scanned");
    setNotice("Discovery returned one Jetson offer. Pairing still requires an explicit code or QR flow and HomeHub approval.");
  };

  const requestPairing = (deviceId: string) => {
    setPairingDrafts((current) => ({ ...current, [deviceId]: true }));
    setNotice("Pairing draft created. The connector is not authorized until HomeHub returns an AccessContext projection.");
  };

  const submitConnector = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedDevice) return;
    const label = connectorLabel.trim() || connectorKind;
    const connector: ConnectorRecord = { id: `connector-${Date.now()}`, label, kind: connectorKind, detail: "Local draft · manifest preview pending", state: "unsupported", manifest: "pending", projected: false };
    setDraftConnectors((current) => ({ ...current, [selectedDevice.id]: [...(current[selectedDevice.id] ?? []), connector] }));
    setConnectorLabel("");
    setConnectorOpen(false);
    setNotice(`${label} was added to a local connector draft. HomeHub still controls source scope and revocation.`);
  };

  if (!selectedDevice) return null;

  return <section className="sw-shell" aria-label="Agent boxes and connectors">
    <div className="sw-hero">
      <div><span className="sw-kicker">AGENT BOX REGISTRY</span><h2>Pair the box, then add the sources it can understand.</h2><p>One Jetson can serve several authorized connectors. This surface shows discovery, pairing, manifest preview, and health as separate states.</p></div>
      <div className="sw-hero-actions"><button type="button" className="sw-button sw-button-primary" onClick={scan}><span aria-hidden="true">⌁</span>{scanState === "idle" ? "Find Jetson boxes" : "Scan again"}</button><button type="button" className="sw-button sw-button-quiet" onClick={() => setConnectorOpen((open) => !open)}>＋ Add connector</button></div>
    </div>
    <div className="sw-boundary"><span className="sw-boundary-mark">⌁</span><span><strong>HomeHub boundary</strong> supplies device ownership, pairing approval, grants, revocation, and audit.</span><span className="sw-boundary-state">{modeTagText[mode]}</span></div>
    <div className="sw-notice"><span aria-hidden="true">●</span>{notice}</div>
    {connectorOpen && <form className="sw-connector-form" onSubmit={submitConnector}><div><span className="sw-kicker">ADD SOURCE OR DEVICE ADAPTER</span><h3>Choose what this Agent Box may analyze or operate.</h3><p>A local draft only. HomeHub must publish an authorized adapter projection before any device read or command.</p></div><label><span>Connector type</span><select value={connectorKind} onChange={(event) => setConnectorKind(event.target.value as ConnectorKind)}><option>Folder / NAS</option><option>GitHub repository</option><option>Jetson device</option><option>Workstation</option><optgroup label="Device adapters">{DEVICE_ADAPTER_OPTIONS.map((option) => <option key={option.id}>{option.label}</option>)}</optgroup></select></label><label><span>Label or endpoint</span><input value={connectorLabel} onChange={(event) => setConnectorLabel(event.target.value)} placeholder="e.g. kitchen lights / research NAS" /></label><button type="submit" className="sw-button sw-button-primary">Create draft <span aria-hidden="true">→</span></button></form>}
    <div className="sw-layout">
      <aside className="sw-device-list" aria-label="Agent Box devices"><div className="sw-section-head"><div><span className="sw-kicker">DEVICES</span><h3>Agent Boxes</h3></div><span className={modeTagClass[mode]}>{modeTagText[mode]}</span></div><div className="sw-device-rows">{devicesWithDrafts.map((device) => <button type="button" key={device.id} className={`sw-device-row ${device.id === selectedDevice.id ? "is-selected" : ""}`} onClick={() => setSelectedDeviceId(device.id)}><span className="sw-device-mark">{device.id.startsWith("jetson") ? "▣" : "◈"}</span><span className="sw-device-copy"><strong>{device.label}</strong><small>{device.detail}</small></span><span className={`sw-state ${pairingClass[device.pairing]}`}>{device.pairing === "discovered" ? "NEW" : device.pairing === "pairing" ? "PENDING" : device.pairing === "paired" ? "READY" : "OFFLINE"}</span></button>)}</div><div className="sw-device-foot"><span className="sw-dot" />{mode === "demo" ? (scanState === "scanned" ? "1 discovery offer" : "LAN discovery optional") : mode === "live" ? `${devicesWithDrafts.length} server projection${devicesWithDrafts.length === 1 ? "" : "s"}` : "Last known projections"}<small>V1 uses explicit pairing</small></div></aside>
      <main className="sw-device-detail" aria-label={`${selectedDevice.label} detail`}><div className="sw-detail-head"><div><span className="sw-kicker">SELECTED AGENT BOX</span><h3>{selectedDevice.label}</h3><p>{selectedDevice.detail}</p></div><span className={`sw-pairing-badge ${pairingClass[selectedDevice.pairing]}`}>{pairingLabel[selectedDevice.pairing]}</span></div><div className="sw-detail-grid"><div><span className="sw-meta-label">Last seen</span><strong>{selectedDevice.lastSeen}</strong></div><div><span className="sw-meta-label">Node identity</span><strong>{selectedDevice.pairing === "paired" ? "HomeHub projection" : "Not issued"}</strong></div><div><span className="sw-meta-label">Transport</span><strong>{selectedDevice.transport ? `${selectedDevice.transport} · server projection` : selectedDevice.id === "jetson-us-cf" ? "LAN offer · Cloudflare endpoint pending" : "Local connector projection"}</strong></div><div><span className="sw-meta-label">Capabilities</span><div className="sw-tags">{selectedDevice.capabilities.map((capability) => <span key={capability}>{capability}</span>)}</div></div></div>{selectedDevice.pairing === "discovered" && <div className="sw-pair-card"><div><strong>Jetson offer found</strong><p>Use a one-time code or QR from the device. Automatic LAN discovery is only an offer; it never creates ownership.</p></div><button type="button" className="sw-button sw-button-primary" onClick={() => requestPairing(selectedDevice.id)}>Start pairing review</button></div>}{selectedDevice.pairing === "pairing" && <div className="sw-pair-card is-pending"><div><strong>Waiting for HomeHub</strong><p>Pairing draft is ready. The device remains outside the readable source set until ownership and policy are returned.</p></div><span className="sw-pending-mark">⌁</span></div>}<div className="sw-connector-heading"><div><span className="sw-kicker">CONNECTORS ON THIS BOX</span><h4>{selectedDevice.connectors.length} sources</h4></div><span>Each source gets its own manifest and grant</span></div><div className="sw-connector-list">{selectedDevice.connectors.map((connector) => <article className="sw-connector-card" key={connector.id}><SourceGlyph kind={connector.kind} /><div className="sw-connector-copy"><strong>{connector.label}</strong><small>{connector.kind} · {connector.detail}</small><div className="sw-connector-actions"><span className={`sw-connector-state sw-connector-${connector.manifest}`}>{connector.manifest === "ready" ? "Manifest available" : connector.manifest === "pending" ? "Manifest preview pending" : "Manifest unavailable"}</span><button type="button" onClick={() => setManifestId(manifestId === connector.id ? null : connector.id)}>{manifestId === connector.id ? "Close preview" : "Preview manifest"}</button></div>{connector.projected && <dl className="sw-connector-meta"><div><dt>State</dt><dd>{stateText(connector.state)}</dd></div><div><dt>Grants</dt><dd>{connector.grantsActive !== undefined ? `${connector.grantsActive} active` : "Not published"}</dd></div><div><dt>Last sync</dt><dd>{connector.lastSyncAt ? formatTimestamp(connector.lastSyncAt) : "Not published"}</dd></div><div><dt>Knowledge items</dt><dd>{connector.knowledgeItems !== undefined ? String(connector.knowledgeItems) : "Not published"}</dd></div></dl>}{manifestId === connector.id && (connector.projected ? <div className="sw-manifest-preview"><span>{connector.latestJob ? `Live IndexJob · ${jobPhaseLabel(connector.latestJob)}` : "Live projection · no IndexJob published"}</span><p>{connector.latestJob ? `Phase ${connector.latestJob.phase}${connector.latestJob.progress ? ` · ${connector.latestJob.progress.processed}${connector.latestJob.progress.total ? ` of ${connector.latestJob.progress.total}` : ""} units processed` : ""}${connector.latestJob.updatedAt ? ` · updated ${formatTimestamp(connector.latestJob.updatedAt)}` : ""}. ` : ""}{connector.grantsActive !== undefined ? `${connector.grantsActive} active grant${connector.grantsActive === 1 ? "" : "s"}` : "Grant count not published"}{connector.grantEpoch ? ` · epoch ${connector.grantEpoch}` : ""}. Last sync {formatTimestamp(connector.lastSyncAt)}.</p></div> : <div className="sw-manifest-preview"><span>Dry run only</span><p>Files, source scope, change cursor, and grant epoch will appear here after the connector API and HomeHub context are connected.</p></div>)}</div><span className={`sw-state-pill ${connector.state === "current" ? "is-current" : ""}`}>{connector.state === "current" ? "Current" : connector.state === "partial" ? "Partial" : "Pending"}</span></article>)}{selectedDevice.connectors.length === 0 && <div className="sw-empty"><span>＋</span><strong>No source connector is attached yet.</strong><p>Add NAS, GitHub, workstation, or another device after this Agent Box completes pairing.</p><button type="button" className="sw-link-button" onClick={() => setConnectorOpen(true)}>Add the first connector →</button></div>}</div></main>
    </div>
    <div className="sw-footer"><div><span className="sw-kicker">INDEXING ROUTE</span><strong>{mode === "demo" ? `${connectorCount} connector drafts · one Jetson queue` : `${liveJobs.length} IndexJob record${liveJobs.length === 1 ? "" : "s"} · ${activeJobCount} active`}</strong><p>Source discovery → HomeHub grant → manifest preview → incremental IndexJob → evidence answer.</p></div><span className="sw-footer-status">{mode === "live" ? (jobsAccessContext === false ? "No HomeHub context · jobs withheld" : "Live queue projection") : mode === "stale" ? "Offline · last queue projection" : mode === "pending" ? "Contacting query API" : "Demo · no live grant issued"}</span></div>
  </section>;
}
