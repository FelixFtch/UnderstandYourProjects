import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// Design primitives for Jarvis Studio. Token-driven (see tokens.css); no third-party UI kit.
// Shared by every feature (FRONTEND-A and FRONTEND-B). Keep them small and boring.
import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./icons";
import { describeError } from "./format";
export function cx(...parts) {
    return parts.filter(Boolean).join(" ");
}
const CHIP_TONE = {
    neutral: "bg-sunk text-ink-2 border-line",
    accent: "bg-accent-soft text-accent-ink border-accent/25",
    ok: "bg-ok-soft text-ok border-ok/25",
    warn: "bg-warn-soft text-warn border-warn/25",
    err: "bg-err-soft text-err border-err/25",
    info: "bg-info-soft text-info border-info/25",
    understand: "bg-g-understand/12 text-g-understand border-g-understand/30",
    retrieve: "bg-g-retrieve/12 text-g-retrieve border-g-retrieve/30",
    act: "bg-g-act/12 text-g-act border-g-act/30",
    respond: "bg-g-respond/12 text-g-respond border-g-respond/30",
};
const DOT_TONE = {
    neutral: "bg-faint text-faint",
    accent: "bg-accent text-accent",
    ok: "bg-ok text-ok",
    warn: "bg-warn text-warn",
    err: "bg-err text-err",
    info: "bg-info text-info",
    understand: "bg-g-understand text-g-understand",
    retrieve: "bg-g-retrieve text-g-retrieve",
    act: "bg-g-act text-g-act",
    respond: "bg-g-respond text-g-respond",
};
const BTN_VARIANT = {
    primary: "bg-accent text-on-accent hover:bg-accent-ink border border-transparent",
    secondary: "bg-surface text-ink border border-line-strong hover:bg-sunk",
    ghost: "text-ink-2 border border-transparent hover:bg-sunk hover:text-ink",
    danger: "bg-surface text-err border border-err/35 hover:bg-err-soft",
};
const BTN_SIZE = {
    sm: "h-8 px-2.5 text-[13px] gap-1.5",
    md: "h-9 px-3.5 text-sm gap-2",
};
export function Button({ variant = "secondary", size = "md", icon, iconRight, loading, className, children, disabled, type = "button", ...rest }) {
    return (_jsxs("button", { type: type, disabled: disabled || loading, className: cx("inline-flex shrink-0 items-center justify-center rounded-control font-medium whitespace-nowrap transition-colors", "disabled:cursor-not-allowed disabled:opacity-55", BTN_VARIANT[variant], BTN_SIZE[size], className), ...rest, children: [loading ? _jsx(Spinner, { size: size === "sm" ? 13 : 15 }) : icon ? _jsx(Icon, { name: icon, size: size === "sm" ? 15 : 16 }) : null, children, iconRight && !loading ? _jsx(Icon, { name: iconRight, size: size === "sm" ? 15 : 16 }) : null] }));
}
export function IconButton({ icon, label, className, size = 34, ...rest }) {
    return (_jsx("button", { type: "button", "aria-label": label, title: label, className: cx("inline-flex shrink-0 items-center justify-center rounded-control text-muted transition-colors hover:bg-sunk hover:text-ink disabled:opacity-50", className), style: { width: size, height: size }, ...rest, children: _jsx(Icon, { name: icon, size: Math.round(size * 0.5) }) }));
}
export function Chip({ tone = "neutral", icon, children, title, href, onClick, className, mono }) {
    const cls = cx("inline-flex max-w-full min-w-0 items-center gap-1 rounded-full border px-2 py-[1px] text-[12px] leading-[18px] font-medium", mono && "font-mono text-[11.5px]", CHIP_TONE[tone], (href || onClick) && "cursor-pointer transition-[filter] hover:brightness-95 dark:hover:brightness-125", className);
    const inner = (_jsxs(_Fragment, { children: [icon ? _jsx(Icon, { name: icon, size: 12, strokeWidth: 1.8 }) : null, _jsx("span", { className: "truncate", children: children })] }));
    if (href)
        return _jsx("a", { href: href, className: cls, title: title, children: inner });
    if (onClick)
        return _jsx("button", { type: "button", onClick: onClick, className: cls, title: title, children: inner });
    return _jsx("span", { className: cls, title: title, children: inner });
}
export function StatusDot({ tone = "neutral", pulse, className, label }) {
    return (_jsx("span", { role: label ? "img" : undefined, "aria-label": label, title: label, className: cx("inline-block size-2 shrink-0 rounded-full", DOT_TONE[tone], pulse && "j-pulse", className) }));
}
// ── Surfaces ────────────────────────────────────────────────────────────────
export function Card({ children, className, ...rest }) {
    return (_jsx("div", { className: cx("rounded-card border border-line bg-surface shadow-card", className), ...rest, children: children }));
}
export function SectionHeader({ eyebrow, title, description, actions, className, level = 2 }) {
    const H = (`h${level}`);
    return (_jsxs("div", { className: cx("flex flex-wrap items-end justify-between gap-x-4 gap-y-3", className), children: [_jsxs("div", { className: "min-w-0 max-w-[68ch]", children: [eyebrow ? _jsx("div", { className: "mb-1 text-[11px] font-semibold tracking-[0.08em] text-muted uppercase", children: eyebrow }) : null, _jsx(H, { className: cx("font-serif text-ink", level === 1 ? "text-[26px] leading-tight" : level === 2 ? "text-[19px] leading-snug" : "text-base"), children: title }), description ? _jsx("p", { className: "mt-1 text-[13.5px] text-muted", children: description }) : null] }), actions ? _jsx("div", { className: "flex flex-wrap items-center gap-2", children: actions }) : null] }));
}
// ── Loading / empty / error ─────────────────────────────────────────────────
export function Skeleton({ className, style }) {
    return _jsx("div", { "aria-hidden": "true", className: cx("j-skeleton rounded-md", className ?? "h-4 w-full"), style: style });
}
export function SkeletonText({ lines = 3, className }) {
    return (_jsx("div", { className: cx("space-y-2", className), "aria-hidden": "true", children: Array.from({ length: lines }, (_, i) => (_jsx(Skeleton, { className: "h-3.5", style: { width: `${i === lines - 1 ? 58 : 100 - (i % 3) * 9}%` } }, i))) }));
}
export function Spinner({ size = 16, className }) {
    return (_jsxs("svg", { width: size, height: size, viewBox: "0 0 24 24", className: cx("animate-spin", className), "aria-hidden": "true", children: [_jsx("circle", { cx: "12", cy: "12", r: "9", fill: "none", stroke: "currentColor", strokeOpacity: "0.2", strokeWidth: "2.5" }), _jsx("path", { d: "M21 12a9 9 0 0 0-9-9", fill: "none", stroke: "currentColor", strokeWidth: "2.5", strokeLinecap: "round" })] }));
}
export function EmptyState({ icon = "sparkle", title, body, action, className }) {
    return (_jsxs("div", { className: cx("flex flex-col items-center justify-center px-6 py-10 text-center", className), children: [_jsx("div", { className: "mb-3 grid size-10 place-items-center rounded-full border border-line bg-sunk text-muted", children: _jsx(Icon, { name: icon, size: 18 }) }), _jsx("div", { className: "font-serif text-[17px] text-ink", children: title }), body ? _jsx("div", { className: "mt-1 max-w-[46ch] text-[13.5px] text-muted", children: body }) : null, action ? _jsx("div", { className: "mt-4", children: action }) : null] }));
}
export function ErrorState({ error, service, onRetry, title, compact, className }) {
    const d = describeError(error, service);
    // a network-level diagnosis ("Agent runtime unreachable") is more useful than a caller's generic title
    const unreachable = d.status === 0 || d.status === 502 || d.status === 503 || d.status === 504 || d.title.startsWith("Can't reach");
    const heading = unreachable ? d.title : title ?? d.title;
    if (compact) {
        return (_jsxs("div", { role: "alert", className: cx("flex items-start gap-2 rounded-control border border-err/25 bg-err-soft px-3 py-2 text-[13px] text-err", className), children: [_jsx(Icon, { name: "alert", size: 15, className: "mt-0.5 shrink-0" }), _jsxs("div", { className: "min-w-0 flex-1", children: [_jsx("span", { className: "font-medium", children: heading }), d.detail ? _jsxs("span", { className: "text-err/80", children: [" \u2014 ", d.detail] }) : null] }), onRetry ? _jsx("button", { type: "button", onClick: onRetry, className: "shrink-0 font-medium underline underline-offset-2", children: "Retry" }) : null] }));
    }
    return (_jsxs("div", { role: "alert", className: cx("flex flex-col items-center justify-center px-6 py-10 text-center", className), children: [_jsx("div", { className: "mb-3 grid size-10 place-items-center rounded-full border border-err/25 bg-err-soft text-err", children: _jsx(Icon, { name: "alert", size: 18 }) }), _jsx("div", { className: "font-serif text-[17px] text-ink", children: heading }), d.detail ? _jsxs("div", { className: "mt-1 max-w-[52ch] text-[13px] break-words text-muted", children: [d.detail, d.status ? ` (HTTP ${d.status})` : ""] }) : null, onRetry ? _jsx(Button, { className: "mt-4", size: "sm", icon: "refresh", onClick: onRetry, children: "Try again" }) : null] }));
}
export function Kbd({ children, className }) {
    return (_jsx("kbd", { className: cx("inline-flex h-5 min-w-5 items-center justify-center rounded border border-line-strong bg-surface px-1 font-sans text-[11px] font-medium text-muted", className), children: children }));
}
export function ProgressBar({ value, max = 1, tone = "accent", className, label }) {
    const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
    return (_jsx("div", { role: "progressbar", "aria-label": label, "aria-valuemin": 0, "aria-valuemax": max, "aria-valuenow": value, className: cx("h-1.5 w-full overflow-hidden rounded-full bg-sunk", className), children: _jsx("div", { className: cx("h-full rounded-full transition-[width] duration-500", DOT_TONE[tone]), style: { width: `${pct}%` } }) }));
}
// ── Segmented control ───────────────────────────────────────────────────────
export function Segmented({ value, options, onChange, label, className }) {
    return (_jsx("div", { role: "tablist", "aria-label": label, className: cx("inline-flex rounded-control border border-line bg-sunk p-0.5", className), children: options.map((o) => (_jsx("button", { type: "button", role: "tab", "aria-selected": o.value === value, onClick: () => onChange(o.value), className: cx("h-7 rounded-[7px] px-3 text-[13px] font-medium transition-colors", o.value === value ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink"), children: o.label }, o.value))) }));
}
// ── Modal ───────────────────────────────────────────────────────────────────
export function Modal({ open, onClose, title, description, children, footer, width = 520 }) {
    const titleId = useId();
    const panel = useRef(null);
    const restore = useRef(null);
    useEffect(() => {
        if (!open)
            return;
        restore.current = document.activeElement;
        const t = window.setTimeout(() => {
            const p = panel.current;
            const first = p?.querySelector("[data-autofocus]") ?? p?.querySelector("input, select, textarea") ?? p?.querySelector("button");
            first?.focus();
        }, 20);
        const onKey = (e) => {
            if (e.key === "Escape") {
                e.stopPropagation();
                onClose();
            }
            if (e.key === "Tab" && panel.current) {
                const nodes = Array.from(panel.current.querySelectorAll("a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex='-1'])"));
                if (!nodes.length)
                    return;
                const first = nodes[0], last = nodes[nodes.length - 1];
                if (e.shiftKey && document.activeElement === first) {
                    e.preventDefault();
                    last.focus();
                }
                else if (!e.shiftKey && document.activeElement === last) {
                    e.preventDefault();
                    first.focus();
                }
            }
        };
        window.addEventListener("keydown", onKey, true);
        return () => {
            window.clearTimeout(t);
            window.removeEventListener("keydown", onKey, true);
            restore.current?.focus?.();
        };
    }, [open, onClose]);
    if (!open)
        return null;
    return createPortal(_jsxs("div", { className: "fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-6", children: [_jsx("div", { className: "absolute inset-0 bg-[rgb(20_16_8/0.38)] backdrop-blur-[2px]", onClick: onClose, "aria-hidden": "true" }), _jsxs("div", { ref: panel, role: "dialog", "aria-modal": "true", "aria-labelledby": titleId, className: "j-rise relative flex max-h-[min(88dvh,760px)] w-full flex-col overflow-hidden rounded-t-card border border-line bg-surface shadow-pop sm:rounded-card", style: { maxWidth: width }, children: [_jsxs("div", { className: "flex items-start gap-3 border-b border-line px-5 pt-4 pb-3", children: [_jsxs("div", { className: "min-w-0 flex-1", children: [_jsx("h2", { id: titleId, className: "font-serif text-[19px] text-ink", children: title }), description ? _jsx("p", { className: "mt-0.5 text-[13px] text-muted", children: description }) : null] }), _jsx(IconButton, { icon: "x", label: "Close", onClick: onClose, size: 30 })] }), _jsx("div", { className: "min-h-0 flex-1 overflow-y-auto px-5 py-4", children: children }), footer ? _jsx("div", { className: "flex flex-wrap items-center justify-end gap-2 border-t border-line bg-canvas/50 px-5 py-3", children: footer }) : null] })] }), document.body);
}
// ── Form field ──────────────────────────────────────────────────────────────
export const inputClass = "h-9 w-full min-w-0 rounded-control border border-line-strong bg-raised px-3 text-sm text-ink placeholder:text-faint " +
    "transition-colors focus:border-accent focus:outline-none focus-visible:outline-none focus:ring-2 focus:ring-accent/25";
export function Field({ label, hint, children, htmlFor }) {
    return (_jsxs("div", { className: "space-y-1.5", children: [_jsx("label", { htmlFor: htmlFor, className: "block text-[13px] font-medium text-ink-2", children: label }), children, hint ? _jsx("div", { className: "text-[12px] text-muted", children: hint }) : null] }));
}
