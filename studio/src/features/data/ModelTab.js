import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// Model tab (added 2026-10-14): the household-wide local ↔ cloud switch for Jarvis's
// LLM route. One big switch card — not a per-scope policy, so it ignores the scope tree
// and applies immediately on PUT /api/settings/model-mode. Guests/members see it read-only.
import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { dataApi } from "./adapter";
import { Icon, Spinner, Toggle } from "./ui";
// Fixed privacy copy — do not soften: this is the promise the switch makes.
// 2026-10-14: also shown by the quick switch in the Jarvis chat header
// (features/jarvis/ModelModeSwitch.tsx); keep the two in sync by sharing this constant.
export const MODEL_MODE_PRIVACY_NOTE = "In cloud mode, turns that involve personal or household-private data still run on the local model (privacy floor); raw voice audio is never uploaded to the cloud.";
function errText(e) {
    if (e instanceof ApiError) {
        if (e.status === 403)
            return "Only the household owner can switch the model mode.";
        return e.message;
    }
    return e instanceof Error ? e.message : String(e);
}
function ModeBadge({ mode }) {
    return (_jsxs("span", { className: `dm-mode-badge is-${mode}`, children: [_jsx(Icon, { name: mode === "cloud" ? "globe" : "home", size: 12 }), mode === "cloud" ? "Cloud" : "Local"] }));
}
export function ModelTab({ me, readOnly }) {
    const [settings, setSettings] = useState(null);
    const [loadError, setLoadError] = useState(null);
    const [busy, setBusy] = useState(false);
    const [switchError, setSwitchError] = useState(null);
    // null until the first switch in this view; then mirrors the PUT response's `pushed`.
    const [pushed, setPushed] = useState(null);
    const [nonce, setNonce] = useState(0);
    useEffect(() => {
        let alive = true;
        setLoadError(null);
        dataApi.modelMode()
            .then((s) => { if (alive)
            setSettings(s); })
            .catch((e) => { if (alive)
            setLoadError(errText(e)); });
        return () => { alive = false; };
    }, [nonce]);
    async function switchTo(next) {
        if (readOnly || busy || !settings || settings.mode === next)
            return;
        setBusy(true);
        setSwitchError(null);
        try {
            const res = await dataApi.putModelMode({ mode: next });
            setSettings({ mode: res.mode, cloud_model_route: res.cloud_model_route, cloud_model_persona: res.cloud_model_persona, updated_at: res.updated_at });
            setPushed(res.pushed);
        }
        catch (e) {
            setSwitchError(errText(e));
        }
        finally {
            setBusy(false);
        }
    }
    if (loadError) {
        return (_jsxs("div", { className: "dm-alert dm-alert-error", children: [_jsx(Icon, { name: "alert" }), _jsx("span", { className: "flex-1", children: loadError }), _jsx("button", { type: "button", className: "dm-btn dm-btn-xs", onClick: () => setNonce((n) => n + 1), children: "Retry" })] }));
    }
    if (!settings)
        return _jsxs("div", { className: "dm-center dm-tall", children: [_jsx(Spinner, {}), " Loading model mode\u2026"] });
    const cloud = settings.mode === "cloud";
    const next = cloud ? "local" : "cloud";
    return (_jsx("div", { className: "dm-model", children: _jsxs("section", { className: "dm-model-card", "aria-label": "Model mode", children: [_jsxs("div", { className: "dm-model-head", children: [_jsx("span", { className: `dm-model-glyph is-${settings.mode}`, "aria-hidden": true, children: _jsx(Icon, { name: cloud ? "globe" : "home", size: 22 }) }), _jsxs("div", { className: "dm-model-title", children: [_jsxs("h3", { children: ["Model mode ", _jsx(ModeBadge, { mode: settings.mode })] }), _jsx("p", { className: "dm-muted", children: cloud
                                        ? "Jarvis routes and replies through the cloud model."
                                        : "Everything runs on the local model on the Jetson." })] }), _jsxs("div", { className: "dm-model-switch", children: [_jsx(Toggle, { checked: cloud, disabled: readOnly || busy, label: "Cloud mode", onChange: (v) => void switchTo(v ? "cloud" : "local") }), _jsx("button", { type: "button", className: "dm-btn dm-btn-primary dm-btn-sm", disabled: readOnly || busy, onClick: () => void switchTo(next), children: busy ? "Switching…" : cloud ? "Switch to local" : "Switch to cloud" })] })] }), _jsxs("dl", { className: "dm-model-specs", children: [_jsxs("div", { children: [_jsx("dt", { children: "Cloud route model" }), _jsx("dd", { className: "dm-mono", children: settings.cloud_model_route })] }), _jsxs("div", { children: [_jsx("dt", { children: "Cloud persona model" }), _jsx("dd", { className: "dm-mono", children: settings.cloud_model_persona })] }), _jsxs("div", { children: [_jsx("dt", { children: "Last changed" }), _jsx("dd", { children: settings.updated_at ? new Date(settings.updated_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—" })] })] }), _jsxs("p", { className: "dm-note dm-note-sm", children: [_jsx(Icon, { name: "info" }), " ", _jsx("span", { children: MODEL_MODE_PRIVACY_NOTE })] }), pushed !== null && !switchError ? (_jsxs("p", { className: "dm-alert dm-alert-ok", role: "status", children: [_jsx(Icon, { name: "check" }), pushed
                            ? `Switched to ${cloud ? "cloud" : "local"} — pushed to the voice runtime, effective immediately.`
                            : `Switched to ${cloud ? "cloud" : "local"} — saved; the voice runtime picks it up on its next turn.`] })) : null, switchError ? (_jsxs("p", { className: "dm-alert dm-alert-error", role: "alert", children: [_jsx(Icon, { name: "alert" }), " ", switchError] })) : null, readOnly ? (_jsxs("p", { className: "dm-note dm-note-sm", children: [_jsx(Icon, { name: "lock", size: 13 }), _jsxs("span", { children: ["Only the household owner can switch the model mode.", me ? _jsxs(_Fragment, { children: [" You're signed in as ", _jsx("b", { children: me.role }), "."] }) : null] })] })) : null] }) }));
}
