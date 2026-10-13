import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// Center pane: transcript of a direct/group thread with paging, 5 s polling, delivery status and composer.
import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { agentsApi } from "./adapter";
import { authorRole, clockTime, dayLabel, handoffOrigin, hueFor, mergeMessages } from "./logic";
import { Avatar, Icon, Spinner, StatusBadge } from "./ui";
const PAGE = 50;
const POLL_MS = 5000;
function errText(e) { return e instanceof Error ? e.message : String(e); }
const STATUS_UI = {
    pending: { icon: "clock", label: "Sending…" },
    sent: { icon: "check", label: "Sent" },
    delivered: { icon: "checks", label: "Delivered" },
    failed: { icon: "alert", label: "Not delivered" },
};
export function ThreadPane({ threadId, thread, me, contacts, cardItems, onActivity, onBack, onOpenCard, onDelete, navigate }) {
    const [messages, setMessages] = useState(null);
    const [hasMore, setHasMore] = useState(false);
    const [loadingEarlier, setLoadingEarlier] = useState(false);
    const [loadError, setLoadError] = useState(null);
    const [notFound, setNotFound] = useState(false);
    const [text, setText] = useState("");
    const [sending, setSending] = useState(false);
    const [deliveries, setDeliveries] = useState({});
    const [localMeta, setLocalMeta] = useState({});
    const [newBelow, setNewBelow] = useState(0);
    const scrollRef = useRef(null);
    const stickRef = useRef(true);
    const prependRef = useRef(null);
    const seenRef = useRef(new Set());
    const onActivityRef = useRef(onActivity);
    onActivityRef.current = onActivity;
    const meId = me?.member_id;
    const contactById = useMemo(() => new Map(contacts.map((c) => [c.contact_id, c])), [contacts]);
    const itemLabel = useMemo(() => new Map((cardItems ?? []).map((i) => [i.item_id, i.label])), [cardItems]);
    const agents = (thread?.participants ?? []).filter((p) => p.kind === "agent");
    const directContact = thread?.kind === "direct" && agents[0] ? contactById.get(agents[0].id) : undefined;
    const allBlocked = agents.length > 0 && agents.every((p) => contactById.get(p.id)?.status === "blocked");
    const sharedCount = (cardItems ?? []).filter((i) => i.enabled && !i.locked).length;
    const absorb = useCallback((incoming) => {
        const fresh = mergeMessages([], incoming.filter((m) => !seenRef.current.has(m.message_id)));
        fresh.forEach((m) => seenRef.current.add(m.message_id));
        setMessages((prev) => mergeMessages(prev ?? [], incoming));
        if (fresh.length) {
            if (!stickRef.current)
                setNewBelow((n) => n + fresh.length);
            onActivityRef.current(threadId, fresh[fresh.length - 1]);
        }
    }, [threadId]);
    // Initial page.
    useEffect(() => {
        let alive = true;
        seenRef.current = new Set();
        agentsApi.messages(threadId, { limit: PAGE })
            .then((r) => {
            if (!alive)
                return;
            r.messages.forEach((m) => seenRef.current.add(m.message_id));
            setMessages(mergeMessages([], r.messages));
            setHasMore(r.has_more);
        })
            .catch((e) => {
            if (!alive)
                return;
            if (e && typeof e === "object" && "status" in e && e.status === 404)
                setNotFound(true);
            else
                setLoadError(errText(e));
        });
        return () => { alive = false; };
    }, [threadId]);
    // Poll for new messages every 5 s while the thread is open and the tab is visible.
    useEffect(() => {
        if (notFound)
            return;
        const id = window.setInterval(() => {
            if (document.visibilityState === "hidden")
                return;
            agentsApi.messages(threadId, { limit: PAGE }).then((r) => absorb(r.messages)).catch(() => { });
        }, POLL_MS);
        return () => window.clearInterval(id);
    }, [threadId, notFound, absorb]);
    // Keep the viewport pinned: restore offset after prepending, stick to bottom otherwise.
    useLayoutEffect(() => {
        const el = scrollRef.current;
        if (!el)
            return;
        if (prependRef.current) {
            el.scrollTop = el.scrollHeight - prependRef.current.height + prependRef.current.top;
            prependRef.current = null;
        }
        else if (stickRef.current) {
            el.scrollTop = el.scrollHeight;
        }
    }, [messages]);
    function onScroll() {
        const el = scrollRef.current;
        if (!el)
            return;
        stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        if (stickRef.current && newBelow)
            setNewBelow(0);
    }
    function jumpToBottom() {
        const el = scrollRef.current;
        if (el)
            el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
        stickRef.current = true;
        setNewBelow(0);
    }
    async function loadEarlier() {
        const oldest = messages?.find((m) => !m.message_id.startsWith("local:"));
        if (!oldest || loadingEarlier)
            return;
        setLoadingEarlier(true);
        try {
            const r = await agentsApi.messages(threadId, { limit: PAGE, before: oldest.message_id });
            const el = scrollRef.current;
            if (el)
                prependRef.current = { height: el.scrollHeight, top: el.scrollTop };
            r.messages.forEach((m) => seenRef.current.add(m.message_id));
            setMessages((prev) => mergeMessages(prev ?? [], r.messages));
            setHasMore(r.has_more);
        }
        catch (e) {
            setLoadError(errText(e));
        }
        finally {
            setLoadingEarlier(false);
        }
    }
    async function send(body, replaceId) {
        const trimmed = body.trim();
        if (!trimmed || sending)
            return;
        const localId = "local:" + Math.random().toString(36).slice(2, 10);
        const local = {
            message_id: localId, thread_id: threadId, text: trimmed, created_at: new Date().toISOString(), status: "pending",
            author: { kind: "member", id: meId ?? "me", display: me?.display_name ?? "Me" }, meta: {},
        };
        setSending(true);
        stickRef.current = true;
        setMessages((prev) => [...(prev ?? []).filter((m) => m.message_id !== replaceId), local]);
        if (!replaceId)
            setText("");
        try {
            const r = await agentsApi.sendMessage(threadId, trimmed);
            [r.message, ...r.replies].forEach((m) => seenRef.current.add(m.message_id));
            setMessages((prev) => mergeMessages((prev ?? []).filter((m) => m.message_id !== localId), [r.message, ...r.replies]));
            setDeliveries((d) => ({ ...d, [r.message.message_id]: r.delivery }));
            const last = r.replies[r.replies.length - 1] ?? r.message;
            onActivityRef.current(threadId, last);
        }
        catch (e) {
            setMessages((prev) => (prev ?? []).map((m) => (m.message_id === localId ? { ...m, status: "failed" } : m)));
            setLocalMeta((lm) => ({ ...lm, [localId]: { error: errText(e) } }));
        }
        finally {
            setSending(false);
        }
    }
    const origin = messages ? handoffOrigin(messages) : null;
    const title = thread?.title ?? (notFound ? "Chat not found" : "Loading…");
    const subtitle = thread?.kind === "group"
        ? agents.map((p) => p.display).join(", ")
        : directContact ? (directContact.number ?? directContact.urn) : "";
    return (_jsxs("div", { className: "ag-thread", children: [_jsxs("header", { className: "ag-pane-head", children: [_jsx("button", { type: "button", className: "ag-iconbtn ag-back", "aria-label": "Back to chats", onClick: onBack, children: _jsx(Icon, { name: "back" }) }), _jsx(Avatar, { id: thread?.kind === "group" ? threadId : agents[0]?.id ?? threadId, name: title, kind: thread?.kind === "group" ? "group" : "agent", size: 34 }), _jsxs("div", { className: "min-w-0 flex-1", children: [_jsx("h2", { className: "ag-head-title ag-truncate", children: title }), _jsxs("div", { className: "ag-sub ag-truncate flex items-center gap-2", children: [directContact ? _jsx(StatusBadge, { status: directContact.status }) : null, thread?.kind === "group" ? _jsxs("span", { className: "ag-tag", children: ["Group \u00B7 ", agents.length] }) : null, _jsx("span", { className: "ag-truncate ag-mono", children: subtitle })] })] }), _jsxs("button", { type: "button", className: "ag-btn ag-btn-sm ag-only-narrow", onClick: onOpenCard, "aria-label": "Open share card", children: [_jsx(Icon, { name: "card", size: 14 }), " ", cardItems ? sharedCount : "…"] }), thread ? _jsx("button", { type: "button", className: "ag-iconbtn", "aria-label": "Delete chat", title: "Delete chat", onClick: onDelete, children: _jsx(Icon, { name: "trash" }) }) : null] }), origin ? (_jsxs("div", { className: "ag-handoff", role: "note", children: [_jsx(Icon, { name: "spark" }), _jsxs("div", { className: "min-w-0 flex-1", children: [_jsx("b", { children: "Started from a Jarvis handoff." }), " ", _jsxs("span", { className: "ag-sub", children: ["Your Jarvis asked on your behalf: \u201C", origin.text.length > 110 ? origin.text.slice(0, 110) + "…" : origin.text, "\u201D"] })] }), _jsx("button", { type: "button", className: "ag-btn ag-btn-sm", onClick: () => navigate("#/jarvis"), children: "Open Jarvis chat" })] })) : null, _jsxs("div", { className: "ag-transcript", ref: scrollRef, onScroll: onScroll, "aria-live": "polite", "aria-busy": !messages, children: [notFound ? (_jsxs("div", { className: "ag-center-note ag-tall", children: [_jsx(Icon, { name: "info" }), " This chat no longer exists. ", _jsx("button", { type: "button", className: "ag-link", onClick: onBack, children: "Back to chats" })] })) : null, loadError ? _jsxs("p", { className: "ag-alert ag-alert-error ag-m", role: "alert", children: [_jsx(Icon, { name: "alert" }), " ", loadError] }) : null, !messages && !notFound && !loadError ? _jsxs("div", { className: "ag-center-note ag-tall", children: [_jsx(Spinner, {}), " Loading messages\u2026"] }) : null, hasMore ? (_jsx("div", { className: "ag-earlier", children: _jsx("button", { type: "button", className: "ag-btn ag-btn-sm", disabled: loadingEarlier, onClick: loadEarlier, children: loadingEarlier ? "Loading…" : "Load earlier messages" }) })) : messages && messages.length ? _jsx("div", { className: "ag-earlier ag-sub", children: "Beginning of the conversation" }) : null, messages && messages.length === 0 ? (_jsxs("div", { className: "ag-center-note ag-tall", children: [_jsx(Icon, { name: "chat", size: 22 }), _jsx("span", { children: "No messages yet. Say hello \u2014 Jarvis will attach only the items enabled on this chat's share card." })] })) : null, messages?.map((m, i) => {
                        const prev = messages[i - 1];
                        const role = authorRole(m.author, meId);
                        const newDay = !prev || new Date(prev.created_at).toDateString() !== new Date(m.created_at).toDateString();
                        const grouped = !newDay && prev && prev.author.id === m.author.id && prev.author.kind === m.author.kind
                            && Date.parse(m.created_at) - Date.parse(prev.created_at) < 5 * 60_000;
                        const mine = role === "me" || role === "my-jarvis";
                        const delivery = deliveries[m.message_id];
                        const local = localMeta[m.message_id];
                        const status = STATUS_UI[m.status];
                        const shared = (m.meta?.shared_items ?? []).map((id) => itemLabel.get(id) ?? id);
                        const showDeliveryRows = delivery && (delivery.length > 1 || delivery.some((d) => !d.ok));
                        return (_jsxs(Fragment, { children: [newDay ? _jsx("div", { className: "ag-day", children: _jsx("span", { children: dayLabel(m.created_at) }) }) : null, _jsxs("div", { className: `ag-msg ag-msg-${role}${grouped ? " is-grouped" : ""}${mine ? " is-mine" : ""}`, children: [!mine ? (grouped ? _jsx("span", { className: "ag-msg-gutter" }) : _jsx(Avatar, { id: m.author.id, name: m.author.display, kind: role === "member" ? "member" : "agent", size: 28 })) : null, _jsxs("div", { className: "ag-msg-col", children: [!grouped ? (_jsx("div", { className: "ag-msg-author", style: role === "agent" || role === "member" ? { ["--ag-hue"]: String(hueFor(m.author.id)) } : undefined, children: role === "me" ? "You" : role === "my-jarvis" ? _jsxs(_Fragment, { children: [_jsx(Icon, { name: "spark", size: 12 }), " ", m.author.display || "Your Jarvis", " \u00B7 on your behalf"] }) : m.author.display })) : null, _jsx("div", { className: "ag-bubble", children: m.text }), _jsxs("div", { className: "ag-msg-meta", children: [_jsx("span", { title: new Date(m.created_at).toLocaleString(), children: clockTime(m.created_at) }), mine ? (_jsxs("span", { className: `ag-msg-status is-${m.status}`, children: [_jsx(Icon, { name: status.icon, size: 13 }), " ", status.label] })) : null, mine && m.status === "failed" ? (_jsx("button", { type: "button", className: "ag-link", disabled: sending, onClick: () => send(m.text, m.message_id.startsWith("local:") ? m.message_id : undefined), children: "Retry" })) : null] }), local?.error ? _jsx("div", { className: "ag-msg-err", children: local.error }) : null, showDeliveryRows ? (_jsx("ul", { className: "ag-delivery", "aria-label": "Delivery per contact", children: delivery.map((d) => (_jsxs("li", { className: d.ok ? "is-ok" : "is-fail", children: [_jsx(Icon, { name: d.ok ? "check" : "alert", size: 12 }), _jsx("span", { className: "ag-truncate", children: contactById.get(d.contact_id)?.display_name ?? agents.find((p) => p.id === d.contact_id)?.display ?? d.contact_id }), _jsx("span", { className: "ag-delivery-state", children: d.ok ? "delivered" : `failed${d.error ? ` · ${d.error}` : ""}` })] }, d.contact_id))) })) : null, mine && shared.length ? _jsxs("div", { className: "ag-shared", children: [_jsx(Icon, { name: "card", size: 12 }), " Shared: ", shared.join(", ")] }) : null] })] })] }, m.message_id));
                    })] }), newBelow ? (_jsxs("button", { type: "button", className: "ag-newbelow", onClick: jumpToBottom, children: [newBelow, " new message", newBelow > 1 ? "s" : "", " \u2193"] })) : null, _jsxs("form", { className: "ag-composer", onSubmit: (e) => { e.preventDefault(); void send(text); }, children: [allBlocked ? (_jsxs("p", { className: "ag-sub ag-composer-note", children: [_jsx(Icon, { name: "ban", size: 13 }), " You blocked ", agents.length > 1 ? "everyone in this chat" : "this contact", ". Unblock to send messages."] })) : (_jsxs("p", { className: "ag-sub ag-composer-note", children: [_jsx(Icon, { name: "card", size: 13 }), " Jarvis attaches ", cardItems ? _jsxs("b", { children: [sharedCount, " share-card item", sharedCount === 1 ? "" : "s"] }) : "your share card", " to each message.", " ", _jsx("button", { type: "button", className: "ag-link ag-only-narrow", onClick: onOpenCard, children: "Review" })] })), _jsxs("div", { className: "ag-composer-row", children: [_jsx("textarea", { className: "ag-input ag-composer-input", rows: Math.min(6, Math.max(1, text.split("\n").length)), value: text, disabled: allBlocked || notFound, placeholder: thread ? `Message ${thread.title}…` : "Message…", "aria-label": "Message", onChange: (e) => setText(e.target.value), onKeyDown: (e) => {
                                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                                        e.preventDefault();
                                        void send(text);
                                    }
                                } }), _jsx("button", { type: "submit", className: "ag-btn ag-btn-primary ag-send", disabled: !text.trim() || sending || allBlocked || notFound, "aria-label": "Send", children: sending ? _jsx(Spinner, { label: "Sending" }) : _jsx(Icon, { name: "send" }) })] })] })] }));
}
