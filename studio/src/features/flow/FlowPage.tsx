// Flow — read-only view of the agent flow spec, lit by the most recent Jarvis turn.
//
// Cross-feature exception (documented in features/jarvis/lastTrace.ts): this file imports
// `useLastTrace` from features/jarvis and nothing else from another feature.
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { FlowGroup, FlowNodeSpec, FlowSpec } from "../../api/contracts";
import type { FeaturePageProps } from "../../app/routes";
import { formatMs, plural, relativeTime } from "../../design/format";
import { useResource } from "../../design/hooks";
import { Icon } from "../../design/icons";
import { Card, Chip, cx, EmptyState, ErrorState, Segmented, SectionHeader, Skeleton, StatusDot } from "../../design/primitives";
import { useLastTrace } from "../jarvis/lastTrace";
import { flowData, type TraceFrame } from "./data";
import { columns, edgeKey, edgePath, GROUP_INFO, nodeRuns, traversed, type NodeRun, type Rect } from "./layout";

const GROUP_TEXT: Record<FlowGroup, string> = { understand: "text-g-understand", retrieve: "text-g-retrieve", act: "text-g-act", respond: "text-g-respond" };
const GROUP_BORDER: Record<FlowGroup, string> = { understand: "border-l-g-understand", retrieve: "border-l-g-retrieve", act: "border-l-g-act", respond: "border-l-g-respond" };
const GROUP_TINT: Record<FlowGroup, string> = { understand: "bg-g-understand/8", retrieve: "bg-g-retrieve/8", act: "bg-g-act/8", respond: "bg-g-respond/8" };
const GROUP_BAR: Record<FlowGroup, string> = { understand: "bg-g-understand", retrieve: "bg-g-retrieve", act: "bg-g-act", respond: "bg-g-respond" };

export default function FlowPage(_props: FeaturePageProps) {
  const flows = useResource(() => flowData.flows(), []);
  const [name, setName] = useState("studio");
  const spec = useResource(() => flowData.flow(name), [name]);
  const recent = useResource((s) => flowData.recentTrace(s), []);
  const live = useLastTrace();
  const [selected, setSelected] = useState<string | null>(null);

  // the live store wins; otherwise the latest persisted reply with a trace
  const trace: { frames: TraceFrame[]; at: string | null; question: string | null; live: boolean } | null =
    live.turnId ? { frames: live.frames, at: live.startedAt, question: live.question, live: live.live }
      : recent.data ? { frames: recent.data.frames, at: recent.data.at, question: recent.data.question, live: false } : null;

  const runs = useMemo(() => nodeRuns(trace?.frames ?? []), [trace?.frames]);
  const names = flows.data?.flows.map((f) => f.name) ?? ["studio"];
  const options = (names.includes(name) ? names : [name, ...names]).map((n) => ({ value: n, label: n }));

  return (
    <div className="@container mx-auto w-full max-w-[1320px] space-y-6 px-4 py-6 sm:px-8 sm:py-8">
      <SectionHeader
        level={1}
        eyebrow="Flow"
        title="How Jarvis thinks"
        description="Every message passes through these steps, left to right: understand, retrieve, act, respond. The path of your most recent Jarvis turn is lit up."
        actions={options.length > 1 ? <Segmented label="Flow" value={name} options={options} onChange={(v) => { setName(v); setSelected(null); }} /> : null}
      />

      <LastTurn trace={trace} runs={runs} loading={recent.loading && !live.turnId} />

      <div className="grid gap-5 @6xl:grid-cols-[minmax(0,1fr)_300px]">
        <Card className="@container min-w-0 p-4 sm:p-5">
          {spec.loading && !spec.data ? <GraphSkeleton /> : null}
          {spec.error && !spec.data ? <ErrorState error={spec.error} service="Agent runtime" title="Couldn't load this flow" onRetry={spec.reload} /> : null}
          {spec.data && spec.data.nodes.length === 0 ? <EmptyState icon="flow" title="This flow has no nodes" body="The agent runtime returned an empty spec." /> : null}
          {spec.data && spec.data.nodes.length ? (
            <>
              {spec.data.description ? <p className="mb-4 text-[13px] text-muted">{spec.data.description} <span className="font-mono text-faint">v{spec.data.version}</span></p> : null}
              <Graph spec={spec.data} runs={runs} hasTrace={!!trace} selected={selected} onSelect={setSelected} />
            </>
          ) : null}
        </Card>
        <NodeDetail spec={spec.data ?? null} id={selected} runs={runs} onSelect={setSelected} />
      </div>
    </div>
  );
}

function LastTurn({ trace, runs, loading }: { trace: { frames: TraceFrame[]; at: string | null; question: string | null; live: boolean } | null; runs: Record<string, NodeRun>; loading: boolean }) {
  if (loading) return <Skeleton className="h-[62px] rounded-card" />;
  if (!trace) {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-card border border-dashed border-line-strong px-4 py-3 text-[13.5px] text-muted">
        <Icon name="info" size={16} />
        <span className="min-w-0 flex-1">No Jarvis turn to show yet. Ask Jarvis something and watch its path light up here.</span>
        <a href="#/jarvis" className="font-medium text-accent-ink hover:underline">Open Jarvis →</a>
      </div>
    );
  }
  const vals = Object.values(runs);
  const steps = vals.filter((r) => r.status !== "skip").length;
  const tools = vals.reduce((a, r) => a + r.tools.length, 0);
  const ms = vals.reduce((a, r) => a + (r.ms ?? 0), 0);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-card border border-line bg-surface px-4 py-3 shadow-card">
      <StatusDot tone={trace.live ? "accent" : "ok"} pulse={trace.live} />
      <div className="min-w-0 flex-[1_1_240px]">
        <div className="text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">{trace.live ? "Running now" : "Last Jarvis turn"}{trace.at ? ` · ${relativeTime(trace.at)}` : ""}</div>
        <div className="truncate text-[14px] text-ink">{trace.question ? `“${trace.question}”` : "(question not recorded)"}</div>
      </div>
      <div className="text-[12.5px] text-muted">{plural(steps, "step")} · {plural(tools, "tool")}{ms ? ` · ${formatMs(ms)}` : ""}</div>
      <a href="#/jarvis" className="text-[12.5px] font-medium text-accent-ink hover:underline">Open chat →</a>
    </div>
  );
}

function Graph({ spec, runs, hasTrace, selected, onSelect }: {
  spec: FlowSpec; runs: Record<string, NodeRun>; hasTrace: boolean; selected: string | null; onSelect: (id: string) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [geo, setGeo] = useState<{ w: number; h: number; rects: Record<string, Rect> }>({ w: 0, h: 0, rects: {} });
  const cols = useMemo(() => columns(spec), [spec]);
  const lit = useMemo(() => traversed(spec.edges, runs), [spec.edges, runs]);

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const measure = () => {
      const base = el.getBoundingClientRect();
      const rects: Record<string, Rect> = {};
      el.querySelectorAll<HTMLElement>("[data-node]").forEach((n) => {
        const r = n.getBoundingClientRect();
        rects[n.dataset.node!] = { x: r.left - base.left, y: r.top - base.top, w: r.width, h: r.height };
      });
      setGeo({ w: base.width, h: base.height, rects });
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [spec, runs]);

  const outgoing = (id: string) => spec.edges.filter((e) => e.from === id).map((e) => spec.nodes.find((n) => n.id === e.to)?.label ?? e.to);

  return (
    <div ref={wrap} className="relative">
      <svg className="pointer-events-none absolute inset-0 hidden overflow-visible @3xl:block" width={geo.w} height={geo.h} aria-hidden="true">
        <defs>
          <marker id="flow-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 L8 4 L0 8 z" fill="var(--j-line-strong)" />
          </marker>
          <marker id="flow-arrow-lit" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 L8 4 L0 8 z" fill="var(--j-accent)" />
          </marker>
        </defs>
        {[...spec.edges].sort((a, b) => Number(lit.has(edgeKey(a))) - Number(lit.has(edgeKey(b)))).map((e) => {
          const a = geo.rects[e.from], b = geo.rects[e.to];
          if (!a || !b) return null;
          const on = lit.has(edgeKey(e));
          return (
            <path
              key={edgeKey(e)}
              d={edgePath(a, b)}
              fill="none"
              stroke={on ? "var(--j-accent)" : "var(--j-line-strong)"}
              strokeWidth={on ? 2 : 1.25}
              strokeDasharray={hasTrace && !on ? "3 4" : undefined}
              markerEnd={`url(#${on ? "flow-arrow-lit" : "flow-arrow"})`}
            />
          );
        })}
      </svg>

      <div className="relative grid gap-6 @3xl:grid-cols-4 @3xl:gap-10">
        {cols.map((col) => (
          <section key={col.group} className="min-w-0" aria-label={GROUP_INFO[col.group].title}>
            <div className={cx("h-1 w-10 rounded-full", GROUP_BAR[col.group])} />
            <h3 className={cx("mt-2 text-[12px] font-semibold tracking-[0.08em] uppercase", GROUP_TEXT[col.group])}>{GROUP_INFO[col.group].title}</h3>
            <p className="mt-0.5 min-h-[34px] text-[12px] leading-snug text-muted">{GROUP_INFO[col.group].body}</p>
            <div className="mt-3 space-y-3 @3xl:space-y-5">
              {col.nodes.length === 0 ? <div className="rounded-[12px] border border-dashed border-line px-3 py-4 text-center text-[12px] text-faint">No steps</div> : null}
              {col.nodes.map((n) => (
                <NodeCard key={n.id} node={n} run={runs[n.id]} dim={hasTrace && !runs[n.id]} selected={selected === n.id} onSelect={onSelect} next={outgoing(n.id)} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function NodeCard({ node, run, dim, selected, onSelect, next }: { node: FlowNodeSpec; run?: NodeRun; dim: boolean; selected: boolean; onSelect: (id: string) => void; next: string[] }) {
  const ran = !!run && run.status !== "skip";
  return (
    <button
      type="button"
      data-node={node.id}
      onClick={() => onSelect(node.id)}
      aria-pressed={selected}
      className={cx(
        "relative block w-full rounded-[12px] border border-l-[3px] bg-surface px-3 py-2.5 text-left transition-[opacity,box-shadow,border-color]",
        GROUP_BORDER[node.group],
        ran ? cx(GROUP_TINT[node.group], "border-y-line-strong border-r-line-strong shadow-card") : "border-y-line border-r-line",
        dim && "opacity-50 hover:opacity-90",
        selected && "ring-2 ring-accent/35",
      )}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-ink">{node.label}</span>
        {run ? <RunBadge run={run} /> : null}
      </div>
      <div className="mt-0.5 truncate font-mono text-[11px] text-muted">{node.type}</div>
      {run?.detail ? <div className="mt-1 truncate text-[11.5px] text-ink-2" title={run.detail}>{run.detail}</div> : null}
      {next.length ? <div className="mt-1 truncate text-[11px] text-faint @3xl:hidden">→ {next.join(", ")}</div> : null}
    </button>
  );
}

function RunBadge({ run }: { run: NodeRun }) {
  if (run.status === "start") return <span className="flex shrink-0 items-center gap-1 text-[11px] text-accent-ink"><StatusDot tone="accent" pulse /> running</span>;
  if (run.status === "skip") return <span className="shrink-0 text-[11px] text-faint">skipped</span>;
  if (run.status === "error") return <span className="shrink-0 text-[11px] font-medium text-err">error</span>;
  return <span className="flex shrink-0 items-center gap-1 font-mono text-[11px] text-ok"><Icon name="check" size={12} strokeWidth={2.2} />{run.ms ? formatMs(run.ms) : ""}</span>;
}

function NodeDetail({ spec, id, runs, onSelect }: { spec: FlowSpec | null; id: string | null; runs: Record<string, NodeRun>; onSelect: (id: string) => void }) {
  const node = spec?.nodes.find((n) => n.id === id) ?? null;
  if (!spec) return null;
  if (!node) {
    return (
      <Card className="h-fit p-4 @6xl:sticky @6xl:top-4">
        <div className="text-[13px] font-semibold text-ink">Reading the graph</div>
        <ul className="mt-2 space-y-2 text-[12.5px] text-muted">
          <li className="flex items-center gap-2"><span className="h-0.5 w-6 rounded bg-accent" /> path taken in the last turn</li>
          <li className="flex items-center gap-2"><span className="h-0 w-6 border-t border-dashed border-line-strong" /> not used last time</li>
          <li className="flex items-center gap-2"><Icon name="check" size={13} className="text-ok" /> ran, with its duration</li>
          <li className="flex items-center gap-2"><span className="text-faint">skipped</span> considered but not needed</li>
        </ul>
        <p className="mt-3 text-[12.5px] text-muted">Select a step to see what it does and what happened in it.</p>
      </Card>
    );
  }
  const run = runs[node.id];
  const ins = spec.edges.filter((e) => e.to === node.id).map((e) => e.from);
  const outs = spec.edges.filter((e) => e.from === node.id).map((e) => e.to);
  const label = (nid: string) => spec.nodes.find((n) => n.id === nid)?.label ?? nid;
  const hasConfig = node.config && Object.keys(node.config).length > 0;
  return (
    <Card className="h-fit min-w-0 p-4 @6xl:sticky @6xl:top-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className={cx("text-[11px] font-semibold tracking-[0.08em] uppercase", GROUP_TEXT[node.group])}>{GROUP_INFO[node.group].title}</div>
          <h3 className="mt-0.5 font-serif text-[19px] leading-snug text-ink">{node.label}</h3>
          <div className="font-mono text-[11.5px] text-muted">{node.type} · {node.id}</div>
        </div>
        <button type="button" onClick={() => onSelect("")} className="rounded-md p-1 text-muted hover:bg-sunk hover:text-ink" aria-label="Close details"><Icon name="x" size={15} /></button>
      </div>

      <div className="mt-4 rounded-[10px] border border-line bg-canvas/50 p-3">
        <div className="text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">Last turn</div>
        {run ? (
          <div className="mt-1 space-y-1.5 text-[12.5px]">
            <div className="flex items-center gap-2"><RunBadge run={run} />{run.status === "done" && !run.ms ? <span className="text-muted">done</span> : null}</div>
            {run.detail ? <div className="text-ink-2">{run.detail}</div> : null}
            {run.tools.map((t, i) => (
              <div key={i} className="rounded-md border border-line bg-surface px-2 py-1">
                <span className={cx("font-mono", t.ok ? "text-ink" : "text-err")}>{t.name}</span>
                {t.summary ? <div className="text-muted">{t.summary}</div> : null}
              </div>
            ))}
          </div>
        ) : <div className="mt-1 text-[12.5px] text-muted">Not reached in the last turn.</div>}
      </div>

      {ins.length || outs.length ? (
        <div className="mt-4 space-y-2 text-[12.5px]">
          {ins.length ? <div><span className="text-muted">Comes after </span>{ins.map((x) => <Chip key={x} onClick={() => onSelect(x)} className="mr-1 mb-1">{label(x)}</Chip>)}</div> : null}
          {outs.length ? <div><span className="text-muted">Leads to </span>{outs.map((x) => <Chip key={x} onClick={() => onSelect(x)} className="mr-1 mb-1">{label(x)}</Chip>)}</div> : null}
        </div>
      ) : null}

      {hasConfig ? (
        <div className="mt-4">
          <div className="mb-1 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">Config</div>
          <pre className="max-h-[200px] overflow-auto rounded-[10px] border border-line bg-sunk p-2.5 font-mono text-[11.5px] leading-relaxed text-ink-2">{JSON.stringify(node.config, null, 2)}</pre>
        </div>
      ) : null}
    </Card>
  );
}

function GraphSkeleton() {
  return (
    <div className="grid gap-6 @3xl:grid-cols-4 @3xl:gap-10" aria-busy="true" aria-label="Loading flow">
      {[3, 3, 2, 2].map((n, c) => (
        <div key={c} className="space-y-3">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-full" />
          {Array.from({ length: n }, (_, i) => <Skeleton key={i} className="h-[64px] rounded-[12px]" />)}
        </div>
      ))}
    </div>
  );
}
