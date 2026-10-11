// Center pane: transcript of a direct/group thread with paging, 5 s polling, delivery status and composer.
import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Contact, Me, Message, SendResult, ShareCardItem, Thread } from "../../api/contracts";
import { agentsApi } from "./adapter";
import { authorRole, clockTime, dayLabel, handoffOrigin, hueFor, mergeMessages } from "./logic";
import { Avatar, Icon, Spinner, StatusBadge } from "./ui";

const PAGE = 50;
const POLL_MS = 5000;

type Delivery = SendResult["delivery"];
interface LocalMeta { error?: string }

function errText(e: unknown): string { return e instanceof Error ? e.message : String(e); }

const STATUS_UI: Record<Message["status"], { icon: string; label: string }> = {
  pending: { icon: "clock", label: "Sending…" },
  sent: { icon: "check", label: "Sent" },
  delivered: { icon: "checks", label: "Delivered" },
  failed: { icon: "alert", label: "Not delivered" },
};

export function ThreadPane({ threadId, thread, me, contacts, cardItems, onActivity, onBack, onOpenCard, onDelete, navigate }: {
  threadId: string;
  thread: Thread | undefined;
  me: Me | null;
  contacts: Contact[];
  cardItems: ShareCardItem[] | null;
  onActivity: (threadId: string, last: Message) => void;
  onBack: () => void;
  onOpenCard: () => void;
  onDelete: () => void;
  navigate: (hash: string) => void;
}) {
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [deliveries, setDeliveries] = useState<Record<string, Delivery>>({});
  const [localMeta, setLocalMeta] = useState<Record<string, LocalMeta>>({});
  const [newBelow, setNewBelow] = useState(0);

  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const prependRef = useRef<{ height: number; top: number } | null>(null);
  const seenRef = useRef<Set<string>>(new Set());
  const onActivityRef = useRef(onActivity);
  onActivityRef.current = onActivity;

  const meId = me?.member_id;
  const contactById = useMemo(() => new Map(contacts.map((c) => [c.contact_id, c])), [contacts]);
  const itemLabel = useMemo(() => new Map((cardItems ?? []).map((i) => [i.item_id, i.label])), [cardItems]);
  const agents = (thread?.participants ?? []).filter((p) => p.kind === "agent");
  const directContact = thread?.kind === "direct" && agents[0] ? contactById.get(agents[0].id) : undefined;
  const allBlocked = agents.length > 0 && agents.every((p) => contactById.get(p.id)?.status === "blocked");
  const sharedCount = (cardItems ?? []).filter((i) => i.enabled && !i.locked).length;

  const absorb = useCallback((incoming: Message[]) => {
    const fresh = mergeMessages([], incoming.filter((m) => !seenRef.current.has(m.message_id)));
    fresh.forEach((m) => seenRef.current.add(m.message_id));
    setMessages((prev) => mergeMessages(prev ?? [], incoming));
    if (fresh.length) {
      if (!stickRef.current) setNewBelow((n) => n + fresh.length);
      onActivityRef.current(threadId, fresh[fresh.length - 1]);
    }
  }, [threadId]);

  // Initial page.
  useEffect(() => {
    let alive = true;
    seenRef.current = new Set();
    agentsApi.messages(threadId, { limit: PAGE })
      .then((r) => {
        if (!alive) return;
        r.messages.forEach((m) => seenRef.current.add(m.message_id));
        setMessages(mergeMessages([], r.messages));
        setHasMore(r.has_more);
      })
      .catch((e) => {
        if (!alive) return;
        if (e && typeof e === "object" && "status" in e && (e as { status: number }).status === 404) setNotFound(true);
        else setLoadError(errText(e));
      });
    return () => { alive = false; };
  }, [threadId]);

  // Poll for new messages every 5 s while the thread is open and the tab is visible.
  useEffect(() => {
    if (notFound) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      agentsApi.messages(threadId, { limit: PAGE }).then((r) => absorb(r.messages)).catch(() => { /* transient; next tick retries */ });
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [threadId, notFound, absorb]);

  // Keep the viewport pinned: restore offset after prepending, stick to bottom otherwise.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (prependRef.current) {
      el.scrollTop = el.scrollHeight - prependRef.current.height + prependRef.current.top;
      prependRef.current = null;
    } else if (stickRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (stickRef.current && newBelow) setNewBelow(0);
  }

  function jumpToBottom() {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    stickRef.current = true;
    setNewBelow(0);
  }

  async function loadEarlier() {
    const oldest = messages?.find((m) => !m.message_id.startsWith("local:"));
    if (!oldest || loadingEarlier) return;
    setLoadingEarlier(true);
    try {
      const r = await agentsApi.messages(threadId, { limit: PAGE, before: oldest.message_id });
      const el = scrollRef.current;
      if (el) prependRef.current = { height: el.scrollHeight, top: el.scrollTop };
      r.messages.forEach((m) => seenRef.current.add(m.message_id));
      setMessages((prev) => mergeMessages(prev ?? [], r.messages));
      setHasMore(r.has_more);
    } catch (e) {
      setLoadError(errText(e));
    } finally {
      setLoadingEarlier(false);
    }
  }

  async function send(body: string, replaceId?: string) {
    const trimmed = body.trim();
    if (!trimmed || sending) return;
    const localId = "local:" + Math.random().toString(36).slice(2, 10);
    const local: Message = {
      message_id: localId, thread_id: threadId, text: trimmed, created_at: new Date().toISOString(), status: "pending",
      author: { kind: "member", id: meId ?? "me", display: me?.display_name ?? "Me" }, meta: {},
    };
    setSending(true);
    stickRef.current = true;
    setMessages((prev) => [...(prev ?? []).filter((m) => m.message_id !== replaceId), local]);
    if (!replaceId) setText("");
    try {
      const r = await agentsApi.sendMessage(threadId, trimmed);
      [r.message, ...r.replies].forEach((m) => seenRef.current.add(m.message_id));
      setMessages((prev) => mergeMessages((prev ?? []).filter((m) => m.message_id !== localId), [r.message, ...r.replies]));
      setDeliveries((d) => ({ ...d, [r.message.message_id]: r.delivery }));
      const last = r.replies[r.replies.length - 1] ?? r.message;
      onActivityRef.current(threadId, last);
    } catch (e) {
      setMessages((prev) => (prev ?? []).map((m) => (m.message_id === localId ? { ...m, status: "failed" } : m)));
      setLocalMeta((lm) => ({ ...lm, [localId]: { error: errText(e) } }));
    } finally {
      setSending(false);
    }
  }

  const origin = messages ? handoffOrigin(messages) : null;
  const title = thread?.title ?? (notFound ? "Chat not found" : "Loading…");
  const subtitle = thread?.kind === "group"
    ? agents.map((p) => p.display).join(", ")
    : directContact ? (directContact.number ?? directContact.urn) : "";

  return (
    <div className="ag-thread">
      <header className="ag-pane-head">
        <button type="button" className="ag-iconbtn ag-back" aria-label="Back to chats" onClick={onBack}><Icon name="back" /></button>
        <Avatar id={thread?.kind === "group" ? threadId : agents[0]?.id ?? threadId} name={title} kind={thread?.kind === "group" ? "group" : "agent"} size={34} />
        <div className="min-w-0 flex-1">
          <h2 className="ag-head-title ag-truncate">{title}</h2>
          <div className="ag-sub ag-truncate flex items-center gap-2">
            {directContact ? <StatusBadge status={directContact.status} /> : null}
            {thread?.kind === "group" ? <span className="ag-tag">Group · {agents.length}</span> : null}
            <span className="ag-truncate ag-mono">{subtitle}</span>
          </div>
        </div>
        <button type="button" className="ag-btn ag-btn-sm ag-only-narrow" onClick={onOpenCard} aria-label="Open share card">
          <Icon name="card" size={14} /> {cardItems ? sharedCount : "…"}
        </button>
        {thread ? <button type="button" className="ag-iconbtn" aria-label="Delete chat" title="Delete chat" onClick={onDelete}><Icon name="trash" /></button> : null}
      </header>

      {origin ? (
        <div className="ag-handoff" role="note">
          <Icon name="spark" />
          <div className="min-w-0 flex-1">
            <b>Started from a Jarvis handoff.</b>{" "}
            <span className="ag-sub">Your Jarvis asked on your behalf: “{origin.text.length > 110 ? origin.text.slice(0, 110) + "…" : origin.text}”</span>
          </div>
          <button type="button" className="ag-btn ag-btn-sm" onClick={() => navigate("#/jarvis")}>Open Jarvis chat</button>
        </div>
      ) : null}

      <div className="ag-transcript" ref={scrollRef} onScroll={onScroll} aria-live="polite" aria-busy={!messages}>
        {notFound ? (
          <div className="ag-center-note ag-tall"><Icon name="info" /> This chat no longer exists. <button type="button" className="ag-link" onClick={onBack}>Back to chats</button></div>
        ) : null}
        {loadError ? <p className="ag-alert ag-alert-error ag-m" role="alert"><Icon name="alert" /> {loadError}</p> : null}
        {!messages && !notFound && !loadError ? <div className="ag-center-note ag-tall"><Spinner /> Loading messages…</div> : null}
        {hasMore ? (
          <div className="ag-earlier">
            <button type="button" className="ag-btn ag-btn-sm" disabled={loadingEarlier} onClick={loadEarlier}>
              {loadingEarlier ? "Loading…" : "Load earlier messages"}
            </button>
          </div>
        ) : messages && messages.length ? <div className="ag-earlier ag-sub">Beginning of the conversation</div> : null}
        {messages && messages.length === 0 ? (
          <div className="ag-center-note ag-tall">
            <Icon name="chat" size={22} />
            <span>No messages yet. Say hello — Jarvis will attach only the items enabled on this chat's share card.</span>
          </div>
        ) : null}
        {messages?.map((m, i) => {
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
          return (
            <Fragment key={m.message_id}>
              {newDay ? <div className="ag-day"><span>{dayLabel(m.created_at)}</span></div> : null}
              <div className={`ag-msg ag-msg-${role}${grouped ? " is-grouped" : ""}${mine ? " is-mine" : ""}`}>
                {!mine ? (grouped ? <span className="ag-msg-gutter" /> : <Avatar id={m.author.id} name={m.author.display} kind={role === "member" ? "member" : "agent"} size={28} />) : null}
                <div className="ag-msg-col">
                  {!grouped ? (
                    <div className="ag-msg-author" style={role === "agent" || role === "member" ? { ["--ag-hue" as string]: String(hueFor(m.author.id)) } : undefined}>
                      {role === "me" ? "You" : role === "my-jarvis" ? <><Icon name="spark" size={12} /> {m.author.display || "Your Jarvis"} · on your behalf</> : m.author.display}
                    </div>
                  ) : null}
                  <div className="ag-bubble">{m.text}</div>
                  <div className="ag-msg-meta">
                    <span title={new Date(m.created_at).toLocaleString()}>{clockTime(m.created_at)}</span>
                    {mine ? (
                      <span className={`ag-msg-status is-${m.status}`}><Icon name={status.icon} size={13} /> {status.label}</span>
                    ) : null}
                    {mine && m.status === "failed" ? (
                      <button type="button" className="ag-link" disabled={sending} onClick={() => send(m.text, m.message_id.startsWith("local:") ? m.message_id : undefined)}>Retry</button>
                    ) : null}
                  </div>
                  {local?.error ? <div className="ag-msg-err">{local.error}</div> : null}
                  {showDeliveryRows ? (
                    <ul className="ag-delivery" aria-label="Delivery per contact">
                      {delivery.map((d) => (
                        <li key={d.contact_id} className={d.ok ? "is-ok" : "is-fail"}>
                          <Icon name={d.ok ? "check" : "alert"} size={12} />
                          <span className="ag-truncate">{contactById.get(d.contact_id)?.display_name ?? agents.find((p) => p.id === d.contact_id)?.display ?? d.contact_id}</span>
                          <span className="ag-delivery-state">{d.ok ? "delivered" : `failed${d.error ? ` · ${d.error}` : ""}`}</span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {mine && shared.length ? <div className="ag-shared"><Icon name="card" size={12} /> Shared: {shared.join(", ")}</div> : null}
                </div>
              </div>
            </Fragment>
          );
        })}
      </div>

      {newBelow ? (
        <button type="button" className="ag-newbelow" onClick={jumpToBottom}>{newBelow} new message{newBelow > 1 ? "s" : ""} ↓</button>
      ) : null}

      <form className="ag-composer" onSubmit={(e) => { e.preventDefault(); void send(text); }}>
        {allBlocked ? (
          <p className="ag-sub ag-composer-note"><Icon name="ban" size={13} /> You blocked {agents.length > 1 ? "everyone in this chat" : "this contact"}. Unblock to send messages.</p>
        ) : (
          <p className="ag-sub ag-composer-note">
            <Icon name="card" size={13} /> Jarvis attaches {cardItems ? <b>{sharedCount} share-card item{sharedCount === 1 ? "" : "s"}</b> : "your share card"} to each message.{" "}
            <button type="button" className="ag-link ag-only-narrow" onClick={onOpenCard}>Review</button>
          </p>
        )}
        <div className="ag-composer-row">
          <textarea
            className="ag-input ag-composer-input"
            rows={Math.min(6, Math.max(1, text.split("\n").length))}
            value={text}
            disabled={allBlocked || notFound}
            placeholder={thread ? `Message ${thread.title}…` : "Message…"}
            aria-label="Message"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(text); }
            }}
          />
          <button type="submit" className="ag-btn ag-btn-primary ag-send" disabled={!text.trim() || sending || allBlocked || notFound} aria-label="Send">
            {sending ? <Spinner label="Sending" /> : <Icon name="send" />}
          </button>
        </div>
      </form>
    </div>
  );
}
