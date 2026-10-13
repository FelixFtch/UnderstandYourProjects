import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { clockTime, dayDiff } from "../../design/format";
import { Icon } from "../../design/icons";
import { Markdown } from "../../design/Markdown";
import { Button, Chip, cx, StatusDot } from "../../design/primitives";
import { TracePanel } from "./TracePanel";
import { buildSteps } from "./turn";
const EVIDENCE_ICON = { file: "file", brain: "brain", project: "project" };
export function MeBubble({ bubble }) {
    return (_jsxs("div", { className: "j-rise flex flex-col items-end", children: [_jsx("div", { className: "max-w-[min(85%,560px)] rounded-[16px] rounded-br-[6px] border border-line bg-raised px-3.5 py-2 text-[15px] leading-relaxed break-words whitespace-pre-wrap text-ink", children: bubble.text }), _jsx("div", { className: "mt-1 pr-1 text-[11.5px] text-faint", children: bubble.status === "pending" ? "Sending…" : bubble.status === "failed" ? _jsx("span", { className: "text-err", children: "Not delivered" }) : clockTime(bubble.createdAt) })] }));
}
export function JarvisReply({ bubble, spec, live, onRetry }) {
    const streaming = bubble.status === "streaming";
    const current = streaming && !bubble.text ? currentStep(bubble, spec) : null;
    return (_jsxs("article", { className: "j-rise min-w-0", "aria-busy": streaming, children: [_jsxs("header", { className: "mb-1.5 flex items-center gap-2 text-[12px] text-muted", children: [_jsx("span", { className: "grid size-[22px] place-items-center rounded-full border border-accent/40 font-serif text-[12px] text-accent-ink italic", children: "J" }), _jsx("span", { className: "font-medium text-ink-2", children: "Jarvis" }), _jsx("span", { className: "text-faint", children: streaming ? "replying…" : clockTime(bubble.createdAt) }), bubble.status === "stopped" ? _jsx(Chip, { tone: "neutral", children: "stopped" }) : null] }), _jsxs("div", { className: "pl-[30px]", children: [bubble.text ? (_jsx(Markdown, { text: bubble.text, className: cx("text-[15px] text-ink", streaming && "j-caret") })) : streaming ? (_jsxs("div", { className: "flex items-center gap-2 py-1 text-[14px] text-muted", children: [_jsx(StatusDot, { tone: current?.group ?? "accent", pulse: true }), current ? `${current.label}…` : "Thinking…"] })) : null, bubble.errors.map((e, i) => (_jsxs("div", { role: "alert", className: "mt-2 flex items-start gap-2 rounded-control border border-err/30 bg-err-soft px-3 py-2 text-[13px] text-err", children: [_jsx(Icon, { name: "alert", size: 15, className: "mt-0.5 shrink-0" }), _jsx("span", { className: "min-w-0 break-words", children: e })] }, i))), bubble.status === "failed" && bubble.question && onRetry ? (_jsx(Button, { size: "sm", variant: "secondary", icon: "refresh", className: "mt-2", onClick: onRetry, children: "Try again" })) : null, bubble.evidence.length || bubble.handoffs.length ? (_jsxs("div", { className: "mt-3 flex flex-wrap gap-1.5", children: [bubble.handoffs.map((h, i) => (_jsxs(Chip, { tone: "accent", icon: "handoff", href: h.thread_id ? `#/agents/${encodeURIComponent(h.thread_id)}` : "#/agents", title: [h.question && `Asked: ${h.question}`, h.answer && `Answer: ${h.answer}`].filter(Boolean).join("\n") || undefined, children: ["Asked ", h.contact, " \u2192 open chat"] }, `h${i}`))), bubble.evidence.map((e) => (_jsx(Chip, { icon: EVIDENCE_ICON[e.kind] ?? "link", mono: e.kind === "file", href: e.kind === "project" ? `#/devices/${encodeURIComponent(e.ref)}` : undefined, title: `${e.kind}: ${e.ref}`, className: "max-w-[260px]", children: e.label }, `${e.kind}|${e.ref}`)))] })) : null, _jsx(TracePanel, { frames: bubble.frames, spec: spec, live: live, stats: bubble.stats })] })] }));
}
function currentStep(bubble, spec) {
    const steps = buildSteps(bubble.frames, spec);
    for (let i = steps.length - 1; i >= 0; i--)
        if (steps[i].status === "start")
            return steps[i];
    return steps[steps.length - 1] ?? null;
}
export function DaySeparator({ iso }) {
    const d = new Date(iso);
    const diff = dayDiff(d, new Date());
    const label = diff === 0 ? "Today" : diff === 1 ? "Yesterday" : d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
    return (_jsxs("div", { className: "flex items-center gap-3 py-1 text-[11px] font-semibold tracking-[0.08em] text-faint uppercase", role: "separator", children: [_jsx("span", { className: "h-px flex-1 bg-line" }), label, _jsx("span", { className: "h-px flex-1 bg-line" })] }));
}
