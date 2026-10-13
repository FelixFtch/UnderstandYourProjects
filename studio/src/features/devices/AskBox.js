import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useState } from "react";
import { Icon } from "../../design/icons";
import { Markdown } from "../../design/Markdown";
import { Button, Chip, ErrorState, inputClass, SkeletonText } from "../../design/primitives";
import { devicesData } from "./data";
const CONFIDENCE = {
    high: { tone: "ok", label: "high confidence" },
    medium: { tone: "info", label: "medium confidence" },
    low: { tone: "warn", label: "low confidence" },
    none: { tone: "neutral", label: "no supporting knowledge" },
    unavailable: { tone: "err", label: "knowledge unavailable" },
};
const SUGGESTIONS = ["What changed this week?", "Where is the entry point?", "What is still unfinished?"];
export function AskBox({ projectId, name }) {
    const [q, setQ] = useState("");
    const [turns, setTurns] = useState([]);
    const [busy, setBusy] = useState(false);
    async function ask(question) {
        const text = question.trim();
        if (!text || busy)
            return;
        setBusy(true);
        setQ("");
        setTurns((t) => [...t, { q: text }]);
        try {
            const a = await devicesData.ask(projectId, text);
            setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, a } : x)));
        }
        catch (error) {
            setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error } : x)));
        }
        finally {
            setBusy(false);
        }
    }
    const submit = (e) => { e.preventDefault(); void ask(q); };
    return (_jsxs("div", { children: [turns.length ? (_jsx("ol", { className: "mb-4 space-y-4", children: turns.map((t, i) => (_jsxs("li", { className: "min-w-0", children: [_jsxs("div", { className: "flex items-start gap-2 text-[13.5px] font-medium text-ink", children: [_jsx(Icon, { name: "search", size: 14, className: "mt-[3px] shrink-0 text-muted" }), _jsx("span", { className: "min-w-0 break-words", children: t.q })] }), _jsx("div", { className: "mt-1.5 pl-[22px]", children: t.a ? (_jsxs(_Fragment, { children: [_jsx(Markdown, { text: t.a.answer || "_No answer._", className: "text-[14px] text-ink-2" }), _jsxs("div", { className: "mt-2 flex flex-wrap items-center gap-1.5", children: [_jsx(Chip, { tone: CONFIDENCE[t.a.confidence]?.tone ?? "neutral", children: CONFIDENCE[t.a.confidence]?.label ?? t.a.confidence }), t.a.sources.map((s) => _jsx(Chip, { icon: "file", mono: true, title: s.file, className: "max-w-[240px]", children: s.file }, s.file))] })] })) : t.error ? (_jsx(ErrorState, { compact: true, error: t.error, service: "Project knowledge (UYP)", onRetry: () => { setTurns((x) => x.filter((_, j) => j !== i)); void ask(t.q); } })) : (_jsxs("div", { children: [_jsxs("div", { className: "mb-2 text-[12.5px] text-muted", children: ["Reading what Jarvis knows about ", name, "\u2026"] }), _jsx(SkeletonText, { lines: 3 })] })) })] }, i))) })) : null, _jsxs("form", { onSubmit: submit, className: "flex gap-2", children: [_jsxs("label", { htmlFor: `ask-${projectId}`, className: "sr-only", children: ["Ask about ", name] }), _jsx("input", { id: `ask-${projectId}`, value: q, onChange: (e) => setQ(e.target.value), placeholder: `Ask about ${name}…`, className: inputClass, autoComplete: "off" }), _jsx(Button, { type: "submit", variant: "primary", disabled: !q.trim(), loading: busy, children: "Ask" })] }), !turns.length ? (_jsx("div", { className: "mt-2.5 flex flex-wrap gap-1.5", children: SUGGESTIONS.map((s) => _jsx(Chip, { onClick: () => void ask(s), children: s }, s)) })) : null] }));
}
