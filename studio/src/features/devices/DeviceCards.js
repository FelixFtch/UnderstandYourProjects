import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { plural, relativeTime } from "../../design/format";
import { Icon } from "../../design/icons";
import { cx, Skeleton, StatusDot } from "../../design/primitives";
const KIND_ICON = { computer: "laptop", nas: "server", jetson: "chip", phone: "phone" };
function connectorLine(d) {
    const c = d.connector;
    if (!c)
        return { tone: "neutral", text: d.kind === "phone" ? "Paired app · no folder connector" : "No connector" };
    if (c.state === "online")
        return { tone: "ok", text: `Connector online${c.watcher ? ` · ${c.watcher}` : ""}` };
    if (c.state === "offline")
        return { tone: "err", text: `Connector offline · seen ${relativeTime(c.last_seen)}` };
    return { tone: "warn", text: `Connector state unknown${c.last_seen ? ` · seen ${relativeTime(c.last_seen)}` : ""}` };
}
export function DeviceCards({ devices, selected, onSelect }) {
    return (_jsx("ul", { className: "grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr))]", children: devices.map((d) => {
            const line = connectorLine(d);
            const on = selected === d.device_id;
            return (_jsx("li", { className: "min-w-0", children: _jsxs("button", { type: "button", onClick: () => onSelect(on ? null : d.device_id), "aria-pressed": on, title: on ? "Show folders from every device" : `Show only folders on ${d.label}`, className: cx("flex h-full w-full min-w-0 flex-col gap-3 rounded-card border bg-surface p-4 text-left shadow-card transition-colors", on ? "border-accent ring-2 ring-accent/20" : "border-line hover:border-line-strong"), children: [_jsxs("div", { className: "flex min-w-0 items-start gap-3", children: [_jsx("span", { className: cx("grid size-9 shrink-0 place-items-center rounded-[10px] border", on ? "border-accent/30 bg-accent-soft text-accent-ink" : "border-line bg-sunk text-ink-2"), children: _jsx(Icon, { name: KIND_ICON[d.kind] ?? "devices", size: 18 }) }), _jsxs("span", { className: "min-w-0 flex-1", children: [_jsx("span", { className: "block truncate text-[14px] font-medium text-ink", children: d.label }), _jsx("span", { className: "block truncate text-[12px] text-muted", children: [d.hostname, d.os].filter(Boolean).join(" · ") })] })] }), _jsxs("div", { className: "flex min-w-0 items-center gap-2 text-[12.5px] text-ink-2", children: [_jsx(StatusDot, { tone: line.tone, pulse: d.connector?.state === "online" }), _jsx("span", { className: "truncate", children: line.text })] }), _jsxs("div", { className: "mt-auto flex items-center justify-between gap-2 border-t border-line pt-2.5 text-[12px] text-muted", children: [_jsxs("span", { children: [plural(d.project_count, "folder"), d.connector ? ` · ${plural(d.connector.grants, "grant")}` : ""] }), _jsx("span", { className: "truncate", children: d.paired_at ? `paired ${relativeTime(d.paired_at)}` : "not paired" })] })] }) }, d.device_id));
        }) }));
}
export function DeviceCardsSkeleton() {
    return (_jsx("div", { className: "grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr))]", "aria-busy": "true", children: [0, 1, 2].map((i) => _jsx(Skeleton, { className: "h-[132px] rounded-card" }, i)) }));
}
