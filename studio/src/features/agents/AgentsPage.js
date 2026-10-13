import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// Agents: contacts + chats (left), thread transcript (center), per-thread share card (right).
// Route: #/agents/<thread_id?>. Three panes when the main area is wide enough, otherwise one
// pane at a time with back buttons.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { agentsApi } from "./adapter";
import { ContactsPane } from "./ContactsPane";
import { AddContactDialog, NewGroupDialog } from "./dialogs";
import { meLink, parseThreadId, upsertThread } from "./logic";
import { ShareCardPane, useShareCard } from "./ShareCardPane";
import { ThreadPane } from "./ThreadPane";
import { Avatar, ConfirmDialog, Icon } from "./ui";
import "./agents.css";
const THREADS_POLL_MS = 15000;
/** Three panes need this much room in the main area (and a ≥ 900 px viewport). */
const WIDE_CONTAINER = 760;
const WIDE_VIEWPORT = 900;
function errText(e) { return e instanceof Error ? e.message : String(e); }
function useWideLayout(ref) {
    const [wide, setWide] = useState(true);
    useLayoutEffect(() => {
        const el = ref.current;
        if (!el)
            return;
        const measure = () => setWide(el.clientWidth >= WIDE_CONTAINER && window.innerWidth >= WIDE_VIEWPORT);
        measure();
        const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
        ro?.observe(el);
        window.addEventListener("resize", measure);
        return () => { ro?.disconnect(); window.removeEventListener("resize", measure); };
    }, [ref]);
    return wide;
}
export default function AgentsPage({ param, navigate }) {
    const threadId = parseThreadId(param);
    const rootRef = useRef(null);
    const wide = useWideLayout(rootRef);
    const [me, setMe] = useState(null);
    const [contacts, setContacts] = useState(null);
    const [threads, setThreads] = useState(null);
    const [listError, setListError] = useState(null);
    const [busy, setBusy] = useState(new Set());
    const [dialog, setDialog] = useState(null);
    const [confirm, setConfirm] = useState(null);
    const [confirmBusy, setConfirmBusy] = useState(false);
    const [notice, setNotice] = useState(null);
    const [panel, setPanel] = useState("thread");
    const shareCard = useShareCard(threadId);
    useEffect(() => { setPanel("thread"); }, [threadId]);
    useEffect(() => {
        if (!notice)
            return;
        const t = window.setTimeout(() => setNotice(null), notice.kind === "error" ? 8000 : 4000);
        return () => window.clearTimeout(t);
    }, [notice]);
    const loadLists = useCallback(async () => {
        setListError(null);
        const [c, t] = await Promise.allSettled([agentsApi.contacts(), agentsApi.threads()]);
        if (c.status === "fulfilled")
            setContacts(c.value.contacts);
        if (t.status === "fulfilled")
            setThreads(t.value.threads);
        const failed = [c, t].find((r) => r.status === "rejected");
        if (failed)
            setListError(`Couldn't load contacts and chats: ${errText(failed.reason)}`);
    }, []);
    useEffect(() => {
        agentsApi.me().then(setMe).catch(() => { });
        void loadLists();
        const id = window.setInterval(() => {
            if (document.visibilityState === "hidden")
                return;
            agentsApi.threads().then((r) => setThreads(r.threads)).catch(() => { });
        }, THREADS_POLL_MS);
        return () => window.clearInterval(id);
    }, [loadLists]);
    const replaceContact = (c) => setContacts((list) => (list ?? []).map((x) => (x.contact_id === c.contact_id ? c : x)));
    async function withBusy(id, fn) {
        setBusy((b) => new Set(b).add(id));
        try {
            await fn();
        }
        catch (e) {
            setNotice({ kind: "error", text: errText(e) });
        }
        finally {
            setBusy((b) => { const n = new Set(b); n.delete(id); return n; });
        }
    }
    function openThread(t) {
        setThreads((list) => upsertThread(list ?? [], { ...t, unread: 0 }));
        navigate(`#/agents/${encodeURIComponent(t.thread_id)}`);
    }
    const actions = {
        message: (c) => withBusy(c.contact_id, async () => {
            const t = await agentsApi.createThread("direct", [c.contact_id]);
            openThread(t);
        }),
        invite: (c) => withBusy(c.contact_id, async () => {
            const r = await agentsApi.inviteContact(c.contact_id);
            if (r.delivery.ok) {
                replaceContact({ ...c, status: "invited" });
                setNotice({ kind: "ok", text: `Invite sent to ${c.display_name}.` });
            }
            else {
                setNotice({ kind: "error", text: `Invite to ${c.display_name} was not delivered: ${r.delivery.error ?? "unknown error"}` });
            }
            agentsApi.contacts().then((x) => setContacts(x.contacts)).catch(() => { });
        }),
        block: (c) => setConfirm({
            title: `Block ${c.display_name}?`,
            body: "Jarvis will stop sending to and accepting messages from this agent. You can unblock later.",
            confirmLabel: "Block", danger: true,
            run: async () => replaceContact(await agentsApi.updateContact(c.contact_id, { status: "blocked" })),
        }),
        unblock: (c) => withBusy(c.contact_id, async () => {
            replaceContact(await agentsApi.updateContact(c.contact_id, { status: "verified" }));
            setNotice({ kind: "ok", text: `${c.display_name} unblocked.` });
        }),
        accept: (c) => withBusy(c.contact_id, async () => {
            if (c.invite?.invite_code) {
                // Real round-trip: verifies them and sends our contact.accept card back.
                const res = await agentsApi.acceptContact(c.invite.invite_code, c.invite.card);
                replaceContact(res.contact);
                setNotice(res.delivery && !res.delivery.ok
                    ? { kind: "error", text: `${c.display_name} is verified, but the acceptance did not reach their Jarvis: ${res.delivery.error ?? "unknown error"}.` }
                    : { kind: "ok", text: `${c.display_name} is now a verified contact.` });
            }
            else {
                replaceContact(await agentsApi.updateContact(c.contact_id, { status: "verified" }));
                setNotice({ kind: "ok", text: `${c.display_name} is now a verified contact.` });
            }
        }),
        decline: (c) => setConfirm({
            title: `Decline ${c.display_name}?`,
            body: "Their invite is discarded and they are removed from your contacts.",
            confirmLabel: "Decline", danger: true,
            run: async () => {
                await agentsApi.deleteContact(c.contact_id);
                setContacts((list) => (list ?? []).filter((x) => x.contact_id !== c.contact_id));
            },
        }),
        remove: (c) => setConfirm({
            title: `Remove ${c.display_name}?`,
            body: "They are removed from your contacts. Existing chats keep their history; you'd need to add and verify them again to message them.",
            confirmLabel: "Remove contact", danger: true,
            run: async () => {
                await agentsApi.deleteContact(c.contact_id);
                setContacts((list) => (list ?? []).filter((x) => x.contact_id !== c.contact_id));
                setNotice({ kind: "ok", text: `${c.display_name} removed.` });
            },
        }),
        addContact: () => setDialog("add"),
        newGroup: () => setDialog("group"),
        openThread,
    };
    const onActivity = useCallback((id, last) => {
        setThreads((list) => (list ?? []).map((t) => (t.thread_id === id
            ? { ...t, last_message_at: last.created_at, last_preview: last.text.slice(0, 120), unread: 0 }
            : t)));
    }, []);
    async function runConfirm() {
        if (!confirm)
            return;
        setConfirmBusy(true);
        try {
            await confirm.run();
            setConfirm(null);
        }
        catch (e) {
            setNotice({ kind: "error", text: errText(e) });
            setConfirm(null);
        }
        finally {
            setConfirmBusy(false);
        }
    }
    const thread = threads?.find((t) => t.thread_id === threadId);
    const view = !threadId ? "list" : panel;
    function deleteThread() {
        if (!threadId || !thread)
            return;
        setConfirm({
            title: `Delete “${thread.title}”?`,
            body: "The conversation history and its share card are deleted from your hub. Contacts are kept.",
            confirmLabel: "Delete chat", danger: true,
            run: async () => {
                await agentsApi.deleteThread(threadId);
                setThreads((list) => (list ?? []).filter((t) => t.thread_id !== threadId));
                navigate("#/agents");
            },
        });
    }
    return (_jsxs("div", { className: "ag-root", ref: rootRef, children: [_jsxs("div", { className: "ag-layout", "data-layout": wide ? "three" : "one", "data-view": view, children: [_jsxs("section", { className: "ag-pane ag-left", "aria-label": "Contacts and chats", children: [_jsxs("header", { className: "ag-pane-head ag-left-head", title: me?.jarvis.urn ?? undefined, children: [_jsx(Avatar, { id: me?.jarvis.node_id ?? "me", name: me?.jarvis.display_name ?? "My Jarvis", kind: "jarvis", size: 34 }), _jsxs("div", { className: "min-w-0 flex-1", children: [_jsx("h2", { className: "ag-head-title ag-truncate", children: me?.jarvis.display_name ?? "Your Jarvis" }), _jsxs("div", { className: "ag-sub ag-truncate", children: ["Share your number: ", _jsx("b", { className: "ag-mono ag-mynum", children: me?.jarvis.number ?? "…" })] })] })] }), _jsx(ContactsPane, { contacts: contacts, threads: threads, activeThreadId: threadId, busy: busy, actions: actions, error: listError, onRetry: () => void loadLists() })] }), _jsx("section", { className: "ag-pane ag-center", "aria-label": "Conversation", children: threadId === "jarvis" ? (_jsxs("div", { className: "ag-center-note ag-tall", children: [_jsx(Icon, { name: "spark", size: 22 }), _jsx("span", { children: "Your 1:1 chat with Jarvis lives in the Jarvis tab." }), _jsx("button", { type: "button", className: "ag-btn ag-btn-primary", onClick: () => navigate("#/jarvis"), children: "Open Jarvis" })] })) : threadId ? (_jsx(ThreadPane, { threadId: threadId, thread: thread, me: me, contacts: contacts ?? [], cardItems: shareCard.card?.items ?? null, onActivity: onActivity, onBack: () => navigate("#/agents"), onOpenCard: () => setPanel("card"), onDelete: deleteThread, navigate: navigate }, threadId)) : (_jsxs("div", { className: "ag-center-note ag-tall ag-welcome", children: [_jsx(Icon, { name: "chat", size: 26 }), _jsx("h2", { children: "Pick a chat or message a contact" }), _jsx("p", { children: "Every message to another agent carries only what this chat's share card allows. Your Jarvis can also open chats for you when you ask it to check with someone." }), _jsxs("div", { className: "ag-actions justify-center", children: [_jsxs("button", { type: "button", className: "ag-btn", onClick: () => setDialog("add"), children: [_jsx(Icon, { name: "plus", size: 14 }), " Add contact"] }), _jsxs("button", { type: "button", className: "ag-btn", onClick: () => setDialog("group"), children: [_jsx(Icon, { name: "users", size: 14 }), " New group"] })] })] })) }), _jsx("aside", { className: "ag-pane ag-right", "aria-label": "Share card", children: threadId && threadId !== "jarvis" ? (_jsx(ShareCardPane, { state: shareCard, thread: thread, me: me, onBack: () => setPanel("thread") })) : (_jsxs("div", { className: "ag-card", children: [_jsx("header", { className: "ag-pane-head", children: _jsxs("div", { className: "min-w-0 flex-1", children: [_jsx("h2", { className: "ag-head-title", children: "Share card" }), _jsx("div", { className: "ag-sub", children: "Per chat" })] }) }), _jsx("div", { className: "ag-scroll ag-card-scroll", children: _jsxs("p", { className: "ag-card-intro", children: [_jsx(Icon, { name: "info", size: 14 }), _jsxs("span", { children: ["Open a chat to see what Jarvis may share there. Defaults come from your privacy rings in ", _jsx("a", { className: "ag-link", href: meLink(me), children: "Data \u2192 Privacy" }), "."] })] }) })] })) })] }), dialog === "add" ? (_jsx(AddContactDialog, { onClose: () => setDialog(null), onAdded: (c, invite) => {
                    setContacts((list) => [...(list ?? []).filter((x) => x.contact_id !== c.contact_id), c]);
                    setDialog(null);
                    setNotice(invite && !invite.sent
                        ? { kind: "error", text: `${c.display_name} added, but the invite was not delivered: ${invite.error ?? "unknown error"}` }
                        : { kind: "ok", text: `${c.display_name} added${invite?.sent ? " and invited" : ""}.` });
                } })) : null, dialog === "group" ? (_jsx(NewGroupDialog, { contacts: contacts ?? [], onClose: () => setDialog(null), onCreate: async (ids, title) => {
                    const t = await agentsApi.createThread("group", ids, title);
                    setDialog(null);
                    openThread(t);
                } })) : null, confirm ? (_jsx(ConfirmDialog, { title: confirm.title, body: confirm.body, confirmLabel: confirm.confirmLabel, danger: confirm.danger, busy: confirmBusy, onConfirm: () => void runConfirm(), onCancel: () => setConfirm(null) })) : null, notice ? (_jsxs("div", { className: `ag-toast is-${notice.kind}`, role: notice.kind === "error" ? "alert" : "status", children: [_jsx(Icon, { name: notice.kind === "error" ? "alert" : "check" }), _jsx("span", { className: "min-w-0 flex-1", children: notice.text }), _jsx("button", { type: "button", className: "ag-iconbtn ag-iconbtn-sm", "aria-label": "Dismiss", onClick: () => setNotice(null), children: _jsx(Icon, { name: "x", size: 14 }) })] })) : null] }));
}
