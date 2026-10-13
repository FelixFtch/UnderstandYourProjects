import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo, useState } from "react";
import { formatMs, plural } from "../../design/format";
import { Icon } from "../../design/icons";
import { cx, StatusDot } from "../../design/primitives";
import { buildSteps, formatArgs, GROUP_LABEL, GROUP_ORDER, groupTotals, toolCount, totalMs, } from "./turn";
export const GROUP_TEXT = {
    understand: "text-g-understand",
    retrieve: "text-g-retrieve",
    act: "text-g-act",
    respond: "text-g-respond",
};
export const GROUP_BG = {
    understand: "bg-g-understand",
    retrieve: "bg-g-retrieve",
    act: "bg-g-act",
    respond: "bg-g-respond",
};
export function TracePanel({ frames, spec, live, stats }) {
    const steps = useMemo(() => buildSteps(frames, spec), [frames, spec]);
    const [open, setOpen] = useState(null);
    const isOpen = open ?? live;
    if (!steps.length && !live)
        return null;
    const total = totalMs(steps, stats);
    const tools = toolCount(steps);
    const touched = new Set(steps.filter((s) => s.status !== "skip").map((s) => s.group));
    return (_jsxs("div", { className: "mt-3 overflow-hidden rounded-[12px] border border-line bg-surface/70", children: [_jsxs("button", { type: "button", onClick: () => setOpen(!isOpen), "aria-expanded": isOpen, className: "flex w-full min-w-0 items-center gap-2 px-3 py-2 text-left text-[12.5px] text-muted transition-colors hover:text-ink", children: [_jsx(Icon, { name: "chevronRight", size: 14, className: cx("shrink-0 transition-transform", isOpen && "rotate-90") }), _jsx("span", { className: "shrink-0 font-medium text-ink-2", children: "How Jarvis handled this" }), _jsxs("span", { className: "min-w-0 truncate", children: [live && !steps.length ? "· starting…" : `· ${plural(steps.length, "step")}`, tools ? ` · ${plural(tools, "tool")}` : "", total && !live ? ` · ${formatMs(total)}` : ""] }), _jsx("span", { className: "ml-auto hidden shrink-0 items-center gap-1 sm:flex", "aria-hidden": "true", children: GROUP_ORDER.map((g) => (_jsx("span", { className: cx("h-1.5 w-4 rounded-full", touched.has(g) ? GROUP_BG[g] : "bg-line") }, g))) })] }), isOpen ? (_jsxs("div", { className: "border-t border-line px-3 pt-3 pb-2", children: [_jsx(GroupBar, { steps: steps }), _jsxs("ol", { className: "mt-3", children: [steps.map((s, i) => _jsx(StepRow, { step: s, last: i === steps.length - 1 }, s.key)), live ? (_jsxs("li", { className: "flex items-center gap-2 py-1 pl-0.5 text-[12px] text-muted", children: [_jsx(StatusDot, { tone: "accent", pulse: true }), " working\u2026"] })) : null] })] })) : null] }));
}
function GroupBar({ steps }) {
    const totals = groupTotals(steps);
    const present = new Set(steps.map((s) => s.group));
    const sum = GROUP_ORDER.reduce((a, g) => a + totals[g], 0);
    return (_jsxs("div", { children: [_jsx("div", { className: "flex h-1.5 gap-0.5 overflow-hidden rounded-full", "aria-hidden": "true", children: GROUP_ORDER.map((g) => (_jsx("span", { className: cx("h-full rounded-full", present.has(g) ? GROUP_BG[g] : "bg-line"), style: { flexGrow: sum ? Math.max(totals[g], sum * 0.04) : 1, flexBasis: 0 } }, g))) }), _jsx("div", { className: "mt-1.5 grid grid-cols-4 gap-1 text-[11px]", children: GROUP_ORDER.map((g) => (_jsxs("div", { className: cx("min-w-0 truncate", present.has(g) ? GROUP_TEXT[g] : "text-faint"), children: [_jsx("span", { className: "font-semibold tracking-wide uppercase", children: GROUP_LABEL[g] }), totals[g] ? _jsx("span", { className: "ml-1 font-mono text-muted", children: formatMs(totals[g]) }) : null] }, g))) })] }));
}
function StepRow({ step: s, last }) {
    const right = s.status === "start" ? "running" : s.status === "skip" ? "skipped" : s.status === "error" ? "error" : formatMs(s.ms) || "done";
    return (_jsxs("li", { className: "relative grid grid-cols-[14px_minmax(0,1fr)_auto] gap-x-2.5 py-1", children: [!last ? _jsx("span", { "aria-hidden": "true", className: "absolute top-[18px] bottom-[-6px] left-[6.5px] w-px bg-line" }) : null, _jsx("span", { className: "relative pt-[6px]", children: _jsx(StatusDot, { tone: s.status === "error" ? "err" : s.group, pulse: s.status === "start", className: cx("ring-2 ring-surface", s.status === "skip" && "opacity-35") }) }), _jsxs("div", { className: "min-w-0", children: [_jsxs("div", { className: "flex min-w-0 flex-wrap items-baseline gap-x-2", children: [_jsx("span", { className: cx("text-[13px] font-medium", s.status === "skip" ? "text-muted" : "text-ink"), children: s.label }), _jsx("span", { className: cx("text-[10.5px] font-semibold tracking-wider uppercase", GROUP_TEXT[s.group], s.status === "skip" && "opacity-60"), children: s.group })] }), s.detail ? _jsx("div", { className: "truncate text-[12px] text-muted", title: s.detail, children: s.detail }) : null, s.tools.map((t, i) => (_jsxs("div", { className: "mt-1 flex min-w-0 items-start gap-1.5 rounded-md border border-line bg-sunk px-2 py-1 text-[12px]", children: [_jsx(Icon, { name: t.ok ? "check" : "x", size: 13, className: cx("mt-[2px] shrink-0", t.ok ? "text-ok" : "text-err") }), _jsxs("div", { className: "min-w-0", children: [_jsx("span", { className: "font-mono text-ink-2", children: t.name }), t.args && Object.keys(t.args).length ? (_jsx("span", { className: "ml-1.5 font-mono break-all text-faint", children: formatArgs(t.args) })) : null, t.summary ? _jsx("div", { className: "text-muted", children: t.summary }) : null] })] }, i)))] }), _jsx("span", { className: cx("pt-[1px] text-right font-mono text-[11.5px] tabular-nums", s.status === "error" ? "text-err" : "text-muted"), children: right })] }));
}
