import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useLayoutEffect, useRef } from "react";
import { Icon } from "../../design/icons";
import { cx } from "../../design/primitives";
export function Composer({ value, onChange, onSend, onStop, streaming, autoFocus }) {
    const ta = useRef(null);
    useLayoutEffect(() => {
        const el = ta.current;
        if (!el)
            return;
        el.style.height = "auto";
        el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    }, [value]);
    useEffect(() => {
        if (autoFocus && window.matchMedia?.("(pointer: fine)").matches)
            ta.current?.focus();
    }, [autoFocus]);
    const submit = (e) => {
        e?.preventDefault();
        if (streaming || !value.trim())
            return;
        onSend(value);
    };
    const onKeyDown = (e) => {
        // Enter sends; Shift+Enter is a newline; never send mid-IME composition (e.g. pinyin).
        if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
            e.preventDefault();
            submit();
        }
    };
    const canSend = !!value.trim() && !streaming;
    return (_jsx("form", { onSubmit: submit, className: "shrink-0 border-t border-line bg-stage px-3 pt-3 pb-3 sm:px-5", children: _jsxs("div", { className: "mx-auto w-full max-w-[760px]", children: [_jsxs("div", { className: "flex items-end gap-2 rounded-[16px] border border-line-strong bg-surface py-1.5 pr-1.5 pl-3.5 transition-colors focus-within:border-accent/60", children: [_jsx("label", { htmlFor: "jarvis-composer", className: "sr-only", children: "Message Jarvis" }), _jsx("textarea", { id: "jarvis-composer", ref: ta, rows: 1, value: value, onChange: (e) => onChange(e.target.value), onKeyDown: onKeyDown, placeholder: "Message Jarvis\u2026", className: "max-h-[200px] min-h-[36px] min-w-0 flex-1 resize-none bg-transparent py-[7px] text-[15px] leading-[22px] text-ink placeholder:text-faint focus:outline-none" }), streaming ? (_jsx("button", { type: "button", onClick: onStop, className: "grid size-9 shrink-0 place-items-center rounded-full border border-line-strong text-ink hover:bg-raised", "aria-label": "Stop Jarvis", title: "Stop", children: _jsx(Icon, { name: "stop", size: 14, strokeWidth: 2.4 }) })) : (_jsx("button", { type: "submit", disabled: !canSend, className: cx("grid size-9 shrink-0 place-items-center rounded-full transition-colors", canSend ? "bg-accent text-on-accent hover:bg-accent-ink" : "bg-raised text-faint"), "aria-label": "Send", title: "Send (Enter)", children: _jsx(Icon, { name: "arrowUp", size: 17, strokeWidth: 2.1 }) }))] }), _jsxs("div", { className: "mt-1.5 hidden justify-between px-1 text-[11.5px] text-faint sm:flex", children: [_jsx("span", { children: "Enter to send \u00B7 Shift+Enter for a new line" }), _jsx("span", { children: "Studio flow \u00B7 answers show how Jarvis handled them" })] })] }) }));
}
