import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useDashboardStore } from "../store";
import type { GraphNode, KnowledgeGraph } from "@understand-anything/core/types";
import { createStudioSnapshotFromGraph } from "../studio-contracts";
import type { EvidenceRef, IndexJob, StudioSnapshot } from "../studio-contracts";
import PrivacyWorkspace, { SharingScopePanel } from "./PrivacyWorkspace";
import GroupWorkspace from "./GroupWorkspace";
import SourcesWorkspace from "./SourcesWorkspace";
import { PrivacyWorkspaceProvider } from "./privacy-model";
import { searchProjectKnowledge, studioApiConfigured } from "../studio-api";

type StudioSection = "overview" | "projects" | "conversation" | "evidence" | "activity" | "collaborate" | "sources" | "privacy";

interface ProjectStudioProps {
  onOpenGraph: () => void;
  /** Optional server-projected Studio data; graph fallback remains explicitly partial. */
  snapshot?: StudioSnapshot;
}

const sectionLabels: Record<StudioSection, { label: string; detail: string }> = {
  overview: { label: "Today", detail: "Project command center" },
  projects: { label: "Projects", detail: "Your indexed work" },
  conversation: { label: "Ask Jarvis", detail: "Project conversation" },
  evidence: { label: "Evidence", detail: "Trace every answer" },
  activity: { label: "Activity", detail: "Freshness and changes" },
  collaborate: { label: "Groups", detail: "Shared project context" },
  sources: { label: "Sources", detail: "Devices and connectors" },
  privacy: { label: "Privacy & audit", detail: "Trust and audit" },
};

function Icon({ name, size = 18 }: { name: "grid" | "folder" | "search" | "pulse" | "users" | "arrow" | "spark" | "shield" | "chevron" | "message"; size?: number }) {
  const paths: Record<string, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    folder: <><path d="M3 7.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M3 9.5h18" /></>,
    search: <><circle cx="10.8" cy="10.8" r="6.3" /><path d="m16 16 4.5 4.5" /></>,
    pulse: <><path d="M3 12h3l2-7 4 14 2-7h7" /></>,
    users: <><path d="M16 20v-1.3a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4V20" /><circle cx="9.5" cy="7" r="3.5" /><path d="M17 11a3.2 3.2 0 0 0 0-6.2M21 20v-1.2a4 4 0 0 0-2.5-3.7" /></>,
    arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
    spark: <><path d="m12 3 1.4 5.6L19 10l-5.6 1.4L12 17l-1.4-5.6L5 10l5.6-1.4z" /><path d="m19 16 .6 2.4L22 19l-2.4.6L19 22l-.6-2.4L16 19l2.4-.6z" /></>,
    shield: <><path d="M12 3 20 6v5c0 5-3.4 8.2-8 10-4.6-1.8-8-5-8-10V6z" /><path d="m8.5 12 2.2 2.2 4.8-5" /></>,
    chevron: <path d="m9 18 6-6-6-6" />,
    message: <><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5 7.6 7.6 0 0 1-3.1-.7L4 20l1.7-4.1A7.5 7.5 0 1 1 20 11.5Z" /><path d="M8 11.5h.01M12 11.5h.01M16 11.5h.01" /></>,
  };

  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown time";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function stateLabel(state: StudioSnapshot["health"]["state"]): string {
  return state === "current" ? "Current" : state === "partial" ? "Partial" : state[0].toUpperCase() + state.slice(1);
}

function humanNodeType(type: string): string {
  return type.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " ");
}

function jobLabel(job: IndexJob): string {
  return job.phase === "retry_wait" ? "Retry waiting" : job.phase.replace(/_/g, " ").replace(/^./, (value) => value.toUpperCase());
}

function accessState(access: NonNullable<StudioSnapshot["access"]>): string {
  if (access.validation === "revoked" || access.revoked) return "Revoked by HomeHub";
  if (access.validation === "expired") return "Expired";
  if (access.validation === "active") return "Active projection from HomeHub";
  if (access.validation === "unknown") return "Validation unavailable";
  return "Validation unavailable";
}

function getNodeCounts(graph: KnowledgeGraph) {
  const counts = new Map<string, number>();
  for (const node of graph.nodes) counts.set(node.type, (counts.get(node.type) ?? 0) + 1);
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
}

function getConnectedNodes(graph: KnowledgeGraph): Array<GraphNode & { connectionCount: number }> {
  const connections = new Map<string, number>();
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  for (const edge of graph.edges) {
    connections.set(edge.source, (connections.get(edge.source) ?? 0) + 1);
    connections.set(edge.target, (connections.get(edge.target) ?? 0) + 1);
  }
  return Array.from(connections.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([id, connectionCount]) => {
      const node = nodesById.get(id);
      return node ? { ...node, connectionCount } : null;
    })
    .filter((node): node is GraphNode & { connectionCount: number } => node !== null);
}

function RelationshipConstellation({ graph, onOpenGraph }: { graph: KnowledgeGraph; onOpenGraph: () => void }) {
  const layers = graph.layers.slice(0, 7);
  const hiddenLayerCount = Math.max(0, graph.layers.length - layers.length);
  const layerForNode = useMemo(() => {
    const map = new Map<string, string>();
    for (const layer of layers) for (const nodeId of layer.nodeIds) map.set(nodeId, layer.id);
    return map;
  }, [layers]);
  const positions = useMemo(() => {
    const center = { x: 310, y: 132 };
    const radiusX = 220;
    const radiusY = 92;
    return layers.map((layer, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(layers.length, 1) - Math.PI / 2;
      return { layer, x: center.x + Math.cos(angle) * radiusX, y: center.y + Math.sin(angle) * radiusY };
    });
  }, [layers]);
  const positionById = new Map(positions.map((position) => [position.layer.id, position]));
  const relationCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const edge of graph.edges) {
      const source = layerForNode.get(edge.source);
      const target = layerForNode.get(edge.target);
      if (!source || !target || source === target) continue;
      const key = [source, target].sort().join("::");
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return Array.from(counts.entries()).map(([key, count]) => ({ layers: key.split("::"), count }));
  }, [graph.edges, layerForNode]);

  return (
    <div className="studio-constellation" aria-label="Layer relationship map">
      <svg viewBox="0 0 620 265" role="img">
        <defs>
          <radialGradient id="studioConstellationGlow" cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="#177d82" stopOpacity=".24" /><stop offset="100%" stopColor="#177d82" stopOpacity="0" /></radialGradient>
          <marker id="studioConstellationArrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0 0 6 3 0 6Z" fill="#a9bbb0" /></marker>
        </defs>
        <circle cx="310" cy="132" r="83" fill="url(#studioConstellationGlow)" />
        {relationCounts.map((relation) => {
          const start = positionById.get(relation.layers[0]);
          const end = positionById.get(relation.layers[1]);
          if (!start || !end) return null;
          return <line key={`${relation.layers.join("-")}`} x1={start.x} y1={start.y} x2={end.x} y2={end.y} stroke="#a9bbb0" strokeWidth={Math.min(4, 1 + relation.count / 4)} strokeOpacity=".7" markerEnd="url(#studioConstellationArrow)" />;
        })}
        <circle cx="310" cy="132" r="42" fill="#17201f" />
        <circle cx="310" cy="132" r="35" fill="#263834" stroke="#92a83e" strokeOpacity=".6" />
        <text x="310" y="128" textAnchor="middle" fill="#f4fbf3" fontSize="11" fontWeight="600">Project</text>
        <text x="310" y="144" textAnchor="middle" fill="#a7c3b0" fontSize="9">{graph.edges.length} links</text>
        {positions.map(({ layer, x, y }, index) => (
          <g key={layer.id} role="button" tabIndex={0} aria-label={`Open layer ${layer.name}`} onClick={onOpenGraph} onKeyDown={(event) => { if (event.key === " ") event.preventDefault(); if (event.key === "Enter" || event.key === " ") onOpenGraph(); }} className="studio-constellation-node">
            <title>{layer.name}: {layer.nodeIds.length} nodes</title>
            <circle cx={x} cy={y} r={index < 4 ? 24 : 20} fill="#fbfbf8" stroke={index % 3 === 0 ? "#177d82" : index % 3 === 1 ? "#7664a4" : "#92a83e"} strokeWidth="2" />
            <text x={x} y={y - 1} textAnchor="middle" fill="#24322e" fontSize="9" fontWeight="600">{layer.name.slice(0, 14)}</text>
            <text x={x} y={y + 12} textAnchor="middle" fill="#738078" fontSize="8">{layer.nodeIds.length} nodes</text>
          </g>
        ))}
      </svg>
      <div className="studio-constellation-caption"><span><i className="studio-relation-line" />Directed layer relations · {hiddenLayerCount > 0 ? `${hiddenLayerCount} more layers hidden` : "all layers shown"}</span><button type="button" onClick={onOpenGraph}>Inspect all relations <Icon name="arrow" size={14} /></button></div>
    </div>
  );
}

function KnowledgeRing({ graph }: { graph: KnowledgeGraph }) {
  const totals = [
    { label: "Code", value: graph.nodes.filter((node) => ["file", "function", "class", "module"].includes(node.type)).length, color: "#177d82" },
    { label: "Domain", value: graph.nodes.filter((node) => ["domain", "flow", "step", "concept"].includes(node.type)).length, color: "#7664a4" },
    { label: "Infra", value: graph.nodes.filter((node) => ["service", "resource", "pipeline", "config"].includes(node.type)).length, color: "#92a83e" },
    { label: "Knowledge", value: graph.nodes.filter((node) => ["article", "entity", "topic", "claim", "source"].includes(node.type)).length, color: "#d16e55" },
  ];
  const classified = totals.reduce((sum, item) => sum + item.value, 0);
  totals.push({ label: "Other", value: Math.max(0, graph.nodes.length - classified), color: "#b3bdb5" });
  const total = Math.max(graph.nodes.length, 1);
  const circumference = 2 * Math.PI * 42;
  let offset = 0;
  return (
    <div className="studio-ring-wrap">
      <div className="studio-ring-chart">
        <svg viewBox="0 0 108 108" aria-label="Knowledge composition ring">
          <circle cx="54" cy="54" r="42" fill="none" stroke="#e4eae2" strokeWidth="10" />
          {totals.map((item) => {
            const arc = (item.value / total) * circumference;
            const element = <circle key={item.label} cx="54" cy="54" r="42" fill="none" stroke={item.color} strokeWidth="10" strokeDasharray={`${arc} ${circumference - arc}`} strokeDashoffset={-offset} transform="rotate(-90 54 54)" />;
            offset += arc;
            return element;
          })}
        </svg>
        <div className="studio-ring-center"><strong>{graph.nodes.length}</strong><span>nodes</span></div>
      </div>
      <div className="studio-ring-legend">{totals.map((item) => <span key={item.label}><i style={{ background: item.color }} />{item.label}<strong>{item.value}</strong></span>)}</div>
    </div>
  );
}

function SectionFrame({ kicker, title, description, children, action }: { kicker: string; title: string; description: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="studio-section-page">
      <div className="studio-section-page-head"><div><span className="studio-eyebrow"><span className="studio-live-dot" />{kicker}</span><h1>{title}</h1><p>{description}</p></div>{action}</div>
      {children}
    </div>
  );
}

function audienceLabel(audience: NonNullable<NonNullable<StudioSnapshot["access"]>["audience"]> | undefined): string {
  switch (audience) {
    case "owner_group": return "Owner group";
    case "external_group": return "External group";
    case "shared": return "Shared project";
    case "private": return "Private project";
    default: return "Access context unavailable";
  }
}

function StudioContextBar({ snapshot, onOpenPrivacy, onOpenGroups }: { snapshot: StudioSnapshot; onOpenPrivacy: () => void; onOpenGroups: () => void }) {
  const access = snapshot.access;
  const label = access?.displayLabel || "Unverified viewer";
  const jarvis = access?.jarvisNodeId || "Jarvis node unavailable";
  return (
    <div className="studio-context-bar" aria-label="Active Jarvis and HomeHub access context">
      <div className="studio-context-identity"><span className="studio-context-avatar"><Icon name="spark" size={14} /></span><span><strong>{label}</strong><small>{jarvis}</small></span></div>
      <span className="studio-context-divider" />
      <span className="studio-context-chip studio-context-chip-scope"><Icon name="shield" size={13} />{audienceLabel(access?.audience)}</span>
      <span className="studio-context-chip"><span className="studio-live-dot" />{access ? accessState(access) : "HomeHub context pending"}</span>
      <span className="studio-context-chip studio-context-chip-muted">Project scope</span>
      <div className="studio-context-actions"><button type="button" className="studio-context-link" onClick={onOpenGroups}>Groups <Icon name="users" size={13} /></button><button type="button" className="studio-context-link" onClick={onOpenPrivacy}>View access <Icon name="arrow" size={13} /></button></div>
    </div>
  );
}

function ConversationSection({ snapshot, onOpenGraph, onOpenEvidence, onOpenPrivacy }: { snapshot: StudioSnapshot; onOpenGraph: () => void; onOpenEvidence: () => void; onOpenPrivacy: () => void }) {
  const [draft, setDraft] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [pending, setPending] = useState(false);
  const liveAnswerLabel = snapshot.evidenceOrigin === "service" ? "Jetson knowledge service" : "Graph-derived preview";
  const [messages, setMessages] = useState<Array<{ id: string; role: "user" | "jarvis"; author: string; body: string; time: string; sources?: string[] }>>([
    { id: "direct-user-1", role: "user", author: "You", body: "How is this project shaped, and where should I start?", time: "09:08" },
    { id: "direct-jarvis-1", role: "jarvis", author: snapshot.evidenceOrigin === "service" ? "Local Jarvis" : "Local Jarvis draft", body: `This project has ${snapshot.project.counts.nodes} indexed entities across ${snapshot.project.counts.layers} logical layers. Start with the most connected entry points, then open the map when you need to follow a dependency path.`, time: "09:09" },
  ]);
  const scopeLabel = audienceLabel(snapshot.access?.audience);
  const send = async () => {
    const question = draft.trim();
    if (!question || pending) return;
    const time = new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    const messageId = Date.now();
    setMessages((current) => [...current, { id: `direct-user-${messageId}`, role: "user", author: "You", body: question, time }]);
    setDraft("");
    setPending(true);
    try {
      let body = "I prepared a graph-derived preview for this question. The answer remains bounded by the current project scope until HomeHub returns an approved AccessContext.";
      let author = "Local Jarvis draft";
      let sources: string[] | undefined;
      if (studioApiConfigured()) {
        const result = await searchProjectKnowledge(question, snapshot.project.projectId);
        body = result.answer || result.message || "The knowledge service returned no answer.";
        author = result.confidence === "unavailable" ? "Jetson knowledge service" : "Local Jarvis";
        sources = result.sources.map((source) => source.file);
      }
      setMessages((current) => [...current, { id: `direct-jarvis-${messageId + 1}`, role: "jarvis", author, body, time: new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }), sources }]);
    } catch (error) {
      const body = error instanceof Error && error.message ? error.message : "The knowledge service is unavailable.";
      setMessages((current) => [...current, { id: `direct-error-${messageId + 1}`, role: "jarvis", author: "Jetson query unavailable", body: `I could not complete this query: ${body}. HomeHub access and the Jetson query API must be available before source-backed answers are returned.`, time: new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) }]);
    } finally {
      setPending(false);
    }
  };
  return (
    <SectionFrame kicker="Jarvis conversation" title="Ask your project memory in context." description="Keep the question, the selected scope, and the evidence trail in one workspace. Answers are attributed to the producing Jarvis and remain bounded by HomeHub context." action={<span className="studio-chip studio-chip-positive"><span className="studio-chip-dot" />{scopeLabel}</span>}>
      <div className="studio-conversation-layout">
        <div className="studio-panel studio-conversation-thread">
          <div className="studio-conversation-header"><div><span className="studio-section-kicker">Direct conversation</span><h2>Ask Jarvis about this project</h2><p className="studio-conversation-subtitle">A focused room for questions, evidence, and the Jarvis that answered.</p></div><span className="studio-conversation-live"><span className="studio-live-dot" />{liveAnswerLabel}</span></div>
          <div className="studio-conversation-scope-row"><span className="studio-scope-lock"><Icon name="shield" size={13} />{snapshot.access ? "HomeHub context supplied" : "HomeHub access context pending"}</span><span>{snapshot.access ? `Grant ${snapshot.access.grantEpoch} · expires ${formatDateTime(snapshot.access.expiresAt)}` : "Source-backed answers require an AccessContext projection"}</span></div>
          <div className="studio-direct-messages" role="log" aria-live="polite" aria-label="Ask Jarvis conversation">{messages.map((message) => <div className={`studio-message studio-message-${message.role === "user" ? "user" : "agent"}`} key={message.id}><span className={`studio-message-avatar ${message.role === "user" ? "studio-message-avatar-user" : ""}`}><Icon name={message.role === "user" ? "spark" : "spark"} size={14} /></span><div className="studio-message-body"><div className="studio-message-meta"><strong>{message.author}</strong><span>{message.role === "user" ? "Project scope" : liveAnswerLabel}</span><time>{message.time}</time></div><p>{message.body}</p>{message.sources && message.sources.length > 0 && <div className="studio-answer-source-list">{message.sources.slice(0, 3).map((source) => <span key={source}>{source}</span>)}</div>}{message.role === "jarvis" && <div className="studio-answer-citations"><button type="button" onClick={onOpenGraph}><Icon name="grid" size={12} />Project map</button><button type="button" onClick={onOpenEvidence}><Icon name="folder" size={12} />Evidence</button><span className="studio-evidence-visibility"><Icon name="shield" size={12} />{scopeLabel}</span></div>}</div></div>)}</div>
          <div className="studio-direct-typing"><span className="studio-typing-dots"><i /><i /><i /></span>{pending ? "Jetson is searching approved project knowledge…" : "Jarvis answers stay inside the selected project scope"}</div>
          <div className="studio-quick-actions"><span className="studio-section-kicker">Quick questions</span><button type="button" onClick={() => setDraft("Which project can I reuse for this feature?")}>Find reusable work <Icon name="arrow" size={13} /></button><button type="button" onClick={() => setDraft("What changed since the last knowledge update?")}>Explain recent changes <Icon name="arrow" size={13} /></button><button type="button" onClick={() => setDraft("Create an onboarding path for a new contributor.")}>Build onboarding path <Icon name="arrow" size={13} /></button></div>
          <form className="studio-conversation-composer" onSubmit={(event) => { event.preventDefault(); void send(); }}><button type="button" className={`studio-voice-button ${isListening ? "is-listening" : ""}`} onClick={() => setIsListening((value) => !value)} aria-pressed={isListening} aria-label={isListening ? "Stop voice input" : "Start voice input"}>{isListening ? "■" : "◉"}</button><Icon name="message" size={17} /><input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={isListening ? "Listening…" : "Ask Jarvis about this project"} aria-label="Ask Jarvis about this project" /><span className="studio-composer-status">{pending ? "Searching" : studioApiConfigured() ? "Jetson API" : "Demo fallback"}</span><button type="submit" className="studio-button studio-button-primary" disabled={!draft.trim() || pending}>Ask Jarvis <span className="studio-key">⌘ ↵</span></button></form>
          <p className="studio-conversation-note"><span aria-hidden="true">✦</span> {snapshot.evidenceOrigin === "service" ? "Answers are returned by the Jetson query service with cited KnowledgeItems." : "Demo responses are graph-derived previews; source ranges remain gated by HomeHub."}</p>
        </div>
        <div className="studio-conversation-side"><SharingScopePanel conversationId="direct:current-project" kind="direct" recipientLabel="One-to-one Jarvis draft" onOpenPrivacy={onOpenPrivacy} /><div className="studio-conversation-trust"><Icon name="shield" size={15} /><p><strong>HomeHub controls access.</strong> Studio only displays the returned audience, scope, expiry, epoch, and audit trace.</p></div></div>
      </div>
    </SectionFrame>
  );
}

function ProjectsSection({ snapshot, onOpenGraph }: { snapshot: StudioSnapshot; onOpenGraph: () => void }) {
  const { project, health } = snapshot;
  return (
    <SectionFrame kicker="Project portfolio" title="Find the work before you open the files." description="A workspace-level view of every authorized project, its source health, and the relationships that make reuse possible." action={<button className="studio-button studio-button-primary" type="button" onClick={onOpenGraph}><Icon name="grid" size={16} /> Open current map</button>}>
      <div className="studio-portfolio-layout">
        <div className="studio-project-card studio-panel">
          <div className="studio-project-card-top"><span className={`studio-chip ${health.state === "current" ? "studio-chip-positive" : ""}`}><span className="studio-chip-dot" />{stateLabel(health.state)} graph</span><span className="studio-panel-caption">{formatDate(project.updatedAt)}</span></div>
          <h2>{project.name}</h2><p>{project.description || "Project description will appear after the first semantic enrichment pass."}</p>
          <div className="studio-project-card-stats"><span><strong>{project.counts.files}</strong> files</span><span><strong>{project.counts.nodes}</strong> nodes</span><span><strong>{project.counts.relations}</strong> links</span></div>
          <div className="studio-chip-row">{project.languages.slice(0, 4).map((language) => <span className="studio-chip" key={language}>{language}</span>)}{project.frameworks.slice(0, 3).map((framework) => <span className="studio-chip" key={framework}>{framework}</span>)}</div>
          <button className="studio-entry studio-project-open" type="button" onClick={onOpenGraph}><span className="studio-entry-copy"><strong>Open project cockpit</strong><small>Map, evidence, files, and changes</small></span><Icon name="arrow" size={15} /></button>
        </div>
        <div className="studio-panel studio-portfolio-graph"><div className="studio-panel-heading"><div><span className="studio-section-kicker">Portfolio relations</span><h2>Reuse constellation</h2></div><span className="studio-panel-caption">1 project connected</span></div><div className="studio-project-constellation"><div className="studio-project-node studio-project-node-main"><Icon name="spark" size={17} /><strong>{project.name}</strong><small>{project.counts.nodes} indexed nodes</small></div><div className="studio-project-node studio-project-node-pending"><span>+</span><strong>Connect another source</strong><small>NAS · GitHub · device</small></div><div className="studio-project-connection studio-project-connection-one" /><div className="studio-project-connection studio-project-connection-two" /></div><div className="studio-empty studio-portfolio-empty"><Icon name="users" size={17} /><p>Cross-project reuse appears when another authorized project is indexed.</p></div></div>
      </div>
      <div className="studio-panel studio-portfolio-table"><div className="studio-panel-heading"><div><span className="studio-section-kicker">Project inventory</span><h2>Indexed work</h2></div><span className="studio-panel-caption">Source scope supplied by HomeHub</span></div><div className="studio-table-row studio-table-header"><span>Project</span><span>Files / nodes</span><span>Knowledge state</span><span>Action</span></div><div className="studio-table-row"><span className="studio-table-project"><i className="studio-legend-dot studio-legend-dot-code" /><strong>{project.name}</strong></span><span className="studio-table-muted">{project.counts.files} / {project.counts.nodes}</span><span><span className={`studio-status-pill ${health.state === "current" ? "studio-status-pill-success" : "studio-status-pill-neutral"}`}>{stateLabel(health.state)}</span><small className="studio-table-muted studio-table-sub">{health.reason || "Connector freshness supplied by the knowledge service"}</small></span><button className="studio-link-button" type="button" onClick={onOpenGraph}>Inspect <Icon name="arrow" size={14} /></button></div></div>
    </SectionFrame>
  );
}

function EvidenceSection({ graph, snapshot, onOpenGraph }: { graph: KnowledgeGraph; snapshot: StudioSnapshot; onOpenGraph: () => void }) {
  const [query, setQuery] = useState("");
  const [resultLimit, setResultLimit] = useState(5);
  const selectNode = useDashboardStore((s) => s.selectNode);
  const graphEvidence = useMemo(() => graph.nodes.map((node): EvidenceRef => ({
    evidenceId: `graph-node:${node.id}`,
    projectId: snapshot.project.projectId,
    locator: { path: node.filePath, lineStart: node.lineRange?.[0], lineEnd: node.lineRange?.[1], symbol: node.name },
    kind: node.filePath ? "structure" : "unavailable",
    summary: node.summary || "No semantic summary has been published for this graph node.",
    freshness: snapshot.health.state,
  })), [graph.nodes, snapshot.health.state, snapshot.project.knowledgeVersion, snapshot.project.projectId]);
  const filteredResults = useMemo(() => {
    const evidence = snapshot.evidenceOrigin === "graph-fallback" ? graphEvidence : snapshot.evidence;
    if (!query.trim()) return evidence;
    const normalized = query.toLowerCase();
    return evidence.filter((item) => [item.summary, item.locator.path ?? "", item.locator.symbol ?? "", item.kind].join(" ").toLowerCase().includes(normalized));
  }, [graphEvidence, query, snapshot.evidence, snapshot.evidenceOrigin]);
  const results = filteredResults.slice(0, resultLimit);
  const evidenceOrigin = snapshot.evidenceOrigin === "graph-fallback" ? "Graph-derived preview" : "Evidence service";
  return (
    <SectionFrame kicker="Evidence search" title="Ask a question. Keep the source attached." description="Every result is a bounded graph or source anchor. Semantic confidence and access provenance will be supplied by the retrieval service when connected." action={<div className="studio-evidence-scope"><span className="studio-chip studio-chip-positive">Current project</span><span className="studio-chip">ACL filter pending</span></div>}>
      <div className="studio-evidence-layout">
        <div className="studio-panel studio-evidence-list"><div className="studio-evidence-query"><Icon name="search" size={17} /><input value={query} onChange={(event) => { setQuery(event.target.value); setResultLimit(5); }} placeholder="Search files, symbols, or summaries" aria-label="Search project evidence" /><span className="studio-key">⌘ K</span></div><div className="studio-evidence-list-head"><span>{results.length} of {filteredResults.length} results</span><span>{evidenceOrigin}</span></div>{results.map((evidence) => { const graphNodeId = evidence.evidenceId.startsWith("graph-node:") ? evidence.evidenceId.slice("graph-node:".length) : undefined; const graphNode = graphNodeId ? graph.nodes.find((node) => node.id === graphNodeId) : undefined; return <button key={evidence.evidenceId} type="button" className="studio-evidence-result" onClick={() => { if (graphNode) selectNode(graphNode.id); onOpenGraph(); }}><div className="studio-evidence-result-top"><span className="studio-status-pill studio-status-pill-neutral">{evidence.kind}</span><span className="studio-table-muted">{stateLabel(evidence.freshness)}</span></div><strong>{evidence.locator.symbol || evidence.locator.path || "Evidence reference"}</strong><p>{evidence.summary}</p><div className="studio-evidence-meta"><span>{evidence.locator.path || "Graph relationship"}{evidence.locator.lineStart ? `:${evidence.locator.lineStart}–${evidence.locator.lineEnd ?? evidence.locator.lineStart}` : ""}</span><span>{evidence.knowledgeVersion ? `v${evidence.knowledgeVersion}` : "Knowledge version pending"}</span></div></button>; })}{results.length === 0 && <div className="studio-empty"><Icon name="search" size={18} /><p>{snapshot.evidenceOrigin === "graph-fallback" ? "No graph evidence matches this query." : "No evidence reference matches this query."}</p></div>}{filteredResults.length > results.length && <button type="button" className="studio-link-button" onClick={() => setResultLimit((limit) => limit + 5)}>Show more evidence <Icon name="arrow" size={14} /></button>}</div>
        <div className="studio-panel studio-evidence-inspector"><span className="studio-section-kicker">Evidence contract</span><h2>What a trusted result will show</h2><div className="studio-trust-stack"><div><span className="studio-trust-index">01</span><p><strong>Conclusion</strong><small>What Jarvis believes the evidence says.</small></p></div><div><span className="studio-trust-index">02</span><p><strong>Source range</strong><small>File, symbol, line range, or graph relationship.</small></p></div><div><span className="studio-trust-index">03</span><p><strong>Version anchor</strong><small>Source commit and knowledge epoch.</small></p></div><div><span className="studio-trust-index">04</span><p><strong>Access trace</strong><small>HomeHub grant, freshness, and audit trace.</small></p></div></div><div className="studio-evidence-warning"><Icon name="shield" size={16} /><p>Raw source stays behind the connector grant. The dashboard never becomes an ACL authority.</p></div></div>
      </div>
    </SectionFrame>
  );
}

function ActivitySection({ snapshot }: { snapshot: StudioSnapshot }) {
  const jobs = snapshot.jobs.slice(0, 3);
  return (
    <SectionFrame kicker="Index activity" title="See what changed, and what still needs work." description="The activity surface separates graph availability from connector freshness, semantic enrichment, and publishing state." action={<span className={`studio-chip ${snapshot.health.state === "current" ? "studio-chip-positive" : ""}`}><span className="studio-chip-dot" />{stateLabel(snapshot.health.state)} knowledge</span>}>
      <div className="studio-activity-grid"><div className="studio-panel studio-activity-timeline"><div className="studio-panel-heading"><div><span className="studio-section-kicker">Knowledge timeline</span><h2>Current epoch</h2></div><span className="studio-panel-caption">{formatDate(snapshot.project.updatedAt)}</span></div>{jobs.length > 0 ? jobs.map((job) => <div className="studio-job-line" key={job.jobId}><span className={`studio-job-marker ${job.phase === "published" ? "studio-job-marker-done" : "studio-job-marker-pending"}`} /><div><strong>{jobLabel(job)}</strong><p>{job.error || (job.progress?.total ? `${job.progress.processed} of ${job.progress.total} units processed.` : "Waiting for the index service to publish progress.")}</p></div><span className={`studio-status-pill ${job.phase === "published" ? "studio-status-pill-success" : "studio-status-pill-neutral"}`}>{jobLabel(job)}</span></div>) : <div className="studio-empty"><Icon name="pulse" size={18} /><p>No IndexJob records are attached. The graph snapshot is available, but job history has not been published.</p></div>}</div><div className="studio-panel studio-resource-panel"><span className="studio-section-kicker">Index budget</span><h2>Make background work visible.</h2><div className="studio-indeterminate-state"><span className="studio-indeterminate-dot" /><strong>Scheduler data unavailable</strong></div><div className="studio-resource-label"><span>Resident Jetson queue</span><strong>Awaiting IndexJob metrics</strong></div><p>CPU, memory, queue age, and batch priority appear here only after the HomeHub inference scheduler exposes an IndexJob resource budget.</p><button type="button" className="studio-button studio-button-quiet">View job contract <Icon name="arrow" size={14} /></button></div></div>
    </SectionFrame>
  );
}

function GroupsSection({ snapshot, onOpenPrivacy }: { snapshot: StudioSnapshot; onOpenPrivacy: () => void }) {
  // The graph fallback never publishes peers; an array means the query service
  // supplied the directory, even when evidence is still graph-derived.
  const directoryLive = Array.isArray(snapshot.peers);
  return (
    <SectionFrame
      kicker="Jarvis groups"
      title="Open a group, then ask across the approved project scope."
      description="Choose a group from the inbox, continue the conversation in the center, and adjust this group's local sharing draft on the right. HomeHub remains the authority for identity, policy, revocation, and audit."
      action={<span className="studio-chip"><span className="studio-chip-dot" />Draft conversations</span>}
    >
      <GroupWorkspace onOpenPrivacy={onOpenPrivacy} peers={snapshot.peers} directoryLive={directoryLive} />
    </SectionFrame>
  );
}

function SourcesSection({ snapshot }: { snapshot: StudioSnapshot }) {
  const live = snapshot.evidenceOrigin === "service";
  // Knowledge items per source are only meaningful on a service snapshot; the
  // graph fallback has no source-attributed evidence.
  const knowledgeItemsBySource = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const item of snapshot.evidence) {
      if (!item.sourceId) continue;
      counts[item.sourceId] = (counts[item.sourceId] ?? 0) + 1;
    }
    return counts;
  }, [snapshot.evidence]);
  return <SectionFrame kicker="Sources & devices" title="Know which Jarvis can see which sources." description="Agent Boxes are the compute and identity boundary. Connectors are the individually scoped Mac, NAS, GitHub, or workstation sources that a Jetson may analyze. Server projections are displayed with their freshness and HomeHub boundary; local actions remain drafts until the authority returns a grant."><SourcesWorkspace sources={snapshot.sources} agentNodes={snapshot.agentNodes} connectors={snapshot.connectors} knowledgeItemsBySource={knowledgeItemsBySource} live={live} /><div className="studio-source-callout"><Icon name="shield" size={18} /><div><strong>HomeHub supplies the authority.</strong><p>UnderstandYourProjects displays discovery, pairing, grants, manifests, and health. It does not create a second ownership database or turn a local pair code into authorization.</p></div></div></SectionFrame>;
}

function PrivacySection({ snapshot, onOpenConversations }: { snapshot: StudioSnapshot; onOpenConversations: () => void }) {
  const access = snapshot.access;
  return <SectionFrame kicker="Privacy & audit" title="Make the audience visible before the answer." description="Your data map sets the default layers. Each direct chat or group can add or remove specific items in a local draft; HomeHub remains the authority for identity, policy, revocation, and audit."><PrivacyWorkspace onOpenConversations={onOpenConversations} /><div className="studio-panel studio-trace-panel studio-privacy-trace"><div className="studio-trace-chain">{["Identity context", "HomeHub policy", "Project scope", "Retrieval", "Evidence answer"].map((step, index) => <div key={step} className="studio-trace-step"><span>{String(index + 1).padStart(2, "0")}</span><strong>{step}</strong>{index < 4 && <b>→</b>}</div>)}</div><div className="studio-trace-fields"><span><small>HomeHub status</small><strong>{access ? accessState(access) : "Awaiting AccessContext"}</strong></span><span><small>Audience</small><strong>{audienceLabel(access?.audience)}</strong></span><span><small>Grant epoch</small><strong>{access?.grantEpoch || "Not exposed"}</strong></span><span><small>Expires</small><strong>{access ? formatDateTime(access.expiresAt) : "Not exposed"}</strong></span><span><small>Audit trace</small><strong>{access?.auditId || "Not exposed"}</strong></span></div></div><div className="studio-source-callout"><Icon name="shield" size={18} /><div><strong>Visual trust is a projection, not a permission engine.</strong><p>{access ? `HomeHub supplied this context at audit ${access.auditId}; Studio does not infer authorization from its presence.` : "Raw source, revocation, and audit decisions remain server-side until HomeHub provides an AccessContext projection."}</p></div></div></SectionFrame>;
}

function CommandPalette({ graph, onClose, onOpenGraph, onOpenEvidence }: { graph: KnowledgeGraph; onClose: () => void; onOpenGraph: () => void; onOpenEvidence: () => void }) {
  const [query, setQuery] = useState("");
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);
  const suggestions = [
    { label: "What is the architecture of this project?", kind: "Architecture" },
    { label: "Where should a new feature start?", kind: "Entry points" },
    { label: "Which files are most connected?", kind: "Dependencies" },
  ].filter((suggestion) => !query || suggestion.label.toLowerCase().includes(query.toLowerCase()));
  return <div className="studio-command-backdrop" role="presentation" onMouseDown={onClose}><div className="studio-command" role="dialog" aria-modal="true" aria-label="Ask Jarvis about this project" onMouseDown={(event) => event.stopPropagation()}><div className="studio-command-top"><Icon name="spark" size={17} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Ask about ${graph.project.name}`} aria-label="Ask Jarvis" /><span className="studio-key">ESC</span></div><div className="studio-command-scope"><span className="studio-chip studio-chip-positive">Project scope</span><span className="studio-chip">Graph evidence only</span><span className="studio-command-scope-note">HomeHub access context required for source ranges</span></div><div className="studio-command-list">{suggestions.map((suggestion) => <button type="button" key={suggestion.label} onClick={onOpenEvidence}><span><strong>{suggestion.label}</strong><small>{suggestion.kind} · cite sources in answer</small></span><Icon name="arrow" size={15} /></button>)}<button type="button" className="studio-command-action" onClick={onOpenGraph}><span><strong>Explore the project map</strong><small>Open relationships, layers, and node inspector</small></span><Icon name="grid" size={15} /></button></div><div className="studio-command-footer"><span><span className="studio-key">↵</span> select</span><span><span className="studio-key">⌘ ↵</span> open evidence</span><button type="button" onClick={onClose}>Close</button></div></div></div>;
}

function CoverageBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="studio-coverage-row">
      <div className="studio-coverage-label"><span>{label}</span><span>{value}</span></div>
      <div className="studio-coverage-track"><span style={{ width: `${Math.max(4, Math.min(100, value))}%`, background: color }} /></div>
    </div>
  );
}

function personalTimelineDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Snapshot date unavailable";
  return new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" }).format(date);
}

function PersonalTimeline({ graph, snapshot, onOpenGraph, onOpenEvidence }: { graph: KnowledgeGraph; snapshot: StudioSnapshot; onOpenGraph: () => void; onOpenEvidence: () => void }) {
  const leadNode = getConnectedNodes(graph)[0];
  return (
    <section className="studio-personal-timeline" aria-labelledby="personal-timeline-title">
      <div className="studio-personal-timeline-head">
        <div><span className="studio-section-kicker">Your project timeline</span><h2 id="personal-timeline-title">A readable day-by-day memory</h2><p>Yesterday's summary is derived from the latest indexed snapshot and keeps every claim linked to a place you can inspect.</p></div>
        <span className="studio-timeline-date">{personalTimelineDate(graph.project.analyzedAt)}</span>
      </div>
      <div className="studio-timeline-summary"><span className="studio-timeline-summary-mark"><Icon name="spark" size={17} /></span><div><strong>Yesterday's project digest</strong><p>{graph.project.name} is represented by {snapshot.project.counts.nodes} indexed entities across {snapshot.project.counts.layers} layers. The current knowledge snapshot is {stateLabel(snapshot.health.state).toLowerCase()}.</p></div><button type="button" className="studio-link-button" onClick={onOpenEvidence}>Open evidence <Icon name="arrow" size={14} /></button></div>
      <div className="studio-personal-timeline-list">
        <article className="studio-personal-timeline-item"><span className="studio-personal-timeline-rail"><i /></span><span className="studio-personal-timeline-icon"><Icon name="folder" size={15} /></span><div><div className="studio-personal-timeline-meta"><strong>Project structure available</strong><time>{personalTimelineDate(graph.project.analyzedAt)}</time></div><p>{snapshot.project.counts.nodes} nodes and {snapshot.project.counts.relations} relationships can be explored in the project map.</p><button type="button" onClick={onOpenGraph}>Open project map <Icon name="arrow" size={13} /></button></div></article>
        <article className="studio-personal-timeline-item"><span className="studio-personal-timeline-rail"><i /></span><span className="studio-personal-timeline-icon studio-personal-timeline-icon-warm"><Icon name="pulse" size={15} /></span><div><div className="studio-personal-timeline-meta"><strong>Knowledge health recorded</strong><time>Snapshot signal</time></div><p>Connector status is {stateLabel(snapshot.health.connectorStatus).toLowerCase()}; freshness reason: {snapshot.health.reason || "not supplied"}.</p><button type="button" onClick={onOpenEvidence}>Inspect source evidence <Icon name="arrow" size={13} /></button></div></article>
        <article className="studio-personal-timeline-item studio-personal-timeline-item-muted"><span className="studio-personal-timeline-rail"><i /></span><span className="studio-personal-timeline-icon studio-personal-timeline-icon-muted"><Icon name="spark" size={15} /></span><div><div className="studio-personal-timeline-meta"><strong>Next useful starting point</strong><time>Suggested from graph</time></div><p>{leadNode ? `${leadNode.name} is the most connected entry point in this snapshot.` : "A connected entry point will appear after the next index update."}</p>{leadNode && <button type="button" onClick={onOpenGraph}>Follow relationships <Icon name="arrow" size={13} /></button>}</div></article>
      </div>
    </section>
  );
}

function Overview({ graph, snapshot, onOpenGraph, onAsk }: { graph: KnowledgeGraph; snapshot: StudioSnapshot; onOpenGraph: () => void; onAsk: () => void }) {
  const setSearchQuery = useDashboardStore((s) => s.setSearchQuery);
  const selectNode = useDashboardStore((s) => s.selectNode);
  const nodeCounts = useMemo(() => getNodeCounts(graph), [graph]);
  const connectedNodes = useMemo(() => getConnectedNodes(graph), [graph]);
  const fileCount = snapshot.project.counts.files;
  const complexCount = graph.nodes.filter((node) => node.complexity === "complex").length;
  const codeCount = graph.nodes.filter((node) => ["file", "function", "class", "module"].includes(node.type)).length;
  const codeShare = graph.nodes.length ? Math.round((codeCount / graph.nodes.length) * 100) : 0;
  const complexShare = graph.nodes.length ? Math.round((complexCount / graph.nodes.length) * 100) : 0;
  const layeredNodeIds = new Set(graph.layers.flatMap((layer) => layer.nodeIds));
  const layerShare = graph.nodes.length ? Math.round((Array.from(layeredNodeIds).filter((nodeId) => graph.nodes.some((node) => node.id === nodeId)).length / graph.nodes.length) * 100) : 0;

  const searchAndOpen = (query: string) => {
    setSearchQuery(query);
    onOpenGraph();
  };

  return (
    <div className="studio-content">
      <section className="studio-hero">
        <div className="studio-hero-copy">
          <div className="studio-eyebrow"><span className="studio-live-dot" />Project intelligence</div>
          <h1>{graph.project.name}</h1>
          <p>{graph.project.description || "A living map of the code, systems, and evidence behind this project."}</p>
          <div className="studio-chip-row">
            <span className={`studio-chip ${snapshot.health.state === "current" ? "studio-chip-positive" : ""}`}><span className="studio-chip-dot" />{stateLabel(snapshot.health.state)} knowledge</span>
            <span className="studio-chip" title={snapshot.health.reason || "Connector freshness supplied by the knowledge service"}>Source freshness: {stateLabel(snapshot.health.connectorStatus)}</span>
            <span className="studio-chip">Analyzed {formatDate(graph.project.analyzedAt)}</span>
            {graph.project.gitCommitHash && <span className="studio-chip studio-chip-mono">{graph.project.gitCommitHash.slice(0, 8)}</span>}
          </div>
        </div>
        <div className="studio-hero-actions">
          <button className="studio-button studio-button-quiet" type="button" onClick={onOpenGraph}><Icon name="grid" size={16} /> Explore graph</button>
          <button className="studio-button studio-button-primary" type="button" onClick={onAsk}><Icon name="spark" size={16} /> Ask Jarvis <span className="studio-key">⌘ K</span></button>
        </div>
      </section>

      <section className="studio-stat-grid" aria-label="Project index statistics">
        <article className="studio-stat-card"><span className="studio-stat-label">Indexed files</span><strong>{fileCount}</strong><span className="studio-stat-note">file nodes only</span></article>
        <article className="studio-stat-card"><span className="studio-stat-label">Graph nodes</span><strong>{snapshot.project.counts.nodes}</strong><span className="studio-stat-note">all indexed entities</span></article>
        <article className="studio-stat-card"><span className="studio-stat-label">Logical layers</span><strong>{snapshot.project.counts.layers}</strong><span className="studio-stat-note">architecture groups</span></article>
        <article className="studio-stat-card studio-stat-card-accent"><span className="studio-stat-label">Review load</span><strong>{complexShare}%</strong><span className="studio-stat-note">nodes marked complex</span></article>
      </section>

      <PersonalTimeline graph={graph} snapshot={snapshot} onOpenGraph={onOpenGraph} onOpenEvidence={() => searchAndOpen("summary")} />

      <section className="studio-grid studio-grid-main">
        <article className="studio-panel studio-map-panel">
          <div className="studio-panel-heading"><div><span className="studio-section-kicker">Orientation</span><h2>How this project is shaped</h2></div><button className="studio-link-button" type="button" onClick={onOpenGraph}>Open full map <Icon name="arrow" size={15} /></button></div>
          <RelationshipConstellation graph={graph} onOpenGraph={onOpenGraph} />
        </article>

        <article className="studio-panel studio-panel-tight">
          <div className="studio-panel-heading"><div><span className="studio-section-kicker">Composition</span><h2>What is inside</h2></div><span className="studio-panel-caption">{snapshot.project.counts.nodes} nodes</span></div>
          <KnowledgeRing graph={graph} />
          <div className="studio-coverage-list">
            <CoverageBar label="Code structure" value={codeShare} color="var(--studio-cyan)" />
            <CoverageBar label="Indexed into layers" value={Math.min(100, layerShare)} color="var(--studio-lime)" />
            <CoverageBar label="Complexity to review" value={complexShare} color="var(--studio-coral)" />
          </div>
          <div className="studio-type-list">
            {nodeCounts.slice(0, 5).map(([type, count]) => <button type="button" key={type} onClick={() => searchAndOpen(type)}><span className="studio-type-mark" /> <span>{humanNodeType(type)}</span><strong>{count}</strong><Icon name="chevron" size={14} /></button>)}
          </div>
        </article>
      </section>

      <section className="studio-grid studio-grid-bottom">
        <article className="studio-panel">
          <div className="studio-panel-heading"><div><span className="studio-section-kicker">Start here</span><h2>High-signal entry points</h2></div><span className="studio-panel-caption">Most connected</span></div>
          <div className="studio-entry-list">
            {connectedNodes.length > 0 ? connectedNodes.map((node, index) => (
              <button type="button" className="studio-entry" key={node.id} onClick={() => { selectNode(node.id); onOpenGraph(); }}>
                <span className="studio-entry-rank">0{index + 1}</span><span className="studio-entry-copy"><strong>{node.name}</strong><small>{node.filePath || node.type} · {node.connectionCount} relationships</small></span><Icon name="arrow" size={15} />
              </button>
            )) : <div className="studio-empty"><Icon name="search" size={18} /><p>No connected entry points are available yet.</p></div>}
          </div>
        </article>

        <article className="studio-panel studio-panel-timeline">
          <div className="studio-panel-heading"><div><span className="studio-section-kicker">Evidence trail</span><h2>What Jarvis knows</h2></div><button className="studio-link-button" type="button" onClick={() => searchAndOpen("summary")}>Search evidence <Icon name="arrow" size={15} /></button></div>
          <div className="studio-timeline-item"><span className="studio-timeline-icon"><Icon name="folder" size={16} /></span><div><strong>Structure indexed</strong><p>{snapshot.project.counts.nodes} nodes and {snapshot.project.counts.relations} relationships are available to inspect.</p></div><time>{stateLabel(snapshot.health.state)} snapshot</time></div>
          <div className="studio-timeline-item"><span className="studio-timeline-icon"><Icon name="pulse" size={16} /></span><div><strong>Last analysis</strong><p>Source snapshot anchored to the recorded project commit.</p></div><time>{formatDate(graph.project.analyzedAt)}</time></div>
          <div className="studio-timeline-item studio-timeline-muted"><span className="studio-timeline-icon"><Icon name="users" size={16} /></span><div><strong>Collaboration history</strong><p>Connect a Jarvis group to show shared project context here.</p></div><time>Not connected</time></div>
        </article>
      </section>

      <section className="studio-handoff">
        <div className="studio-handoff-icon"><Icon name="shield" size={20} /></div>
        <div><span className="studio-section-kicker">Coding Agent handoff</span><h2>Give the agent a bounded, cited starting point.</h2><p>Search returns selected files, symbols, and source ranges. The agent never needs to guess where the project context lives.</p></div>
        <button className="studio-button studio-button-quiet" type="button" onClick={() => searchAndOpen("")}>Find evidence <Icon name="arrow" size={15} /></button>
      </section>
    </div>
  );
}

function ProjectStudioSurface({ onOpenGraph, snapshot: suppliedSnapshot }: ProjectStudioProps) {
  const graph = useDashboardStore((s) => s.graph);
  const [activeSection, setActiveSection] = useState<StudioSection>("overview");
  const [commandOpen, setCommandOpen] = useState(false);

  if (!graph) {
    return <div className="studio-loading"><span className="studio-live-dot" />Loading project intelligence…</div>;
  }

  const snapshot = suppliedSnapshot ?? createStudioSnapshotFromGraph(graph);

  return (
    <div className="studio-shell">
      <aside className="studio-sidebar">
        <div className="studio-brand"><div className="studio-brand-mark"><Icon name="spark" size={17} /></div><div><strong>Understand</strong><span>Your Projects</span></div></div>
        <div className="studio-workspace-label">Workspace</div>
        <button className="studio-workspace-switcher" type="button" onClick={() => setActiveSection("sources")}><span className="studio-workspace-avatar">J</span><span><strong>Current Jarvis box</strong><small>Jetson target · pairing draft</small></span><Icon name="chevron" size={14} /></button>
        <nav className="studio-nav" aria-label="Project studio navigation">
          {(Object.keys(sectionLabels) as StudioSection[]).map((section) => (
            <button key={section} type="button" className={`studio-nav-item ${activeSection === section ? "is-active" : ""} ${section === "conversation" || section === "collaborate" || section === "privacy" ? "studio-nav-priority" : ""}`} onClick={() => setActiveSection(section)}><Icon name={section === "overview" ? "grid" : section === "projects" || section === "sources" ? "folder" : section === "evidence" ? "search" : section === "activity" ? "pulse" : section === "privacy" ? "shield" : section === "conversation" ? "message" : "users"} size={17} /><span>{sectionLabels[section].label}</span>{section === "overview" && <span className="studio-nav-badge">Now</span>}{section === "collaborate" && <span className="studio-nav-badge studio-nav-badge-warn">New</span>}</button>
          ))}
        </nav>
        <div className="studio-sidebar-bottom"><div className="studio-privacy-card"><span className="studio-privacy-icon"><Icon name="shield" size={15} /></span><div><strong>HomeHub boundary</strong><p>Identity and access are supplied by HomeHub.</p></div></div><button type="button" className="studio-help-link">Keyboard shortcuts <span>?</span></button></div>
      </aside>
      <main className="studio-main">
        <header className="studio-topbar"><div className="studio-breadcrumb"><span>Workspace</span><b>/</b><strong>{sectionLabels[activeSection].label}</strong></div><button className="studio-global-search" type="button" onClick={() => setCommandOpen(true)}><Icon name="search" size={17} /><span>Ask about this project…</span><span className="studio-key">⌘ K</span></button><div className="studio-topbar-actions"><span className="studio-sync-status"><span className="studio-live-dot" />{stateLabel(snapshot.health.state)} knowledge</span><button className="studio-avatar" type="button" title="HomeHub access context" aria-label="HomeHub access context" onClick={() => setActiveSection("privacy")}>F</button></div></header>
        <StudioContextBar snapshot={snapshot} onOpenPrivacy={() => setActiveSection("privacy")} onOpenGroups={() => setActiveSection("collaborate")} />
        {activeSection === "overview" ? <Overview graph={graph} snapshot={snapshot} onOpenGraph={onOpenGraph} onAsk={() => setActiveSection("conversation")} /> : activeSection === "projects" ? <ProjectsSection snapshot={snapshot} onOpenGraph={onOpenGraph} /> : activeSection === "conversation" ? <ConversationSection snapshot={snapshot} onOpenGraph={onOpenGraph} onOpenEvidence={() => setActiveSection("evidence")} onOpenPrivacy={() => setActiveSection("privacy")} /> : activeSection === "evidence" ? <EvidenceSection graph={graph} snapshot={snapshot} onOpenGraph={onOpenGraph} /> : activeSection === "activity" ? <ActivitySection snapshot={snapshot} /> : activeSection === "collaborate" ? <GroupsSection snapshot={snapshot} onOpenPrivacy={() => setActiveSection("privacy")} /> : activeSection === "sources" ? <SourcesSection snapshot={snapshot} /> : <PrivacySection snapshot={snapshot} onOpenConversations={() => setActiveSection("conversation")} />}
      </main>
      {commandOpen && <CommandPalette graph={graph} onClose={() => setCommandOpen(false)} onOpenGraph={() => { setCommandOpen(false); onOpenGraph(); }} onOpenEvidence={() => { setCommandOpen(false); setActiveSection("evidence"); }} />}
    </div>
  );
}

export default function ProjectStudio(props: ProjectStudioProps) {
  return <PrivacyWorkspaceProvider><ProjectStudioSurface {...props} /></PrivacyWorkspaceProvider>;
}
