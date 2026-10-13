import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Icon } from "../../design/icons";
const PROMPTS = [
    { text: "What did I work on yesterday in commontasks?", kind: "Projects", icon: "activity" },
    { text: "Analyze ~/code/adhd-agent", kind: "Analyze a folder", icon: "folder" },
    { text: "Turn on the clinic lights", kind: "Home", icon: "bulb" },
    { text: "Ask Felix's Jarvis if he is free tomorrow", kind: "Other Jarvises", icon: "handoff" },
];
function greeting(d = new Date()) {
    const h = d.getHours();
    if (h < 5)
        return "Still up";
    if (h < 12)
        return "Good morning";
    if (h < 18)
        return "Good afternoon";
    return "Good evening";
}
export function SuggestedPrompts({ name, onPick }) {
    return (_jsxs("div", { className: "flex min-h-full flex-col items-center justify-center py-8 text-center", children: [_jsx("span", { className: "grid size-12 place-items-center rounded-full border border-accent/40 font-serif text-[24px] text-accent-ink italic", children: "J" }), _jsxs("h2", { className: "mt-4 font-serif text-[26px] leading-tight text-ink", children: [greeting(), name ? `, ${name}` : "", "."] }), _jsx("p", { className: "mt-2 max-w-[44ch] text-[14px] text-muted", children: "Ask about your projects, your home, or other Jarvises. Every answer shows how Jarvis handled it: what it understood, what it looked up, and what it did." }), _jsx("div", { className: "mt-7 grid w-full max-w-[640px] gap-2 sm:grid-cols-2", children: PROMPTS.map((p) => (_jsxs("button", { type: "button", onClick: () => onPick(p.text), className: "group flex min-w-0 items-start gap-3 rounded-[14px] border border-line bg-surface p-3.5 text-left transition-colors hover:border-line-strong hover:bg-raised", children: [_jsx("span", { className: "grid size-8 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-ink", children: _jsx(Icon, { name: p.icon, size: 16 }) }), _jsxs("span", { className: "min-w-0", children: [_jsx("span", { className: "block text-[11px] font-semibold tracking-[0.06em] text-muted uppercase", children: p.kind }), _jsx("span", { className: "mt-0.5 block text-[14px] leading-snug text-ink", children: p.text })] })] }, p.text))) })] }));
}
