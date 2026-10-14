import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { compact, relativeTime } from "../../design/format";
import { Icon } from "../../design/icons";
import { Button, Card, Chip, Skeleton } from "../../design/primitives";
/** "¥1.23" — CNY with two decimals. */
export function yuan(n) {
    return `¥${n.toFixed(2)}`;
}
/** "913k in · 246k out" — compact token pair for one bucket. */
export function tokenPair(b) {
    return `${compact(b.prompt_tokens)} in · ${compact(b.completion_tokens)} out`;
}
const SURFACE_LABEL = { route: "Route", persona: "Persona", split: "Split" };
const PERIODS = [
    ["Today", (u) => u.today],
    ["This month", (u) => u.month],
    ["All time", (u) => u.total],
];
export function CloudUsageCard({ usage, onRefresh }) {
    const cloud = usage.mode === "cloud";
    return (_jsxs(Card, { className: "p-4", children: [_jsxs("div", { className: "flex min-w-0 items-start gap-3", children: [_jsx("span", { className: "grid size-9 shrink-0 place-items-center rounded-[10px] border border-accent/30 bg-accent-soft text-accent-ink", children: _jsx(Icon, { name: "chip", size: 18 }) }), _jsxs("div", { className: "min-w-0 flex-1", children: [_jsx("div", { className: "truncate text-[14px] font-medium text-ink", children: "Cloud usage (qwen)" }), _jsxs("div", { className: "mt-0.5 truncate text-[12px] text-muted", children: ["Text-only cloud turns, metered by companion-api \u00B7 ", usage.currency] })] }), _jsx(Chip, { tone: cloud ? "accent" : "ok", icon: "activity", children: cloud ? "Cloud" : "Local" })] }), _jsx("div", { className: "mt-3 grid grid-cols-1 gap-3 border-t border-line pt-3 sm:grid-cols-3", children: PERIODS.map(([label, pick]) => {
                    const b = pick(usage);
                    return (_jsxs("div", { className: "min-w-0", children: [_jsx("div", { className: "text-[11.5px] text-muted", children: label }), _jsx("div", { className: "mt-0.5 text-[21px] font-semibold tabular-nums text-ink", children: yuan(b.cost_yuan) }), _jsxs("div", { className: "mt-0.5 text-[11.5px] text-faint tabular-nums", children: [tokenPair(b), " tokens"] })] }, label));
                }) }), usage.by_surface.length ? (_jsxs("table", { className: "mt-3 w-full border-t border-line text-[12px] tabular-nums", children: [_jsx("thead", { children: _jsxs("tr", { className: "text-left text-[11px] tracking-[0.06em] text-muted uppercase", children: [_jsx("th", { scope: "col", className: "pt-2.5 pb-1 font-medium", children: "Surface" }), _jsx("th", { scope: "col", className: "pt-2.5 pb-1 font-medium", children: "Tokens in" }), _jsx("th", { scope: "col", className: "pt-2.5 pb-1 font-medium", children: "Tokens out" }), _jsx("th", { scope: "col", className: "pt-2.5 pb-1 text-right font-medium", children: "Cost" })] }) }), _jsx("tbody", { children: usage.by_surface.map((row) => (_jsxs("tr", { className: "border-t border-line/60 text-ink-2", children: [_jsx("td", { className: "py-1.5 font-medium", children: SURFACE_LABEL[row.surface] ?? row.surface }), _jsx("td", { className: "py-1.5", children: compact(row.prompt_tokens) }), _jsx("td", { className: "py-1.5", children: compact(row.completion_tokens) }), _jsx("td", { className: "py-1.5 text-right", children: yuan(row.cost_yuan) })] }, row.surface))) })] })) : null, _jsxs("div", { className: "mt-3 flex items-center justify-between gap-2 border-t border-line pt-2.5 text-[11.5px] text-muted", children: [_jsxs("span", { children: ["Updated ", relativeTime(usage.updated_at)] }), onRefresh ? _jsx(Button, { size: "sm", variant: "ghost", icon: "refresh", onClick: onRefresh, "aria-label": "Refresh cloud usage" }) : null] })] }));
}
export function CloudUsageCardSkeleton() {
    return _jsx(Skeleton, { className: "h-[220px] rounded-card" });
}
