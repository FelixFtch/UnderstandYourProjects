import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// Voice profile card (2026-10-15): the Model tab card between the mode switch
// and the Cloud provider card — it bundles the voice chain (STT/LLM/TTS) into
// switchable profiles (GET/PUT /api/settings/voice-profiles). The two builtins
// (Local / Cloud full chain) are one-tap switches; owners can also save custom
// mixes. Switching reports the per-section push result (pushed.llm/stt/tts);
// saving a mix never pushes. Non-owners see everything read-only.
// Note: the *_options lists come from the hub as-is (local + providers with a
// stored key); the hub is capability-agnostic, so e.g. a provider without a TTS
// offering could still be listed — the frontend intentionally does not filter.
import { useEffect, useId, useState } from "react";
import { ApiError } from "../../api/client";
import { dataApi } from "./adapter";
import { Icon, Spinner } from "./ui";
const NEW_MIX = "__new__";
const SEGMENTS = ["stt", "llm", "tts"];
const SEG_LABEL = { stt: "STT", llm: "LLM", tts: "TTS" };
/** Custom mix names are slugs derived from the label ("My mix" → "my-mix"). */
export function slugifyProfileName(label) {
    const s = label.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    return s || "my-mix";
}
function errText(e) {
    if (e instanceof ApiError) {
        if (e.status === 403)
            return "Only the household owner can change voice profiles.";
        return e.message;
    }
    return e instanceof Error ? e.message : String(e);
}
function chainSummary(p) {
    return `STT ${p.stt} · LLM ${p.llm} · TTS ${p.tts}`;
}
/** Per-section push feedback, e.g. "LLM: pushed to the voice runtime · STT: pushed … · TTS: applies on the next turn". */
function pushSummary(pushed) {
    return ["llm", "stt", "tts"]
        .map((k) => `${SEG_LABEL[k]}: ${pushed[k] ? "pushed to the voice runtime" : "applies on the next turn"}`)
        .join(" · ");
}
export function VoiceProfileCard({ me, readOnly }) {
    const [settings, setSettings] = useState(null);
    const [loadError, setLoadError] = useState(null);
    const [nonce, setNonce] = useState(0);
    const [sel, setSel] = useState(NEW_MIX); // which custom mix is being edited
    const [draft, setDraft] = useState({ stt: "local", llm: "local", tts: "local", label: "" });
    const [busy, setBusy] = useState(null); // "save" | "activate" | a builtin name
    const [feedback, setFeedback] = useState(null);
    const [actionError, setActionError] = useState(null);
    const sttId = useId();
    const llmId = useId();
    const ttsId = useId();
    const labelId = useId();
    const mixId = useId();
    function seedDraft(s, target) {
        if (target) {
            setDraft({ stt: target.stt, llm: target.llm, tts: target.tts, label: target.label });
        }
        else {
            setDraft({ stt: s.stt_options[0] ?? "local", llm: s.llm_options[0] ?? "local", tts: s.tts_options[0] ?? "local", label: "" });
        }
    }
    useEffect(() => {
        let alive = true;
        setLoadError(null);
        dataApi.voiceProfiles()
            .then((s) => {
            if (!alive)
                return;
            setSettings(s);
            // default the editor to the first custom mix, or a fresh one
            const firstCustom = s.profiles.find((p) => !p.builtin) ?? null;
            setSel(firstCustom?.name ?? NEW_MIX);
            seedDraft(s, firstCustom);
        })
            .catch((e) => { if (alive)
            setLoadError(errText(e)); });
        return () => { alive = false; };
    }, [nonce]);
    const customs = settings?.profiles.filter((p) => !p.builtin) ?? [];
    const builtins = settings?.profiles.filter((p) => p.builtin) ?? [];
    const activeProfile = settings?.profiles.find((p) => p.name === settings.active) ?? null;
    const editing = sel !== NEW_MIX ? customs.find((p) => p.name === sel) ?? null : null;
    function pickMix(name) {
        if (!settings)
            return;
        setSel(name);
        setFeedback(null);
        setActionError(null);
        seedDraft(settings, name === NEW_MIX ? null : customs.find((p) => p.name === name) ?? null);
    }
    const dirty = editing
        ? draft.stt !== editing.stt || draft.llm !== editing.llm || draft.tts !== editing.tts || draft.label.trim() !== editing.label
        : draft.label.trim().length > 0;
    const canSave = !readOnly && busy === null && dirty && (editing !== null || draft.label.trim().length > 0);
    const canActivate = !readOnly && busy === null && editing !== null && !dirty && sel !== settings?.active;
    async function activate(name) {
        if (readOnly || busy || !settings || settings.active === name)
            return;
        setBusy(name === sel ? "activate" : name);
        setActionError(null);
        setFeedback(null);
        try {
            const res = await dataApi.putVoiceProfiles({ active: name });
            setSettings(res);
            const label = res.profiles.find((p) => p.name === res.active)?.label ?? res.active;
            setFeedback(res.pushed
                ? `Active profile: ${label} — ${pushSummary(res.pushed)}.`
                : `Active profile: ${label} — saved; nothing was pushed to the voice runtime.`);
        }
        catch (e) {
            setActionError(errText(e));
        }
        finally {
            setBusy(null);
        }
    }
    async function saveCustom() {
        if (readOnly || busy || !settings || !canSave)
            return;
        const name = editing ? editing.name : slugifyProfileName(draft.label);
        setBusy("save");
        setActionError(null);
        setFeedback(null);
        try {
            const res = await dataApi.putVoiceProfiles({
                name, stt: draft.stt, llm: draft.llm, tts: draft.tts,
                label: draft.label.trim() || name,
            });
            setSettings(res);
            setSel(name);
            const saved = res.profiles.find((p) => p.name === name) ?? null;
            if (saved)
                setDraft({ stt: saved.stt, llm: saved.llm, tts: saved.tts, label: saved.label });
            // saving never pushes (pushed: null) — say so explicitly
            setFeedback(`Saved "${saved?.label ?? name}" — stored on the hub, not pushed to the voice runtime. Activate it to use it.`);
        }
        catch (e) {
            setActionError(errText(e));
        }
        finally {
            setBusy(null);
        }
    }
    if (loadError) {
        return (_jsx("section", { className: "dm-model-card dm-voice", "aria-label": "Voice profiles", children: _jsxs("div", { className: "dm-alert dm-alert-error", style: { margin: 0 }, children: [_jsx(Icon, { name: "alert" }), _jsx("span", { className: "flex-1", children: loadError }), _jsx("button", { type: "button", className: "dm-btn dm-btn-xs", onClick: () => setNonce((n) => n + 1), children: "Retry" })] }) }));
    }
    if (!settings) {
        return (_jsx("section", { className: "dm-model-card dm-voice", "aria-label": "Voice profiles", children: _jsxs("div", { className: "dm-center", children: [_jsx(Spinner, {}), " Loading voice profiles\u2026"] }) }));
    }
    return (_jsxs("section", { className: "dm-model-card dm-voice", "aria-label": "Voice profiles", children: [_jsxs("div", { className: "dm-model-head", children: [_jsx("span", { className: `dm-model-glyph ${activeProfile?.name === "local" ? "is-local" : "is-cloud"}`, "aria-hidden": true, children: _jsx(Icon, { name: "activity", size: 22 }) }), _jsxs("div", { className: "dm-model-title", children: [_jsxs("h3", { children: ["Voice profiles", activeProfile ? (_jsxs("span", { className: `dm-mode-badge ${activeProfile.name === "local" ? "is-local" : "is-cloud"}`, children: [_jsx(Icon, { name: activeProfile.name === "local" ? "home" : "globe", size: 12 }), " ", activeProfile.label] })) : null] }), _jsx("p", { className: "dm-muted", children: "One profile bundles the whole voice chain \u2014 speech-to-text, the model, and the voice." })] })] }), _jsx("div", { className: "dm-voice-builtins", children: builtins.map((p) => (_jsxs("button", { type: "button", className: "dm-prov-current dm-voice-builtin", disabled: readOnly || busy !== null || p.name === settings.active, title: p.name === settings.active ? `${p.label} is the active profile` : `Switch to ${p.label}`, onClick: () => void activate(p.name), children: [_jsxs("span", { className: "dm-prov-row-text", children: [_jsx("span", { className: "dm-prov-label", children: busy === p.name ? "Switching…" : p.label }), _jsx("span", { className: "dm-mono dm-prov-model", children: chainSummary(p) })] }), p.name === settings.active ? _jsx("span", { className: "dm-prov-active", children: "Active" }) : null] }, p.name))) }), _jsxs("div", { className: "dm-field dm-voice-custom", children: [_jsxs("div", { className: "dm-field-head", children: [_jsxs("div", { className: "min-w-0 flex-1", children: [_jsx("div", { className: "dm-field-title", children: "Custom mix" }), _jsx("div", { className: "dm-field-hint", children: "Combine any available sections \u2014 e.g. local ears, cloud brain, cloud voice." })] }), customs.length ? (_jsxs("select", { id: mixId, className: "dm-input dm-voice-mixsel", value: sel, onChange: (e) => pickMix(e.target.value), disabled: readOnly || busy !== null, "aria-label": "Mix to edit", children: [customs.map((p) => _jsx("option", { value: p.name, children: p.label }, p.name)), _jsx("option", { value: NEW_MIX, children: "New custom mix\u2026" })] })) : null] }), _jsxs("div", { className: "dm-field-body", children: [_jsx("div", { className: "dm-voice-mix", children: SEGMENTS.map((seg) => {
                                    const id = seg === "stt" ? sttId : seg === "llm" ? llmId : ttsId;
                                    return (_jsxs("div", { className: "dm-prov-field", children: [_jsx("label", { className: "dm-prov-field-label", htmlFor: id, children: SEG_LABEL[seg] }), _jsx("select", { id: id, className: "dm-input dm-mono", value: draft[seg], onChange: (e) => { setDraft((d) => ({ ...d, [seg]: e.target.value })); setFeedback(null); }, disabled: readOnly || busy !== null, children: settings[`${seg}_options`].map((o) => _jsx("option", { value: o, children: o }, o)) })] }, seg));
                                }) }), _jsxs("div", { className: "dm-prov-field", style: { marginTop: 10 }, children: [_jsx("label", { className: "dm-prov-field-label", htmlFor: labelId, children: "Label" }), _jsx("input", { id: labelId, className: "dm-input", placeholder: "My mix", value: draft.label, onChange: (e) => { setDraft((d) => ({ ...d, label: e.target.value })); setFeedback(null); }, disabled: readOnly || busy !== null, maxLength: 48 })] })] }), _jsxs("div", { className: "dm-field-foot dm-prov-actions", style: { marginTop: 12 }, children: [_jsx("button", { type: "button", className: "dm-btn dm-btn-sm dm-btn-primary", disabled: !canSave, onClick: () => void saveCustom(), children: busy === "save" ? "Saving…" : "Save custom" }), _jsx("button", { type: "button", className: "dm-btn dm-btn-sm", disabled: !canActivate, title: editing ? (dirty ? "Save the mix first" : sel === settings.active ? "This mix is already active" : `Make ${editing.label} the active profile`) : "Save the mix first", onClick: () => void activate(sel), children: busy === "activate" ? "Activating…" : "Activate" })] })] }), feedback && !actionError ? (_jsxs("p", { className: "dm-alert dm-alert-ok", role: "status", children: [_jsx(Icon, { name: "check" }), " ", feedback] })) : null, actionError ? (_jsxs("p", { className: "dm-alert dm-alert-error", role: "alert", children: [_jsx(Icon, { name: "alert" }), " ", actionError] })) : null, _jsxs("p", { className: "dm-note dm-note-sm", children: [_jsx(Icon, { name: "info" }), _jsxs("span", { children: [_jsx("b", { children: "Keep local weights warm:" }), " Switching never unloads the local models - switching back is instant."] })] }), readOnly ? (_jsxs("p", { className: "dm-note dm-note-sm", children: [_jsx(Icon, { name: "lock", size: 13 }), _jsxs("span", { children: ["Only the household owner can change voice profiles.", me ? _jsxs(_Fragment, { children: [" You're signed in as ", _jsx("b", { children: me.role }), "."] }) : null] })] })) : null] }));
}
