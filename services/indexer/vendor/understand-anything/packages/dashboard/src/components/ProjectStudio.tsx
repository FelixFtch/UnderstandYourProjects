import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useDashboardStore } from "../store";
import type { GraphNode, KnowledgeGraph } from "@understand-anything/core/types";

type StudioSection = "overview" | "projects" | "evidence" | "activity" | "collaborate" | "sources" | "privacy";

interface ProjectStudioProps {
  onOpenGraph: () => void;
}

const sectionLabels: Record<StudioSection, { label: string; detail: string }> = {
  overview: { label: "Overview", detail: "Project command center" },
  projects: { label: "Projects", detail: "Your indexed work" },
  evidence: { label: "Evidence", detail: "Trace every answer" },
  activity: { label: "Activity", detail: "Freshness and changes" },
  collaborate: { label: "Jarvis groups", detail: "Shared project context" },
  sources: { label: "Sources", detail: "Devices and connectors" },
  privacy: { label: "Privacy", detail: "Trust and audit" },
};

function Icon({ name, size = 18 }: { name: "grid" | "folder" | "search" | "pulse" | "users" | "arrow" | "spark" | "shield" | "chevron"; size?: number }) {
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

function ProjectsSection({ graph, onOpenGraph }: { graph: KnowledgeGraph; onOpenGraph: () => void }) {
  return (
    <SectionFrame kicker="Project portfolio" title="Find the work before you open the files." description="A workspace-level view of every authorized project, its source health, and the relationships that make reuse possible." action={<button className="studio-button studio-button-primary" type="button" onClick={onOpenGraph}><Icon name="grid" size={16} /> Open current map</button>}>
      <div className="studio-portfolio-layout">
        <div className="studio-project-card studio-panel">
          <div className="studio-project-card-top"><span className="studio-chip studio-chip-positive"><span className="studio-chip-dot" />Current graph</span><span className="studio-panel-caption">{formatDate(graph.project.analyzedAt)}</span></div>
          <h2>{graph.project.name}</h2><p>{graph.project.description || "Project description will appear after the first semantic enrichment pass."}</p>
          <div className="studio-project-card-stats"><span><strong>{graph.nodes.filter((node) => node.type === "file").length}</strong> files</span><span><strong>{graph.nodes.length}</strong> nodes</span><span><strong>{graph.edges.length}</strong> links</span></div>
          <div className="studio-chip-row">{graph.project.languages.slice(0, 4).map((language) => <span className="studio-chip" key={language}>{language}</span>)}{graph.project.frameworks.slice(0, 3).map((framework) => <span className="studio-chip" key={framework}>{framework}</span>)}</div>
          <button className="studio-entry studio-project-open" type="button" onClick={onOpenGraph}><span className="studio-entry-copy"><strong>Open project cockpit</strong><small>Map, evidence, files, and changes</small></span><Icon name="arrow" size={15} /></button>
        </div>
        <div className="studio-panel studio-portfolio-graph"><div className="studio-panel-heading"><div><span className="studio-section-kicker">Portfolio relations</span><h2>Reuse constellation</h2></div><span className="studio-panel-caption">1 project connected</span></div><div className="studio-project-constellation"><div className="studio-project-node studio-project-node-main"><Icon name="spark" size={17} /><strong>{graph.project.name}</strong><small>{graph.nodes.length} indexed nodes</small></div><div className="studio-project-node studio-project-node-pending"><span>+</span><strong>Connect another source</strong><small>NAS · GitHub · device</small></div><div className="studio-project-connection studio-project-connection-one" /><div className="studio-project-connection studio-project-connection-two" /></div><div className="studio-empty studio-portfolio-empty"><Icon name="users" size={17} /><p>Cross-project reuse appears when another authorized project is indexed.</p></div></div>
      </div>
      <div className="studio-panel studio-portfolio-table"><div className="studio-panel-heading"><div><span className="studio-section-kicker">Project inventory</span><h2>Indexed work</h2></div><span className="studio-panel-caption">Source scope supplied by HomeHub</span></div><div className="studio-table-row studio-table-header"><span>Project</span><span>Files / nodes</span><span>Knowledge state</span><span>Action</span></div><div className="studio-table-row"><span className="studio-table-project"><i className="studio-legend-dot studio-legend-dot-code" /><strong>{graph.project.name}</strong></span><span className="studio-table-muted">{graph.nodes.filter((node) => node.type === "file").length} / {graph.nodes.length}</span><span><span className="studio-status-pill studio-status-pill-neutral">Graph loaded</span><small className="studio-table-muted studio-table-sub">connector freshness pending</small></span><button className="studio-link-button" type="button" onClick={onOpenGraph}>Inspect <Icon name="arrow" size={14} /></button></div></div>
    </SectionFrame>
  );
}

function EvidenceSection({ graph, onOpenGraph }: { graph: KnowledgeGraph; onOpenGraph: () => void }) {
  const [query, setQuery] = useState("");
  const selectNode = useDashboardStore((s) => s.selectNode);
  const results = useMemo(() => graph.nodes.filter((node) => {
    if (!query.trim()) return true;
    const haystack = [node.name, node.summary, node.filePath ?? "", ...node.tags].join(" ").toLowerCase();
    return haystack.includes(query.toLowerCase());
  }).slice(0, 8), [graph.nodes, query]);
  return (
    <SectionFrame kicker="Evidence search" title="Ask a question. Keep the source attached." description="Every result is a bounded graph or source anchor. Semantic confidence and access provenance will be supplied by the retrieval service when connected." action={<div className="studio-evidence-scope"><span className="studio-chip studio-chip-positive">Current project</span><span className="studio-chip">ACL filter pending</span></div>}>
      <div className="studio-evidence-layout">
        <div className="studio-panel studio-evidence-list"><div className="studio-evidence-query"><Icon name="search" size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search files, symbols, tags, or summaries" aria-label="Search project evidence" /><span className="studio-key">⌘ K</span></div><div className="studio-evidence-list-head"><span>{results.length} graph-backed results</span><span>Evidence first</span></div>{results.map((node) => <button key={node.id} type="button" className="studio-evidence-result" onClick={() => { selectNode(node.id); onOpenGraph(); }}><div className="studio-evidence-result-top"><span className="studio-status-pill studio-status-pill-neutral">{node.filePath ? "source anchor" : "graph node"}</span><span className="studio-table-muted">{node.type}</span></div><strong>{node.name}</strong><p>{node.summary || "No semantic summary has been published for this node."}</p><div className="studio-evidence-meta"><span>{node.filePath || "No file path"}{node.lineRange ? `:${node.lineRange[0]}–${node.lineRange[1]}` : ""}</span><span>{node.tags.slice(0, 2).join(" · ") || "No tags"}</span></div></button>)}{results.length === 0 && <div className="studio-empty"><Icon name="search" size={18} /><p>No graph-backed result matches this query.</p></div>}</div>
        <div className="studio-panel studio-evidence-inspector"><span className="studio-section-kicker">Evidence contract</span><h2>What a trusted result will show</h2><div className="studio-trust-stack"><div><span className="studio-trust-index">01</span><p><strong>Conclusion</strong><small>What Jarvis believes the evidence says.</small></p></div><div><span className="studio-trust-index">02</span><p><strong>Source range</strong><small>File, symbol, line range, or graph relationship.</small></p></div><div><span className="studio-trust-index">03</span><p><strong>Version anchor</strong><small>Source commit and knowledge epoch.</small></p></div><div><span className="studio-trust-index">04</span><p><strong>Access trace</strong><small>HomeHub grant, freshness, and audit trace.</small></p></div></div><div className="studio-evidence-warning"><Icon name="shield" size={16} /><p>Raw source stays behind the connector grant. The dashboard never becomes an ACL authority.</p></div></div>
      </div>
    </SectionFrame>
  );
}

function ActivitySection({ graph }: { graph: KnowledgeGraph }) {
  return (
    <SectionFrame kicker="Index activity" title="See what changed, and what still needs work." description="The activity surface separates graph availability from connector freshness, semantic enrichment, and publishing state." action={<span className="studio-chip studio-chip-positive"><span className="studio-chip-dot" />Current graph available</span>}>
      <div className="studio-activity-grid"><div className="studio-panel studio-activity-timeline"><div className="studio-panel-heading"><div><span className="studio-section-kicker">Knowledge timeline</span><h2>Current epoch</h2></div><span className="studio-panel-caption">{formatDate(graph.project.analyzedAt)}</span></div><div className="studio-job-line"><span className="studio-job-marker studio-job-marker-done" /><div><strong>Graph snapshot published</strong><p>{graph.nodes.length} nodes and {graph.edges.length} relationships are readable.</p></div><span className="studio-status-pill studio-status-pill-success">Available</span></div><div className="studio-job-line"><span className="studio-job-marker studio-job-marker-pending" /><div><strong>Semantic enrichment</strong><p>Summaries, tags, and semantic edges require the Jetson enrichment queue.</p></div><span className="studio-status-pill studio-status-pill-neutral">Pending</span></div><div className="studio-job-line"><span className="studio-job-marker studio-job-marker-pending" /><div><strong>Connector freshness</strong><p>Source commit reconciliation is not connected to this dashboard yet.</p></div><span className="studio-status-pill studio-status-pill-neutral">Unknown</span></div></div><div className="studio-panel studio-resource-panel"><span className="studio-section-kicker">Index budget</span><h2>Make background work visible.</h2><div className="studio-resource-meter"><span style={{ width: "42%" }} /></div><div className="studio-resource-label"><span>Resident Jetson queue</span><strong>Budget contract pending</strong></div><p>Show CPU, memory, queue age, and batch priority here once the HomeHub inference scheduler exposes them.</p><button type="button" className="studio-button studio-button-quiet">View job contract <Icon name="arrow" size={14} /></button></div></div>
    </SectionFrame>
  );
}

function GroupsSection({ graph }: { graph: KnowledgeGraph }) {
  return (
    <SectionFrame kicker="Jarvis groups" title="Share context through scoped evidence." description="A group is a controlled retrieval relationship between Jarvis boxes. It never grants direct access to another box's source files or vector store." action={<span className="studio-chip">No external grant connected</span>}>
      <div className="studio-groups-grid"><div className="studio-panel studio-group-card"><div className="studio-group-avatar studio-group-avatar-local"><Icon name="spark" size={18} /></div><span className="studio-section-kicker">This Jarvis</span><h2>Local project box</h2><p>Owns the current indexed graph for <strong>{graph.project.name}</strong>.</p><div className="studio-chip-row"><span className="studio-chip studio-chip-positive">Owner scope</span><span className="studio-chip">Local evidence</span></div></div><div className="studio-group-bridge"><span className="studio-group-line" /><span className="studio-group-bridge-label">scoped evidence request</span><span className="studio-group-line" /></div><div className="studio-panel studio-group-card studio-group-card-muted"><div className="studio-group-avatar"><Icon name="users" size={18} /></div><span className="studio-section-kicker">External Jarvis</span><h2>Awaiting group grant</h2><p>Connect another Jarvis only after HomeHub supplies an allowed project scope, TTL, epoch, and provenance.</p><button type="button" className="studio-button studio-button-quiet">Review group contract <Icon name="arrow" size={14} /></button></div></div><div className="studio-panel studio-provenance-panel"><div><span className="studio-section-kicker">Provenance rule</span><h2>Every shared answer carries its producing Jarvis.</h2></div><div className="studio-provenance-chain"><span>request</span><b>→</b><span>local ACL</span><b>→</b><span>remote query</span><b>→</b><span>cited evidence</span></div></div>
    </SectionFrame>
  );
}

function SourcesSection({ graph }: { graph: KnowledgeGraph }) {
  const sourceRows = [{ label: "Current graph endpoint", status: "Graph loaded", detail: `${graph.nodes.length} nodes · commit ${graph.project.gitCommitHash ? graph.project.gitCommitHash.slice(0, 8) : "unavailable"}` }, { label: "NAS connector", status: "Not connected", detail: "Waiting for a HomeHub-owned source grant" }, { label: "GitHub connector", status: "Not connected", detail: "Waiting for repository manifest and source scope" }];
  return <SectionFrame kicker="Sources & devices" title="Know what the box can see." description="Connector cards expose source scope, manifest state, and health without duplicating HomeHub ownership or revocation logic."><div className="studio-panel studio-source-list">{sourceRows.map((row) => <div className="studio-source-row" key={row.label}><span className="studio-source-icon"><Icon name="folder" size={17} /></span><div><strong>{row.label}</strong><small>{row.detail}</small></div><span className={`studio-status-pill ${row.status === "Graph loaded" ? "studio-status-pill-success" : "studio-status-pill-neutral"}`}>{row.status}</span><Icon name="chevron" size={15} /></div>)}</div><div className="studio-source-callout"><Icon name="shield" size={18} /><div><strong>HomeHub supplies the authority.</strong><p>UnderstandYourProjects displays the result of a grant and its epoch. It does not create a second ownership database.</p></div></div></SectionFrame>;
}

function PrivacySection() {
  return <SectionFrame kicker="Privacy & audit" title="Make every answer explainable." description="This surface will visualize the HomeHub access trace that allowed a project query to return evidence."><div className="studio-panel studio-trace-panel"><div className="studio-trace-chain">{["Identity context", "HomeHub policy", "Project scope", "Retrieval", "Evidence answer"].map((step, index) => <div key={step} className="studio-trace-step"><span>{String(index + 1).padStart(2, "0")}</span><strong>{step}</strong>{index < 4 && <b>→</b>}</div>)}</div><div className="studio-trace-fields"><span><small>Grant epoch</small><strong>Awaiting AccessContext</strong></span><span><small>Policy digest</small><strong>Not exposed</strong></span><span><small>Audit trace</small><strong>Created by HomeHub</strong></span></div></div><div className="studio-source-callout"><Icon name="shield" size={18} /><div><strong>Visual trust is a projection, not a permission engine.</strong><p>Raw source, revocation, and audit decisions remain server-side and are never inferred from UI state.</p></div></div></SectionFrame>;
}

function CommandPalette({ graph, onClose, onOpenGraph, onOpenEvidence }: { graph: KnowledgeGraph; onClose: () => void; onOpenGraph: () => void; onOpenEvidence: () => void }) {
  const [query, setQuery] = useState("");
  const suggestions = [
    { label: "What is the architecture of this project?", kind: "Architecture" },
    { label: "Where should a new feature start?", kind: "Entry points" },
    { label: "Which files are most connected?", kind: "Dependencies" },
  ].filter((suggestion) => !query || suggestion.label.toLowerCase().includes(query.toLowerCase()));
  return <div className="studio-command-backdrop" role="presentation" onMouseDown={onClose}><div className="studio-command" role="dialog" aria-modal="true" aria-label="Ask Jarvis about this project" onMouseDown={(event) => event.stopPropagation()}><div className="studio-command-top"><Icon name="spark" size={17} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Ask about ${graph.project.name}`} /><span className="studio-key">ESC</span></div><div className="studio-command-scope"><span className="studio-chip studio-chip-positive">Project scope</span><span className="studio-chip">Graph evidence only</span><span className="studio-command-scope-note">HomeHub access context required for source ranges</span></div><div className="studio-command-list">{suggestions.map((suggestion) => <button type="button" key={suggestion.label} onClick={onOpenEvidence}><span><strong>{suggestion.label}</strong><small>{suggestion.kind} · cite sources in answer</small></span><Icon name="arrow" size={15} /></button>)}<button type="button" className="studio-command-action" onClick={onOpenGraph}><span><strong>Explore the project map</strong><small>Open relationships, layers, and node inspector</small></span><Icon name="grid" size={15} /></button></div><div className="studio-command-footer"><span><span className="studio-key">↵</span> select</span><span><span className="studio-key">⌘ ↵</span> open evidence</span><button type="button" onClick={onClose}>Close</button></div></div></div>;
}

function CoverageBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="studio-coverage-row">
      <div className="studio-coverage-label"><span>{label}</span><span>{value}</span></div>
      <div className="studio-coverage-track"><span style={{ width: `${Math.max(4, Math.min(100, value))}%`, background: color }} /></div>
    </div>
  );
}

function Overview({ graph, onOpenGraph, onAsk }: { graph: KnowledgeGraph; onOpenGraph: () => void; onAsk: () => void }) {
  const setSearchQuery = useDashboardStore((s) => s.setSearchQuery);
  const selectNode = useDashboardStore((s) => s.selectNode);
  const nodeCounts = useMemo(() => getNodeCounts(graph), [graph]);
  const connectedNodes = useMemo(() => getConnectedNodes(graph), [graph]);
  const fileCount = graph.nodes.filter((node) => node.type === "file").length;
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
            <span className="studio-chip studio-chip-positive"><span className="studio-chip-dot" />Graph loaded</span>
            <span className="studio-chip">Sync state from connector pending</span>
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
        <article className="studio-stat-card"><span className="studio-stat-label">Graph nodes</span><strong>{graph.nodes.length}</strong><span className="studio-stat-note">all indexed entities</span></article>
        <article className="studio-stat-card"><span className="studio-stat-label">Logical layers</span><strong>{graph.layers.length}</strong><span className="studio-stat-note">architecture groups</span></article>
        <article className="studio-stat-card studio-stat-card-accent"><span className="studio-stat-label">Review load</span><strong>{complexShare}%</strong><span className="studio-stat-note">nodes marked complex</span></article>
      </section>

      <section className="studio-grid studio-grid-main">
        <article className="studio-panel studio-map-panel">
          <div className="studio-panel-heading"><div><span className="studio-section-kicker">Orientation</span><h2>How this project is shaped</h2></div><button className="studio-link-button" type="button" onClick={onOpenGraph}>Open full map <Icon name="arrow" size={15} /></button></div>
          <RelationshipConstellation graph={graph} onOpenGraph={onOpenGraph} />
        </article>

        <article className="studio-panel studio-panel-tight">
          <div className="studio-panel-heading"><div><span className="studio-section-kicker">Composition</span><h2>What is inside</h2></div><span className="studio-panel-caption">{graph.nodes.length} nodes</span></div>
          <KnowledgeRing graph={graph} />
          <div className="studio-coverage-list">
            <CoverageBar label="Code structure" value={codeShare} color="var(--studio-cyan)" />
            <CoverageBar label="Indexed into layers" value={Math.min(100, layerShare)} color="var(--studio-lime)" />
            <CoverageBar label="Complexity to review" value={complexShare} color="var(--studio-coral)" />
          </div>
          <div className="studio-type-list">
            {nodeCounts.slice(0, 5).map(([type, count]) => <button type="button" key={type} onClick={() => searchAndOpen(type)}><span className="studio-type-mark" /> <span>{type}</span><strong>{count}</strong><Icon name="chevron" size={14} /></button>)}
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
          <div className="studio-timeline-item"><span className="studio-timeline-icon"><Icon name="folder" size={16} /></span><div><strong>Structure indexed</strong><p>{graph.nodes.length} nodes and {graph.edges.length} relationships are available to inspect.</p></div><time>Current graph</time></div>
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

export default function ProjectStudio({ onOpenGraph }: ProjectStudioProps) {
  const graph = useDashboardStore((s) => s.graph);
  const [activeSection, setActiveSection] = useState<StudioSection>("overview");
  const [commandOpen, setCommandOpen] = useState(false);

  if (!graph) {
    return <div className="studio-loading"><span className="studio-live-dot" />Loading project intelligence…</div>;
  }

  return (
    <div className="studio-shell">
      <aside className="studio-sidebar">
        <div className="studio-brand"><div className="studio-brand-mark"><Icon name="spark" size={17} /></div><div><strong>Understand</strong><span>Your Projects</span></div></div>
        <div className="studio-workspace-label">Workspace</div>
        <button className="studio-workspace-switcher" type="button" onClick={() => setActiveSection("projects")}><span className="studio-workspace-avatar">U</span><span><strong>Current workspace</strong><small>Project catalog pending</small></span><Icon name="chevron" size={14} /></button>
        <nav className="studio-nav" aria-label="Project studio navigation">
          {(Object.keys(sectionLabels) as StudioSection[]).map((section) => (
            <button key={section} type="button" className={`studio-nav-item ${activeSection === section ? "is-active" : ""}`} onClick={() => setActiveSection(section)}><Icon name={section === "overview" ? "grid" : section === "projects" || section === "sources" ? "folder" : section === "evidence" ? "search" : section === "activity" ? "pulse" : section === "privacy" ? "shield" : "users"} size={17} /><span>{sectionLabels[section].label}</span>{section === "overview" && <span className="studio-nav-badge">Now</span>}</button>
          ))}
        </nav>
        <div className="studio-sidebar-bottom"><div className="studio-privacy-card"><span className="studio-privacy-icon"><Icon name="shield" size={15} /></span><div><strong>HomeHub boundary</strong><p>Identity and access are supplied by HomeHub.</p></div></div><button type="button" className="studio-help-link">Keyboard shortcuts <span>?</span></button></div>
      </aside>
      <main className="studio-main">
        <header className="studio-topbar"><div className="studio-breadcrumb"><span>Workspace</span><b>/</b><strong>{sectionLabels[activeSection].label}</strong></div><button className="studio-global-search" type="button" onClick={() => setCommandOpen(true)}><Icon name="search" size={17} /><span>Ask about this project…</span><span className="studio-key">⌘ K</span></button><div className="studio-topbar-actions"><span className="studio-sync-status"><span className="studio-live-dot" />Graph loaded</span><button className="studio-avatar" type="button" title="HomeHub access context" aria-label="HomeHub access context">F</button></div></header>
        {activeSection === "overview" ? <Overview graph={graph} onOpenGraph={onOpenGraph} onAsk={() => setCommandOpen(true)} /> : activeSection === "projects" ? <ProjectsSection graph={graph} onOpenGraph={onOpenGraph} /> : activeSection === "evidence" ? <EvidenceSection graph={graph} onOpenGraph={onOpenGraph} /> : activeSection === "activity" ? <ActivitySection graph={graph} /> : activeSection === "collaborate" ? <GroupsSection graph={graph} /> : activeSection === "sources" ? <SourcesSection graph={graph} /> : <PrivacySection />}
      </main>
      {commandOpen && <CommandPalette graph={graph} onClose={() => setCommandOpen(false)} onOpenGraph={() => { setCommandOpen(false); onOpenGraph(); }} onOpenEvidence={() => { setCommandOpen(false); setActiveSection("evidence"); }} />}
    </div>
  );
}
