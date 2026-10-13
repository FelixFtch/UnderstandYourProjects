import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// Devices — device cards → folder hierarchy (tree + treemap) → project digest.
// Sensors from the household sensor-hub live here too: their cards sit under
// the computer cards, and a sensor opens its detail at #/devices/sensors/<id>.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useMe } from "../../app/session";
import { compact, plural, tildePath } from "../../design/format";
import { useResource } from "../../design/hooks";
import { Icon } from "../../design/icons";
import { Button, Card, cx, EmptyState, ErrorState, ProgressBar, SectionHeader, Skeleton } from "../../design/primitives";
import { AnalyzeDialog } from "./AnalyzeDialog";
import { isFinished, useAnalyzeJob } from "./analyzeJob";
import { devicesData } from "./data";
import { DeviceCards, DeviceCardsSkeleton } from "./DeviceCards";
import { FolderTree, TreeLegend } from "./FolderTree";
import { ProjectDigestView } from "./ProjectDigestView";
import { SensorCards, SensorCardsSkeleton } from "./SensorCards";
import { SensorDetailView } from "./SensorDetail";
import { SENSORS_POLL_MS, sensorsData, sortSensorDevices, usePolling } from "./sensors";
import { ancestors, buildForest, treemapCells, visibleRows } from "./tree";
import { Treemap } from "./Treemap";
export default function DevicesPage({ param, navigate }) {
    const me = useMe();
    const owner = me?.role === "owner";
    const devices = useResource((s) => devicesData.devices(s), []);
    const projects = useResource((s) => devicesData.projects(s), []);
    const sensors = useResource((s) => sensorsData.devices(s), []);
    const sensorStates = useResource((s) => sensorsData.states(s), []);
    const forest = useMemo(() => buildForest(projects.data), [projects.data]);
    const [deviceFilter, setDeviceFilter] = useState(null);
    const [expanded, setExpanded] = useState(null);
    const [dialog, setDialog] = useState({ open: false });
    // #/devices/<project_id> opens a digest; #/devices/sensors/<device_id> a sensor.
    const sensorId = param?.startsWith("sensors/") ? param.slice("sensors/".length) || null : null;
    const selected = sensorId ? null : param ?? null;
    const open = useCallback((id) => navigate(id ? `#/devices/${encodeURIComponent(id)}` : "#/devices"), [navigate]);
    const openSensor = useCallback((id) => navigate(id ? `#/devices/sensors/${encodeURIComponent(id)}` : "#/devices"), [navigate]);
    // Poll live sensors in place while this section is visible: reload() keeps the
    // previous data mounted, so nothing remounts and no open state is lost.
    usePolling(() => {
        if (selected)
            return; // a project digest is open; the sensor column isn't visible
        sensors.reload();
        sensorStates.reload();
    }, SENSORS_POLL_MS);
    const sensorList = useMemo(() => sortSensorDevices(sensors.data?.devices ?? []), [sensors.data]);
    const statesMap = useMemo(() => new Map((sensorStates.data ?? []).map((r) => [r.entity_id, r])), [sensorStates.data]);
    const { state: job, start, clear } = useAnalyzeJob(() => projects.reload());
    // expand every folder that has children on first load; always reveal the selection
    useEffect(() => {
        if (!projects.data)
            return;
        setExpanded((prev) => {
            const next = new Set(prev ?? [...forest.children.entries()].filter(([, c]) => c.length).map(([id]) => id));
            if (selected)
                for (const a of ancestors(forest, selected))
                    next.add(a.project_id);
            return next;
        });
    }, [projects.data, forest, selected]);
    const matches = useMemo(() => (deviceFilter ? (p) => p.device_id === deviceFilter : undefined), [deviceFilter]);
    const rows = useMemo(() => visibleRows(forest, expanded ?? new Set(), matches), [forest, expanded, matches]);
    const cells = useMemo(() => {
        const roots = deviceFilter ? forest.roots.filter((id) => rows.some((r) => r.project.project_id === id)) : forest.roots;
        return treemapCells(forest, roots);
    }, [forest, rows, deviceFilter]);
    const toggle = (id) => setExpanded((prev) => {
        const next = new Set(prev ?? []);
        if (next.has(id))
            next.delete(id);
        else
            next.add(id);
        return next;
    });
    const openAnalyze = (path) => setDialog({ open: true, path });
    const all = projects.data?.projects ?? [];
    const totals = useMemo(() => all.reduce((a, p) => ({ files: a.files + (p.parent_id ? 0 : p.stats.files), nodes: a.nodes + (p.parent_id ? 0 : p.stats.nodes) }), { files: 0, nodes: 0 }), [all]);
    const tree = (_jsx(TreeBlock, { loading: projects.loading && !projects.data, error: projects.error && !projects.data ? projects.error : null, onRetry: projects.reload, empty: !!projects.data && all.length === 0, owner: owner, onAnalyze: () => openAnalyze(), children: _jsx(FolderTree, { rows: rows, forest: forest, selected: selected, onToggle: toggle, onOpen: open }) }));
    return (_jsxs("div", { className: "@container/devices h-full min-h-0", children: [_jsxs("div", { className: "grid h-full min-h-0 grid-cols-1 @4xl/devices:grid-cols-[minmax(250px,300px)_minmax(0,1fr)]", children: [_jsxs("aside", { className: "hidden min-h-0 flex-col border-r border-line bg-canvas @4xl/devices:flex", "aria-label": "Folder hierarchy", children: [_jsxs("div", { className: "flex items-center justify-between gap-2 px-4 pt-4 pb-2", children: [_jsxs("div", { children: [_jsx("h2", { className: "text-[13px] font-semibold text-ink", children: "Folders Jarvis knows" }), _jsx("p", { className: "text-[11.5px] text-muted", children: projects.data ? `${plural(all.length, "folder")} · ${compact(totals.files)} files` : " " })] }), owner ? _jsx(Button, { size: "sm", variant: "ghost", icon: "plus", onClick: () => openAnalyze(), "aria-label": "Analyze a folder", title: "Analyze a folder" }) : null] }), deviceFilter ? _jsx(FilterNote, { device: devices.data?.devices.find((d) => d.device_id === deviceFilter)?.label, onClear: () => setDeviceFilter(null) }) : null, _jsx("div", { className: "min-h-0 flex-1 overflow-y-auto px-2 pb-3", children: tree }), _jsx("div", { className: "border-t border-line px-4 py-2.5", children: _jsx(TreeLegend, {}) })] }), _jsxs("section", { className: "@container min-h-0 min-w-0 overflow-y-auto", children: [job && !dialog.open ? _jsx(JobBanner, { job: job, onOpen: () => setDialog({ open: true }), onDismiss: clear, onOpenProject: open }) : null, sensorId ? (_jsx(SensorDetailView, { id: sensorId, sensors: sensors, states: sensorStates, onBack: () => openSensor(null) })) : selected ? (_jsx(ProjectDigestView, { id: selected, forest: forest, devices: devices.data?.devices ?? [], owner: owner, onOpen: open, onAnalyze: openAnalyze }, selected)) : (_jsxs("div", { className: "mx-auto w-full max-w-[1120px] space-y-9 px-4 py-6 sm:px-8 sm:py-8", children: [_jsx(SectionHeader, { level: 1, eyebrow: "Devices", title: "Where your work lives", description: "Jarvis reads folders on these devices through their connectors. Each analyzed folder becomes project knowledge it can reason about, and folders nest the way they do on disk.", actions: owner ? _jsx(Button, { variant: "primary", icon: "plus", onClick: () => openAnalyze(), children: "Analyze a folder" }) : null }), _jsxs("section", { "aria-labelledby": "devices-h", className: "space-y-3", children: [_jsxs("div", { className: "flex items-baseline justify-between gap-2", children: [_jsx("h2", { id: "devices-h", className: "text-[13px] font-semibold text-ink", children: "Devices" }), deviceFilter ? _jsx("button", { type: "button", onClick: () => setDeviceFilter(null), className: "text-[12px] text-accent-ink hover:underline", children: "Show all devices" }) : _jsx("span", { className: "text-[12px] text-muted", children: "Select a device to filter its folders" })] }), devices.loading && !devices.data ? _jsx(DeviceCardsSkeleton, {}) : null, devices.error && !devices.data ? _jsx(ErrorState, { compact: true, error: devices.error, service: "Device registry", title: "Couldn't load devices", onRetry: devices.reload }) : null, devices.data && devices.data.devices.length === 0 ? (_jsx(Card, { children: _jsx(EmptyState, { icon: "devices", title: "No devices yet", body: "Pair a computer's connector (UYP connector on the Mac) and it appears here." }) })) : null, devices.data?.devices.length ? _jsx(DeviceCards, { devices: devices.data.devices, selected: deviceFilter, onSelect: setDeviceFilter }) : null] }), _jsxs("section", { "aria-labelledby": "sensors-h", className: "space-y-3", children: [_jsxs("div", { className: "flex flex-wrap items-baseline justify-between gap-2", children: [_jsxs("div", { children: [_jsx("h2", { id: "sensors-h", className: "text-[13px] font-semibold text-ink", children: "Sensors" }), _jsx("p", { className: "text-[12.5px] text-muted", children: "Live household readings from the sensor hub \u2014 air quality, presence, meeting audio. Updates every 10 s." })] }), sensors.data ? _jsx("span", { className: "text-[12px] text-muted", children: plural(sensorList.length, "device") }) : null] }), sensors.loading && !sensors.data ? _jsx(SensorCardsSkeleton, {}) : null, sensors.error && !sensors.data ? _jsx(ErrorState, { compact: true, error: sensors.error, service: "Sensor hub", title: "Couldn't load sensors", onRetry: sensors.reload }) : null, sensors.data && sensors.data.devices.length === 0 && !(sensors.data.placeholders ?? []).length ? (_jsx(Card, { children: _jsx(EmptyState, { icon: "devices", title: "No sensors yet", body: "Any device that speaks the Home Assistant MQTT discovery convention appears here automatically \u2014 power it on and it shows up." }) })) : null, sensorList.length || (sensors.data?.placeholders ?? []).length ? (_jsx(SensorCards, { devices: sensorList, placeholders: sensors.data?.placeholders ?? [], states: statesMap, openId: null, onOpen: openSensor })) : null] }), _jsxs("section", { "aria-labelledby": "hier-h", className: "space-y-3", children: [_jsxs("div", { className: "flex flex-wrap items-baseline justify-between gap-2", children: [_jsxs("div", { children: [_jsx("h2", { id: "hier-h", className: "text-[13px] font-semibold text-ink", children: "Folder hierarchy" }), _jsx("p", { className: "text-[12.5px] text-muted", children: "Area = files. A folder inside another analyzed folder is its child and inherits its overview as context." })] }), projects.data ? _jsxs("span", { className: "text-[12px] text-muted", children: [plural(all.length, "folder"), " \u00B7 ", compact(totals.files), " files \u00B7 ", compact(totals.nodes), " graph nodes"] }) : null] }), projects.loading && !projects.data ? _jsx(Skeleton, { className: "h-[220px] rounded-card" }) : null, projects.error && !projects.data ? _jsx(ErrorState, { compact: true, error: projects.error, service: "Project knowledge (UYP)", title: "Couldn't load analyzed folders", onRetry: projects.reload }) : null, projects.data && all.length ? _jsx(Treemap, { cells: cells, selected: selected, onOpen: open }) : null] }), _jsxs("section", { "aria-label": "Folders", className: "space-y-2 @4xl/devices:hidden", children: [_jsx("h2", { className: "text-[13px] font-semibold text-ink", children: "Folders" }), deviceFilter ? _jsx(FilterNote, { device: devices.data?.devices.find((d) => d.device_id === deviceFilter)?.label, onClear: () => setDeviceFilter(null) }) : null, _jsx(Card, { className: "p-2", children: tree }), _jsx(TreeLegend, {})] })] }))] })] }), _jsx(AnalyzeDialog, { open: dialog.open, onClose: () => setDialog({ open: false }), initialPath: dialog.path, devices: devices.data?.devices ?? [], projects: all, job: job, onStart: start, onReset: clear, onOpenProject: open, owner: owner })] }));
}
function TreeBlock({ loading, error, onRetry, empty, owner, onAnalyze, children }) {
    if (loading) {
        return (_jsx("div", { className: "space-y-2 p-2", "aria-busy": "true", children: [70, 55, 62, 48, 66].map((w, i) => _jsx(Skeleton, { className: "h-6", style: { width: `${w}%`, marginLeft: i % 3 ? 18 : 0 } }, i)) }));
    }
    if (error)
        return _jsx(ErrorState, { error: error, service: "Project knowledge (UYP)", title: "Folders unavailable", onRetry: onRetry });
    if (empty) {
        return (_jsx(EmptyState, { icon: "folder", title: "No folders analyzed yet", body: "Point Jarvis at a folder and it builds a digest it can answer from.", action: owner ? _jsx(Button, { size: "sm", variant: "primary", icon: "plus", onClick: onAnalyze, children: "Analyze a folder" }) : undefined }));
    }
    return _jsx(_Fragment, { children: children });
}
function FilterNote({ device, onClear }) {
    return (_jsxs("div", { className: "mx-2 mb-1 flex items-center justify-between gap-2 rounded-control bg-accent-soft px-2.5 py-1.5 text-[12px] text-accent-ink", children: [_jsxs("span", { className: "truncate", children: ["Only ", device ?? "one device"] }), _jsx("button", { type: "button", onClick: onClear, className: "shrink-0 font-medium underline underline-offset-2", children: "Clear" })] }));
}
function JobBanner({ job, onOpen, onDismiss, onOpenProject }) {
    const j = job.job;
    const done = isFinished(job);
    const ok = j?.status === "done";
    return (_jsx("div", { className: cx("sticky top-0 z-10 border-b px-4 py-2.5 backdrop-blur sm:px-8", ok ? "border-ok/25 bg-ok-soft/90" : j?.status === "failed" ? "border-err/25 bg-err-soft/90" : "border-line bg-surface/90"), children: _jsxs("div", { className: "mx-auto flex max-w-[1120px] flex-wrap items-center gap-x-3 gap-y-1.5", children: [_jsx(Icon, { name: ok ? "check" : j?.status === "failed" ? "alert" : "activity", size: 15, className: ok ? "text-ok" : j?.status === "failed" ? "text-err" : "text-accent-ink" }), _jsxs("span", { className: "min-w-0 truncate text-[13px] text-ink", children: [ok ? "Analysis finished" : j?.status === "failed" ? "Analysis failed" : "Analyzing", " ", _jsx("span", { className: "font-mono text-[12px] text-muted", children: tildePath(job.path) }), !done && j ? _jsxs("span", { className: "text-muted", children: [" \u00B7 ", j.phase] }) : null] }), !done ? _jsx(ProgressBar, { value: j?.progress.done ?? 0, max: j?.progress.total || 1, className: "w-32", label: "Analysis progress" }) : null, _jsxs("span", { className: "ml-auto flex items-center gap-1", children: [ok ? _jsx(Button, { size: "sm", variant: "secondary", onClick: () => { onOpenProject(job.result.project_id); onDismiss(); }, children: "Open digest" }) : _jsx(Button, { size: "sm", variant: "ghost", onClick: onOpen, children: "Details" }), done ? _jsx(Button, { size: "sm", variant: "ghost", icon: "x", onClick: onDismiss, "aria-label": "Dismiss" }) : null] })] }) }));
}
