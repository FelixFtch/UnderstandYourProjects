import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// Cloud provider card (2026-10-15): the Model tab's second card, below the
// local ↔ cloud mode switch. Picks which of the five vendors serves cloud mode
// (GET/PUT /api/settings/llm-providers), and edits one provider's model + API
// key. Keys are write-only: the server returns has_key + key_hint, never the
// key itself. Owner-only to change; members/guests can inspect but not edit.
// `pushed` feedback mirrors the model-mode switch semantics (ModelModeSwitch.tsx).
import { useEffect, useId, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { dataApi } from "./adapter";
import { Icon, Spinner } from "./ui";
/** Default model hints per vendor for the datalist — suggestions only, the
 * field accepts any model name; the provider's current model is always listed. */
const MODEL_SUGGESTIONS = {
    qwen: ["qwen3.8-flash", "qwen3.8-plus", "qwen3-max"],
    openai: ["gpt-5.2", "gpt-5.2-mini", "gpt-5.2-pro"],
    claude: ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"],
    gemini: ["gemini-3-flash", "gemini-3-pro"],
    deepseek: ["deepseek-v4-flash", "deepseek-v4-pro"],
};
const KEY_PLACEHOLDER = "Paste the key - stored on the Jetson, never shown in full";
function errText(e) {
    if (e instanceof ApiError) {
        if (e.status === 403)
            return "Only the household owner can change cloud provider settings.";
        return e.message;
    }
    return e instanceof Error ? e.message : String(e);
}
function KeyDot({ p }) {
    return (_jsx("span", { className: `dm-prov-dot${p.has_key ? " is-key" : ""}`, title: p.has_key ? `Key stored (${p.key_hint ?? "hint unavailable"})` : "No key stored", "aria-label": p.has_key ? `Key stored ${p.key_hint ?? ""}` : "No key stored" }));
}
export function ProviderCard({ me, readOnly }) {
    const [settings, setSettings] = useState(null);
    const [loadError, setLoadError] = useState(null);
    const [nonce, setNonce] = useState(0);
    const [sel, setSel] = useState(null); // selected provider id (defaults to the active one)
    const [open, setOpen] = useState(false);
    const [model, setModel] = useState("");
    const [key, setKey] = useState("");
    const [keyEditing, setKeyEditing] = useState(false);
    const [busy, setBusy] = useState(null);
    const [feedback, setFeedback] = useState(null);
    const [actionError, setActionError] = useState(null);
    const pickerRef = useRef(null);
    const modelId = useId();
    const keyId = useId();
    const listId = useId();
    useEffect(() => {
        let alive = true;
        setLoadError(null);
        dataApi.llmProviders()
            .then((s) => {
            if (!alive)
                return;
            setSettings(s);
            setSel((cur) => cur ?? s.active); // first load: show the active provider
        })
            .catch((e) => { if (alive)
            setLoadError(errText(e)); });
        return () => { alive = false; };
    }, [nonce]);
    // Close the provider dropdown on outside click / Escape (ProfileMenu pattern).
    useEffect(() => {
        if (!open)
            return;
        const onDown = (e) => { if (!pickerRef.current?.contains(e.target))
            setOpen(false); };
        const onKey = (e) => { if (e.key === "Escape")
            setOpen(false); };
        document.addEventListener("mousedown", onDown);
        document.addEventListener("keydown", onKey);
        return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
    }, [open]);
    const provider = settings?.providers.find((p) => p.id === sel) ?? null;
    const active = settings?.providers.find((p) => p.id === settings.active) ?? null;
    function pick(id) {
        setOpen(false);
        if (id === sel || !settings)
            return;
        const p = settings.providers.find((x) => x.id === id);
        if (!p)
            return;
        setSel(id);
        setModel(p.model);
        setKey("");
        setKeyEditing(false);
        setFeedback(null);
        setActionError(null);
    }
    // Seed the model field when the selection lands (first load → the active
    // provider). pick()/apply() set the form explicitly; this only covers the
    // async first load, and never overwrites mid-edit input (model !== "").
    useEffect(() => {
        if (provider && model === "" && !keyEditing && key === "")
            setModel(provider.model);
    }, [provider?.id, settings]);
    /** Fold a PUT response into local state and reset the form around the (possibly new) provider values. */
    function apply(res) {
        setSettings(res);
        const p = res.providers.find((x) => x.id === sel) ?? null;
        setModel(p?.model ?? "");
        setKey("");
        setKeyEditing(false);
    }
    async function save() {
        if (readOnly || busy || !provider)
            return;
        const m = model.trim();
        if (!m)
            return;
        setBusy("save");
        setActionError(null);
        try {
            const res = await dataApi.putLlmProviders({ provider: provider.id, model: m, ...(key ? { api_key: key } : {}) });
            apply(res);
            setFeedback(res.pushed
                ? `Saved ${provider.label} — pushed to the voice runtime, effective immediately.`
                : `Saved ${provider.label} — the voice runtime picks it up on its next turn.`);
        }
        catch (e) {
            setActionError(errText(e));
        }
        finally {
            setBusy(null);
        }
    }
    async function useThis() {
        if (readOnly || busy || !provider || !settings || provider.id === settings.active)
            return;
        setBusy("use");
        setActionError(null);
        try {
            const res = await dataApi.putLlmProviders({ active: provider.id });
            apply(res);
            setFeedback(res.pushed
                ? `Now using ${provider.label} — pushed to the voice runtime, effective immediately.`
                : `Now using ${provider.label} — saved; the voice runtime picks it up on its next turn.`);
        }
        catch (e) {
            setActionError(errText(e));
        }
        finally {
            setBusy(null);
        }
    }
    if (loadError) {
        return (_jsx("section", { className: "dm-model-card dm-prov", "aria-label": "Cloud provider", children: _jsxs("div", { className: "dm-alert dm-alert-error", style: { margin: 0 }, children: [_jsx(Icon, { name: "alert" }), _jsx("span", { className: "flex-1", children: loadError }), _jsx("button", { type: "button", className: "dm-btn dm-btn-xs", onClick: () => setNonce((n) => n + 1), children: "Retry" })] }) }));
    }
    if (!settings) {
        return (_jsx("section", { className: "dm-model-card dm-prov", "aria-label": "Cloud provider", children: _jsxs("div", { className: "dm-center", children: [_jsx(Spinner, {}), " Loading cloud providers\u2026"] }) }));
    }
    if (!provider || !active) {
        return (_jsx("section", { className: "dm-model-card dm-prov", "aria-label": "Cloud provider", children: _jsxs("p", { className: "dm-note dm-note-sm", style: { margin: 0 }, children: [_jsx(Icon, { name: "info" }), " ", _jsx("span", { children: "No cloud providers are configured on the hub yet." })] }) }));
    }
    const dirty = model.trim() !== provider.model || key.length > 0;
    const canSave = dirty && model.trim().length > 0 && !readOnly && busy === null;
    const suggestions = [...new Set([provider.model, ...(MODEL_SUGGESTIONS[provider.id] ?? [])])];
    return (_jsxs("section", { className: "dm-model-card dm-prov", "aria-label": "Cloud provider", children: [_jsxs("div", { className: "dm-model-head", children: [_jsx("span", { className: "dm-model-glyph is-cloud", "aria-hidden": true, children: _jsx(Icon, { name: "server", size: 22 }) }), _jsxs("div", { className: "dm-model-title", children: [_jsxs("h3", { children: ["Cloud provider", _jsxs("span", { className: "dm-mode-badge is-cloud", children: [_jsx(Icon, { name: "check", size: 12 }), " ", active.label] })] }), _jsx("p", { className: "dm-muted", children: "Which vendor serves cloud mode, with what model and key. Used when the mode above is Cloud." })] })] }), _jsxs("div", { className: "dm-prov-picker", ref: pickerRef, children: [_jsxs("button", { type: "button", className: "dm-prov-current", "aria-haspopup": "listbox", "aria-expanded": open, "aria-label": "Provider", onClick: () => setOpen((v) => !v), children: [_jsx(KeyDot, { p: provider }), _jsxs("span", { className: "dm-prov-row-text", children: [_jsx("span", { className: "dm-prov-label", children: provider.label }), _jsx("span", { className: "dm-mono dm-prov-model", children: provider.model })] }), provider.id === settings.active ? _jsx("span", { className: "dm-prov-active", children: "Active" }) : null, _jsx(Icon, { name: "chevronDown", size: 14 })] }), open ? (_jsx("div", { className: "dm-prov-list", role: "listbox", "aria-label": "Cloud providers", children: settings.providers.map((p) => (_jsxs("button", { type: "button", role: "option", "aria-selected": p.id === provider.id, className: "dm-prov-row", onClick: () => pick(p.id), children: [_jsx(KeyDot, { p: p }), _jsxs("span", { className: "dm-prov-row-text", children: [_jsx("span", { className: "dm-prov-label", children: p.label }), _jsx("span", { className: "dm-mono dm-prov-model", children: p.model })] }), p.id === settings.active ? _jsx("span", { className: "dm-prov-active", children: "Active" }) : null] }, p.id))) })) : null] }), _jsxs("div", { className: "dm-prov-form", children: [_jsxs("div", { className: "dm-prov-field", children: [_jsx("label", { className: "dm-prov-field-label", htmlFor: modelId, children: "Model" }), _jsx("input", { id: modelId, className: "dm-input dm-mono", value: model, onChange: (e) => { setModel(e.target.value); setFeedback(null); }, disabled: readOnly || busy !== null, list: listId, spellCheck: false, autoComplete: "off" }), _jsx("datalist", { id: listId, children: suggestions.map((m) => _jsx("option", { value: m }, m)) })] }), _jsxs("div", { className: "dm-prov-field", children: [_jsx("label", { className: "dm-prov-field-label", htmlFor: keyId, children: "API key" }), provider.has_key && !keyEditing ? (_jsxs("div", { className: "dm-prov-keyrow", children: [_jsx("input", { id: keyId, className: "dm-input dm-mono", disabled: true, readOnly: true, value: "", placeholder: `Stored key ${provider.key_hint ?? ""}` }), !readOnly ? (_jsx("button", { type: "button", className: "dm-btn dm-btn-sm", disabled: busy !== null, onClick: () => { setKeyEditing(true); setFeedback(null); }, children: "Replace key" })) : null] })) : (_jsxs("div", { className: "dm-prov-keyrow", children: [_jsx("input", { id: keyId, type: "password", className: "dm-input dm-mono", placeholder: KEY_PLACEHOLDER, value: key, onChange: (e) => { setKey(e.target.value); setFeedback(null); }, disabled: readOnly || busy !== null, autoComplete: "new-password" }), provider.has_key && keyEditing ? (_jsx("button", { type: "button", className: "dm-btn dm-btn-sm", disabled: busy !== null, onClick: () => { setKeyEditing(false); setKey(""); }, children: "Cancel" })) : null] })), _jsxs("p", { className: "dm-note dm-note-sm", children: [_jsx(Icon, { name: "lock", size: 13 }), " ", _jsx("span", { children: "Keys are stored server-side and never returned in full." })] })] })] }), _jsxs("div", { className: "dm-prov-actions", children: [_jsx("button", { type: "button", className: "dm-btn dm-btn-sm dm-btn-primary", disabled: !canSave, onClick: () => void save(), children: busy === "save" ? "Saving…" : "Save" }), _jsx("button", { type: "button", className: "dm-btn dm-btn-sm", disabled: readOnly || busy !== null || provider.id === settings.active, onClick: () => void useThis(), title: provider.id === settings.active ? `${provider.label} is already the active provider` : `Make ${provider.label} the active provider for cloud mode`, children: busy === "use" ? "Switching…" : "Use this provider" })] }), feedback && !actionError ? (_jsxs("p", { className: "dm-alert dm-alert-ok", role: "status", children: [_jsx(Icon, { name: "check" }), " ", feedback] })) : null, actionError ? (_jsxs("p", { className: "dm-alert dm-alert-error", role: "alert", children: [_jsx(Icon, { name: "alert" }), " ", actionError] })) : null, readOnly ? (_jsxs("p", { className: "dm-note dm-note-sm", children: [_jsx(Icon, { name: "lock", size: 13 }), _jsxs("span", { children: ["Only the household owner can change cloud provider settings.", me ? _jsxs(_Fragment, { children: [" You're signed in as ", _jsx("b", { children: me.role }), "."] }) : null] })] })) : null] }));
}
