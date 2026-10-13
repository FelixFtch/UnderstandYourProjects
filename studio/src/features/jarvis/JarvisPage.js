import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// Jarvis — the primary 1:1 chat. Dark stage transcript + docked composer.
import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMe } from "../../app/session";
import { dayDiff } from "../../design/format";
import { Icon } from "../../design/icons";
import { Button, ErrorState, Skeleton, Spinner, StatusDot } from "../../design/primitives";
import { useChat } from "./chatStore";
import { Composer } from "./Composer";
import { DaySeparator, JarvisReply, MeBubble } from "./Reply";
import { SuggestedPrompts } from "./SuggestedPrompts";
export default function JarvisPage(_props) {
    const me = useMe();
    const bubbles = useChat((s) => s.bubbles);
    const history = useChat((s) => s.history);
    const historyError = useChat((s) => s.historyError);
    const hasMore = useChat((s) => s.hasMore);
    const loadingEarlier = useChat((s) => s.loadingEarlier);
    const streaming = useChat((s) => s.streaming);
    const draft = useChat((s) => s.draft);
    const spec = useChat((s) => s.spec);
    const { setDraft, loadHistory, loadEarlier, loadSpec, send, stop, retry } = useChat.getState();
    useEffect(() => {
        void loadHistory();
        void loadSpec();
    }, [loadHistory, loadSpec]);
    // ── scrolling: stick to the bottom unless the reader scrolled up ──────────
    const scroller = useRef(null);
    const content = useRef(null);
    const stick = useRef(true);
    const [away, setAway] = useState(false);
    const anchor = useRef(null);
    const toBottom = useCallback((smooth = false) => {
        const el = scroller.current;
        if (!el)
            return;
        el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
        stick.current = true;
        setAway(false);
    }, []);
    const lastTop = useRef(0);
    const onScroll = () => {
        const el = scroller.current;
        if (!el)
            return;
        const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
        // Only an upward scroll by the reader releases the stick. Scroll events are async, so
        // content that grew again before the event fired must not count as "scrolled away".
        const up = el.scrollTop < lastTop.current - 1;
        lastTop.current = el.scrollTop;
        if (dist < 72) {
            stick.current = true;
            setAway(false);
        }
        else if (up)
            stick.current = false;
    };
    useEffect(() => {
        const el = content.current;
        if (!el || typeof ResizeObserver === "undefined")
            return;
        const ro = new ResizeObserver(() => {
            const sc = scroller.current;
            if (!sc)
                return;
            if (anchor.current) {
                // keep the reader's place after prepending older messages
                sc.scrollTop = sc.scrollHeight - anchor.current.height + anchor.current.top;
                anchor.current = null;
                return;
            }
            if (stick.current)
                sc.scrollTop = sc.scrollHeight;
            else
                setAway(true);
        });
        ro.observe(el);
        return () => ro.disconnect();
    }, []);
    useLayoutEffect(() => {
        if (stick.current && scroller.current)
            scroller.current.scrollTop = scroller.current.scrollHeight;
    }, [bubbles.length, history]);
    const sendText = (text) => {
        stick.current = true;
        setAway(false);
        void send(text);
        requestAnimationFrame(() => toBottom());
    };
    const earlier = () => {
        const sc = scroller.current;
        if (sc)
            anchor.current = { height: sc.scrollHeight, top: sc.scrollTop };
        void loadEarlier();
    };
    const lastJarvis = [...bubbles].reverse().find((b) => b.role === "jarvis");
    const empty = history === "ready" && bubbles.length === 0;
    return (_jsx("div", { className: "flex h-full min-h-0 flex-col sm:p-3 lg:p-4", children: _jsxs("section", { className: "j-stage relative flex min-h-0 flex-1 flex-col overflow-hidden border-line sm:rounded-card sm:border", "aria-label": "Chat with Jarvis", children: [_jsxs("header", { className: "flex shrink-0 items-center gap-3 border-b border-line px-4 py-2.5 sm:px-5", children: [_jsxs("div", { className: "flex min-w-0 flex-1 items-center gap-2.5", children: [_jsx("span", { className: "grid size-7 shrink-0 place-items-center rounded-full border border-accent/40 font-serif text-[14px] text-accent-ink italic", children: "J" }), _jsxs("div", { className: "min-w-0", children: [_jsx("div", { className: "truncate text-[14px] font-medium text-ink", children: me?.jarvis.display_name ?? "Jarvis" }), _jsxs("div", { className: "flex items-center gap-1.5 text-[11.5px] text-muted", children: [_jsx(StatusDot, { tone: streaming ? "accent" : history === "error" ? "err" : "ok", pulse: streaming }), streaming ? "Working on it" : history === "error" ? "History unavailable" : "Ready", me ? _jsxs("span", { className: "hidden font-mono text-faint sm:inline", children: ["\u00B7 ", me.jarvis.number] }) : null] })] })] }), _jsxs("a", { href: "#/flow", className: "flex shrink-0 items-center gap-1.5 rounded-control px-2 py-1 text-[12.5px] text-muted hover:bg-surface hover:text-ink", children: [_jsx(Icon, { name: "flow", size: 15 }), " ", _jsx("span", { className: "hidden sm:inline", children: "See the flow" })] })] }), _jsx("div", { ref: scroller, onScroll: onScroll, className: "relative min-h-0 flex-1 overflow-y-auto overscroll-contain", children: _jsxs("div", { ref: content, className: "mx-auto flex min-h-full w-full max-w-[760px] flex-col gap-6 px-4 py-6 sm:px-6", children: [history === "loading" && bubbles.length === 0 ? _jsx(TranscriptSkeleton, {}) : null, history === "error" ? (_jsx(ErrorState, { compact: true, error: historyError, service: "Studio threads", title: "Couldn't load your earlier messages", onRetry: () => void loadHistory(true) })) : null, hasMore ? (_jsx("div", { className: "flex justify-center", children: _jsxs(Button, { size: "sm", variant: "ghost", onClick: earlier, disabled: loadingEarlier, children: [loadingEarlier ? _jsx(Spinner, { size: 13 }) : _jsx(Icon, { name: "arrowUp", size: 14 }), " Earlier messages"] }) })) : null, empty ? _jsx(SuggestedPrompts, { name: me?.display_name ?? null, onPick: sendText }) : null, bubbles.map((b, i) => {
                                const prev = bubbles[i - 1];
                                const newDay = !prev || dayDiff(new Date(prev.createdAt), new Date(b.createdAt)) !== 0;
                                return (_jsxs(Fragment, { children: [newDay && !empty ? _jsx(DaySeparator, { iso: b.createdAt }) : null, b.role === "me" ? (_jsx(MeBubble, { bubble: b })) : (_jsx(JarvisReply, { bubble: b, spec: spec, live: streaming && b === lastJarvis && b.status === "streaming", onRetry: () => retry(b.id) }))] }, b.id));
                            })] }) }), away ? (_jsxs("button", { type: "button", onClick: () => toBottom(true), className: "j-rise absolute bottom-[92px] left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-line-strong bg-raised px-3 py-1.5 text-[12.5px] text-ink shadow-pop sm:bottom-[104px]", children: [_jsx(Icon, { name: "arrowDown", size: 14 }), " ", streaming ? "Jarvis is replying" : "Jump to latest"] })) : null, _jsx(Composer, { value: draft, onChange: setDraft, onSend: sendText, onStop: stop, streaming: streaming, autoFocus: true })] }) }));
}
function TranscriptSkeleton() {
    return (_jsxs("div", { className: "space-y-6", "aria-busy": "true", "aria-label": "Loading messages", children: [_jsx("div", { className: "flex justify-end", children: _jsx(Skeleton, { className: "h-9 w-56 rounded-[16px]" }) }), _jsxs("div", { className: "space-y-2 pl-[30px]", children: [_jsx(Skeleton, { className: "h-3.5 w-11/12" }), _jsx(Skeleton, { className: "h-3.5 w-10/12" }), _jsx(Skeleton, { className: "h-3.5 w-7/12" })] }), _jsx("div", { className: "flex justify-end", children: _jsx(Skeleton, { className: "h-9 w-40 rounded-[16px]" }) }), _jsxs("div", { className: "space-y-2 pl-[30px]", children: [_jsx(Skeleton, { className: "h-3.5 w-9/12" }), _jsx(Skeleton, { className: "h-3.5 w-5/12" })] })] }));
}
