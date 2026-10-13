import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// Flow — read-only view of the agent flow spec, lit by the most recent Jarvis turn.
//
// Cross-feature exception (documented in features/jarvis/lastTrace.ts): this file imports
// `useLastTrace` from features/jarvis and nothing else from another feature.
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { formatMs, plural, relativeTime } from "../../design/format";
import { useResource } from "../../design/hooks";
import { Icon } from "../../design/icons";
import { Card, Chip, cx, EmptyState, ErrorState, Segmented, SectionHeader, Skeleton, StatusDot } from "../../design/primitives";
import { useLastTrace } from "../jarvis/lastTrace";
import { flowData } from "./data";
import { columns, edgeKey, edgePath, GROUP_INFO, nodeRuns, traversed } from "./layout";
const GROUP_TEXT = { understand: "text-g-understand", retrieve: "text-g-retrieve", act: "text-g-act", respond: "text-g-respond" };
const GROUP_BORDER = { understand: "border-l-g-understand", retrieve: "border-l-g-retrieve", act: "border-l-g-act", respond: "border-l-g-respond" };
const GROUP_TINT = { understand: "bg-g-understand/8", retrieve: "bg-g-retrieve/8", act: "bg-g-act/8", respond: "bg-g-respond/8" };
const GROUP_BAR = { understand: "bg-g-understand", retrieve: "bg-g-retrieve", act: "bg-g-act", respond: "bg-g-respond" };
export default function FlowPage(_props) {
    const flows = useResource(() => flowData.flows(), []);
    const [name, setName] = useState("studio");
    const spec = useResource(() => flowData.flow(name), [name]);
    const recent = useResource((s) => flowData.recentTrace(s), []);
    const live = useLastTrace();
    const [selected, setSelected] = useState(null);
    // the live store wins; otherwise the latest persisted reply with a trace
    const trace = live.turnId ? { frames: live.frames, at: live.startedAt, question: live.question, live: live.live }
        : recent.data ? { frames: recent.data.frames, at: recent.data.at, question: recent.data.question, live: false } : null;
    const runs = useMemo(() => nodeRuns(trace?.frames ?? []), [trace?.frames]);
    const names = flows.data?.flows.map((f) => f.name) ?? ["studio"];
    const options = (names.includes(name) ? names : [name, ...names]).map((n) => ({ value: n, label: n }));
    return (_jsxs("div", { className: "@container mx-auto w-full max-w-[1320px] space-y-6 px-4 py-6 sm:px-8 sm:py-8", children: [_jsx(SectionHeader, { level: 1, eyebrow: "Flow", title: "How Jarvis thinks", description: "Every message passes through these steps, left to right: understand, retrieve, act, respond. The path of your most recent Jarvis turn is lit up.", actions: options.length > 1 ? _jsx(Segmented, { label: "Flow", value: name, options: options, onChange: (v) => { setName(v); setSelected(null); } }) : null }), _jsx(LastTurn, { trace: trace, runs: runs, loading: recent.loading && !live.turnId }), _jsxs("div", { className: "grid gap-5 @6xl:grid-cols-[minmax(0,1fr)_300px]", children: [_jsxs(Card, { className: "@container min-w-0 p-4 sm:p-5", children: [spec.loading && !spec.data ? _jsx(GraphSkeleton, {}) : null, spec.error && !spec.data ? _jsx(ErrorState, { error: spec.error, service: "Agent runtime", title: "Couldn't load this flow", onRetry: spec.reload }) : null, spec.data && spec.data.nodes.length === 0 ? _jsx(EmptyState, { icon: "flow", title: "This flow has no nodes", body: "The agent runtime returned an empty spec." }) : null, spec.data && spec.data.nodes.length ? (_jsxs(_Fragment, { children: [spec.data.description ? _jsxs("p", { className: "mb-4 text-[13px] text-muted", children: [spec.data.description, " ", _jsxs("span", { className: "font-mono text-faint", children: ["v", spec.data.version] })] }) : null, _jsx(Graph, { spec: spec.data, runs: runs, hasTrace: !!trace, selected: selected, onSelect: setSelected })] })) : null] }), _jsx(NodeDetail, { spec: spec.data ?? null, id: selected, runs: runs, onSelect: setSelected })] })] }));
}
function LastTurn({ trace, runs, loading }) {
    if (loading)
        return _jsx(Skeleton, { className: "h-[62px] rounded-card" });
    if (!trace) {
        return (_jsxs("div", { className: "flex flex-wrap items-center gap-3 rounded-card border border-dashed border-line-strong px-4 py-3 text-[13.5px] text-muted", children: [_jsx(Icon, { name: "info", size: 16 }), _jsx("span", { className: "min-w-0 flex-1", children: "No Jarvis turn to show yet. Ask Jarvis something and watch its path light up here." }), _jsx("a", { href: "#/jarvis", className: "font-medium text-accent-ink hover:underline", children: "Open Jarvis \u2192" })] }));
    }
    const vals = Object.values(runs);
    const steps = vals.filter((r) => r.status !== "skip").length;
    const tools = vals.reduce((a, r) => a + r.tools.length, 0);
    const ms = vals.reduce((a, r) => a + (r.ms ?? 0), 0);
    return (_jsxs("div", { className: "flex flex-wrap items-center gap-x-4 gap-y-2 rounded-card border border-line bg-surface px-4 py-3 shadow-card", children: [_jsx(StatusDot, { tone: trace.live ? "accent" : "ok", pulse: trace.live }), _jsxs("div", { className: "min-w-0 flex-[1_1_240px]", children: [_jsxs("div", { className: "text-[11px] font-semibold tracking-[0.06em] text-muted uppercase", children: [trace.live ? "Running now" : "Last Jarvis turn", trace.at ? ` · ${relativeTime(trace.at)}` : ""] }), _jsx("div", { className: "truncate text-[14px] text-ink", children: trace.question ? `“${trace.question}”` : "(question not recorded)" })] }), _jsxs("div", { className: "text-[12.5px] text-muted", children: [plural(steps, "step"), " \u00B7 ", plural(tools, "tool"), ms ? ` · ${formatMs(ms)}` : ""] }), _jsx("a", { href: "#/jarvis", className: "text-[12.5px] font-medium text-accent-ink hover:underline", children: "Open chat \u2192" })] }));
}
function Graph({ spec, runs, hasTrace, selected, onSelect }) {
    const wrap = useRef(null);
    const [geo, setGeo] = useState({ w: 0, h: 0, rects: {} });
    const cols = useMemo(() => columns(spec), [spec]);
    const lit = useMemo(() => traversed(spec.edges, runs), [spec.edges, runs]);
    useLayoutEffect(() => {
        const el = wrap.current;
        if (!el)
            return;
        const measure = () => {
            const base = el.getBoundingClientRect();
            const rects = {};
            el.querySelectorAll("[data-node]").forEach((n) => {
                const r = n.getBoundingClientRect();
                rects[n.dataset.node] = { x: r.left - base.left, y: r.top - base.top, w: r.width, h: r.height };
            });
            setGeo({ w: base.width, h: base.height, rects });
        };
        measure();
        if (typeof ResizeObserver === "undefined")
            return;
        const ro = new ResizeObserver(measure);
        ro.observe(el);
        return () => ro.disconnect();
    }, [spec, runs]);
    const outgoing = (id) => spec.edges.filter((e) => e.from === id).map((e) => spec.nodes.find((n) => n.id === e.to)?.label ?? e.to);
    return (_jsxs("div", { ref: wrap, className: "relative", children: [_jsxs("svg", { className: "pointer-events-none absolute inset-0 hidden overflow-visible @3xl:block", width: geo.w, height: geo.h, "aria-hidden": "true", children: [_jsxs("defs", { children: [_jsx("marker", { id: "flow-arrow", viewBox: "0 0 8 8", refX: "7", refY: "4", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse", children: _jsx("path", { d: "M0 0 L8 4 L0 8 z", fill: "var(--j-line-strong)" }) }), _jsx("marker", { id: "flow-arrow-lit", viewBox: "0 0 8 8", refX: "7", refY: "4", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse", children: _jsx("path", { d: "M0 0 L8 4 L0 8 z", fill: "var(--j-accent)" }) })] }), [...spec.edges].sort((a, b) => Number(lit.has(edgeKey(a))) - Number(lit.has(edgeKey(b)))).map((e) => {
                        const a = geo.rects[e.from], b = geo.rects[e.to];
                        if (!a || !b)
                            return null;
                        const on = lit.has(edgeKey(e));
                        return (_jsx("path", { d: edgePath(a, b), fill: "none", stroke: on ? "var(--j-accent)" : "var(--j-line-strong)", strokeWidth: on ? 2 : 1.25, strokeDasharray: hasTrace && !on ? "3 4" : undefined, markerEnd: `url(#${on ? "flow-arrow-lit" : "flow-arrow"})` }, edgeKey(e)));
                    })] }), _jsx("div", { className: "relative grid gap-6 @3xl:grid-cols-4 @3xl:gap-10", children: cols.map((col) => (_jsxs("section", { className: "min-w-0", "aria-label": GROUP_INFO[col.group].title, children: [_jsx("div", { className: cx("h-1 w-10 rounded-full", GROUP_BAR[col.group]) }), _jsx("h3", { className: cx("mt-2 text-[12px] font-semibold tracking-[0.08em] uppercase", GROUP_TEXT[col.group]), children: GROUP_INFO[col.group].title }), _jsx("p", { className: "mt-0.5 min-h-[34px] text-[12px] leading-snug text-muted", children: GROUP_INFO[col.group].body }), _jsxs("div", { className: "mt-3 space-y-3 @3xl:space-y-5", children: [col.nodes.length === 0 ? _jsx("div", { className: "rounded-[12px] border border-dashed border-line px-3 py-4 text-center text-[12px] text-faint", children: "No steps" }) : null, col.nodes.map((n) => (_jsx(NodeCard, { node: n, run: runs[n.id], dim: hasTrace && !runs[n.id], selected: selected === n.id, onSelect: onSelect, next: outgoing(n.id) }, n.id)))] })] }, col.group))) })] }));
}
function NodeCard({ node, run, dim, selected, onSelect, next }) {
    const ran = !!run && run.status !== "skip";
    return (_jsxs("button", { type: "button", "data-node": node.id, onClick: () => onSelect(node.id), "aria-pressed": selected, className: cx("relative block w-full rounded-[12px] border border-l-[3px] bg-surface px-3 py-2.5 text-left transition-[opacity,box-shadow,border-color]", GROUP_BORDER[node.group], ran ? cx(GROUP_TINT[node.group], "border-y-line-strong border-r-line-strong shadow-card") : "border-y-line border-r-line", dim && "opacity-50 hover:opacity-90", selected && "ring-2 ring-accent/35"), children: [_jsxs("div", { className: "flex min-w-0 items-center gap-2", children: [_jsx("span", { className: "min-w-0 flex-1 truncate text-[13.5px] font-medium text-ink", children: node.label }), run ? _jsx(RunBadge, { run: run }) : null] }), _jsx("div", { className: "mt-0.5 truncate font-mono text-[11px] text-muted", children: node.type }), run?.detail ? _jsx("div", { className: "mt-1 truncate text-[11.5px] text-ink-2", title: run.detail, children: run.detail }) : null, next.length ? _jsxs("div", { className: "mt-1 truncate text-[11px] text-faint @3xl:hidden", children: ["\u2192 ", next.join(", ")] }) : null] }));
}
function RunBadge({ run }) {
    if (run.status === "start")
        return _jsxs("span", { className: "flex shrink-0 items-center gap-1 text-[11px] text-accent-ink", children: [_jsx(StatusDot, { tone: "accent", pulse: true }), " running"] });
    if (run.status === "skip")
        return _jsx("span", { className: "shrink-0 text-[11px] text-faint", children: "skipped" });
    if (run.status === "error")
        return _jsx("span", { className: "shrink-0 text-[11px] font-medium text-err", children: "error" });
    return _jsxs("span", { className: "flex shrink-0 items-center gap-1 font-mono text-[11px] text-ok", children: [_jsx(Icon, { name: "check", size: 12, strokeWidth: 2.2 }), run.ms ? formatMs(run.ms) : ""] });
}
function NodeDetail({ spec, id, runs, onSelect }) {
    const node = spec?.nodes.find((n) => n.id === id) ?? null;
    if (!spec)
        return null;
    if (!node) {
        return (_jsxs(Card, { className: "h-fit p-4 @6xl:sticky @6xl:top-4", children: [_jsx("div", { className: "text-[13px] font-semibold text-ink", children: "Reading the graph" }), _jsxs("ul", { className: "mt-2 space-y-2 text-[12.5px] text-muted", children: [_jsxs("li", { className: "flex items-center gap-2", children: [_jsx("span", { className: "h-0.5 w-6 rounded bg-accent" }), " path taken in the last turn"] }), _jsxs("li", { className: "flex items-center gap-2", children: [_jsx("span", { className: "h-0 w-6 border-t border-dashed border-line-strong" }), " not used last time"] }), _jsxs("li", { className: "flex items-center gap-2", children: [_jsx(Icon, { name: "check", size: 13, className: "text-ok" }), " ran, with its duration"] }), _jsxs("li", { className: "flex items-center gap-2", children: [_jsx("span", { className: "text-faint", children: "skipped" }), " considered but not needed"] })] }), _jsx("p", { className: "mt-3 text-[12.5px] text-muted", children: "Select a step to see what it does and what happened in it." })] }));
    }
    const run = runs[node.id];
    const ins = spec.edges.filter((e) => e.to === node.id).map((e) => e.from);
    const outs = spec.edges.filter((e) => e.from === node.id).map((e) => e.to);
    const label = (nid) => spec.nodes.find((n) => n.id === nid)?.label ?? nid;
    const hasConfig = node.config && Object.keys(node.config).length > 0;
    return (_jsxs(Card, { className: "h-fit min-w-0 p-4 @6xl:sticky @6xl:top-4", children: [_jsxs("div", { className: "flex items-start justify-between gap-2", children: [_jsxs("div", { className: "min-w-0", children: [_jsx("div", { className: cx("text-[11px] font-semibold tracking-[0.08em] uppercase", GROUP_TEXT[node.group]), children: GROUP_INFO[node.group].title }), _jsx("h3", { className: "mt-0.5 font-serif text-[19px] leading-snug text-ink", children: node.label }), _jsxs("div", { className: "font-mono text-[11.5px] text-muted", children: [node.type, " \u00B7 ", node.id] })] }), _jsx("button", { type: "button", onClick: () => onSelect(""), className: "rounded-md p-1 text-muted hover:bg-sunk hover:text-ink", "aria-label": "Close details", children: _jsx(Icon, { name: "x", size: 15 }) })] }), _jsxs("div", { className: "mt-4 rounded-[10px] border border-line bg-canvas/50 p-3", children: [_jsx("div", { className: "text-[11px] font-semibold tracking-[0.06em] text-muted uppercase", children: "Last turn" }), run ? (_jsxs("div", { className: "mt-1 space-y-1.5 text-[12.5px]", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx(RunBadge, { run: run }), run.status === "done" && !run.ms ? _jsx("span", { className: "text-muted", children: "done" }) : null] }), run.detail ? _jsx("div", { className: "text-ink-2", children: run.detail }) : null, run.tools.map((t, i) => (_jsxs("div", { className: "rounded-md border border-line bg-surface px-2 py-1", children: [_jsx("span", { className: cx("font-mono", t.ok ? "text-ink" : "text-err"), children: t.name }), t.summary ? _jsx("div", { className: "text-muted", children: t.summary }) : null] }, i)))] })) : _jsx("div", { className: "mt-1 text-[12.5px] text-muted", children: "Not reached in the last turn." })] }), ins.length || outs.length ? (_jsxs("div", { className: "mt-4 space-y-2 text-[12.5px]", children: [ins.length ? _jsxs("div", { children: [_jsx("span", { className: "text-muted", children: "Comes after " }), ins.map((x) => _jsx(Chip, { onClick: () => onSelect(x), className: "mr-1 mb-1", children: label(x) }, x))] }) : null, outs.length ? _jsxs("div", { children: [_jsx("span", { className: "text-muted", children: "Leads to " }), outs.map((x) => _jsx(Chip, { onClick: () => onSelect(x), className: "mr-1 mb-1", children: label(x) }, x))] }) : null] })) : null, hasConfig ? (_jsxs("div", { className: "mt-4", children: [_jsx("div", { className: "mb-1 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase", children: "Config" }), _jsx("pre", { className: "max-h-[200px] overflow-auto rounded-[10px] border border-line bg-sunk p-2.5 font-mono text-[11.5px] leading-relaxed text-ink-2", children: JSON.stringify(node.config, null, 2) })] })) : null] }));
}
function GraphSkeleton() {
    return (_jsx("div", { className: "grid gap-6 @3xl:grid-cols-4 @3xl:gap-10", "aria-busy": "true", "aria-label": "Loading flow", children: [3, 3, 2, 2].map((n, c) => (_jsxs("div", { className: "space-y-3", children: [_jsx(Skeleton, { className: "h-3 w-20" }), _jsx(Skeleton, { className: "h-3 w-full" }), Array.from({ length: n }, (_, i) => _jsx(Skeleton, { className: "h-[64px] rounded-[12px]" }, i))] }, c))) }));
}
