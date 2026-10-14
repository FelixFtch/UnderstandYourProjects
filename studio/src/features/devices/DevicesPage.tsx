// Devices — device cards → folder hierarchy (tree + treemap) → project digest.
// Sensors from the household sensor-hub live here too: their cards sit under
// the computer cards, and a sensor opens its detail at #/devices/sensors/<id>.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import type { FeaturePageProps } from "../../app/routes";
import { useMe } from "../../app/session";
import { compact, plural, tildePath } from "../../design/format";
import { useResource } from "../../design/hooks";
import { Icon } from "../../design/icons";
import { Button, Card, cx, EmptyState, ErrorState, ProgressBar, SectionHeader, Skeleton } from "../../design/primitives";
import { AnalyzeDialog } from "./AnalyzeDialog";
import { isFinished, useAnalyzeJob, type JobState } from "./analyzeJob";
import { devicesData } from "./data";
import { DeviceCards, DeviceCardsSkeleton } from "./DeviceCards";
import { HOME_DEVICE_CONTRACT_PENDING, HomeDeviceCards, HomeDeviceCardsSkeleton } from "./HomeDeviceCards";
import { FolderTree, TreeLegend } from "./FolderTree";
import { ProjectDigestView } from "./ProjectDigestView";
import { SensorCards, SensorCardsSkeleton } from "./SensorCards";
import { SensorDetailView } from "./SensorDetail";
import { SENSORS_POLL_MS, sensorsData, sortSensorDevices, usePolling } from "./sensors";
import { ancestors, buildForest, treemapCells, visibleRows } from "./tree";
import { Treemap } from "./Treemap";

export default function DevicesPage({ param, navigate }: FeaturePageProps) {
  const me = useMe();
  const owner = me?.role === "owner";
  const devices = useResource((s) => devicesData.devices(s), []);
  const projects = useResource((s) => devicesData.projects(s), []);
  const homeDevices = useResource((s) => devicesData.homeDevices(s), []);
  const sensors = useResource((s) => sensorsData.devices(s), []);
  const sensorStates = useResource((s) => sensorsData.states(s), []);
  const forest = useMemo(() => buildForest(projects.data), [projects.data]);
  const [deviceFilter, setDeviceFilter] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string> | null>(null);
  const [dialog, setDialog] = useState<{ open: boolean; path?: string }>({ open: false });

  // #/devices/<project_id> opens a digest; #/devices/sensors/<device_id> a sensor.
  const sensorId = param?.startsWith("sensors/") ? param.slice("sensors/".length) || null : null;
  const selected = sensorId ? null : param ?? null;
  const open = useCallback((id: string | null) => navigate(id ? `#/devices/${encodeURIComponent(id)}` : "#/devices"), [navigate]);
  const openSensor = useCallback((id: string | null) => navigate(id ? `#/devices/sensors/${encodeURIComponent(id)}` : "#/devices"), [navigate]);

  // Poll live sensors in place while this section is visible: reload() keeps the
  // previous data mounted, so nothing remounts and no open state is lost.
  usePolling(() => {
    if (selected) return; // a project digest is open; the sensor column isn't visible
    sensors.reload();
    sensorStates.reload();
  }, SENSORS_POLL_MS);

  const sensorList = useMemo(() => sortSensorDevices(sensors.data?.devices ?? []), [sensors.data]);
  const statesMap = useMemo(() => new Map((sensorStates.data ?? []).map((r) => [r.entity_id, r])), [sensorStates.data]);

  const { state: job, start, clear } = useAnalyzeJob(() => projects.reload());

  // expand every folder that has children on first load; always reveal the selection
  useEffect(() => {
    if (!projects.data) return;
    setExpanded((prev) => {
      const next = new Set(prev ?? [...forest.children.entries()].filter(([, c]) => c.length).map(([id]) => id));
      if (selected) for (const a of ancestors(forest, selected)) next.add(a.project_id);
      return next;
    });
  }, [projects.data, forest, selected]);

  const matches = useMemo(() => (deviceFilter ? (p: { device_id: string | null }) => p.device_id === deviceFilter : undefined), [deviceFilter]);
  const rows = useMemo(() => visibleRows(forest, expanded ?? new Set(), matches), [forest, expanded, matches]);
  const cells = useMemo(() => {
    const roots = deviceFilter ? forest.roots.filter((id) => rows.some((r) => r.project.project_id === id)) : forest.roots;
    return treemapCells(forest, roots);
  }, [forest, rows, deviceFilter]);

  const toggle = (id: string) => setExpanded((prev) => {
    const next = new Set(prev ?? []);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const openAnalyze = (path?: string) => setDialog({ open: true, path });
  const all = projects.data?.projects ?? [];
  const totals = useMemo(() => all.reduce((a, p) => ({ files: a.files + (p.parent_id ? 0 : p.stats.files), nodes: a.nodes + (p.parent_id ? 0 : p.stats.nodes) }), { files: 0, nodes: 0 }), [all]);

  const tree = (
    <TreeBlock
      loading={projects.loading && !projects.data}
      error={projects.error && !projects.data ? projects.error : null}
      onRetry={projects.reload}
      empty={!!projects.data && all.length === 0}
      owner={owner}
      onAnalyze={() => openAnalyze()}
    >
      <FolderTree rows={rows} forest={forest} selected={selected} onToggle={toggle} onOpen={open} />
    </TreeBlock>
  );

  return (
    <div className="@container/devices h-full min-h-0">
      <div className="grid h-full min-h-0 grid-cols-1 @4xl/devices:grid-cols-[minmax(250px,300px)_minmax(0,1fr)]">
        {/* left: the hierarchy, always visible on wide containers */}
        <aside className="hidden min-h-0 flex-col border-r border-line bg-canvas @4xl/devices:flex" aria-label="Folder hierarchy">
          <div className="flex items-center justify-between gap-2 px-4 pt-4 pb-2">
            <div>
              <h2 className="text-[13px] font-semibold text-ink">Folders Jarvis knows</h2>
              <p className="text-[11.5px] text-muted">{projects.data ? `${plural(all.length, "folder")} · ${compact(totals.files)} files` : " "}</p>
            </div>
            {owner ? <Button size="sm" variant="ghost" icon="plus" onClick={() => openAnalyze()} aria-label="Analyze a folder" title="Analyze a folder" /> : null}
          </div>
          {deviceFilter ? <FilterNote device={devices.data?.devices.find((d) => d.device_id === deviceFilter)?.label} onClear={() => setDeviceFilter(null)} /> : null}
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">{tree}</div>
          <div className="border-t border-line px-4 py-2.5"><TreeLegend /></div>
        </aside>

        <section className="@container min-h-0 min-w-0 overflow-y-auto">
          {job && !dialog.open ? <JobBanner job={job} onOpen={() => setDialog({ open: true })} onDismiss={clear} onOpenProject={open} /> : null}

          {sensorId ? (
            <SensorDetailView
              id={sensorId}
              sensors={sensors}
              states={sensorStates}
              onBack={() => openSensor(null)}
            />
          ) : selected ? (
            <ProjectDigestView
              key={selected}
              id={selected}
              forest={forest}
              devices={devices.data?.devices ?? []}
              owner={owner}
              onOpen={open}
              onAnalyze={openAnalyze}
            />
          ) : (
            <div className="mx-auto w-full max-w-[1120px] space-y-9 px-4 py-6 sm:px-8 sm:py-8">
              <SectionHeader
                level={1}
                eyebrow="Devices"
                title="Where your work lives"
                description="Jarvis reads folders on these devices through their connectors. Each analyzed folder becomes project knowledge it can reason about, and folders nest the way they do on disk."
                actions={owner ? <Button variant="primary" icon="plus" onClick={() => openAnalyze()}>Analyze a folder</Button> : null}
              />

              <section aria-labelledby="devices-h" className="space-y-3">
                <div className="flex items-baseline justify-between gap-2">
                  <h2 id="devices-h" className="text-[13px] font-semibold text-ink">Devices</h2>
                  {deviceFilter ? <button type="button" onClick={() => setDeviceFilter(null)} className="text-[12px] text-accent-ink hover:underline">Show all devices</button> : <span className="text-[12px] text-muted">Select a device to filter its folders</span>}
                </div>
                {devices.loading && !devices.data ? <DeviceCardsSkeleton /> : null}
                {devices.error && !devices.data ? <ErrorState compact error={devices.error} service="Device registry" title="Couldn't load devices" onRetry={devices.reload} /> : null}
                {devices.data && devices.data.devices.length === 0 ? (
                  <Card><EmptyState icon="devices" title="No devices yet" body="Pair a computer's connector (UYP connector on the Mac) and it appears here." /></Card>
                ) : null}
                {devices.data?.devices.length ? <DeviceCards devices={devices.data.devices} selected={deviceFilter} onSelect={setDeviceFilter} /> : null}
              </section>

                <section aria-labelledby="home-devices-h" className="space-y-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div>
                      <h2 id="home-devices-h" className="text-[13px] font-semibold text-ink">Home devices</h2>
                      <p className="text-[12.5px] text-muted">HomeHub-owned lights. Card actions use the same governed Jarvis/HomeHub route as voice and chat.</p>
                    </div>
                    {homeDevices.data ? <span className="text-[12px] text-muted">{homeDevices.data.provider ?? "HomeHub"}</span> : null}
                  </div>
                  {homeDevices.loading && !homeDevices.data ? <HomeDeviceCardsSkeleton /> : null}
                  {homeDevices.error && !homeDevices.data ? (
                    <div className="space-y-3">
                      <div className="rounded-control border border-warn/25 bg-warn-soft px-3 py-2 text-[12.5px] text-warn">Catalog placeholders only · HomeHub has not issued a device projection. Controls stay disabled until the authorized GET response is available.</div>
                      <HomeDeviceCards projection={HOME_DEVICE_CONTRACT_PENDING} onRefresh={homeDevices.reload} />
                      <div><Button size="sm" variant="secondary" icon="refresh" onClick={homeDevices.reload}>Retry HomeHub projection</Button></div>
                    </div>
                  ) : null}
                  {homeDevices.data ? <HomeDeviceCards projection={homeDevices.data} onRefresh={homeDevices.reload} /> : null}
                </section>

              <section aria-labelledby="sensors-h" className="space-y-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div>
                    <h2 id="sensors-h" className="text-[13px] font-semibold text-ink">Sensors</h2>
                    <p className="text-[12.5px] text-muted">Live household readings from the sensor hub — air quality, presence, meeting audio. Updates every 10 s.</p>
                  </div>
                  {sensors.data ? <span className="text-[12px] text-muted">{plural(sensorList.length, "device")}</span> : null}
                </div>
                {sensors.loading && !sensors.data ? <SensorCardsSkeleton /> : null}
                {sensors.error && !sensors.data ? <ErrorState compact error={sensors.error} service="Sensor hub" title="Couldn't load sensors" onRetry={sensors.reload} /> : null}
                {sensors.data && sensors.data.devices.length === 0 && !(sensors.data.placeholders ?? []).length ? (
                  <Card>
                    <EmptyState
                      icon="devices"
                      title="No sensors yet"
                      body="Approved device providers publish their discovery and availability here — ESP-NOW, MQTT, Matter, or another HomeHub adapter can appear after pairing."
                    />
                  </Card>
                ) : null}
                {sensorList.length || (sensors.data?.placeholders ?? []).length ? (
                  <SensorCards
                    devices={sensorList}
                    placeholders={sensors.data?.placeholders ?? []}
                    states={statesMap}
                    openId={null}
                    onOpen={openSensor}
                  />
                ) : null}
              </section>

              <section aria-labelledby="hier-h" className="space-y-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div>
                    <h2 id="hier-h" className="text-[13px] font-semibold text-ink">Folder hierarchy</h2>
                    <p className="text-[12.5px] text-muted">Area = files. A folder inside another analyzed folder is its child and inherits its overview as context.</p>
                  </div>
                  {projects.data ? <span className="text-[12px] text-muted">{plural(all.length, "folder")} · {compact(totals.files)} files · {compact(totals.nodes)} graph nodes</span> : null}
                </div>
                {projects.loading && !projects.data ? <Skeleton className="h-[220px] rounded-card" /> : null}
                {projects.error && !projects.data ? <ErrorState compact error={projects.error} service="Project knowledge (UYP)" title="Couldn't load analyzed folders" onRetry={projects.reload} /> : null}
                {projects.data && all.length ? <Treemap cells={cells} selected={selected} onOpen={open} /> : null}
              </section>

              {/* narrow containers: the tree lives here instead of the side rail */}
              <section aria-label="Folders" className="space-y-2 @4xl/devices:hidden">
                <h2 className="text-[13px] font-semibold text-ink">Folders</h2>
                {deviceFilter ? <FilterNote device={devices.data?.devices.find((d) => d.device_id === deviceFilter)?.label} onClear={() => setDeviceFilter(null)} /> : null}
                <Card className="p-2">{tree}</Card>
                <TreeLegend />
              </section>
            </div>
          )}
        </section>
      </div>

      <AnalyzeDialog
        open={dialog.open}
        onClose={() => setDialog({ open: false })}
        initialPath={dialog.path}
        devices={devices.data?.devices ?? []}
        projects={all}
        job={job}
        onStart={start}
        onReset={clear}
        onOpenProject={open}
        owner={owner}
      />
    </div>
  );
}

function TreeBlock({ loading, error, onRetry, empty, owner, onAnalyze, children }: {
  loading: boolean; error: unknown; onRetry: () => void; empty: boolean; owner: boolean; onAnalyze: () => void; children: ReactNode;
}) {
  if (loading) {
    return (
      <div className="space-y-2 p-2" aria-busy="true">
        {[70, 55, 62, 48, 66].map((w, i) => <Skeleton key={i} className="h-6" style={{ width: `${w}%`, marginLeft: i % 3 ? 18 : 0 }} />)}
      </div>
    );
  }
  if (error) return <ErrorState error={error} service="Project knowledge (UYP)" title="Folders unavailable" onRetry={onRetry} />;
  if (empty) {
    return (
      <EmptyState
        icon="folder"
        title="No folders analyzed yet"
        body="Point Jarvis at a folder and it builds a digest it can answer from."
        action={owner ? <Button size="sm" variant="primary" icon="plus" onClick={onAnalyze}>Analyze a folder</Button> : undefined}
      />
    );
  }
  return <>{children}</>;
}

function FilterNote({ device, onClear }: { device?: string; onClear: () => void }) {
  return (
    <div className="mx-2 mb-1 flex items-center justify-between gap-2 rounded-control bg-accent-soft px-2.5 py-1.5 text-[12px] text-accent-ink">
      <span className="truncate">Only {device ?? "one device"}</span>
      <button type="button" onClick={onClear} className="shrink-0 font-medium underline underline-offset-2">Clear</button>
    </div>
  );
}

function JobBanner({ job, onOpen, onDismiss, onOpenProject }: { job: JobState; onOpen: () => void; onDismiss: () => void; onOpenProject: (id: string) => void }) {
  const j = job.job;
  const done = isFinished(job);
  const ok = j?.status === "done";
  return (
    <div className={cx("sticky top-0 z-10 border-b px-4 py-2.5 backdrop-blur sm:px-8", ok ? "border-ok/25 bg-ok-soft/90" : j?.status === "failed" ? "border-err/25 bg-err-soft/90" : "border-line bg-surface/90")}>
      <div className="mx-auto flex max-w-[1120px] flex-wrap items-center gap-x-3 gap-y-1.5">
        <Icon name={ok ? "check" : j?.status === "failed" ? "alert" : "activity"} size={15} className={ok ? "text-ok" : j?.status === "failed" ? "text-err" : "text-accent-ink"} />
        <span className="min-w-0 truncate text-[13px] text-ink">
          {ok ? "Analysis finished" : j?.status === "failed" ? "Analysis failed" : "Analyzing"} <span className="font-mono text-[12px] text-muted">{tildePath(job.path)}</span>
          {!done && j ? <span className="text-muted"> · {j.phase}</span> : null}
        </span>
        {!done ? <ProgressBar value={j?.progress.done ?? 0} max={j?.progress.total || 1} className="w-32" label="Analysis progress" /> : null}
        <span className="ml-auto flex items-center gap-1">
          {ok ? <Button size="sm" variant="secondary" onClick={() => { onOpenProject(job.result.project_id); onDismiss(); }}>Open digest</Button> : <Button size="sm" variant="ghost" onClick={onOpen}>Details</Button>}
          {done ? <Button size="sm" variant="ghost" icon="x" onClick={onDismiss} aria-label="Dismiss" /> : null}
        </span>
      </div>
    </div>
  );
}
