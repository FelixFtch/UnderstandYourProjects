import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// Model mode quick switch (2026-10-14): a compact Local/Cloud badge in the Jarvis chat
// header — the entry point users actually see. Clicking opens a confirm dialog (the
// privacy-floor copy is mandatory), then PUTs the new mode and reflects `pushed`.
// The full settings (model names, last changed) stay in Data → Model.
import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { useMe } from "../../app/session";
import { Icon } from "../../design/icons";
import { Button, cx, Modal } from "../../design/primitives";
import { MODEL_MODE_PRIVACY_NOTE } from "../data/ModelTab";
import { jarvisData } from "./data";
function errText(e) {
    if (e instanceof ApiError && e.status === 403)
        return "Only the household owner can switch the model mode.";
    return e instanceof Error ? e.message : String(e);
}
export function ModelModeSwitch() {
    const me = useMe();
    const readOnly = !me || me.role !== "owner";
    const [settings, setSettings] = useState(null);
    const [loadError, setLoadError] = useState(null);
    const [nonce, setNonce] = useState(0);
    const [dialog, setDialog] = useState(null);
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState(null);
    const [switchError, setSwitchError] = useState(null);
    useEffect(() => {
        let alive = true;
        setLoadError(null);
        jarvisData.modelMode()
            .then((s) => { if (alive)
            setSettings(s); })
            .catch((e) => { if (alive)
            setLoadError(errText(e)); });
        return () => { alive = false; };
    }, [nonce]);
    function openDialog() {
        if (!settings || readOnly)
            return;
        setResult(null);
        setSwitchError(null);
        setDialog({ target: settings.mode === "cloud" ? "local" : "cloud" });
    }
    async function confirmSwitch(target) {
        setBusy(true);
        setSwitchError(null);
        try {
            const res = await jarvisData.putModelMode({ mode: target });
            // badge updates immediately from the response, before the dialog closes
            setSettings({ mode: res.mode, cloud_model_route: res.cloud_model_route, cloud_model_persona: res.cloud_model_persona, updated_at: res.updated_at });
            setResult(res);
        }
        catch (e) {
            setSwitchError(errText(e));
        }
        finally {
            setBusy(false);
        }
    }
    if (loadError) {
        return (_jsxs("button", { type: "button", onClick: () => setNonce((n) => n + 1), title: `${loadError} — tap to retry`, className: "flex shrink-0 items-center gap-1.5 rounded-full border border-warn/30 bg-warn-soft px-2.5 py-1 text-[12.5px] font-medium text-warn", children: [_jsx(Icon, { name: "alert", size: 13 }), " Model mode?"] }));
    }
    if (!settings) {
        return _jsx("span", { className: "flex shrink-0 items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-[12.5px] text-faint", "aria-busy": "true", children: "\u2026" });
    }
    const cloud = settings.mode === "cloud";
    const badge = (_jsxs("button", { type: "button", onClick: openDialog, disabled: readOnly, "aria-haspopup": "dialog", "aria-label": readOnly ? undefined : `Model mode: ${cloud ? "cloud" : "local"} — select to switch`, title: readOnly
            ? `Only the household owner can switch the model mode${me ? ` — you're signed in as ${me.role}` : ""}.`
            : `Model mode: ${cloud ? "cloud" : "local"} — select to switch`, className: cx("flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60", cloud ? "border-accent/30 bg-accent-soft text-accent-ink" : "border-ok/30 bg-ok-soft text-ok"), children: [_jsx(Icon, { name: cloud ? "globe" : "home", size: 13 }), " ", cloud ? "Cloud" : "Local"] }));
    const target = dialog?.target;
    const targetCloud = target === "cloud";
    return (_jsxs(_Fragment, { children: [badge, _jsx(Modal, { open: dialog !== null, onClose: () => { if (!busy)
                    setDialog(null); }, title: result ? "Model mode switched" : targetCloud ? "Switch to cloud mode?" : "Switch back to local mode?", width: 460, footer: result ? (_jsx(Button, { variant: "primary", "data-autofocus": true, onClick: () => setDialog(null), children: "Done" })) : (_jsxs(_Fragment, { children: [_jsx(Button, { onClick: () => setDialog(null), disabled: busy, children: "Cancel" }), _jsx(Button, { variant: "primary", "data-autofocus": true, loading: busy, onClick: () => target && void confirmSwitch(target), children: targetCloud ? "Switch to cloud" : "Switch to local" })] })), children: result ? (_jsx("p", { className: "text-[13.5px] text-ink-2", role: "status", children: result.pushed
                        ? `Now in ${result.mode} mode — pushed to the voice runtime, effective immediately.`
                        : `Now in ${result.mode} mode — saved; the voice runtime picks it up on its next turn.` })) : (_jsxs("div", { className: "space-y-2.5 text-[13.5px] text-ink-2", children: [_jsx("p", { children: targetCloud
                                ? _jsxs(_Fragment, { children: ["Jarvis will route and reply through the cloud model (", _jsx("span", { className: "font-mono text-[12.5px]", children: settings.cloud_model_route }), " / ", _jsx("span", { className: "font-mono text-[12.5px]", children: settings.cloud_model_persona }), ")."] })
                                : "Everything runs on the local model on the Jetson again." }), _jsx("p", { className: "rounded-control border border-line bg-canvas px-3 py-2 text-[12.5px] text-muted", children: MODEL_MODE_PRIVACY_NOTE }), _jsxs("p", { className: "text-[12.5px] text-muted", children: ["Model names and history live under ", _jsx("a", { className: "text-accent-ink hover:underline", href: "#/data/household/model", children: "Data \u2192 Model" }), "."] }), switchError ? _jsx("p", { role: "alert", className: "rounded-control border border-err/25 bg-err-soft px-3 py-2 text-[12.5px] text-err", children: switchError }) : null] })) })] }));
}
