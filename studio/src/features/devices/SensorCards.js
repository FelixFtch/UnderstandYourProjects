import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { relativeTime } from "../../design/format";
import { Icon } from "../../design/icons";
import { Chip, cx, Skeleton, StatusDot } from "../../design/primitives";
import { isPositive, lastSeenText, pickPresenceHero, readingStatus, SENSOR_CATEGORY_LABEL } from "./sensors";
const CATEGORY_ICON = {
    air_quality: "activity",
    presence: "agents",
    meeting_audio: "chat",
    checkin: "key",
    lighting: "bulb",
    other: "devices",
};
function presenceLine(dev, states) {
    const hero = pickPresenceHero(dev, states);
    if (!hero)
        return null;
    if (hero.state === "unavailable")
        return { tone: "err", text: "Presence sensor offline" };
    return isPositive(hero.state) ? { tone: "accent", text: "Someone is there now" } : { tone: "neutral", text: "No one detected" };
}
export function SensorCards({ devices, placeholders, states, openId, onOpen }) {
    return (_jsxs("ul", { className: "grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,240px),1fr))]", children: [devices.map((dev) => {
                const on = openId === dev.device_id;
                const presence = dev.category === "presence" ? presenceLine(dev, states) : null;
                return (_jsx("li", { className: "min-w-0", children: _jsxs("button", { type: "button", onClick: () => onOpen(dev.device_id), "aria-pressed": on, title: `Open ${dev.name} readings`, className: cx("flex h-full w-full min-w-0 flex-col gap-3 rounded-card border bg-surface p-4 text-left shadow-card transition-colors", on ? "border-accent ring-2 ring-accent/20" : "border-line hover:border-line-strong", !dev.online && "opacity-75"), children: [_jsxs("div", { className: "flex min-w-0 items-start gap-3", children: [_jsx("span", { className: cx("grid size-9 shrink-0 place-items-center rounded-[10px] border", on ? "border-accent/30 bg-accent-soft text-accent-ink" : "border-line bg-sunk text-ink-2"), children: _jsx(Icon, { name: CATEGORY_ICON[dev.category] ?? "devices", size: 18 }) }), _jsxs("span", { className: "min-w-0 flex-1", children: [_jsx("span", { className: "block truncate text-[14px] font-medium text-ink", children: dev.name }), _jsx("span", { className: "block truncate text-[12px] text-muted", children: [dev.manufacturer, dev.model].filter(Boolean).join(" · ") || `${dev.entity_count} entities` })] })] }), _jsxs("div", { className: "flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5", children: [(dev.readings ?? []).slice(0, 4).map((r, i) => {
                                        const row = r.entity_id ? states.get(r.entity_id) : undefined;
                                        const status = row ? readingStatus(row) : "ok";
                                        return (_jsxs("span", { className: "min-w-0", children: [_jsx("span", { className: "block max-w-[150px] truncate text-[11.5px] text-muted", children: r.label }), _jsxs("span", { className: cx("text-[19px] leading-tight font-semibold tabular-nums", status === "unavailable" ? "text-faint" : status === "stale" ? "text-warn" : "text-ink"), children: [status === "unavailable" ? "—" : r.value, status !== "unavailable" && r.unit ? _jsx("span", { className: "ml-0.5 text-[11.5px] font-normal text-muted", children: r.unit }) : null] })] }, `${r.entity_id ?? r.label}-${i}`));
                                    }), !dev.readings?.length && !presence ? _jsx("span", { className: "text-[13px] text-faint", children: "No key readings" }) : null] }), _jsxs("div", { className: "mt-auto flex min-w-0 flex-wrap items-center gap-2 border-t border-line pt-2.5 text-[12px] text-muted", children: [presence ? (_jsxs("span", { className: cx("flex min-w-0 items-center gap-1.5 font-medium", presence.tone === "accent" ? "text-accent-ink" : presence.tone === "err" ? "text-err" : "text-muted"), children: [_jsx(StatusDot, { tone: presence.tone, pulse: presence.tone === "accent" }), _jsx("span", { className: "truncate", children: presence.text })] })) : (_jsxs("span", { className: "flex items-center gap-1.5", children: [_jsx(StatusDot, { tone: dev.online ? "ok" : "err", pulse: dev.online }), _jsx("span", { children: (() => {
                                                    if (dev.online)
                                                        return "Online";
                                                    const ago = lastSeenText(dev, states);
                                                    return ago ? `Offline · last data ${ago}` : "Offline";
                                                })() })] })), _jsxs("span", { className: "ml-auto flex items-center gap-1.5", children: [!!dev.unavailable && _jsxs(Chip, { tone: "err", className: "px-1.5", children: [dev.unavailable, " off"] }), !!dev.stale && _jsxs(Chip, { tone: "warn", className: "px-1.5", children: [dev.stale, " stale"] }), _jsx("span", { className: "truncate", children: SENSOR_CATEGORY_LABEL[dev.category] }), _jsx("span", { "aria-hidden": "true", children: "\u00B7" }), _jsx("span", { className: "whitespace-nowrap", children: relativeTime(dev.last_changed ?? null) })] })] })] }) }, dev.device_id));
            }), placeholders.map((p) => (_jsx("li", { className: "min-w-0", children: _jsxs("div", { "aria-disabled": "true", title: "Reserved category \u2014 no devices yet", className: "flex h-full w-full min-w-0 flex-col gap-3 rounded-card border border-dashed border-line-strong bg-surface/50 p-4 text-left", children: [_jsxs("div", { className: "flex min-w-0 items-start gap-3 opacity-70", children: [_jsx("span", { className: "grid size-9 shrink-0 place-items-center rounded-[10px] border border-line bg-sunk text-muted", children: _jsx(Icon, { name: CATEGORY_ICON[p.category], size: 18 }) }), _jsxs("span", { className: "min-w-0 flex-1", children: [_jsx("span", { className: "block truncate text-[14px] font-medium text-ink-2", children: SENSOR_CATEGORY_LABEL[p.category] }), _jsx("span", { className: "block text-[12px] text-faint", children: "reserved" })] })] }), _jsx("p", { className: "text-[12.5px] leading-relaxed text-muted", children: p.note })] }) }, `placeholder_${p.category}`)))] }));
}
export function SensorCardsSkeleton() {
    return (_jsx("div", { className: "grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,240px),1fr))]", "aria-busy": "true", children: [0, 1, 2, 3].map((i) => _jsx(Skeleton, { className: "h-[168px] rounded-card" }, i)) }));
}
