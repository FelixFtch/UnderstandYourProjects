import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { Icon } from "../design/icons";
import { Button, Chip, cx, Kbd, Segmented, Spinner, StatusDot } from "../design/primitives";
import { Monogram } from "./Brand";
import { MOD_KEY } from "./nav";
import { FIXTURES, useSession } from "./session";
import { useTheme } from "./theme";
export function TopBar({ route, onOpenPalette, className }) {
    const me = useSession((s) => s.me);
    return (_jsxs("header", { className: cx("flex h-14 min-w-0 items-center gap-3 border-b border-line bg-canvas px-3 sm:px-5", className), children: [_jsxs("div", { className: "flex min-w-0 flex-1 items-center gap-3", children: [_jsx("span", { className: "md:hidden", children: _jsx(Monogram, { size: 28 }) }), _jsxs("div", { className: "flex min-w-0 items-baseline gap-3", children: [_jsx("h1", { className: "shrink-0 font-serif text-[18px] text-ink", children: route.label }), _jsx("p", { className: "hidden truncate text-[13px] text-muted lg:block", children: route.hint })] }), FIXTURES ? _jsx(Chip, { tone: "info", className: "hidden sm:inline-flex", title: "VITE_STUDIO_FIXTURES=true: offline sample data", children: "Fixtures" }) : null] }), _jsxs("button", { type: "button", onClick: onOpenPalette, className: "hidden h-8 items-center gap-2 rounded-control border border-line bg-surface pr-1.5 pl-2.5 text-[13px] text-muted hover:border-line-strong hover:text-ink xl:flex", children: [_jsx(Icon, { name: "search", size: 15 }), "Jump to\u2026", _jsxs("span", { className: "ml-3 flex gap-0.5", children: [_jsx(Kbd, { children: MOD_KEY }), _jsx(Kbd, { children: "K" })] })] }), me ? _jsx(AgentBoxStatus, { me: me }) : null, me ? (_jsxs("div", { className: "hidden min-w-0 items-center gap-2 lg:flex", title: me.jarvis.urn ?? undefined, children: [_jsx("span", { className: "truncate text-[13px] text-ink-2", children: me.jarvis.display_name }), _jsx("span", { className: "rounded-md border border-line bg-surface px-1.5 py-0.5 font-mono text-[12px] text-ink", children: me.jarvis.number })] })) : null, me ? _jsx(ProfileMenu, { me: me }) : null] }));
}
function AgentBoxStatus({ me }) {
    const enrolling = useSession((s) => s.enrolling);
    const enrollError = useSession((s) => s.enrollError);
    const enroll = useSession((s) => s.enroll);
    if (me.agent_box.enrolled) {
        return (_jsxs("span", { className: "hidden items-center gap-1.5 text-[12.5px] text-muted sm:flex", title: `Agent box ${me.agent_box.box_id ?? ""}: this Jetson's project worker is enrolled`, children: [_jsx(StatusDot, { tone: "ok" }), "Agent box enrolled"] }));
    }
    return (_jsxs("div", { className: "hidden items-center gap-2 sm:flex", children: [_jsxs("span", { className: "flex items-center gap-1.5 text-[12.5px] text-warn", title: enrollError ?? "This Jetson's project worker has no HomeHub token yet", children: [_jsx(StatusDot, { tone: enrollError ? "err" : "warn" }), _jsx("span", { className: "hidden md:inline", children: enrollError ? "Enroll failed" : "Agent box not enrolled" })] }), me.role === "owner" ? (_jsx(Button, { size: "sm", variant: "secondary", onClick: () => void enroll(), loading: enrolling, title: "Enroll this Jetson's UYP worker with HomeHub", children: enrollError ? "Retry" : "Enroll" })) : null] }));
}
function ProfileMenu({ me }) {
    const [open, setOpen] = useState(false);
    const [copied, setCopied] = useState(false);
    const root = useRef(null);
    const signOut = useSession((s) => s.signOut);
    const enroll = useSession((s) => s.enroll);
    const enrolling = useSession((s) => s.enrolling);
    const enrollError = useSession((s) => s.enrollError);
    const pref = useTheme((s) => s.pref);
    const setPref = useTheme((s) => s.setPref);
    useEffect(() => {
        if (!open)
            return;
        const onDown = (e) => { if (!root.current?.contains(e.target))
            setOpen(false); };
        const onKey = (e) => { if (e.key === "Escape")
            setOpen(false); };
        document.addEventListener("mousedown", onDown);
        document.addEventListener("keydown", onKey);
        return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
    }, [open]);
    const copyNumber = async () => {
        try {
            await navigator.clipboard.writeText(me.jarvis.number);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1400);
        }
        catch { /* ignore */ }
    };
    return (_jsxs("div", { ref: root, className: "relative shrink-0", children: [_jsxs("button", { type: "button", onClick: () => setOpen((v) => !v), "aria-haspopup": "dialog", "aria-expanded": open, className: "flex items-center gap-2 rounded-full border border-line bg-surface py-0.5 pr-2.5 pl-0.5 hover:border-line-strong", children: [_jsx("span", { className: "grid size-7 place-items-center rounded-full bg-accent-soft font-serif text-[14px] text-accent-ink", children: me.display_name.slice(0, 1).toUpperCase() }), _jsxs("span", { className: "text-[13px] text-ink-2", children: [_jsx("span", { className: "font-medium text-ink", children: me.display_name }), _jsxs("span", { className: "hidden sm:inline", children: [" \u00B7 ", me.role] })] }), !me.agent_box.enrolled ? _jsx(StatusDot, { tone: "warn", className: "sm:hidden", label: "Agent box not enrolled" }) : null] }), open ? (_jsxs("div", { role: "dialog", "aria-label": "Profile", className: "j-rise absolute top-[calc(100%+8px)] right-0 z-40 w-[min(320px,calc(100vw-24px))] rounded-card border border-line bg-surface p-4 shadow-pop", children: [_jsx("div", { className: "text-[11px] font-semibold tracking-[0.08em] text-muted uppercase", children: "Signed in as" }), _jsxs("div", { className: "mt-1 font-serif text-[18px] text-ink", children: [me.display_name, " ", _jsxs("span", { className: "font-sans text-[13px] text-muted", children: ["\u00B7 ", me.role] })] }), _jsxs("div", { className: "text-[12px] text-muted", children: ["member ", _jsx("span", { className: "font-mono", children: me.member_id }), " \u00B7 ", me.household_id] }), _jsxs("div", { className: "mt-4 rounded-control border border-line bg-canvas/60 p-3", children: [_jsx("div", { className: "text-[12.5px] font-medium text-ink-2", children: me.jarvis.display_name }), _jsxs("button", { type: "button", onClick: copyNumber, className: "mt-1 flex items-center gap-2 font-mono text-[17px] tracking-wide text-ink hover:text-accent-ink", title: "Copy Jarvis number", children: [me.jarvis.number, _jsx(Icon, { name: copied ? "check" : "copy", size: 14, className: "text-muted" })] }), me.jarvis.urn ? _jsx("div", { className: "mt-1 truncate font-mono text-[11px] text-muted", title: me.jarvis.urn, children: me.jarvis.urn }) : null, _jsx("div", { className: "mt-1 text-[12px] text-muted", children: me.jarvis.town ? _jsxs(_Fragment, { children: ["NANDA Town \u00B7 ", me.jarvis.town.participant, " ", _jsxs("span", { className: "font-mono", children: ["(", me.jarvis.town.run_id, ")"] })] }) : "Not joined to NANDA Town" })] }), _jsxs("div", { className: "mt-3 flex items-center justify-between gap-2 rounded-control border border-line p-3", children: [_jsxs("div", { className: "min-w-0", children: [_jsxs("div", { className: "flex items-center gap-1.5 text-[12.5px] font-medium text-ink-2", children: [_jsx(StatusDot, { tone: me.agent_box.enrolled ? "ok" : "warn" }), " Agent box"] }), _jsx("div", { className: "truncate text-[12px] text-muted", children: me.agent_box.enrolled ? _jsxs(_Fragment, { children: ["Enrolled \u00B7 ", _jsx("span", { className: "font-mono", children: me.agent_box.box_id })] }) : enrollError ? `Enroll failed: ${enrollError}` : "This Jetson's project worker is not enrolled" })] }), !me.agent_box.enrolled && me.role === "owner" ? (_jsx(Button, { size: "sm", onClick: () => void enroll(), disabled: enrolling, children: enrolling ? _jsx(Spinner, { size: 13 }) : "Enroll" })) : null] }), _jsxs("div", { className: "mt-3 flex items-center justify-between gap-2", children: [_jsx("span", { className: "text-[12.5px] text-ink-2", children: "Theme" }), _jsx(Segmented, { label: "Theme", value: pref, onChange: setPref, options: [{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }, { value: "system", label: "Auto" }] })] }), _jsx(Button, { variant: "ghost", icon: "logout", className: "mt-3 w-full justify-start", onClick: () => { setOpen(false); signOut(); }, children: "Sign out of this browser" })] })) : null] }));
}
