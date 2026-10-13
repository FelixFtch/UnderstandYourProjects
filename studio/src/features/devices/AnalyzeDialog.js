import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { describeError, tildePath } from "../../design/format";
import { Icon } from "../../design/icons";
import { Button, Field, inputClass, Modal, ProgressBar, Spinner, StatusDot } from "../../design/primitives";
import { isFinished, POLL_MS } from "./analyzeJob";
import { confirmedRelation, predictRelation, relationSentence } from "./tree";
export function AnalyzeDialog({ open, onClose, devices, projects, initialPath, job, onStart, onOpenProject, onReset, owner }) {
    const targets = devices.filter((d) => d.kind !== "phone");
    const defaultDevice = (targets.find((d) => d.kind === "computer" && d.connector?.state === "online") ?? targets[0])?.device_id ?? "";
    const [path, setPath] = useState("");
    const [deviceId, setDeviceId] = useState(defaultDevice);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    useEffect(() => {
        if (!open)
            return;
        setError(null);
        if (initialPath !== undefined)
            setPath(tildePath(initialPath));
        if (!deviceId && defaultDevice)
            setDeviceId(defaultDevice);
    }, [open, initialPath, defaultDevice, deviceId]);
    const preview = useMemo(() => (path.trim() ? predictRelation(path, projects, deviceId || null) : null), [path, projects, deviceId]);
    const byId = useMemo(() => new Map(projects.map((p) => [p.project_id, p])), [projects]);
    const valid = /^(~|\/)/.test(path.trim());
    const device = devices.find((d) => d.device_id === deviceId);
    async function submit(e) {
        e.preventDefault();
        if (!valid || busy)
            return;
        setBusy(true);
        setError(null);
        try {
            await onStart(path.trim(), deviceId || undefined);
        }
        catch (err) {
            const d = describeError(err, "Project knowledge (UYP)");
            setError(d.detail ? `${d.title}: ${d.detail}` : d.title);
        }
        finally {
            setBusy(false);
        }
    }
    const finished = isFinished(job);
    const j = job?.job;
    const pct = j && j.progress.total ? Math.round((j.progress.done / j.progress.total) * 100) : 0;
    return (_jsx(Modal, { open: open, onClose: onClose, width: 560, title: job ? "Analyzing a folder" : "Analyze a folder", description: job ? tildePath(job.path) : "Jarvis reads the folder through its device connector and builds project knowledge.", footer: job ? (_jsxs(_Fragment, { children: [finished ? _jsx(Button, { variant: "ghost", onClick: () => { onReset(); setPath(""); }, children: "Analyze another" }) : _jsx("span", { className: "mr-auto text-[12px] text-muted", children: "You can close this; it keeps running." }), finished && j?.status === "done" ? (_jsx(Button, { variant: "primary", iconRight: "arrowRight", onClick: () => { onClose(); onOpenProject(job.result.project_id); }, children: "Open digest" })) : (_jsx(Button, { onClick: onClose, children: "Close" }))] })) : (_jsxs(_Fragment, { children: [_jsx(Button, { variant: "ghost", onClick: onClose, children: "Cancel" }), _jsx(Button, { variant: "primary", type: "submit", form: "analyze-form", disabled: !valid || !owner, loading: busy, children: "Start analysis" })] })), children: !job ? (_jsxs("form", { id: "analyze-form", onSubmit: submit, className: "space-y-4", children: [!owner ? (_jsx("div", { className: "rounded-control border border-warn/25 bg-warn-soft px-3 py-2 text-[13px] text-warn", children: "Only the household owner can start an analysis." })) : null, _jsx(Field, { label: "Folder path", htmlFor: "analyze-path", hint: "An absolute path on the device, e.g. ~/code/adhd-agent", children: _jsx("input", { id: "analyze-path", "data-autofocus": "", value: path, onChange: (e) => { setPath(e.target.value); setError(null); }, placeholder: "~/code/adhd-agent", spellCheck: false, autoComplete: "off", className: `${inputClass} font-mono text-[13px]` }) }), _jsx(Field, { label: "Device", htmlFor: "analyze-device", hint: device?.connector?.state === "offline" ? "This device's connector is offline; the job will wait for it." : undefined, children: _jsxs("select", { id: "analyze-device", value: deviceId, onChange: (e) => setDeviceId(e.target.value), className: inputClass, children: [targets.length === 0 ? _jsx("option", { value: "", children: "No devices with a connector" }) : null, targets.map((d) => (_jsxs("option", { value: d.device_id, children: [d.label, d.connector ? ` · ${d.connector.state}` : " · no connector"] }, d.device_id)))] }) }), preview && valid ? (_jsxs("div", { className: "rounded-[12px] border border-line bg-canvas/50 p-3.5", children: [_jsxs("div", { className: "mb-2 flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase", children: [_jsx(Icon, { name: "project", size: 13 }), " Where it fits"] }), _jsx(RelationDiagram, { path: path, parent: preview.parent, kids: preview.children, existing: !!preview.existing }), _jsx("p", { className: "mt-2.5 text-[13px] text-ink-2", children: relationSentence(preview) }), _jsx("p", { className: "mt-1 text-[11.5px] text-faint", children: "Preview from the folders Jarvis knows; the hub confirms it when you start." })] })) : null, error ? (_jsxs("div", { role: "alert", className: "flex items-start gap-2 rounded-control border border-err/25 bg-err-soft px-3 py-2 text-[13px] text-err", children: [_jsx(Icon, { name: "alert", size: 15, className: "mt-0.5 shrink-0" }), " ", error] })) : null] })) : (_jsxs("div", { className: "space-y-4", children: [_jsxs("div", { className: "flex items-start gap-2 rounded-[12px] border border-accent/25 bg-accent-soft px-3.5 py-3 text-[13.5px] text-accent-ink", children: [_jsx(Icon, { name: "check", size: 16, className: "mt-0.5 shrink-0" }), _jsx("span", { children: confirmedRelation(job.result.relation, byId) })] }), _jsxs("div", { children: [_jsxs("div", { className: "mb-1.5 flex items-center justify-between gap-2 text-[13px]", children: [_jsxs("span", { className: "flex min-w-0 items-center gap-2 text-ink", children: [j?.status === "done" ? _jsx(StatusDot, { tone: "ok" }) : j?.status === "failed" ? _jsx(StatusDot, { tone: "err" }) : _jsx(Spinner, { size: 13 }), _jsx("span", { className: "truncate font-medium", children: j ? (j.status === "done" ? "Done" : j.status === "failed" ? "Failed" : j.phase || j.status) : "Queued" })] }), _jsx("span", { className: "shrink-0 font-mono text-[12px] text-muted", children: j ? `${j.progress.done}/${j.progress.total} · ${pct}%` : "waiting…" })] }), _jsx(ProgressBar, { value: j?.progress.done ?? 0, max: j?.progress.total || 1, tone: j?.status === "failed" ? "err" : j?.status === "done" ? "ok" : "accent", label: "Analysis progress" }), !finished ? _jsxs("div", { className: "mt-1 text-[11.5px] text-faint", children: ["Updates every ", POLL_MS / 1000, " s."] }) : null] }), job.pollError ? (_jsxs("div", { className: "rounded-control border border-warn/25 bg-warn-soft px-3 py-2 text-[12.5px] text-warn", children: ["Couldn't refresh the job status (", describeError(job.pollError).title, "). Retrying\u2026"] })) : null, j?.log_tail?.length ? (_jsxs("div", { children: [_jsx("div", { className: "mb-1 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase", children: "Log" }), _jsx("pre", { className: "max-h-[180px] overflow-auto rounded-[10px] border border-line bg-sunk p-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-ink-2", children: j.log_tail.join("\n") })] })) : null] })) }));
}
function RelationDiagram({ path, parent, kids, existing }) {
    const name = path.trim().replace(/\/+$/, "").split("/").pop() || path;
    const indent = parent ? 1 : 0;
    return (_jsxs("ul", { className: "space-y-1 font-mono text-[12.5px]", children: [parent ? (_jsxs("li", { className: "flex items-center gap-2 text-muted", children: [_jsx(Icon, { name: "folderOpen", size: 14 }), " ", parent.root_name, " ", _jsx("span", { className: "font-sans text-[11px] text-faint", children: "analyzed" })] })) : null, _jsxs("li", { className: "flex items-center gap-2 text-ink", style: { paddingLeft: indent * 18 }, children: [indent ? _jsx("span", { className: "text-faint", children: "\u2514" }) : null, _jsx(Icon, { name: "folder", size: 14, className: "text-accent-ink" }), " ", name, _jsx("span", { className: "rounded-full bg-accent-soft px-1.5 font-sans text-[10.5px] font-semibold text-accent-ink", children: existing ? "refresh" : "new" })] }), kids.slice(0, 4).map((k) => (_jsxs("li", { className: "flex items-center gap-2 text-muted", style: { paddingLeft: (indent + 1) * 18 }, children: [_jsx("span", { className: "text-faint", children: "\u2514" }), _jsx(Icon, { name: "folder", size: 14 }), " ", k.root_name, " ", _jsx("span", { className: "font-sans text-[11px] text-faint", children: "reused" })] }, k.project_id))), kids.length > 4 ? _jsxs("li", { className: "pl-12 font-sans text-[11.5px] text-faint", children: ["+", kids.length - 4, " more"] }) : null] }));
}
