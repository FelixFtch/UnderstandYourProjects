import { useMemo, useState, type ReactNode } from "react";
import { ApiError } from "../../api/client";
import type { Device, ProjectDigest, ProjectSummary } from "../../api/contracts";
import { basename, compact, plural, relativeTime, tildePath } from "../../design/format";
import { useResource } from "../../design/hooks";
import { Icon, type IconName } from "../../design/icons";
import { Markdown } from "../../design/Markdown";
import { Button, Card, Chip, cx, EmptyState, ErrorState, Skeleton, SkeletonText, StatusDot } from "../../design/primitives";
import { AskBox } from "./AskBox";
import { devicesData } from "./data";
import { bucketChanges, dayBars, hierarchyPhrases, statusMeta, tierMeta } from "./digest";
import { ancestors, type ProjectForest } from "./tree";

export function ProjectDigestView({ id, forest, devices, owner, onOpen, onAnalyze }: {
  id: string;
  forest: ProjectForest;
  devices: Device[];
  owner: boolean;
  onOpen: (id: string | null) => void;
  onAnalyze: (path?: string) => void;
}) {
  const res = useResource((s) => devicesData.project(id, s), [id]);
  const known = forest.byId.get(id);
  const crumbs = known ? ancestors(forest, id) : [];

  return (
    <div className="mx-auto w-full max-w-[1120px] px-4 py-5 sm:px-8 sm:py-7">
      <nav aria-label="Breadcrumb" className="mb-4 flex min-w-0 flex-wrap items-center gap-1 text-[12.5px] text-muted">
        <a href="#/devices" onClick={(e) => { e.preventDefault(); onOpen(null); }} className="flex items-center gap-1 rounded px-1 hover:text-ink">
          <Icon name="arrowLeft" size={13} /> Devices
        </a>
        {crumbs.map((c) => (
          <span key={c.project_id} className="flex min-w-0 items-center gap-1">
            <Icon name="chevronRight" size={12} className="text-faint" />
            <a href={`#/devices/${encodeURIComponent(c.project_id)}`} onClick={(e) => { e.preventDefault(); onOpen(c.project_id); }} className="truncate rounded px-1 hover:text-ink">{c.root_name}</a>
          </span>
        ))}
        <Icon name="chevronRight" size={12} className="text-faint" />
        <span className="truncate px-1 text-ink-2">{known?.root_name ?? id}</span>
      </nav>

      {res.loading && !res.data ? <DigestSkeleton /> : null}

      {res.error && !res.data ? (
        res.error instanceof ApiError && res.error.status === 404 ? (
          <Card>
            <EmptyState
              icon="folder"
              title="Jarvis doesn't know this folder yet"
              body={known ? `${known.root_name} is registered but has no digest yet (${statusMeta(known.status).label.toLowerCase()}).` : `There is no analyzed folder with the id “${id}”.`}
              action={owner ? <Button variant="primary" icon="plus" onClick={() => onAnalyze(known?.path)}>Analyze a folder</Button> : undefined}
            />
          </Card>
        ) : (
          <Card><ErrorState error={res.error} service="Project knowledge (UYP)" title={`Couldn't load the digest for ${known?.root_name ?? id}`} onRetry={res.reload} /></Card>
        )
      ) : null}

      {res.data ? <Digest d={res.data} forest={forest} devices={devices} onOpen={onOpen} owner={owner} onAnalyze={onAnalyze} /> : null}
    </div>
  );
}

function Digest({ d, forest, devices, onOpen, owner, onAnalyze }: {
  d: ProjectDigest; forest: ProjectForest; devices: Device[]; onOpen: (id: string | null) => void; owner: boolean; onAnalyze: (path?: string) => void;
}) {
  const p = d.project;
  const st = statusMeta(p.status);
  const device = devices.find((x) => x.device_id === p.device_id);
  const parent = d.related.parent ?? (p.parent_id ? forest.byId.get(p.parent_id) ?? null : null);
  const childCount = d.related.children.length || p.children.length;
  const phrases = hierarchyPhrases(parent?.root_name ?? null, childCount);

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start gap-x-8 gap-y-4">
        <div className="min-w-0 flex-[1_1_320px]">
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
            <Chip tone={st.tone}><span className="flex items-center gap-1.5"><StatusDot tone={st.tone} pulse={st.pulse} />{st.label}</span></Chip>
            {device ? <span className="flex items-center gap-1"><Icon name={device.kind === "jetson" ? "chip" : device.kind === "nas" ? "server" : "laptop"} size={13} />{device.label}</span> : null}
            <span>· analyzed {relativeTime(p.analyzed_at)}</span>
          </div>
          <h1 className="mt-2 font-serif text-[28px] leading-tight break-words text-ink">{p.root_name}</h1>
          <div className="mt-1 font-mono text-[12.5px] break-all text-muted">{tildePath(p.path)}</div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {phrases.map((ph) => (
              <Chip key={ph} tone="accent" icon={ph.startsWith("inside") ? "arrowUp" : "layers"} onClick={ph.startsWith("inside") && parent ? () => onOpen(parent.project_id) : undefined}>{ph}</Chip>
            ))}
            {p.stats.languages.map((l) => <Chip key={l}>{l}</Chip>)}
          </div>
        </div>
        <dl className="grid flex-[0_1_auto] grid-cols-4 gap-x-6 gap-y-1">
          {([["Files", p.stats.files], ["Summarized", p.stats.summarized], ["Nodes", p.stats.nodes], ["Edges", p.stats.edges]] as const).map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">{k}</dt>
              <dd className="font-serif text-[22px] text-ink tabular-nums">{compact(v)}</dd>
            </div>
          ))}
        </dl>
      </header>

      <TierBar tiers={p.tiers} />

      {(p.status === "analyzing" || p.status === "queued") ? (
        <div className="flex items-center gap-2 rounded-control border border-accent/25 bg-accent-soft px-3 py-2 text-[13px] text-accent-ink">
          <StatusDot tone="accent" pulse /> Analysis in progress: this digest shows the last completed run.
        </div>
      ) : p.status === "stale" && owner ? (
        <div className="flex flex-wrap items-center gap-2 rounded-control border border-warn/25 bg-warn-soft px-3 py-2 text-[13px] text-warn">
          <Icon name="clock" size={15} /> Files changed since the last analysis.
          <button type="button" className="font-medium underline underline-offset-2" onClick={() => onAnalyze(p.path)}>Re-analyze</button>
        </div>
      ) : null}

      <div className="grid gap-5 @3xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-5">
          <Panel title="Overview" icon="sparkle">
            {d.overview ? <Markdown text={d.overview} className="text-[14.5px] text-ink-2" /> : <p className="text-[13.5px] text-muted">No overview yet.</p>}
          </Panel>
          <Panel title={`Ask about ${p.root_name}`} icon="search" hint="Answers come from the analyzed knowledge, with sources.">
            <AskBox key={p.project_id} projectId={p.project_id} name={p.root_name} />
          </Panel>
          <Panel title="Key files" icon="file" hint="Tier A files are read in full; B summarized; C indexed by structure.">
            <KeyFiles files={d.key_files} />
          </Panel>
          <Panel title="Areas" icon="folder">
            {d.areas.length ? (
              <ul className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(min(100%,220px),1fr))]">
                {d.areas.map((a) => (
                  <li key={a.folder} className="min-w-0 rounded-[10px] border border-line bg-canvas/40 p-3">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate font-mono text-[12.5px] text-ink">{a.folder}</span>
                      <span className="shrink-0 text-[11.5px] text-muted">{plural(a.files, "file")}</span>
                    </div>
                    <p className="mt-1 text-[12.5px] text-muted">{a.summary}</p>
                  </li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-muted">No areas yet.</p>}
          </Panel>
        </div>
        <div className="min-w-0 space-y-5">
          <Panel title="Activity" icon="activity" hint={`Last ${d.activity.window || "7d"}`}>
            <Activity activity={d.activity} />
          </Panel>
          <Panel title="Knowledge graph" icon="layers">
            <Graph graph={d.graph} />
          </Panel>
          <Panel title="Related folders" icon="project">
            <Related related={d.related} onOpen={onOpen} />
          </Panel>
          <p className="px-1 text-[11.5px] text-faint">Digest generated {relativeTime(d.generated_at)}.</p>
        </div>
      </div>
    </div>
  );
}

function Panel({ title, icon, hint, children }: { title: string; icon: IconName; hint?: string; children: ReactNode }) {
  return (
    <Card className="min-w-0 p-4 sm:p-5">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="flex items-center gap-2 text-[14px] font-semibold text-ink">
          <Icon name={icon} size={15} className="text-muted" />
          {title}
        </h2>
        {hint ? <span className="truncate text-[11.5px] text-muted">{hint}</span> : null}
      </div>
      {children}
    </Card>
  );
}

function TierBar({ tiers }: { tiers: ProjectSummary["tiers"] }) {
  const order = ["A", "B", "C", "gate"] as const;
  const total = order.reduce((a, k) => a + (tiers?.[k] ?? 0), 0);
  if (!total) return null;
  const color: Record<(typeof order)[number], string> = { A: "bg-accent", B: "bg-info/70", C: "bg-line-strong", gate: "bg-warn/50" };
  return (
    <div>
      <div className="flex h-2 gap-0.5 overflow-hidden rounded-full" aria-hidden="true">
        {order.map((k) => (tiers[k] ? <span key={k} className={color[k]} style={{ flexGrow: tiers[k], flexBasis: 0 }} /> : null))}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-muted">
        {order.map((k) => (
          <span key={k} className="flex items-center gap-1.5" title={tierMeta(k).hint}>
            <span className={cx("size-2 rounded-sm", color[k])} />
            Tier {tierMeta(k).label} <span className="font-mono text-ink-2">{compact(tiers[k])}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function KeyFiles({ files }: { files: ProjectDigest["key_files"] }) {
  const [all, setAll] = useState(false);
  if (!files.length) return <p className="text-[13px] text-muted">No key files identified yet.</p>;
  const shown = all ? files : files.slice(0, 6);
  return (
    <>
      <ul className="divide-y divide-line">
        {shown.map((f) => {
          const t = tierMeta(f.tier);
          return (
            <li key={f.file} className="flex min-w-0 gap-3 py-2.5 first:pt-0 last:pb-0">
              <Chip tone={t.tone} title={t.hint} className="mt-[1px] h-fit shrink-0">{t.label}</Chip>
              <div className="min-w-0 flex-1">
                <div className="font-mono text-[12.5px] break-all text-ink" title={f.file}>
                  <span className="text-muted">{f.file.slice(0, f.file.length - basename(f.file).length)}</span>{basename(f.file)}
                </div>
                {f.purpose ? <p className="mt-0.5 text-[13px] text-ink-2">{f.purpose}</p> : null}
                {f.key_points.length ? (
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[12.5px] text-muted marker:text-faint">
                    {f.key_points.slice(0, 3).map((k) => <li key={k}>{k}</li>)}
                  </ul>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
      {files.length > 6 ? (
        <button type="button" onClick={() => setAll((v) => !v)} className="mt-2 text-[12.5px] font-medium text-accent-ink hover:underline">
          {all ? "Show fewer" : `Show all ${files.length}`}
        </button>
      ) : null}
    </>
  );
}

function Activity({ activity }: { activity: ProjectDigest["activity"] }) {
  const bars = useMemo(() => dayBars(activity.by_day), [activity.by_day]);
  const groups = useMemo(() => bucketChanges(activity.changed), [activity.changed]);
  const max = Math.max(1, ...bars.map((b) => b.count));
  const total = bars.reduce((a, b) => a + b.count, 0);
  return (
    <div>
      <div className="mb-1 text-[12px] text-muted">{plural(total, "change")} in the last {bars.length} days</div>
      <div className="flex h-[96px] items-end gap-1.5" role="img" aria-label={bars.map((b) => `${b.label}: ${b.count}`).join(", ")}>
        {bars.map((b) => (
          <div key={b.date} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1" title={`${b.date}: ${plural(b.count, "change")}`}>
            <span className={cx("font-mono text-[10.5px]", b.count ? "text-ink-2" : "text-faint")}>{b.count || ""}</span>
            <span
              className={cx("w-full max-w-[28px] rounded-t-[4px]", b.count ? (b.isToday ? "bg-accent" : "bg-accent/45") : "bg-line")}
              style={{ height: b.count ? `${Math.max(8, (b.count / max) * 64)}px` : "3px" }}
            />
            <span className={cx("text-[10.5px]", b.isToday ? "font-semibold text-ink" : "text-muted")}>{b.label}</span>
          </div>
        ))}
      </div>
      {groups.length ? (
        <div className="mt-4 space-y-3">
          {groups.map((g) => (
            <div key={g.bucket}>
              <div className="mb-1 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">{g.label}</div>
              <ul className="space-y-1">
                {g.items.slice(0, 8).map((c) => (
                  <li key={c.file + c.mtime} className="flex min-w-0 items-baseline gap-2 text-[12.5px]">
                    <span className="min-w-0 flex-1 truncate font-mono text-ink" title={`${c.file}${c.purpose ? ` · ${c.purpose}` : ""}`}>
                      <span className="text-muted">{c.file.slice(0, c.file.length - basename(c.file).length)}</span>{basename(c.file)}
                    </span>
                    <span className="shrink-0 text-[11.5px] text-faint">{relativeTime(c.mtime)}</span>
                  </li>
                ))}
                {g.items.length > 8 ? <li className="text-[12px] text-muted">+{g.items.length - 8} more</li> : null}
              </ul>
            </div>
          ))}
        </div>
      ) : <p className="mt-3 text-[13px] text-muted">No files changed in this window.</p>}
    </div>
  );
}

function Graph({ graph }: { graph: ProjectDigest["graph"] }) {
  const max = Math.max(1, ...graph.layers.map((l) => l.files));
  if (!graph.layers.length && !graph.top_nodes.length) return <p className="text-[13px] text-muted">No graph yet.</p>;
  return (
    <div className="space-y-4">
      {graph.layers.length ? (
        <ul className="space-y-1.5">
          {graph.layers.map((l) => (
            <li key={l.name} className="grid grid-cols-[minmax(0,88px)_minmax(0,1fr)_auto] items-center gap-2 text-[12.5px]">
              <span className="truncate text-ink-2">{l.name}</span>
              <span className="h-2 rounded-full bg-sunk"><span className="block h-full rounded-full bg-g-retrieve/60" style={{ width: `${(l.files / max) * 100}%` }} /></span>
              <span className="font-mono text-[11.5px] text-muted">{compact(l.files)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {graph.top_nodes.length ? (
        <div>
          <div className="mb-1 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">Most connected</div>
          <ul className="space-y-1">
            {graph.top_nodes.map((n) => (
              <li key={`${n.name}|${n.file}`} className="flex min-w-0 items-baseline gap-2 text-[12.5px]">
                <span className="shrink-0 font-mono text-ink">{n.name}</span>
                <span className="shrink-0 text-[11px] text-muted">{n.type}</span>
                <span className="min-w-0 flex-1 truncate text-right font-mono text-[11.5px] text-faint" title={n.file}>{n.file}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function Related({ related, onOpen }: { related: ProjectDigest["related"]; onOpen: (id: string) => void }) {
  const groups: Array<[string, ProjectSummary[]]> = [
    ["Inside", related.parent ? [related.parent] : []],
    ["Contains", related.children],
    ["Next to", related.siblings],
  ];
  if (!groups.some(([, l]) => l.length)) return <p className="text-[13px] text-muted">This folder stands alone: no parent, children or siblings.</p>;
  return (
    <div className="space-y-3">
      {groups.filter(([, l]) => l.length).map(([label, list]) => (
        <div key={label}>
          <div className="mb-1 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">{label}</div>
          <div className="flex flex-wrap gap-1.5">
            {list.map((p) => (
              <Chip key={p.project_id} onClick={() => onOpen(p.project_id)} title={tildePath(p.path)}>
                <span className="flex items-center gap-1.5"><StatusDot tone={statusMeta(p.status).tone} />{p.root_name}</span>
              </Chip>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function DigestSkeleton() {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="Loading digest">
      <div className="space-y-2">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-8 w-72 max-w-full" />
        <Skeleton className="h-3.5 w-96 max-w-full" />
      </div>
      <Skeleton className="h-2 w-full rounded-full" />
      <div className="grid gap-5 @3xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <Card className="p-5"><SkeletonText lines={4} /></Card>
          <Card className="p-5"><SkeletonText lines={2} /></Card>
        </div>
        <Card className="p-5"><Skeleton className="h-24" /><SkeletonText lines={4} className="mt-4" /></Card>
      </div>
    </div>
  );
}
