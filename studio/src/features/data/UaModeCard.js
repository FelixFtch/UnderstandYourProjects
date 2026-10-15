import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// UA analysis mode card (2026-10-15): the bottom card of the Model tab — which
// engine runs Understand Anything's deep analysis (GET/PUT /api/settings/ua-mode).
// Local is the default; cloud targets one of the seven vendors. The response's
// `written` flag tells whether the indexer config file was actually updated.
// Owner-only to change; members/guests read-only.
import { useEffect, useId, useState } from "react";
import { ApiError } from "../../api/client";
import { dataApi } from "./adapter";
import { MODEL_SUGGESTIONS, UA_PROVIDERS } from "./providerCatalog";
import { Icon, Spinner } from "./ui";
function errText(e) {
    if (e instanceof ApiError) {
        if (e.status === 403)
            return "Only the household owner can change the analysis mode.";
        return e.message;
    }
    return e instanceof Error ? e.message : String(e);
}
export function UaModeCard({ me, readOnly }) {
    const [settings, setSettings] = useState(null);
    const [loadError, setLoadError] = useState(null);
    const [nonce, setNonce] = useState(0);
    const [mode, setMode] = useState("local");
    const [provider, setProvider] = useState("qwen");
    const [model, setModel] = useState("");
    const [busy, setBusy] = useState(false);
    const [feedback, setFeedback] = useState(null);
    const [actionError, setActionError] = useState(null);
    const providerId = useId();
    const modelId = useId();
    const listId = useId();
    useEffect(() => {
        let alive = true;
        setLoadError(null);
        dataApi.uaMode()
            .then((s) => {
            if (!alive)
                return;
            setSettings(s);
            setMode(s.mode);
            setProvider(s.provider);
            setModel(s.model);
        })
            .catch((e) => { if (alive)
            setLoadError(errText(e)); });
        return () => { alive = false; };
    }, [nonce]);
    if (loadError) {
        return (_jsx("section", { className: "dm-model-card dm-ua", "aria-label": "UA analysis mode", children: _jsxs("div", { className: "dm-alert dm-alert-error", style: { margin: 0 }, children: [_jsx(Icon, { name: "alert" }), _jsx("span", { className: "flex-1", children: loadError }), _jsx("button", { type: "button", className: "dm-btn dm-btn-xs", onClick: () => setNonce((n) => n + 1), children: "Retry" })] }) }));
    }
    if (!settings) {
        return (_jsx("section", { className: "dm-model-card dm-ua", "aria-label": "UA analysis mode", children: _jsxs("div", { className: "dm-center", children: [_jsx(Spinner, {}), " Loading analysis mode\u2026"] }) }));
    }
    const cloud = mode === "cloud";
    const dirty = mode !== settings.mode
        || (cloud && (provider !== settings.provider || model.trim() !== settings.model));
    const canSave = !readOnly && !busy && dirty && (!cloud || model.trim().length > 0);
    const suggestions = [...new Set([model || settings.model, ...(MODEL_SUGGESTIONS[provider] ?? [])])].filter(Boolean);
    async function save() {
        if (!canSave)
            return;
        setBusy(true);
        setActionError(null);
        setFeedback(null);
        try {
            const res = await dataApi.putUaMode(cloud
                ? { mode: "cloud", provider, model: model.trim() }
                : { mode: "local" });
            setSettings(res);
            setMode(res.mode);
            setProvider(res.provider);
            setModel(res.model);
            const what = res.mode === "cloud" ? `cloud analysis via ${res.provider} (${res.model})` : "local analysis";
            // `written` = the indexer config file was updated by the hub
            setFeedback(res.written
                ? `Saved — ${what}; written to the indexer config, effective on the next analysis run.`
                : `Saved — ${what}; the indexer config was not written, so the running indexer keeps its previous mode.`);
        }
        catch (e) {
            setActionError(errText(e));
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs("section", { className: "dm-model-card dm-ua", "aria-label": "UA analysis mode", children: [_jsxs("div", { className: "dm-model-head", children: [_jsx("span", { className: `dm-model-glyph ${settings.mode === "cloud" ? "is-cloud" : "is-local"}`, "aria-hidden": true, children: _jsx(Icon, { name: "brain", size: 22 }) }), _jsxs("div", { className: "dm-model-title", children: [_jsxs("h3", { children: ["UA analysis mode", _jsxs("span", { className: `dm-mode-badge ${settings.mode === "cloud" ? "is-cloud" : "is-local"}`, children: [_jsx(Icon, { name: settings.mode === "cloud" ? "globe" : "home", size: 12 }), settings.mode === "cloud" ? "Cloud analysis" : "Local analysis"] })] }), _jsx("p", { className: "dm-muted", children: "Which engine runs Understand Anything's deep analysis over your folders." })] })] }), _jsx("div", { className: "dm-seg dm-ua-mode", role: "radiogroup", "aria-label": "Analysis mode", children: ["local", "cloud"].map((m) => (_jsx("button", { type: "button", role: "radio", "aria-checked": mode === m, className: "dm-seg-btn", disabled: readOnly || busy, onClick: () => { setMode(m); setFeedback(null); }, children: m === "local" ? "Local analysis" : "Cloud analysis" }, m))) }), cloud ? (_jsxs("div", { className: "dm-prov-form", children: [_jsxs("div", { className: "dm-prov-field", children: [_jsx("label", { className: "dm-prov-field-label", htmlFor: providerId, children: "Provider" }), _jsx("select", { id: providerId, className: "dm-input", value: provider, onChange: (e) => { setProvider(e.target.value); setFeedback(null); }, disabled: readOnly || busy, children: UA_PROVIDERS.map((p) => _jsx("option", { value: p.id, children: p.label }, p.id)) })] }), _jsxs("div", { className: "dm-prov-field", children: [_jsx("label", { className: "dm-prov-field-label", htmlFor: modelId, children: "Model" }), _jsx("input", { id: modelId, className: "dm-input dm-mono", value: model, onChange: (e) => { setModel(e.target.value); setFeedback(null); }, disabled: readOnly || busy, list: listId, spellCheck: false, autoComplete: "off", placeholder: MODEL_SUGGESTIONS[provider]?.[0] ?? "model name" }), _jsx("datalist", { id: listId, children: suggestions.map((m) => _jsx("option", { value: m }, m)) })] })] })) : null, _jsx("div", { className: "dm-prov-actions", children: _jsx("button", { type: "button", className: "dm-btn dm-btn-sm dm-btn-primary", disabled: !canSave, onClick: () => void save(), children: busy ? "Saving…" : "Save" }) }), feedback && !actionError ? (_jsxs("p", { className: "dm-alert dm-alert-ok", role: "status", children: [_jsx(Icon, { name: "check" }), " ", feedback] })) : null, actionError ? (_jsxs("p", { className: "dm-alert dm-alert-error", role: "alert", children: [_jsx(Icon, { name: "alert" }), " ", actionError] })) : null, _jsxs("p", { className: "dm-note dm-note-sm", children: [_jsx(Icon, { name: "info" }), _jsx("span", { children: "Laya pre-filtering always stays local; only the deep-analysis step moves to the chosen cloud model." })] }), readOnly ? (_jsxs("p", { className: "dm-note dm-note-sm", children: [_jsx(Icon, { name: "lock", size: 13 }), _jsxs("span", { children: ["Only the household owner can change the analysis mode.", me ? _jsxs(_Fragment, { children: [" You're signed in as ", _jsx("b", { children: me.role }), "."] }) : null] })] })) : null] }));
}
