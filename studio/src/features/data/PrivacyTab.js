import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// Privacy rings editor: one ring + "share with agents" per category, own vs inherited.
import { useState } from "react";
import { CATEGORY_INFO, RING_INFO, explainPrivacy, privacyRows, setPrivacy, unsetPath, } from "./inherit";
import { FieldShell, Icon, RingControl, RingLegend, Toggle } from "./ui";
export function PrivacyTab({ doc, draft, setDraft, readOnly, parentLabel, isRoot, dirty }) {
    const [focus, setFocus] = useState(undefined);
    const rows = privacyRows(draft, doc.inherited, doc.effective);
    const sharedNow = rows.filter((r) => (dirty ? r.local : r.effective)?.share_with_agents && (dirty ? r.local : r.effective)?.ring === "R4");
    function change(cat, patch) {
        setDraft(setPrivacy(draft, doc.inherited, cat, patch));
    }
    return (_jsxs("div", { className: "dm-privacy", children: [_jsxs("section", { className: "dm-intro", children: [_jsx(RingLegend, { highlight: focus }), _jsxs("div", { className: "dm-intro-text", children: [_jsx("h3", { children: "Who may Jarvis tell?" }), _jsxs("p", { children: ["Each kind of data sits in a ring. Jarvis answers someone only if they are inside that ring: ", _jsx("b", { children: "R1" }), " is just you, ", _jsx("b", { children: "R4" }), " reaches other Jarvis agents outside the house."] }), _jsxs("p", { children: [_jsx("b", { children: "Share with agents" }), " pre-enables a category on every new agent chat's ", _jsx("a", { className: "dm-link", href: "#/agents", children: "share card" }), ". It is only possible at R4."] }), _jsx("p", { className: "dm-muted", children: sharedNow.length
                                    ? _jsxs(_Fragment, { children: ["On share cards by default", dirty ? " (after save)" : "", ": ", sharedNow.map((r) => CATEGORY_INFO[r.category].label).join(", "), "."] })
                                    : _jsxs(_Fragment, { children: ["Nothing is shared with agents by default", dirty ? " (after save)" : "", "."] }) })] })] }), _jsx("div", { className: "dm-fields", children: rows.map((row) => (_jsx(PrivacyField, { row: row, readOnly: readOnly, parentLabel: parentLabel, isRoot: isRoot, dirty: dirty, onFocus: () => setFocus(row.local.ring), onChange: (patch) => change(row.category, patch), onReset: () => setDraft(unsetPath(draft, ["categories", row.category])) }, row.category))) })] }));
}
function PrivacyField({ row, readOnly, parentLabel, isRoot, dirty, onChange, onReset, onFocus }) {
    const info = CATEGORY_INFO[row.category];
    const shown = dirty ? row.local : (row.effective ?? row.local);
    const explain = explainPrivacy(dirty ? row.local : row.effective);
    const canShare = row.local.ring === "R4";
    const inh = row.inherited;
    const clamped = !dirty && row.effective && (row.effective.ring !== row.local.ring || Boolean(row.effective.share_with_agents) !== row.local.share_with_agents);
    return (_jsx("div", { onFocusCapture: onFocus, onMouseEnter: onFocus, children: _jsx(FieldShell, { title: info.label, hint: info.hint, view: row, parentLabel: parentLabel, readOnly: readOnly, canInherit: !isRoot, onReset: onReset, footer: _jsxs("div", { className: `dm-effective dm-ring-${shown.ring ?? "R1"}`, children: [_jsx("span", { className: "dm-effective-k", children: dirty ? "After save" : "Effective" }), _jsx("span", { className: "dm-effective-v", children: explain.headline }), _jsx("span", { className: "dm-effective-d", children: explain.detail }), row.source === "own" && inh?.ring ? (_jsxs("span", { className: "dm-effective-d", children: [row.overrides ? "Overrides" : "Same as", " inherited ", inh.ring, " ", RING_INFO[inh.ring].label.toLowerCase(), inh.ring === "R4" ? (inh.share_with_agents ? ", shared" : ", not shared") : "", ".", row.partial ? " Only part of this setting is set here; the rest is inherited." : ""] })) : null, clamped ? _jsxs("span", { className: "dm-effective-d dm-warn", children: [_jsx(Icon, { name: "alert", size: 12 }), " The hub limits this level (for example guests never exceed the household), so the effective value differs from what is set."] }) : null] }), children: _jsxs("div", { className: "dm-privacy-controls", children: [_jsx(RingControl, { value: row.local.ring, disabled: readOnly, label: `${info.label} ring`, onChange: (ring) => onChange({ ring }) }), _jsxs("label", { className: `dm-share${canShare ? "" : " is-off"}`, title: canShare ? "" : "Only R4 (external) data can be shared with other agents", children: [_jsx(Toggle, { checked: row.local.share_with_agents && canShare, disabled: readOnly || !canShare, label: `Share ${info.label} with agents`, onChange: (v) => onChange({ share_with_agents: v }) }), _jsxs("span", { children: ["Share with agents", !canShare ? _jsx("small", { children: "needs R4" }) : null] })] })] }) }) }));
}
