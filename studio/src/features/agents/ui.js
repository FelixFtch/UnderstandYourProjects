import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
// Small presentational primitives for the Agents feature (ag- prefixed CSS in agents.css).
import { useEffect, useId, useRef } from "react";
import { RINGS, STATUS_HINT, STATUS_LABEL, hueFor, initials } from "./logic";
const PATHS = {
    chat: _jsx("path", { d: "M4 5h16v11H8l-4 4V5z" }),
    plus: _jsx("path", { d: "M12 5v14M5 12h14" }),
    users: _jsxs(_Fragment, { children: [_jsx("circle", { cx: "9", cy: "8", r: "3.2" }), _jsx("path", { d: "M3 19c.6-3.2 3-5 6-5s5.4 1.8 6 5" }), _jsx("path", { d: "M16 5.2a3 3 0 0 1 0 5.6M18 14.4c1.6.7 2.7 2.3 3 4.6" })] }),
    back: _jsx("path", { d: "M15 5l-7 7 7 7" }),
    lock: _jsxs(_Fragment, { children: [_jsx("rect", { x: "5", y: "11", width: "14", height: "9", rx: "2" }), _jsx("path", { d: "M8 11V8a4 4 0 0 1 8 0v3" })] }),
    check: _jsx("path", { d: "M5 12.5l4.5 4.5L19 7.5" }),
    checks: _jsxs(_Fragment, { children: [_jsx("path", { d: "M2.5 12.5l4.5 4.5L16.5 7.5" }), _jsx("path", { d: "M11.5 16.5l.5.5L21.5 7.5" })] }),
    alert: _jsxs(_Fragment, { children: [_jsx("path", { d: "M12 4l9 16H3L12 4z" }), _jsx("path", { d: "M12 10v4M12 17v.5" })] }),
    clock: _jsxs(_Fragment, { children: [_jsx("circle", { cx: "12", cy: "12", r: "8" }), _jsx("path", { d: "M12 8v4l3 2" })] }),
    trash: _jsx("path", { d: "M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12" }),
    send: _jsx("path", { d: "M4 12l16-7-6 16-2.5-6.5L4 12z" }),
    x: _jsx("path", { d: "M6 6l12 12M18 6L6 18" }),
    mail: _jsxs(_Fragment, { children: [_jsx("rect", { x: "3.5", y: "6", width: "17", height: "12", rx: "2" }), _jsx("path", { d: "M4 7l8 6 8-6" })] }),
    ban: _jsxs(_Fragment, { children: [_jsx("circle", { cx: "12", cy: "12", r: "8" }), _jsx("path", { d: "M6.5 6.5l11 11" })] }),
    search: _jsxs(_Fragment, { children: [_jsx("circle", { cx: "11", cy: "11", r: "6" }), _jsx("path", { d: "M16 16l4 4" })] }),
    info: _jsxs(_Fragment, { children: [_jsx("circle", { cx: "12", cy: "12", r: "8.5" }), _jsx("path", { d: "M12 11v5M12 8v.5" })] }),
    card: _jsxs(_Fragment, { children: [_jsx("rect", { x: "3.5", y: "5", width: "17", height: "14", rx: "2" }), _jsx("path", { d: "M7 10h6M7 14h10" })] }),
    spark: _jsx("path", { d: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" }),
    globe: _jsxs(_Fragment, { children: [_jsx("circle", { cx: "12", cy: "12", r: "8.5" }), _jsx("path", { d: "M3.5 12h17M12 3.5c2.5 2.6 2.5 14.4 0 17M12 3.5c-2.5 2.6-2.5 14.4 0 17" })] }),
    more: _jsxs(_Fragment, { children: [_jsx("circle", { cx: "6", cy: "12", r: "1.2" }), _jsx("circle", { cx: "12", cy: "12", r: "1.2" }), _jsx("circle", { cx: "18", cy: "12", r: "1.2" })] }),
    undo: _jsx("path", { d: "M9 7L5 11l4 4M5 11h9a5 5 0 0 1 0 10h-3" }),
};
export function Icon({ name, size = 16, title }) {
    return (_jsxs("svg", { className: "ag-icon", width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": title ? undefined : true, role: title ? "img" : undefined, children: [title ? _jsx("title", { children: title }) : null, PATHS[name] ?? null] }));
}
export function Avatar({ id, name, kind = "agent", size = 32 }) {
    const hue = hueFor(id);
    return (_jsx("span", { className: `ag-avatar ag-avatar-${kind}`, style: { width: size, height: size, ["--ag-hue"]: String(hue) }, "aria-hidden": true, children: kind === "group" ? _jsx(Icon, { name: "users", size: Math.round(size * 0.5) }) : kind === "jarvis" ? _jsx(Icon, { name: "spark", size: Math.round(size * 0.5) }) : initials(name) }));
}
export function StatusBadge({ status }) {
    return _jsx("span", { className: `ag-status ag-status-${status}`, title: STATUS_HINT[status], children: STATUS_LABEL[status] });
}
export function RingBadge({ ring, compact = false }) {
    const info = RINGS.find((r) => r.ring === ring);
    return (_jsxs("span", { className: `ag-ring ag-ring-${ring}`, title: info ? `${ring} ${info.label}: ${info.who}` : ring, children: [_jsx("span", { className: "ag-ring-dot", "aria-hidden": true }), ring, compact || !info ? "" : ` ${info.label}`] }));
}
export function Toggle({ checked, disabled, onChange, label }) {
    return (_jsx("button", { type: "button", role: "switch", "aria-checked": checked, "aria-label": label, disabled: disabled, className: "ag-switch", "data-on": checked ? "true" : "false", onClick: () => onChange(!checked), children: _jsx("span", { className: "ag-switch-knob" }) }));
}
export function Modal({ title, onClose, children, footer, wide = false }) {
    const titleId = useId();
    const ref = useRef(null);
    const closeRef = useRef(onClose);
    closeRef.current = onClose;
    useEffect(() => {
        const prev = document.activeElement;
        const first = ref.current?.querySelector("[data-autofocus]")
            ?? ref.current?.querySelector("input, select, textarea, button:not([data-close])");
        first?.focus();
        const onKey = (e) => { if (e.key === "Escape")
            closeRef.current(); };
        window.addEventListener("keydown", onKey);
        return () => { window.removeEventListener("keydown", onKey); prev?.focus?.(); };
    }, []);
    return (_jsx("div", { className: "ag-modal-backdrop", onMouseDown: (e) => { if (e.target === e.currentTarget)
            onClose(); }, children: _jsxs("div", { ref: ref, className: `ag-modal${wide ? " ag-modal-wide" : ""}`, role: "dialog", "aria-modal": "true", "aria-labelledby": titleId, children: [_jsxs("header", { className: "ag-modal-head", children: [_jsx("h2", { id: titleId, children: title }), _jsx("button", { type: "button", className: "ag-iconbtn", "data-close": true, "aria-label": "Close", onClick: onClose, children: _jsx(Icon, { name: "x" }) })] }), _jsx("div", { className: "ag-modal-body", children: children }), footer ? _jsx("footer", { className: "ag-modal-foot", children: footer }) : null] }) }));
}
export function ConfirmDialog({ title, body, confirmLabel, danger, busy, onConfirm, onCancel }) {
    return (_jsx(Modal, { title: title, onClose: onCancel, footer: _jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "ag-btn", onClick: onCancel, children: "Cancel" }), _jsx("button", { type: "button", className: `ag-btn ${danger ? "ag-btn-danger" : "ag-btn-primary"}`, "data-autofocus": danger ? undefined : true, disabled: busy, onClick: onConfirm, children: busy ? "Working…" : confirmLabel })] }), children: _jsx("div", { className: "ag-confirm-body", children: body }) }));
}
export function Spinner({ label = "Loading" }) {
    return _jsx("span", { className: "ag-spinner", role: "status", "aria-label": label });
}
