import { useMemo, type ReactNode } from "react";
import type { FeaturePageProps } from "../../app/routes";
import type { ProjectDigest, ProjectGraph, ProjectSummary } from "../../api/contracts";
import { compact, plural, relativeTime, tildePath } from "../../design/format";
import { useResource } from "../../design/hooks";
import { Icon, type IconName } from "../../design/icons";
import { Markdown } from "../../design/Markdown";
import { Button, Card, Chip, cx, EmptyState, ErrorState, ProgressBar, SectionHeader, Skeleton, StatusDot, type Tone } from "../../design/primitives";
import { AskBox } from "../devices/AskBox";
import { devicesData } from "../devices/data";
import { statusMeta, tierMeta } from "../devices/digest";

/**
 * A deliberately calmer view of Understand Anything than the full Devices
 * workspace. Devices answers “where is this folder?”; this page answers “what
 * did UA learn from it?”. Every value is projected from the existing project
 * and digest APIs. Missing data stays visibly missing instead of becoming a
 * demo number.
 */
export default function UnderstandingPage({ param, navigate }: FeaturePageProps) {
  const projects = useResource((s) => devicesData.projects(s), []);
  const selectedId = param ?? null;
  const selected = projects.data?.projects.find((p) => p.project_id === selectedId) ?? null;
  const digest = useResource((s) => selectedId ? devicesData.project(selectedId, s) : Promise.resolve<ProjectDigest | undefined>(undefined), [selectedId]);
  const graph = useResource((s) => selectedId ? devicesData.projectGraph(selectedId, s) : Promise.resolve<ProjectGraph | undefined>(undefined), [selectedId]);
  const all = projects.data?.projects ?? [];
  const totals = useMemo(() => all.reduce((a, p) => ({
    files: a.files + p.stats.files,
    summarized: a.summarized + p.stats.summarized,
    nodes: a.nodes + p.stats.nodes,
    edges: a.edges + p.stats.edges,
  }), { files: 0, summarized: 0, nodes: 0, edges: 0 }), [all]);
  const active = all.filter((p) => p.status === "analyzing" || p.status === "queued").length;
  const stale = all.filter((p) => p.status === "stale").length;

  return (
    <div className="mx-auto w-full max-w-[1260px] px-4 py-6 sm:px-8 sm:py-8">
      <SectionHeader
        eyebrow="Understand Anything"
        title="See what Jarvis learned."
        description="Understand Anything turns each authorized folder into a readable project map: files, structure, meaning, and evidence. Select a folder to inspect its understanding."
        actions={<Button variant="secondary" icon="devices" onClick={() => navigate("#/devices")}>Manage folders</Button>}
        level={1}
      />

      <ReadingGuide />

      {projects.loading && !projects.data ? <UnderstandingSkeleton /> : null}
      {projects.error && !projects.data ? <Card className="mt-6"><ErrorState error={projects.error} service="Project knowledge (UYP)" title="Couldn't load Understand Anything" onRetry={projects.reload} /></Card> : null}
      {projects.data && all.length === 0 ? (
        <Card className="mt-6"><EmptyState icon="brain" title="Understand Anything has no folders yet" body="Authorize a folder from Devices. Once its first IndexJob finishes, its understanding appears here." action={<Button variant="primary" icon="devices" onClick={() => navigate("#/devices")}>Open Devices</Button>} /></Card>
      ) : null}

      {projects.data && all.length > 0 ? (
        <>
          <SummaryRow totals={totals} folders={all.length} active={active} stale={stale} />
          <div className="mt-6 grid min-w-0 gap-5 @4xl:grid-cols-[minmax(260px,340px)_minmax(0,1fr)]">
            <FolderUnderstandingList projects={all} selectedId={selectedId} onOpen={(id) => navigate(`#/understanding/${encodeURIComponent(id)}`)} />
            {selectedId && selected ? (
              <UnderstandingDetail
                project={selected}
                digest={digest.data}
                loading={digest.loading}
                error={digest.error}
                onRetry={digest.reload}
                graph={graph.data}
                graphLoading={graph.loading}
                graphError={graph.error}
                onGraphRetry={graph.reload}
                onOpenDevices={() => navigate(`#/devices/${encodeURIComponent(selected.project_id)}`)}
              />
            ) : (
              <WelcomeUnderstanding projects={all} onOpen={(id) => navigate(`#/understanding/${encodeURIComponent(id)}`)} />
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}

function ReadingGuide() {
  const steps: Array<{ icon: IconName; label: string; text: string; tone: Tone }> = [
    { icon: "folder", label: "Source", text: "Authorized files and folders", tone: "neutral" },
    { icon: "layers", label: "Structure", text: "Symbols, imports, and layers", tone: "understand" },
    { icon: "brain", label: "Meaning", text: "Summaries and project areas", tone: "retrieve" },
    { icon: "link", label: "Evidence", text: "Answers linked back to files", tone: "respond" },
  ];
  return (
    <Card className="mt-6 overflow-hidden">
      <div className="border-b border-line bg-canvas/45 px-4 py-3 sm:px-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-[13px] font-semibold text-ink">How to read this page</h2>
          <span className="text-[11.5px] text-muted">Derived from the latest completed IndexJob</span>
        </div>
      </div>
      <ol className="grid divide-y divide-line sm:grid-cols-4 sm:divide-x sm:divide-y-0">
        {steps.map((step, i) => (
          <li key={step.label} className="flex min-w-0 gap-3 px-4 py-3 sm:block sm:px-5">
            <div className="flex shrink-0 items-center gap-2 sm:mb-2">
              <span className={cx("grid size-7 place-items-center rounded-[9px] border", guideToneClass(step.tone))}><Icon name={step.icon} size={15} /></span>
              <span className="font-mono text-[10px] text-faint">0{i + 1}</span>
            </div>
            <div className="min-w-0"><div className="text-[12.5px] font-medium text-ink">{step.label}</div><div className="text-[12px] text-muted">{step.text}</div></div>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function guideToneClass(tone: Tone): string {
  const styles: Record<Tone, string> = {
    neutral: "border-line bg-sunk text-muted",
    accent: "border-accent/25 bg-accent-soft text-accent-ink",
    ok: "border-ok/25 bg-ok-soft text-ok",
    warn: "border-warn/25 bg-warn-soft text-warn",
    err: "border-err/25 bg-err-soft text-err",
    info: "border-info/25 bg-info-soft text-info",
    understand: "border-g-understand/25 bg-g-understand/10 text-g-understand",
    retrieve: "border-g-retrieve/25 bg-g-retrieve/10 text-g-retrieve",
    act: "border-g-act/25 bg-g-act/10 text-g-act",
    respond: "border-g-respond/25 bg-g-respond/10 text-g-respond",
  };
  return styles[tone];
}

function SummaryRow({ totals, folders, active, stale }: { totals: { files: number; summarized: number; nodes: number; edges: number }; folders: number; active: number; stale: number }) {
  const items = [
    ["Folders", folders, "Authorized folders with a project projection"],
    ["Files mapped", totals.files, "Files discovered by the Connector"],
    ["Summarized", totals.summarized, "Files with generated semantic context"],
    ["Graph links", totals.edges, "Relationships between understood entities"],
  ] as const;
  return (
    <div className="mt-6 grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]" aria-label="Understanding totals">
      {items.map(([label, value, hint]) => <Card key={label} className="p-3.5"><div className="text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">{label}</div><div className="mt-1 font-serif text-[25px] leading-none text-ink tabular-nums">{compact(value)}</div><div className="mt-1 text-[11.5px] text-muted">{hint}</div></Card>)}
      <Card className="p-3.5"><div className="text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">Attention</div><div className="mt-1 flex items-baseline gap-3"><span className={cx("font-serif text-[25px] leading-none tabular-nums", active ? "text-accent-ink" : "text-ink")}>{active}</span><span className="text-[12px] text-muted">in progress</span></div><div className="mt-1 text-[11.5px] text-muted">{stale ? `${stale} stale · review needed` : "No stale folders"}</div></Card>
    </div>
  );
}

function FolderUnderstandingList({ projects, selectedId, onOpen }: { projects: ProjectSummary[]; selectedId: string | null; onOpen: (id: string) => void }) {
  const sorted = [...projects].sort((a, b) => (Date.parse(b.analyzed_at ?? "") || 0) - (Date.parse(a.analyzed_at ?? "") || 0));
  return (
    <Card className="min-w-0 overflow-hidden">
      <div className="flex items-baseline justify-between gap-2 border-b border-line px-4 py-3.5"><div><h2 className="text-[14px] font-semibold text-ink">Folders understood</h2><p className="mt-0.5 text-[11.5px] text-muted">Choose a folder to inspect its map</p></div><span className="font-mono text-[11px] text-faint">{projects.length}</span></div>
      <ul className="divide-y divide-line">
        {sorted.map((p) => {
          const status = statusMeta(p.status);
          const on = p.project_id === selectedId;
          const totalTier = Object.values(p.tiers ?? {}).reduce((a, n) => a + (Number(n) || 0), 0);
          const understood = (p.tiers?.A ?? 0) + (p.tiers?.B ?? 0);
          return <li key={p.project_id}><button type="button" onClick={() => onOpen(p.project_id)} aria-current={on ? "page" : undefined} className={cx("w-full min-w-0 px-4 py-3.5 text-left transition-colors", on ? "bg-accent-soft" : "hover:bg-sunk/60")}>
            <div className="flex min-w-0 items-start gap-2.5"><span className={cx("mt-0.5 grid size-7 shrink-0 place-items-center rounded-[8px] border", on ? "border-accent/30 bg-surface text-accent-ink" : "border-line bg-sunk text-muted")}><Icon name="folder" size={15} /></span><span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium text-ink">{p.root_name}</span><span className="mt-0.5 block truncate font-mono text-[10.5px] text-faint" title={p.path}>{tildePath(p.path)}</span></span><StatusDot tone={status.tone} pulse={status.pulse} label={status.label} /></div>
            <div className="mt-3 flex items-center justify-between gap-2 text-[11.5px] text-muted"><span>{compact(p.stats.files)} files · {compact(p.stats.nodes)} nodes</span><span>{status.label}</span></div>
            {totalTier > 0 ? <><ProgressBar value={understood} max={totalTier} tone={status.tone === "ok" ? "retrieve" : "accent"} className="mt-2" label={`${understood} of ${totalTier} files semantically understood`} /><div className="mt-1 flex justify-between text-[10.5px] text-faint"><span>semantic coverage</span><span>{Math.round((understood / totalTier) * 100)}%</span></div></> : <div className="mt-2 text-[11px] text-faint">No tier data yet</div>}
          </button></li>;
        })}
      </ul>
    </Card>
  );
}

function WelcomeUnderstanding({ projects, onOpen }: { projects: ProjectSummary[]; onOpen: (id: string) => void }) {
  const first = projects.find((p) => p.status === "analyzed") ?? projects[0];
  return <Card className="flex min-h-[360px] min-w-0 flex-col justify-between overflow-hidden bg-[linear-gradient(140deg,var(--j-surface),var(--j-accent-soft))] p-6 sm:p-8">
    <div><div className="flex items-center gap-2 text-[11px] font-semibold tracking-[0.1em] text-accent-ink uppercase"><Icon name="brain" size={15} /> Understanding workspace</div><h2 className="mt-4 max-w-[14ch] font-serif text-[34px] leading-[1.02] text-ink sm:text-[42px]">Your project memory, explained.</h2><p className="mt-4 max-w-[54ch] text-[14px] leading-relaxed text-ink-2">Pick a folder on the left to see the overview, key files, logical areas, graph layers, and recent changes that Understand Anything extracted.</p></div>
    <div className="mt-8 flex flex-wrap items-center gap-3"><Button variant="primary" iconRight="arrowRight" onClick={() => onOpen(first.project_id)}>Open {first.root_name}</Button><span className="text-[12px] text-muted">The source remains on its authorized device.</span></div>
  </Card>;
}

function UnderstandingDetail({ project, digest, loading, error, onRetry, graph, graphLoading, graphError, onGraphRetry, onOpenDevices }: { project: ProjectSummary; digest?: ProjectDigest; loading: boolean; error: unknown; onRetry: () => void; graph?: ProjectGraph; graphLoading: boolean; graphError: unknown; onGraphRetry: () => void; onOpenDevices: () => void }) {
  const status = statusMeta(project.status);
  return <div className="min-w-0 space-y-5">
    <Card className="overflow-hidden">
      <div className="border-b border-line bg-canvas/45 px-5 py-4 sm:px-6"><div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><Chip tone={status.tone}><StatusDot tone={status.tone} pulse={status.pulse} />{status.label}</Chip><span className="text-[12px] text-muted">last analyzed {relativeTime(project.analyzed_at)}</span></div><h2 className="mt-2 truncate font-serif text-[26px] text-ink" title={project.root_name}>{project.root_name}</h2><div className="mt-0.5 break-all font-mono text-[11.5px] text-faint">{tildePath(project.path)}</div></div><Button size="sm" variant="secondary" icon="devices" onClick={onOpenDevices}>Open in Devices</Button></div></div>
      <div className="grid gap-0 sm:grid-cols-4"><InsightStat label="Files" value={project.stats.files} icon="file" /><InsightStat label="Summarized" value={project.stats.summarized} icon="brain" /><InsightStat label="Graph nodes" value={project.stats.nodes} icon="layers" /><InsightStat label="Graph edges" value={project.stats.edges} icon="link" /></div>
    </Card>
    {loading && !digest ? <DigestSkeleton /> : null}
    {error && !digest ? <Card><ErrorState error={error} service="Project digest" title="Understanding details unavailable" onRetry={onRetry} /></Card> : null}
    {digest ? <DigestSections digest={digest} project={project} graph={graph} graphLoading={graphLoading} graphError={graphError} onGraphRetry={onGraphRetry} /> : null}
  </div>;
}

function InsightStat({ label, value, icon }: { label: string; value: number; icon: IconName }) { return <div className="border-b border-line px-5 py-3.5 first:sm:border-l-0 sm:border-b-0 sm:border-l"><div className="flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase"><Icon name={icon} size={13} />{label}</div><div className="mt-1 font-serif text-[24px] text-ink tabular-nums">{compact(value)}</div></div>; }

function DigestSections({ digest, project, graph, graphLoading, graphError, onGraphRetry }: { digest: ProjectDigest; project: ProjectSummary; graph?: ProjectGraph; graphLoading: boolean; graphError: unknown; onGraphRetry: () => void }) {
  return <div className="space-y-5">
    <div className="grid min-w-0 gap-5 @3xl:grid-cols-[minmax(0,1.25fr)_minmax(260px,.75fr)]">
      <div className="min-w-0 space-y-5"><Panel title="What UA understood" icon="brain" hint="Generated project overview">{digest.overview ? <Markdown text={digest.overview} className="text-[14px] leading-relaxed text-ink-2" /> : <Missing label="No overview was returned for this run." />}</Panel><Panel title="Key files and why they matter" icon="file" hint="Highest-value source evidence"><KeyFileList digest={digest} /></Panel><Panel title="Ask about this understanding" icon="search" hint="Answers include source files"><AskBox key={project.project_id} projectId={project.project_id} name={project.root_name} /></Panel></div>
      <div className="min-w-0 space-y-5"><Panel title="Logical areas" icon="folder" hint="How the folder is organized"><AreaList digest={digest} /></Panel><Panel title="Understanding layers" icon="layers" hint="Extracted graph concepts"><LayerList digest={digest} /></Panel><Panel title="Recent learning" icon="activity" hint={digest.activity.window || "Latest changes"}><RecentLearning digest={digest} /></Panel></div>
    </div>
    <StructureTour graph={graph} loading={graphLoading} error={graphError} onRetry={onGraphRetry} />
  </div>;
}

function Panel({ title, icon, hint, children }: { title: string; icon: IconName; hint?: string; children: ReactNode }) { return <Card className="min-w-0 p-4 sm:p-5"><div className="mb-3 flex flex-wrap items-baseline justify-between gap-2"><h3 className="flex items-center gap-2 text-[14px] font-semibold text-ink"><Icon name={icon} size={15} className="text-accent-ink" />{title}</h3>{hint ? <span className="text-[11px] text-muted">{hint}</span> : null}</div>{children}</Card>; }

function KeyFileList({ digest }: { digest: ProjectDigest }) { if (!digest.key_files.length) return <Missing label="No key files were returned." />; return <ul className="divide-y divide-line">{digest.key_files.slice(0, 8).map((f) => { const t = tierMeta(f.tier); return <li key={f.file} className="flex min-w-0 gap-2.5 py-2.5 first:pt-0 last:pb-0"><Chip tone={t.tone} mono title={t.hint}>{t.label}</Chip><div className="min-w-0 flex-1"><div className="truncate font-mono text-[12px] text-ink" title={f.file}>{f.file}</div>{f.purpose ? <div className="mt-0.5 text-[12.5px] text-ink-2">{f.purpose}</div> : null}</div></li>; })}</ul>; }

function AreaList({ digest }: { digest: ProjectDigest }) { if (!digest.areas.length) return <Missing label="No logical areas were returned." />; return <ul className="space-y-2">{digest.areas.slice(0, 8).map((a) => <li key={a.folder} className="rounded-control border border-line bg-canvas/35 p-3"><div className="flex items-baseline justify-between gap-2"><span className="truncate font-mono text-[12px] text-ink">{a.folder}</span><span className="shrink-0 text-[11px] text-muted">{plural(a.files, "file")}</span></div><p className="mt-1 text-[12px] leading-relaxed text-muted">{a.summary || "No area summary yet."}</p></li>)}</ul>; }

function LayerList({ digest }: { digest: ProjectDigest }) { if (!digest.graph.layers.length) return <Missing label="The graph has no layers yet." />; const max = Math.max(1, ...digest.graph.layers.map((x) => x.files)); return <ul className="space-y-3">{digest.graph.layers.map((layer) => <li key={layer.name}><div className="flex items-center justify-between gap-2 text-[12px]"><span className="truncate text-ink-2">{layer.name}</span><span className="font-mono text-[11px] text-muted">{compact(layer.files)}</span></div><ProgressBar value={layer.files} max={max} tone="understand" className="mt-1.5" label={`${layer.name}: ${layer.files} files`} /></li>)}</ul>; }

function RecentLearning({ digest }: { digest: ProjectDigest }) { const changes = digest.activity.changed.slice(0, 5); return <div>{digest.activity.by_day.length ? <div className="mb-3 flex h-14 items-end gap-1">{digest.activity.by_day.slice(-14).map((d) => <span key={d.date} className="min-w-0 flex-1 rounded-t-[3px] bg-g-understand/60" style={{ height: `${Math.max(4, Math.min(100, d.count * 18))}%` }} title={`${d.date}: ${d.count} changes`} />)}</div> : null}{changes.length ? <ul className="space-y-2">{changes.map((c) => <li key={`${c.file}-${c.mtime}`} className="flex min-w-0 items-center gap-2 text-[11.5px]"><StatusDot tone="understand" /><span className="min-w-0 flex-1 truncate font-mono text-ink" title={c.file}>{c.file}</span><span className="shrink-0 text-faint">{relativeTime(c.mtime)}</span></li>)}</ul> : <Missing label="No recent changes were returned." />}</div>; }

function StructureTour({ graph, loading, error, onRetry }: { graph?: ProjectGraph; loading: boolean; error: unknown; onRetry: () => void }) {
  if (loading && !graph) return <Card className="p-5" aria-busy="true"><Skeleton className="h-4 w-40" /><Skeleton className="mt-3 h-3 w-3/4" /><div className="mt-5 grid gap-3 sm:grid-cols-3"><Skeleton className="h-20" /><Skeleton className="h-20" /><Skeleton className="h-20" /></div></Card>;
  if (error && !graph) return <Card><ErrorState compact error={error} service="Understand Anything graph" title="Structure map unavailable" onRetry={onRetry} /></Card>;
  if (!graph) return <Card className="p-5"><PanelHeading title="Structure & tour" icon="layers" hint="Understand Anything graph" /><Missing label="No graph projection was returned for this folder yet." /></Card>;

  const nodeById = new Map(graph.nodes.map((node, i) => [String(node.id ?? i), node]));
  const nameFor = (id: unknown) => {
    const node = nodeById.get(String(id));
    return stringValue(node?.name) || String(id ?? "unknown");
  };
  const projectName = stringValue(graph.project.name);
  const languages = stringArray(graph.project.languages);
  const tour = graph.tour.slice(0, 4);
  const nodes = graph.nodes.slice(0, 8);
  const edges = graph.edges.slice(0, 7);
  return <Card className="min-w-0 overflow-hidden">
    <div className="border-b border-line bg-canvas/45 px-4 py-4 sm:px-5"><div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><PanelHeading title="Structure & tour" icon="layers" hint={`${graph.kind ?? "project"} graph${graph.version ? ` · ${graph.version}` : ""}`} /><p className="mt-1 max-w-[72ch] text-[12.5px] leading-relaxed text-muted">This is the bounded structural view of {projectName || "this folder"}. It shows how UA grouped the code and where to start reading, without exposing source contents.</p></div>{languages.length ? <div className="flex max-w-[260px] flex-wrap justify-end gap-1.5">{languages.slice(0, 6).map((language) => <Chip key={language} mono>{language}</Chip>)}</div> : null}</div></div>
    <div className="grid divide-y divide-line sm:grid-cols-3 sm:divide-x sm:divide-y-0"><GraphMetric label="Nodes" value={graph.counts.nodes} hint={graph.truncated.nodes ? "first 500 shown" : "entities in the map"} /><GraphMetric label="Relations" value={graph.counts.edges} hint={graph.truncated.edges ? "first 1,000 shown" : "links between entities"} /><GraphMetric label="Layers" value={graph.counts.layers} hint={graph.truncated.layers ? "first 200 shown" : "logical groups"} /></div>
    <div className="grid min-w-0 gap-5 border-t border-line p-4 sm:p-5 @3xl:grid-cols-[minmax(0,1.05fr)_minmax(0,.95fr)]">
      <div className="min-w-0 space-y-5"><div><h4 className="text-[13px] font-semibold text-ink">Guided tour</h4><p className="mt-0.5 text-[11.5px] text-muted">A suggested path through the project structure.</p>{tour.length ? <ol className="mt-3 space-y-2">{tour.map((step, i) => <li key={`${String(step.order ?? i)}-${String(step.title ?? i)}`} className="flex min-w-0 gap-3 rounded-control border border-line bg-canvas/35 p-3"><span className="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft font-mono text-[10.5px] text-accent-ink">{String(step.order ?? i + 1)}</span><div className="min-w-0"><div className="text-[12.5px] font-medium text-ink">{stringValue(step.title) || `Tour step ${i + 1}`}</div><p className="mt-0.5 text-[12px] leading-relaxed text-muted">{stringValue(step.description) || "Follow the related nodes to understand this area."}</p><span className="mt-1 inline-block text-[10.5px] text-faint">{arrayLength(step.nodeIds)} mapped nodes</span></div></li>)}</ol> : <Missing label="UA has not produced a guided tour for this run." />}</div><div><h4 className="text-[13px] font-semibold text-ink">Logical layers</h4><p className="mt-0.5 text-[11.5px] text-muted">Groups extracted from the graph.</p>{graph.layers.length ? <ul className="mt-3 grid gap-2 sm:grid-cols-2">{graph.layers.slice(0, 8).map((layer, i) => <li key={String(layer.id ?? layer.name ?? i)} className="rounded-control border border-line p-2.5"><div className="flex items-baseline justify-between gap-2"><span className="truncate text-[12px] font-medium text-ink">{stringValue(layer.name) || `Layer ${i + 1}`}</span><span className="shrink-0 font-mono text-[10.5px] text-faint">{arrayLength(layer.nodeIds)} nodes</span></div>{stringValue(layer.description) ? <p className="mt-1 text-[11.5px] leading-relaxed text-muted">{stringValue(layer.description)}</p> : null}</li>)}</ul> : <Missing label="No layers returned." />}</div></div>
      <div className="min-w-0 space-y-5"><div><h4 className="text-[13px] font-semibold text-ink">Top nodes</h4><p className="mt-0.5 text-[11.5px] text-muted">The entities UA considers useful starting points.</p>{nodes.length ? <ul className="mt-3 divide-y divide-line">{nodes.map((node, i) => <li key={String(node.id ?? i)} className="flex min-w-0 items-start gap-2.5 py-2.5 first:pt-0 last:pb-0"><span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-[7px] bg-g-understand/10 text-g-understand"><Icon name={node.type === "file" ? "file" : node.type === "class" ? "layers" : "sparkle"} size={13} /></span><span className="min-w-0 flex-1"><span className="block truncate text-[12.5px] font-medium text-ink">{stringValue(node.name) || `Node ${i + 1}`}</span><span className="block truncate font-mono text-[10.5px] text-faint" title={stringValue(node.filePath)}>{stringValue(node.filePath) || stringValue(node.type) || "semantic entity"}</span></span></li>)}</ul> : <Missing label="No nodes returned." />}</div><div><h4 className="text-[13px] font-semibold text-ink">Relations to follow</h4><p className="mt-0.5 text-[11.5px] text-muted">A readable sample of the graph edges.</p>{edges.length ? <ul className="mt-3 space-y-2">{edges.map((edge, i) => <li key={`${String(edge.source)}-${String(edge.target)}-${i}`} className="flex min-w-0 items-center gap-2 rounded-control border border-line bg-canvas/35 px-2.5 py-2 text-[11.5px]"><span className="min-w-0 truncate text-ink" title={nameFor(edge.source)}>{nameFor(edge.source)}</span><Icon name="arrowRight" size={13} className="shrink-0 text-accent-ink" /><span className="min-w-0 truncate text-ink" title={nameFor(edge.target)}>{nameFor(edge.target)}</span><Chip mono className="ml-auto shrink-0">{stringValue(edge.type) || "related"}</Chip></li>)}</ul> : <Missing label="No relations returned." />}</div></div>
    </div>
    {(graph.truncated.nodes || graph.truncated.edges || graph.truncated.layers || graph.truncated.tour) ? <div className="border-t border-line px-4 py-3 text-[11.5px] text-muted sm:px-5">This view is intentionally bounded for readability. Open the full project map from Devices for the complete exploration surface.</div> : null}
  </Card>;
}

function PanelHeading({ title, icon, hint }: { title: string; icon: IconName; hint?: string }) { return <div className="flex flex-wrap items-center gap-2"><h3 className="flex items-center gap-2 text-[14px] font-semibold text-ink"><Icon name={icon} size={15} className="text-accent-ink" />{title}</h3>{hint ? <span className="text-[11px] text-muted">{hint}</span> : null}</div>; }
function GraphMetric({ label, value, hint }: { label: string; value: number; hint: string }) { return <div className="px-4 py-3 sm:px-5"><div className="text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">{label}</div><div className="mt-1 font-serif text-[23px] text-ink tabular-nums">{compact(value)}</div><div className="text-[11px] text-muted">{hint}</div></div>; }
function stringValue(value: unknown): string { return typeof value === "string" ? value : value == null ? "" : String(value); }
function stringArray(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []; }
function arrayLength(value: unknown): number { return Array.isArray(value) ? value.length : 0; }

function Missing({ label }: { label: string }) { return <div className="rounded-control border border-dashed border-line-strong px-3 py-4 text-center text-[12.5px] text-muted">{label}</div>; }

function DigestSkeleton() { return <div className="grid gap-5 @3xl:grid-cols-2" aria-busy="true"><Card className="p-5"><Skeleton className="h-4 w-32" /><Skeleton className="mt-4 h-20" /><Skeleton className="mt-3 h-4 w-4/5" /></Card><Card className="p-5"><Skeleton className="h-4 w-24" /><Skeleton className="mt-4 h-32" /></Card></div>; }

function UnderstandingSkeleton() { return <div className="mt-6 grid gap-3 sm:grid-cols-4" aria-busy="true">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24 rounded-card" />)}</div>; }
