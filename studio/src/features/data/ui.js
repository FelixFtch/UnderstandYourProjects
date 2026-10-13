import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
// Presentational primitives for the Data feature (dm- prefixed CSS in data.css).
import { useEffect, useId, useRef } from "react";
import { RING_INFO, RING_ORDER } from "./inherit";
const PATHS = {
    globe: _jsxs(_Fragment, { children: [_jsx("circle", { cx: "12", cy: "12", r: "8.5" }), _jsx("path", { d: "M3.5 12h17M12 3.5c2.5 2.6 2.5 14.4 0 17M12 3.5c-2.5 2.6-2.5 14.4 0 17" })] }),
    home: _jsxs(_Fragment, { children: [_jsx("path", { d: "M4 11l8-6.5 8 6.5" }), _jsx("path", { d: "M6 10v9.5h12V10" }), _jsx("path", { d: "M10 19.5v-5h4v5" })] }),
    person: _jsxs(_Fragment, { children: [_jsx("circle", { cx: "12", cy: "8.5", r: "3.5" }), _jsx("path", { d: "M5 20c.8-3.8 3.6-6 7-6s6.2 2.2 7 6" })] }),
    guest: _jsxs(_Fragment, { children: [_jsx("circle", { cx: "12", cy: "8.5", r: "3.5", strokeDasharray: "2.4 2" }), _jsx("path", { d: "M5 20c.8-3.8 3.6-6 7-6s6.2 2.2 7 6", strokeDasharray: "2.4 2" })] }),
    lock: _jsxs(_Fragment, { children: [_jsx("rect", { x: "5", y: "11", width: "14", height: "9", rx: "2" }), _jsx("path", { d: "M8 11V8a4 4 0 0 1 8 0v3" })] }),
    undo: _jsx("path", { d: "M9 7L5 11l4 4M5 11h9a5 5 0 0 1 0 10h-3" }),
    alert: _jsxs(_Fragment, { children: [_jsx("path", { d: "M12 4l9 16H3L12 4z" }), _jsx("path", { d: "M12 10v4M12 17v.5" })] }),
    info: _jsxs(_Fragment, { children: [_jsx("circle", { cx: "12", cy: "12", r: "8.5" }), _jsx("path", { d: "M12 11v5M12 8v.5" })] }),
    check: _jsx("path", { d: "M5 12.5l4.5 4.5L19 7.5" }),
    x: _jsx("path", { d: "M6 6l12 12M18 6L6 18" }),
    plus: _jsx("path", { d: "M12 5v14M5 12h14" }),
    key: _jsxs(_Fragment, { children: [_jsx("circle", { cx: "8", cy: "15", r: "3.5" }), _jsx("path", { d: "M10.5 12.5L19 4M16 7l2.5 2.5M14 9l2 2" })] }),
    arrow: _jsx("path", { d: "M5 12h14M13 6l6 6-6 6" }),
    trash: _jsx("path", { d: "M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12" }),
    chevron: _jsx("path", { d: "M9 6l6 6-6 6" }),
};
export function Icon({ name, size = 16 }) {
    return (_jsx("svg", { className: "dm-icon", width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true, children: PATHS[name] ?? null }));
}
export const KIND_ICON = { town: "globe", household: "home", member: "person", guest: "guest" };
export function Toggle({ checked, disabled, onChange, label }) {
    return (_jsx("button", { type: "button", role: "switch", "aria-checked": checked, "aria-label": label, disabled: disabled, className: "dm-switch", "data-on": checked ? "true" : "false", onClick: () => onChange(!checked), children: _jsx("span", { className: "dm-switch-knob" }) }));
}
export function Segmented({ value, options, onChange, disabled, label }) {
    return (_jsx("div", { className: "dm-seg", role: "radiogroup", "aria-label": label, children: options.map((o) => (_jsx("button", { type: "button", role: "radio", "aria-checked": value === o.value, disabled: disabled, className: "dm-seg-btn", title: o.hint, onClick: () => onChange(o.value), children: o.label }, o.value))) }));
}
/** Concentric ring mini-glyph: R1 is the centre dot, R4 the outer ring. */
export function RingGlyph({ ring, size = 16 }) {
    const idx = RING_ORDER.indexOf(ring);
    return (_jsx("svg", { width: size, height: size, viewBox: "0 0 20 20", "aria-hidden": true, className: "dm-ringglyph", children: [9, 6.6, 4.2, 2].map((r, i) => {
            const level = 3 - i; // 3 = R4 … 0 = R1
            const active = level <= idx;
            return _jsx("circle", { cx: "10", cy: "10", r: r, fill: level === 0 ? (active ? "currentColor" : "none") : "none", stroke: "currentColor", strokeWidth: level === idx ? 1.8 : 1, opacity: active ? (level === idx ? 1 : 0.45) : 0.18 }, r);
        }) }));
}
export function RingControl({ value, onChange, disabled, label }) {
    return (_jsx("div", { className: "dm-rings", role: "radiogroup", "aria-label": label, children: RING_ORDER.map((r) => (_jsxs("button", { type: "button", role: "radio", "aria-checked": value === r, disabled: disabled, className: `dm-ringbtn dm-ring-${r}`, title: `${r} ${RING_INFO[r].label}: ${RING_INFO[r].who}`, onClick: () => onChange(r), children: [_jsx(RingGlyph, { ring: r, size: 14 }), _jsx("span", { className: "dm-ringbtn-code", children: r }), _jsx("span", { className: "dm-ringbtn-label", children: RING_INFO[r].label })] }, r))) }));
}
/** Concentric legend: R1 personal at the centre → R4 external at the edge. */
export function RingLegend({ highlight }) {
    const radii = [26, 46, 66, 86];
    return (_jsxs("div", { className: "dm-legend", children: [_jsxs("svg", { viewBox: "0 0 180 180", className: "dm-legend-svg", role: "img", "aria-label": "Privacy rings from R1 personal at the centre to R4 external at the edge", children: [[...RING_ORDER].reverse().map((r) => {
                        const i = RING_ORDER.indexOf(r);
                        return _jsx("circle", { cx: "90", cy: "90", r: radii[i], className: `dm-legend-ring dm-ring-${r}${highlight === r ? " is-hl" : ""}` }, r);
                    }), RING_ORDER.map((r, i) => (_jsx("text", { x: "90", y: i === 0 ? 94 : 90 - radii[i] + 14, textAnchor: "middle", className: "dm-legend-text", children: r }, r)))] }), _jsx("ul", { className: "dm-legend-list", children: RING_ORDER.map((r) => (_jsxs("li", { className: `dm-ring-${r}${highlight === r ? " is-hl" : ""}`, children: [_jsx("span", { className: "dm-legend-dot", "aria-hidden": true }), _jsxs("b", { children: [r, " ", RING_INFO[r].label] }), _jsx("span", { children: RING_INFO[r].who })] }, r))) })] }));
}
export function SourceBadge({ view, parentLabel }) {
    if (view.source === "own") {
        return _jsxs("span", { className: "dm-src dm-src-own", title: view.redundant ? "Set here, but identical to the inherited value" : "Set at this level", children: ["Own setting", view.redundant ? " (same as inherited)" : ""] });
    }
    if (view.source === "inherited") {
        return _jsxs("span", { className: "dm-src dm-src-inh", title: "Merged from the levels above this one", children: ["Inherited", parentLabel ? ` via ${parentLabel}` : ""] });
    }
    return _jsx("span", { className: "dm-src dm-src-unset", children: "Not set" });
}
export function FieldShell({ title, hint, view, parentLabel, readOnly, canInherit, onReset, children, footer }) {
    return (_jsxs("div", { className: `dm-field is-${view.source}`, children: [_jsxs("div", { className: "dm-field-head", children: [_jsxs("div", { className: "min-w-0 flex-1", children: [_jsx("div", { className: "dm-field-title", children: title }), hint ? _jsx("div", { className: "dm-field-hint", children: hint }) : null] }), _jsxs("div", { className: "dm-field-meta", children: [_jsx(SourceBadge, { view: view, parentLabel: parentLabel }), view.source === "own" && canInherit && !readOnly ? (_jsxs("button", { type: "button", className: "dm-btn dm-btn-xs", onClick: onReset, title: "Remove the own value and use the inherited one", children: [_jsx(Icon, { name: "undo", size: 13 }), " Reset to inherited"] })) : null] })] }), _jsx("div", { className: "dm-field-body", children: children }), footer ? _jsx("div", { className: "dm-field-foot", children: footer }) : null] }));
}
export function ChipsEditor({ values, onChange, disabled, placeholder, suggestions, validate, label }) {
    const listId = useId();
    const inputRef = useRef(null);
    function commit(fromBlur = false) {
        const el = inputRef.current;
        if (!el)
            return;
        const v = el.value.trim();
        if (!v)
            return;
        const err = validate?.(v) ?? null;
        if (err) {
            el.setCustomValidity(err);
            if (!fromBlur)
                el.reportValidity();
            return;
        }
        el.setCustomValidity("");
        if (!values.includes(v))
            onChange([...values, v]);
        el.value = "";
    }
    return (_jsxs("div", { className: "dm-chips", "aria-label": label, children: [values.map((v) => (_jsxs("span", { className: "dm-chip", children: [_jsx("span", { className: "dm-mono", children: v }), !disabled ? (_jsx("button", { type: "button", className: "dm-chip-x", "aria-label": `Remove ${v}`, onClick: () => onChange(values.filter((x) => x !== v)), children: _jsx(Icon, { name: "x", size: 11 }) })) : null] }, v))), values.length === 0 && disabled ? _jsx("span", { className: "dm-muted", children: "none" }) : null, !disabled ? (_jsxs("span", { className: "dm-chip-add", children: [_jsx("input", { ref: inputRef, className: "dm-chip-input dm-mono", placeholder: placeholder, list: suggestions ? listId : undefined, "aria-label": `Add to ${label}`, onInput: (e) => e.target.setCustomValidity(""), onKeyDown: (e) => { if (e.key === "Enter" || e.key === ",") {
                            e.preventDefault();
                            commit();
                        } }, onBlur: () => commit(true) }), suggestions ? _jsx("datalist", { id: listId, children: suggestions.filter((s) => !values.includes(s)).map((s) => _jsx("option", { value: s }, s)) }) : null] })) : null] }));
}
export function Modal({ title, onClose, children, footer }) {
    const titleId = useId();
    const ref = useRef(null);
    const closeRef = useRef(onClose);
    closeRef.current = onClose;
    useEffect(() => {
        const prev = document.activeElement;
        (ref.current?.querySelector("[data-autofocus]") ?? ref.current?.querySelector("button"))?.focus();
        const onKey = (e) => { if (e.key === "Escape")
            closeRef.current(); };
        window.addEventListener("keydown", onKey);
        return () => { window.removeEventListener("keydown", onKey); prev?.focus?.(); };
    }, []);
    return (_jsx("div", { className: "dm-modal-backdrop", onMouseDown: (e) => { if (e.target === e.currentTarget)
            onClose(); }, children: _jsxs("div", { ref: ref, className: "dm-modal", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId, children: [_jsx("h2", { id: titleId, className: "dm-modal-title", children: title }), _jsx("div", { className: "dm-modal-body", children: children }), footer ? _jsx("div", { className: "dm-modal-foot", children: footer }) : null] }) }));
}
export function Spinner({ label = "Loading" }) {
    return _jsx("span", { className: "dm-spinner", role: "status", "aria-label": label });
}
