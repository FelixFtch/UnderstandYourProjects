import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// Right pane: the per-thread share card (§4.3). Edits are local until "Save"; the save is
// optimistic (the card shows the new state immediately) and rolls back if the server rejects it.
import { useEffect, useRef, useState } from "react";
import { agentsApi } from "./adapter";
import { CATEGORY_ORDER, RINGS, categoryLabel, countChanges, diffShareCard, groupByCategory, makeNewItem, meLink, visibleToAgents, } from "./logic";
import { Icon, RingBadge, Spinner, Toggle } from "./ui";
function errText(e) { return e instanceof Error ? e.message : String(e); }
export function useShareCard(threadId) {
    const [card, setCard] = useState(null);
    const [draft, setDraftState] = useState(null);
    const [loadError, setLoadError] = useState(null);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState(null);
    const [nonce, setNonce] = useState(0);
    const current = useRef(threadId);
    current.current = threadId;
    useEffect(() => {
        setCard(null);
        setDraftState(null);
        setLoadError(null);
        setSaveError(null);
        setSaving(false);
        if (!threadId || threadId === "jarvis")
            return;
        let alive = true;
        agentsApi.shareCard(threadId)
            .then((c) => { if (alive) {
            setCard(c);
            setDraftState(c.items);
        } })
            .catch((e) => { if (alive)
            setLoadError(errText(e)); });
        return () => { alive = false; };
    }, [threadId, nonce]);
    async function save() {
        if (!threadId || !card || !draft)
            return;
        const update = diffShareCard(card.items, draft);
        if (!update)
            return;
        const previous = card;
        const attempted = draft;
        setSaving(true);
        setSaveError(null);
        // Optimistic: what you see is what will be shared.
        setCard({ ...card, items: draft.map(({ isNew: _n, value: _v, ...item }) => item) });
        try {
            const next = await agentsApi.updateShareCard(threadId, update);
            if (current.current !== threadId)
                return;
            setCard(next);
            setDraftState(next.items);
        }
        catch (e) {
            if (current.current !== threadId)
                return;
            setCard(previous);
            setDraftState(previous.items);
            setSaveError({ message: errText(e), attempted });
        }
        finally {
            if (current.current === threadId)
                setSaving(false);
        }
    }
    return {
        card, draft, loadError, saving, saveError,
        setDraft: (fn) => setDraftState((d) => (d ? fn(d) : d)),
        save,
        discard: () => { if (card)
            setDraftState(card.items); setSaveError(null); },
        restoreAttempt: () => { if (saveError)
            setDraftState(saveError.attempted); setSaveError(null); },
        reload: () => setNonce((n) => n + 1),
    };
}
export function ShareCardPane({ state, thread, me, onBack }) {
    const { card, draft, loadError, saving, saveError } = state;
    const [adding, setAdding] = useState(false);
    const [cat, setCat] = useState("profile");
    const [label, setLabel] = useState("");
    const [value, setValue] = useState("");
    const update = card && draft ? diffShareCard(card.items, draft) : null;
    const changes = countChanges(update);
    const visible = draft ? groupByCategory(visibleToAgents(draft)).flatMap(([, xs]) => xs) : [];
    const recipients = (thread?.participants ?? []).filter((p) => p.kind === "agent").map((p) => p.display);
    const privacyHref = meLink(me);
    function toggle(id, enabled) {
        state.setDraft((d) => d.map((i) => (i.item_id === id ? { ...i, enabled } : i)));
    }
    function remove(id) {
        state.setDraft((d) => d.filter((i) => i.item_id !== id));
    }
    function addItem() {
        if (!label.trim() || !value.trim())
            return;
        state.setDraft((d) => [...d, makeNewItem(cat, label.trim(), value.trim())]);
        setLabel("");
        setValue("");
        setAdding(false);
    }
    return (_jsxs("div", { className: "ag-card", children: [_jsxs("header", { className: "ag-pane-head", children: [_jsx("button", { type: "button", className: "ag-iconbtn ag-back", "aria-label": "Back to conversation", onClick: onBack, children: _jsx(Icon, { name: "back" }) }), _jsxs("div", { className: "min-w-0 flex-1", children: [_jsx("h2", { className: "ag-head-title", children: "Share card" }), _jsxs("div", { className: "ag-sub ag-truncate", children: ["What Jarvis may tell ", recipients.length ? recipients.join(", ") : "agents", " in this chat"] })] })] }), _jsxs("div", { className: "ag-scroll ag-card-scroll", children: [_jsxs("p", { className: "ag-card-intro", children: [_jsx(Icon, { name: "info", size: 14 }), _jsxs("span", { children: ["Defaults come from your privacy rings in ", _jsx("a", { className: "ag-link", href: privacyHref, children: "Data \u2192 Privacy" }), ". Edits here apply to this chat only."] })] }), _jsx("ul", { className: "ag-ringlegend", "aria-label": "Privacy rings", children: RINGS.map((r) => (_jsxs("li", { children: [_jsx(RingBadge, { ring: r.ring, compact: true }), " ", _jsx("b", { children: r.label }), " ", _jsx("small", { children: r.who })] }, r.ring))) }), loadError ? (_jsxs("div", { className: "ag-alert ag-alert-error", role: "alert", children: [_jsx(Icon, { name: "alert" }), " ", loadError, _jsx("button", { type: "button", className: "ag-btn ag-btn-sm ml-auto", onClick: state.reload, children: "Retry" })] })) : null, !card && !loadError ? _jsxs("div", { className: "ag-center-note", children: [_jsx(Spinner, {}), " Loading share card\u2026"] }) : null, draft ? groupByCategory(draft).map(([category, items]) => (_jsxs("section", { className: "ag-cat", children: [_jsx("h4", { className: "ag-cat-head", children: categoryLabel(category) }), _jsx("ul", { className: "ag-list", children: items.map((it) => {
                                    const ringInfo = RINGS.find((r) => r.ring === it.ring);
                                    return (_jsxs("li", { className: `ag-item${it.enabled && !it.locked ? " is-on" : ""}${it.locked ? " is-locked" : ""}`, children: [_jsx(Toggle, { checked: it.enabled && !it.locked, disabled: it.locked || saving || it.isNew, label: `Share ${it.label}`, onChange: (v) => toggle(it.item_id, v) }), _jsxs("div", { className: "min-w-0 flex-1", children: [_jsxs("div", { className: "ag-item-label", children: [_jsx("span", { className: "ag-break", children: it.label }), it.isNew ? _jsx("span", { className: "ag-tag ag-tag-new", children: "Unsaved" }) : it.source === "added" ? _jsx("span", { className: "ag-tag", children: "Added" }) : null] }), _jsx("div", { className: "ag-item-value ag-mono ag-break", children: it.value_preview || "—" }), it.locked ? (_jsxs("div", { className: "ag-item-note", children: [_jsx(Icon, { name: "lock", size: 12 }), " Locked: your privacy policy never shares ", categoryLabel(it.category).toLowerCase(), " with agents. Change it in ", _jsx("a", { className: "ag-link", href: privacyHref, children: "Data \u2192 Privacy" }), "."] })) : it.enabled && it.ring !== "R4" ? (_jsxs("div", { className: "ag-item-note is-warn", children: [_jsx(Icon, { name: "alert", size: 12 }), " ", it.ring, " ", ringInfo?.label.toLowerCase(), ": normally ", ringInfo?.who, ". Sharing it here is an exception for this chat."] })) : null] }), _jsxs("div", { className: "ag-item-side", children: [_jsx(RingBadge, { ring: it.ring, compact: true }), it.source === "added" ? (_jsx("button", { type: "button", className: "ag-iconbtn ag-iconbtn-sm", "aria-label": `Remove ${it.label}`, title: "Remove", disabled: saving, onClick: () => remove(it.item_id), children: _jsx(Icon, { name: "trash", size: 14 }) })) : null] })] }, it.item_id));
                                }) })] }, category))) : null, draft ? (adding ? (_jsxs("form", { className: "ag-additem", onSubmit: (e) => { e.preventDefault(); addItem(); }, children: [_jsx("h4", { className: "ag-cat-head", children: "Add an item" }), _jsxs("label", { className: "ag-field", children: [_jsx("span", { children: "Category" }), _jsx("select", { className: "ag-input", value: cat, onChange: (e) => setCat(e.target.value), children: CATEGORY_ORDER.map((c) => _jsx("option", { value: c, children: categoryLabel(c) }, c)) })] }), _jsxs("label", { className: "ag-field", children: [_jsx("span", { children: "Label" }), _jsx("input", { className: "ag-input", value: label, onChange: (e) => setLabel(e.target.value), placeholder: "Dietary preferences", autoFocus: true })] }), _jsxs("label", { className: "ag-field", children: [_jsx("span", { children: "Value" }), _jsx("textarea", { className: "ag-input", rows: 2, value: value, onChange: (e) => setValue(e.target.value), placeholder: "Vegetarian, no peanuts" }), _jsx("small", { children: "Stored on your hub; agents receive it only with messages in this chat." })] }), _jsxs("div", { className: "ag-actions", children: [_jsx("button", { type: "submit", className: "ag-btn ag-btn-sm ag-btn-primary", disabled: !label.trim() || !value.trim(), children: "Add to card" }), _jsx("button", { type: "button", className: "ag-btn ag-btn-sm", onClick: () => setAdding(false), children: "Cancel" })] })] })) : (_jsxs("button", { type: "button", className: "ag-btn ag-btn-sm ag-addbtn", disabled: saving, onClick: () => setAdding(true), children: [_jsx(Icon, { name: "plus", size: 14 }), " Add an item"] }))) : null, draft ? (_jsxs("section", { className: "ag-preview", "aria-label": "What the other agents will see", children: [_jsxs("h4", { className: "ag-cat-head", children: ["What the other agents will see", changes ? _jsx("span", { className: "ag-tag ag-tag-new", children: "after you save" }) : null] }), visible.length === 0 ? (_jsx("p", { className: "ag-sub", children: "Nothing beyond the text of your messages." })) : (_jsx("ul", { className: "ag-preview-list", children: visible.map((i) => (_jsxs("li", { children: [_jsxs("span", { className: "ag-preview-k", children: [categoryLabel(i.category), " \u00B7 ", i.label] }), _jsx("span", { className: "ag-preview-v ag-mono ag-break", children: i.value_preview || "—" })] }, i.item_id))) })), _jsx("p", { className: "ag-help", children: "Values are resolved on your hub when a message is sent; previews are redacted." })] })) : null] }), saveError ? (_jsxs("div", { className: "ag-card-foot is-error", role: "alert", children: [_jsx(Icon, { name: "alert" }), _jsxs("span", { className: "min-w-0 flex-1", children: ["Not saved: ", saveError.message, ". The card was rolled back."] }), _jsx("button", { type: "button", className: "ag-btn ag-btn-sm", onClick: state.restoreAttempt, children: "Restore my edits" })] })) : saving ? (_jsxs("div", { className: "ag-card-foot", children: [_jsx(Spinner, { label: "Saving" }), " ", _jsx("span", { className: "flex-1", children: "Saving\u2026" })] })) : changes ? (_jsxs("div", { className: "ag-card-foot is-dirty", children: [_jsxs("span", { className: "flex-1", children: [changes, " unsaved change", changes > 1 ? "s" : ""] }), _jsx("button", { type: "button", className: "ag-btn ag-btn-sm", onClick: state.discard, children: "Discard" }), _jsx("button", { type: "button", className: "ag-btn ag-btn-sm ag-btn-primary", onClick: () => void state.save(), children: "Save" })] })) : card ? (_jsxs("div", { className: "ag-card-foot is-clean", children: [_jsx(Icon, { name: "check", size: 14 }), " ", _jsxs("span", { className: "flex-1 ag-sub", children: ["Saved", card.updated_at ? ` · ${new Date(card.updated_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}` : ""] })] })) : null] }));
}
