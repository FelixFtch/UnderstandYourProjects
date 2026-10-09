import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import type { ConnectionState, SourceSummary } from "../studio-contracts";
import "./sources-workspace.css";

type PairingState = "discovered" | "pairing" | "paired" | "offline";
type ConnectorKind = "Folder / NAS" | "GitHub repository" | "Jetson device" | "Workstation";

type ConnectorRecord = {
  id: string;
  label: string;
  kind: ConnectorKind;
  detail: string;
  state: ConnectionState;
  manifest: "ready" | "pending" | "unavailable";
};

type DeviceRecord = {
  id: string;
  label: string;
  detail: string;
  pairing: PairingState;
  lastSeen: string;
  capabilities: string[];
  connectors: ConnectorRecord[];
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

function SourceGlyph({ kind }: { kind: string }) {
  const mark = kind.toLowerCase().includes("github") ? "⌘" : kind.toLowerCase().includes("nas") || kind.toLowerCase().includes("folder") ? "▤" : kind.toLowerCase().includes("jetson") ? "▣" : "◈";
  return <span className="sw-source-glyph" aria-hidden="true">{mark}</span>;
}

function initialDevices(sources: SourceSummary[]): DeviceRecord[] {
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
      connectors: [{ id: "graph-snapshot", label: "Graph snapshot", kind: "Workstation", detail: "97 nodes · local fallback", state: "partial", manifest: "ready" }],
    },
    {
      id: "source-host",
      label: "Source connector host",
      detail: "Mac / NAS / GitHub connector family",
      pairing: "pairing",
      lastSeen: "AccessContext unavailable",
      capabilities: ["Manifest preview", "Range read", "Change events"],
      connectors: [
        { id: nas?.sourceId ?? "nas", label: nas?.label ?? "NAS connector", kind: "Folder / NAS", detail: nas?.detail ?? "Waiting for source grant", state: nas?.state ?? "unsupported", manifest: "pending" },
        { id: github?.sourceId ?? "github", label: github?.label ?? "GitHub connector", kind: "GitHub repository", detail: github?.detail ?? "Waiting for repository scope", state: github?.state ?? "unsupported", manifest: "pending" },
      ],
    },
  ];
}

export default function SourcesWorkspace({ sources }: { sources: SourceSummary[] }) {
  const [devices, setDevices] = useState<DeviceRecord[]>(() => initialDevices(sources));
  const [selectedDeviceId, setSelectedDeviceId] = useState("jetson-us-cf");
  const [scanState, setScanState] = useState<"idle" | "scanned">("idle");
  const [connectorOpen, setConnectorOpen] = useState(false);
  const [connectorKind, setConnectorKind] = useState<ConnectorKind>("Folder / NAS");
  const [connectorLabel, setConnectorLabel] = useState("");
  const [manifestId, setManifestId] = useState<string | null>(null);
  const [notice, setNotice] = useState("No HomeHub ownership or grant has been issued in this demo.");

  const selectedDevice = devices.find((device) => device.id === selectedDeviceId) ?? devices[0];
  const connectorCount = useMemo(() => devices.reduce((total, device) => total + device.connectors.length, 0), [devices]);

  const scan = () => {
    setScanState("scanned");
    setNotice("Discovery returned one Jetson offer. Pairing still requires an explicit code or QR flow and HomeHub approval.");
  };

  const requestPairing = (deviceId: string) => {
    setDevices((current) => current.map((device) => device.id === deviceId ? { ...device, pairing: "pairing" } : device));
    setNotice("Pairing draft created. The connector is not authorized until HomeHub returns an AccessContext projection.");
  };

  const submitConnector = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const label = connectorLabel.trim() || connectorKind;
    const connector: ConnectorRecord = { id: `connector-${Date.now()}`, label, kind: connectorKind, detail: "Local draft · manifest preview pending", state: "unsupported", manifest: "pending" };
    setDevices((current) => current.map((device) => device.id === selectedDevice.id ? { ...device, connectors: [...device.connectors, connector] } : device));
    setConnectorLabel("");
    setConnectorOpen(false);
    setNotice(`${label} was added to a local connector draft. HomeHub still controls source scope and revocation.`);
  };

  return <section className="sw-shell" aria-label="Agent boxes and connectors">
    <div className="sw-hero">
      <div><span className="sw-kicker">AGENT BOX REGISTRY</span><h2>Pair the box, then add the sources it can understand.</h2><p>One Jetson can serve several authorized connectors. This surface shows discovery, pairing, manifest preview, and health as separate states.</p></div>
      <div className="sw-hero-actions"><button type="button" className="sw-button sw-button-primary" onClick={scan}><span aria-hidden="true">⌁</span>{scanState === "idle" ? "Find Jetson boxes" : "Scan again"}</button><button type="button" className="sw-button sw-button-quiet" onClick={() => setConnectorOpen((open) => !open)}>＋ Add connector</button></div>
    </div>
    <div className="sw-boundary"><span className="sw-boundary-mark">⌁</span><span><strong>HomeHub boundary</strong> supplies device ownership, pairing approval, grants, revocation, and audit.</span><span className="sw-boundary-state">{scanState === "scanned" ? "Discovery draft" : "Waiting for discovery"}</span></div>
    <div className="sw-notice"><span aria-hidden="true">●</span>{notice}</div>
    {connectorOpen && <form className="sw-connector-form" onSubmit={submitConnector}><div><span className="sw-kicker">ADD SOURCE CONNECTOR</span><h3>Choose what this Agent Box may analyze.</h3><p>A local draft only. The manifest and requested scope go to HomeHub before any read.</p></div><label><span>Connector type</span><select value={connectorKind} onChange={(event) => setConnectorKind(event.target.value as ConnectorKind)}><option>Folder / NAS</option><option>GitHub repository</option><option>Jetson device</option><option>Workstation</option></select></label><label><span>Label or endpoint</span><input value={connectorLabel} onChange={(event) => setConnectorLabel(event.target.value)} placeholder="e.g. research NAS / org/repository" /></label><button type="submit" className="sw-button sw-button-primary">Create draft <span aria-hidden="true">→</span></button></form>}
    <div className="sw-layout">
      <aside className="sw-device-list" aria-label="Agent Box devices"><div className="sw-section-head"><div><span className="sw-kicker">DEVICES</span><h3>Agent Boxes</h3></div><span>{devices.length}</span></div><div className="sw-device-rows">{devices.map((device) => <button type="button" key={device.id} className={`sw-device-row ${device.id === selectedDevice.id ? "is-selected" : ""}`} onClick={() => setSelectedDeviceId(device.id)}><span className="sw-device-mark">{device.id.startsWith("jetson") ? "▣" : "◈"}</span><span className="sw-device-copy"><strong>{device.label}</strong><small>{device.detail}</small></span><span className={`sw-state ${pairingClass[device.pairing]}`}>{device.pairing === "discovered" ? "NEW" : device.pairing === "pairing" ? "PENDING" : device.pairing === "paired" ? "READY" : "OFFLINE"}</span></button>)}</div><div className="sw-device-foot"><span className="sw-dot" />{scanState === "scanned" ? "1 discovery offer" : "LAN discovery optional"}<small>V1 uses explicit pairing</small></div></aside>
      <main className="sw-device-detail" aria-label={`${selectedDevice.label} detail`}><div className="sw-detail-head"><div><span className="sw-kicker">SELECTED AGENT BOX</span><h3>{selectedDevice.label}</h3><p>{selectedDevice.detail}</p></div><span className={`sw-pairing-badge ${pairingClass[selectedDevice.pairing]}`}>{pairingLabel[selectedDevice.pairing]}</span></div><div className="sw-detail-grid"><div><span className="sw-meta-label">Last seen</span><strong>{selectedDevice.lastSeen}</strong></div><div><span className="sw-meta-label">Node identity</span><strong>{selectedDevice.pairing === "paired" ? "HomeHub projection" : "Not issued"}</strong></div><div><span className="sw-meta-label">Transport</span><strong>{selectedDevice.id === "jetson-us-cf" ? "LAN offer · Cloudflare endpoint pending" : "Local connector projection"}</strong></div><div><span className="sw-meta-label">Capabilities</span><div className="sw-tags">{selectedDevice.capabilities.map((capability) => <span key={capability}>{capability}</span>)}</div></div></div>{selectedDevice.pairing === "discovered" && <div className="sw-pair-card"><div><strong>Jetson offer found</strong><p>Use a one-time code or QR from the device. Automatic LAN discovery is only an offer; it never creates ownership.</p></div><button type="button" className="sw-button sw-button-primary" onClick={() => requestPairing(selectedDevice.id)}>Start pairing review</button></div>}{selectedDevice.pairing === "pairing" && <div className="sw-pair-card is-pending"><div><strong>Waiting for HomeHub</strong><p>Pairing draft is ready. The device remains outside the readable source set until ownership and policy are returned.</p></div><span className="sw-pending-mark">⌁</span></div>}<div className="sw-connector-heading"><div><span className="sw-kicker">CONNECTORS ON THIS BOX</span><h4>{selectedDevice.connectors.length} sources</h4></div><span>Each source gets its own manifest and grant</span></div><div className="sw-connector-list">{selectedDevice.connectors.map((connector) => <article className="sw-connector-card" key={connector.id}><SourceGlyph kind={connector.kind} /><div className="sw-connector-copy"><strong>{connector.label}</strong><small>{connector.kind} · {connector.detail}</small><div className="sw-connector-actions"><span className={`sw-connector-state sw-connector-${connector.manifest}`}>{connector.manifest === "ready" ? "Manifest available" : connector.manifest === "pending" ? "Manifest preview pending" : "Manifest unavailable"}</span><button type="button" onClick={() => setManifestId(manifestId === connector.id ? null : connector.id)}>{manifestId === connector.id ? "Close preview" : "Preview manifest"}</button></div>{manifestId === connector.id && <div className="sw-manifest-preview"><span>Dry run only</span><p>Files, source scope, change cursor, and grant epoch will appear here after the connector API and HomeHub context are connected.</p></div>}</div><span className={`sw-state-pill ${connector.state === "current" ? "is-current" : ""}`}>{connector.state === "current" ? "Current" : connector.state === "partial" ? "Partial" : "Pending"}</span></article>)}{selectedDevice.connectors.length === 0 && <div className="sw-empty"><span>＋</span><strong>No source connector is attached yet.</strong><p>Add NAS, GitHub, workstation, or another device after this Agent Box completes pairing.</p><button type="button" className="sw-link-button" onClick={() => setConnectorOpen(true)}>Add the first connector →</button></div>}</div></main>
    </div>
    <div className="sw-footer"><div><span className="sw-kicker">INDEXING ROUTE</span><strong>{connectorCount} connector drafts · one Jetson queue</strong><p>Source discovery → HomeHub grant → manifest preview → incremental IndexJob → evidence answer.</p></div><span className="sw-footer-status">No live grant issued</span></div>
  </section>;
}
