import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { ApiError } from "../api/client";
import { Icon } from "../design/icons";
import { Button, cx } from "../design/primitives";
import { Monogram } from "./Brand";
import { FIXTURES, isValidInviteCode, normalizeInviteCode, useSession } from "./session";
const JETSON_CMD = "cd ~/jetson/services/companion-api && PYTHONPATH=src venv/bin/python -m companion_api.studio_admin invite";
export function LoginScreen() {
    const signIn = useSession((s) => s.signIn);
    const expired = useSession((s) => s.expired);
    const [code, setCode] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [copied, setCopied] = useState(false);
    const normalized = normalizeInviteCode(code);
    const valid = isValidInviteCode(normalized);
    async function submit(e) {
        e.preventDefault();
        if (!valid || busy)
            return;
        setBusy(true);
        setError(null);
        try {
            await signIn(normalized);
        }
        catch (err) {
            if (err instanceof ApiError && err.status === 0)
                setError("Can't reach the hub. Check that companion-api is running.");
            else if (err instanceof TypeError)
                setError("Can't reach the hub. Check that companion-api is running (or your tunnel to :5120).");
            else
                setError(err instanceof Error ? err.message : String(err));
            setBusy(false);
        }
    }
    async function copy() {
        try {
            await navigator.clipboard.writeText(JETSON_CMD);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1600);
        }
        catch { /* clipboard blocked: the command is selectable */ }
    }
    return (_jsxs("div", { className: "h-dvh overflow-y-auto bg-canvas", children: [_jsx("div", { "aria-hidden": "true", className: "pointer-events-none fixed inset-x-0 top-0 h-[42vh] opacity-80", style: { background: "radial-gradient(60% 100% at 50% 0%, color-mix(in oklab, var(--j-accent) 16%, transparent), transparent)" } }), _jsxs("main", { className: "relative mx-auto flex min-h-full w-full max-w-[460px] flex-col justify-center px-4 py-10 sm:px-6", children: [_jsxs("div", { className: "mb-6 flex items-center gap-3", children: [_jsx(Monogram, { size: 38 }), _jsxs("div", { children: [_jsx("div", { className: "font-serif text-[17px] leading-tight text-ink", children: "Jarvis Studio" }), _jsx("div", { className: "text-[12.5px] text-muted", children: "The console for your household Jarvis" })] })] }), _jsxs("section", { className: "rounded-card border border-line bg-surface p-5 shadow-card sm:p-7", children: [_jsx("h1", { className: "font-serif text-[26px] leading-tight text-ink", children: "Sign in to Jarvis Studio" }), _jsx("p", { className: "mt-2 text-[14px] text-muted", children: "Studio pairs with your HomeHub the way a phone does. Enter a one-time invite code: it works once and expires after a few minutes." }), expired ? (_jsxs("div", { className: "mt-4 flex items-start gap-2 rounded-control border border-info/25 bg-info-soft px-3 py-2 text-[13px] text-info", children: [_jsx(Icon, { name: "info", size: 15, className: "mt-0.5 shrink-0" }), "Your session ended (the hub no longer accepts this browser's token). Pair again to continue."] })) : null, _jsxs("form", { onSubmit: submit, className: "mt-5 space-y-3", noValidate: true, children: [_jsx("label", { htmlFor: "invite", className: "block text-[13px] font-medium text-ink-2", children: "Invite code" }), _jsx("input", { id: "invite", value: code, onChange: (e) => { setCode(e.target.value.slice(0, 12)); setError(null); }, autoFocus: true, autoComplete: "one-time-code", autoCapitalize: "characters", autoCorrect: "off", spellCheck: false, inputMode: "text", placeholder: "A1B2C3D4", "aria-invalid": !!error, "aria-describedby": "invite-hint", className: cx("h-14 w-full rounded-control border bg-raised px-4 text-center font-mono text-[24px] tracking-[0.32em] text-ink uppercase", "placeholder:text-faint/70 focus:ring-2 focus:ring-accent/25 focus:outline-none", error ? "border-err/60" : "border-line-strong focus:border-accent") }), _jsxs("div", { id: "invite-hint", className: "flex items-center justify-between text-[12px] text-muted", children: [_jsx("span", { children: "8 characters, from the hub. Spaces and dashes are ignored." }), _jsxs("span", { className: cx("font-mono", valid ? "text-ok" : ""), children: [normalized.length, "/8"] })] }), error ? (_jsxs("div", { role: "alert", className: "flex items-start gap-2 rounded-control border border-err/25 bg-err-soft px-3 py-2 text-[13px] text-err", children: [_jsx(Icon, { name: "alert", size: 15, className: "mt-0.5 shrink-0" }), _jsx("span", { children: error })] })) : null, _jsx(Button, { type: "submit", variant: "primary", className: "h-11 w-full text-[15px]", disabled: !valid, loading: busy, children: busy ? "Pairing…" : "Pair this browser" })] }), _jsxs("div", { className: "mt-7 border-t border-line pt-5", children: [_jsx("h2", { className: "text-[13px] font-semibold text-ink-2", children: "Where does the code come from?" }), _jsxs("ol", { className: "mt-3 space-y-4 text-[13.5px] text-ink-2", children: [_jsxs("li", { className: "flex gap-3", children: [_jsx("span", { className: "grid size-6 shrink-0 place-items-center rounded-full bg-sunk text-[12px] font-semibold text-muted", children: "1" }), _jsxs("span", { children: ["On your phone: open the ", _jsx("strong", { className: "font-semibold text-ink", children: "JarvisHub" }), " app and tap ", _jsx("strong", { className: "font-semibold text-ink", children: "Invite" }), "."] })] }), _jsxs("li", { className: "flex min-w-0 gap-3", children: [_jsx("span", { className: "grid size-6 shrink-0 place-items-center rounded-full bg-sunk text-[12px] font-semibold text-muted", children: "2" }), _jsxs("div", { className: "min-w-0 flex-1", children: ["Or on the Jetson, run:", _jsxs("div", { className: "mt-2 flex items-start gap-2 rounded-control border border-line bg-sunk p-2.5", children: [_jsx("code", { className: "min-w-0 flex-1 font-mono text-[12px] leading-relaxed [overflow-wrap:anywhere] text-ink select-all", children: JETSON_CMD }), _jsx("button", { type: "button", onClick: copy, className: "shrink-0 rounded-md p-1 text-muted hover:bg-surface hover:text-ink", "aria-label": "Copy command", title: "Copy command", children: _jsx(Icon, { name: copied ? "check" : "copy", size: 15 }) })] }), _jsxs("div", { className: "mt-1.5 text-[12px] text-muted", children: ["It prints an 8-character code (add ", _jsx("code", { className: "font-mono", children: "--ttl 900" }), " for 15 minutes)."] })] })] })] })] })] }), _jsxs("p", { className: "mt-4 px-1 text-[12px] text-muted", children: ["The token stays in this browser only. Sign out any time from your profile menu.", FIXTURES ? " Fixture mode: any code works except 00000000." : ""] })] })] }));
}
