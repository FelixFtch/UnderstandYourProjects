import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useDashboardStore } from "../store";
import type { GraphNode, KnowledgeGraph } from "@understand-anything/core/types";

type StudioSection = "overview" | "projects" | "evidence" | "activity" | "collaborate";

interface ProjectStudioProps {
  onOpenGraph: () => void;
}

const sectionLabels: Record<StudioSection, { label: string; detail: string }> = {
  overview: { label: "Overview", detail: "Project command center" },
  projects: { label: "Projects", detail: "Your indexed work" },
  evidence: { label: "Evidence", detail: "Trace every answer" },
  activity: { label: "Activity", detail: "Freshness and changes" },
  collaborate: { label: "Jarvis groups", detail: "Shared project context" },
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
  for (const edge of graph.edges) {
    connections.set(edge.source, (connections.get(edge.source) ?? 0) + 1);
    connections.set(edge.target, (connections.get(edge.target) ?? 0) + 1);
  }
  return Array.from(connections.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([id, connectionCount]) => {
      const node = graph.nodes.find((candidate) => candidate.id === id);
      return node ? { ...node, connectionCount } : null;
    })
    .filter((node): node is GraphNode & { connectionCount: number } => node !== null);
}

function CoverageBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="studio-coverage-row">
      <div className="studio-coverage-label"><span>{label}</span><span>{value}</span></div>
      <div className="studio-coverage-track"><span style={{ width: `${Math.max(4, Math.min(100, value))}%`, background: color }} /></div>
    </div>
  );
}

function Overview({ graph, onOpenGraph }: { graph: KnowledgeGraph; onOpenGraph: () => void }) {
  const setSearchQuery = useDashboardStore((s) => s.setSearchQuery);
  const selectNode = useDashboardStore((s) => s.selectNode);
  const nodeCounts = useMemo(() => getNodeCounts(graph), [graph]);
  const connectedNodes = useMemo(() => getConnectedNodes(graph), [graph]);
  const fileCount = graph.nodes.filter((node) => node.type === "file").length;
  const complexCount = graph.nodes.filter((node) => node.complexity === "complex").length;
  const codeCount = graph.nodes.filter((node) => ["file", "function", "class", "module"].includes(node.type)).length;
  const codeShare = graph.nodes.length ? Math.round((codeCount / graph.nodes.length) * 100) : 0;
  const complexShare = graph.nodes.length ? Math.round((complexCount / graph.nodes.length) * 100) : 0;
  const layerShare = graph.nodes.length ? Math.round((graph.layers.reduce((sum, layer) => sum + layer.nodeIds.length, 0) / graph.nodes.length) * 100) : 0;

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
            <span className="studio-chip studio-chip-positive"><span className="studio-chip-dot" />Index available</span>
            <span className="studio-chip">Analyzed {formatDate(graph.project.analyzedAt)}</span>
            {graph.project.gitCommitHash && <span className="studio-chip studio-chip-mono">{graph.project.gitCommitHash.slice(0, 8)}</span>}
          </div>
        </div>
        <div className="studio-hero-actions">
          <button className="studio-button studio-button-quiet" type="button" onClick={onOpenGraph}><Icon name="grid" size={16} /> Explore graph</button>
          <button className="studio-button studio-button-primary" type="button" onClick={() => searchAndOpen("")}><Icon name="spark" size={16} /> Ask Jarvis <span className="studio-key">⌘ K</span></button>
        </div>
      </section>

      <section className="studio-stat-grid" aria-label="Project index statistics">
        <article className="studio-stat-card"><span className="studio-stat-label">Indexed files</span><strong>{fileCount || graph.nodes.length}</strong><span className="studio-stat-note">source nodes</span></article>
        <article className="studio-stat-card"><span className="studio-stat-label">Relationships</span><strong>{graph.edges.length}</strong><span className="studio-stat-note">evidence links</span></article>
        <article className="studio-stat-card"><span className="studio-stat-label">Logical layers</span><strong>{graph.layers.length}</strong><span className="studio-stat-note">architecture groups</span></article>
        <article className="studio-stat-card studio-stat-card-accent"><span className="studio-stat-label">Project health</span><strong>{complexShare < 30 ? "Clear" : "Dense"}</strong><span className="studio-stat-note">based on indexed complexity</span></article>
      </section>

      <section className="studio-grid studio-grid-main">
        <article className="studio-panel studio-map-panel">
          <div className="studio-panel-heading"><div><span className="studio-section-kicker">Orientation</span><h2>How this project is shaped</h2></div><button className="studio-link-button" type="button" onClick={onOpenGraph}>Open full map <Icon name="arrow" size={15} /></button></div>
          <div className="studio-map-visual" aria-label="Architecture map preview">
            <div className="studio-map-orbit studio-map-orbit-one" />
            <div className="studio-map-orbit studio-map-orbit-two" />
            <div className="studio-map-center"><Icon name="spark" size={20} /><span>{graph.project.name}</span><small>{graph.layers.length} layers</small></div>
            {graph.layers.slice(0, 6).map((layer, index) => (
              <button key={layer.id} type="button" className={`studio-map-node studio-map-node-${index + 1}`} onClick={onOpenGraph} title={`Open ${layer.name}`}>
                <span>{layer.name}</span><small>{layer.nodeIds.length} nodes</small>
              </button>
            ))}
          </div>
          <div className="studio-map-legend"><span><i className="studio-legend-dot studio-legend-dot-code" />Code</span><span><i className="studio-legend-dot studio-legend-dot-domain" />Domain</span><span><i className="studio-legend-dot studio-legend-dot-infra" />Infrastructure</span><span><i className="studio-legend-dot studio-legend-dot-edge" />Relationship</span></div>
        </article>

        <article className="studio-panel studio-panel-tight">
          <div className="studio-panel-heading"><div><span className="studio-section-kicker">Composition</span><h2>What is inside</h2></div><span className="studio-panel-caption">{graph.nodes.length} nodes</span></div>
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

function EmptySection({ section }: { section: StudioSection }) {
  const meta = sectionLabels[section];
  return (
    <div className="studio-empty-state">
      <span className="studio-empty-state-icon"><Icon name={section === "collaborate" ? "users" : section === "activity" ? "pulse" : section === "evidence" ? "search" : "folder"} size={24} /></span>
      <span className="studio-section-kicker">{meta.label}</span>
      <h1>{meta.detail}</h1>
      <p>This surface is designed and ready for its data contract. The current graph remains the source of truth; connect the corresponding index or HomeHub capability before showing results here.</p>
      <span className="studio-chip">Design state · awaiting connector</span>
    </div>
  );
}

export default function ProjectStudio({ onOpenGraph }: ProjectStudioProps) {
  const graph = useDashboardStore((s) => s.graph);
  const [activeSection, setActiveSection] = useState<StudioSection>("overview");

  if (!graph) {
    return <div className="studio-loading"><span className="studio-live-dot" />Loading project intelligence…</div>;
  }

  return (
    <div className="studio-shell">
      <aside className="studio-sidebar">
        <div className="studio-brand"><div className="studio-brand-mark"><Icon name="spark" size={17} /></div><div><strong>Understand</strong><span>Your Projects</span></div></div>
        <div className="studio-workspace-label">Workspace</div>
        <button className="studio-workspace-switcher" type="button" onClick={() => setActiveSection("projects")}><span className="studio-workspace-avatar">U</span><span><strong>Personal workspace</strong><small>1 indexed project</small></span><Icon name="chevron" size={14} /></button>
        <nav className="studio-nav" aria-label="Project studio navigation">
          {(Object.keys(sectionLabels) as StudioSection[]).map((section) => (
            <button key={section} type="button" className={`studio-nav-item ${activeSection === section ? "is-active" : ""}`} onClick={() => setActiveSection(section)}><Icon name={section === "overview" ? "grid" : section === "projects" ? "folder" : section === "evidence" ? "search" : section === "activity" ? "pulse" : "users"} size={17} /><span>{sectionLabels[section].label}</span>{section === "overview" && <span className="studio-nav-badge">Now</span>}</button>
          ))}
        </nav>
        <div className="studio-sidebar-bottom"><div className="studio-privacy-card"><span className="studio-privacy-icon"><Icon name="shield" size={15} /></span><div><strong>HomeHub protected</strong><p>Identity and access remain authoritative.</p></div></div><button type="button" className="studio-help-link">Keyboard shortcuts <span>?</span></button></div>
      </aside>
      <main className="studio-main">
        <header className="studio-topbar"><div className="studio-breadcrumb"><span>Workspace</span><b>/</b><strong>{sectionLabels[activeSection].label}</strong></div><button className="studio-global-search" type="button" onClick={onOpenGraph}><Icon name="search" size={17} /><span>Ask about this project…</span><span className="studio-key">⌘ K</span></button><div className="studio-topbar-actions"><span className="studio-sync-status"><span className="studio-live-dot" />Index ready</span><button className="studio-avatar" type="button" title="HomeHub identity context">F</button></div></header>
        {activeSection === "overview" ? <Overview graph={graph} onOpenGraph={onOpenGraph} /> : <EmptySection section={activeSection} />}
      </main>
    </div>
  );
}
