// Left pane: my Jarvis card, pending invites, contacts (with actions) and the chats list.
import { useState } from "react";
import type { Contact, Thread } from "../../api/contracts";
import { STATUS_HINT, relativeTime, sortChats, splitContacts } from "./logic";
import { Avatar, Icon, Spinner, StatusBadge } from "./ui";

export interface ContactActions {
  message(c: Contact): void;
  invite(c: Contact): void;
  block(c: Contact): void;
  unblock(c: Contact): void;
  remove(c: Contact): void;
  accept(c: Contact): void;
  decline(c: Contact): void;
  addContact(): void;
  newGroup(): void;
  openThread(t: Thread): void;
}

const TRANSPORT: Record<string, string> = { town: "NANDA Town", a2a: "A2A", "contracts-v1": "Contracts v1" };

export function ContactsPane({ contacts, threads, activeThreadId, busy, actions, error, onRetry }: {
  contacts: Contact[] | null;
  threads: Thread[] | null;
  activeThreadId?: string;
  busy: Set<string>;
  actions: ContactActions;
  error: string | null;
  onRetry: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const { pending, others } = splitContacts(contacts ?? []);
  const chats = sortChats(threads ?? []);
  const now = Date.now();

  return (
    <div className="ag-scroll ag-left-scroll">
      {error ? (
        <div className="ag-alert ag-alert-error ag-m" role="alert">
          <Icon name="alert" /> <span className="min-w-0">{error}</span>
          <button type="button" className="ag-btn ag-btn-sm ml-auto" onClick={onRetry}>Retry</button>
        </div>
      ) : null}

      {pending.length ? (
        <section className="ag-section" aria-label="Invites to accept">
          <h3 className="ag-section-head ag-section-head-accent"><Icon name="mail" /> Invites to accept <span className="ag-count">{pending.length}</span></h3>
          <ul className="ag-list">
            {pending.map((c) => (
              <li key={c.contact_id} className="ag-invite">
                <Avatar id={c.contact_id} name={c.display_name} />
                <div className="min-w-0 flex-1">
                  <div className="ag-row-title ag-truncate">{c.display_name}</div>
                  <div className="ag-mono ag-sub">{c.number ?? "no number yet"}</div>
                  <div className="ag-sub">{STATUS_HINT.pending_acceptance}</div>
                  <div className="ag-actions">
                    <button type="button" className="ag-btn ag-btn-sm ag-btn-primary" disabled={busy.has(c.contact_id)} onClick={() => actions.accept(c)}>
                      <Icon name="check" size={14} /> Accept
                    </button>
                    <button type="button" className="ag-btn ag-btn-sm" disabled={busy.has(c.contact_id)} onClick={() => actions.decline(c)}>Decline</button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="ag-section" aria-label="Contacts">
        <h3 className="ag-section-head">
          Contacts {contacts ? <span className="ag-count">{others.length}</span> : null}
          <button type="button" className="ag-btn ag-btn-sm ml-auto" onClick={actions.addContact} title="Add contact" aria-label="Add contact"><Icon name="plus" size={14} /><span className="ag-btn-label">Add contact</span></button>
        </h3>
        {!contacts && !error ? <div className="ag-center-note"><Spinner /> Loading contacts…</div> : null}
        {contacts && others.length === 0 ? <p className="ag-empty">No contacts yet. Add another Jarvis from the directory or by its URN.</p> : null}
        <ul className="ag-list">
          {others.map((c) => {
            const expanded = open === c.contact_id;
            const isBusy = busy.has(c.contact_id);
            return (
              <li key={c.contact_id} className={`ag-contact${expanded ? " is-open" : ""}${c.status === "blocked" ? " is-blocked" : ""}`}>
                <div className="ag-contact-row">
                  <button type="button" className="ag-contact-main" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : c.contact_id)}>
                    <Avatar id={c.contact_id} name={c.display_name} />
                    <span className="min-w-0 flex-1 text-left">
                      <span className="ag-row-title ag-truncate block">{c.display_name}</span>
                      <span className="ag-contact-sub">
                        <StatusBadge status={c.status} />
                        <span className="ag-mono ag-sub ag-truncate">{c.number ?? "no number"}</span>
                      </span>
                    </span>
                  </button>
                  <button type="button" className="ag-iconbtn" title={c.status === "blocked" ? "Unblock to message" : `Message ${c.display_name}`}
                    aria-label={`Message ${c.display_name}`} disabled={c.status === "blocked" || isBusy} onClick={() => actions.message(c)}>
                    <Icon name="chat" />
                  </button>
                </div>
                {expanded ? (
                  <div className="ag-contact-detail">
                    <dl className="ag-dl">
                      <dt>URN</dt><dd className="ag-mono ag-break">{c.urn}</dd>
                      <dt>Via</dt><dd>{TRANSPORT[c.transport] ?? c.transport}{c.town ? ` · ${c.town.participant}` : ""}</dd>
                      <dt>Seen</dt><dd>{c.last_seen ? (relativeTime(c.last_seen, now) === "now" ? "just now" : relativeTime(c.last_seen, now) + " ago") : "never"}</dd>
                      {c.note ? (<><dt>Note</dt><dd>{c.note}</dd></>) : null}
                    </dl>
                    <p className="ag-sub">{STATUS_HINT[c.status]}</p>
                    <div className="ag-actions">
                      {c.status !== "blocked" ? (
                        <button type="button" className="ag-btn ag-btn-sm ag-btn-primary" disabled={isBusy} onClick={() => actions.message(c)}><Icon name="chat" size={14} /> Message</button>
                      ) : null}
                      {c.status === "unverified" || c.status === "invited" ? (
                        <button type="button" className="ag-btn ag-btn-sm" disabled={isBusy} onClick={() => actions.invite(c)}>
                          <Icon name="mail" size={14} /> {c.status === "invited" ? "Re-send invite" : "Invite"}
                        </button>
                      ) : null}
                      {c.status === "blocked" ? (
                        <button type="button" className="ag-btn ag-btn-sm" disabled={isBusy} onClick={() => actions.unblock(c)}>Unblock</button>
                      ) : (
                        <button type="button" className="ag-btn ag-btn-sm" disabled={isBusy} onClick={() => actions.block(c)}><Icon name="ban" size={14} /> Block</button>
                      )}
                      <button type="button" className="ag-btn ag-btn-sm ag-btn-ghost-danger" disabled={isBusy} onClick={() => actions.remove(c)}><Icon name="trash" size={14} /> Remove</button>
                    </div>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </section>

      <section className="ag-section" aria-label="Chats">
        <h3 className="ag-section-head">
          Chats {threads ? <span className="ag-count">{chats.length}</span> : null}
          <button type="button" className="ag-btn ag-btn-sm ml-auto" onClick={actions.newGroup} title="New group chat" aria-label="New group chat"><Icon name="users" size={14} /><span className="ag-btn-label">New group</span></button>
        </h3>
        {!threads && !error ? <div className="ag-center-note"><Spinner /> Loading chats…</div> : null}
        {threads && chats.length === 0 ? <p className="ag-empty">No chats yet. Message a contact to start one.</p> : null}
        <ul className="ag-list">
          {chats.map((t) => {
            const others = t.participants.filter((p) => p.kind !== "member");
            const active = t.thread_id === activeThreadId;
            const unread = active ? 0 : t.unread;
            return (
              <li key={t.thread_id}>
                <button type="button" className={`ag-chat${active ? " is-active" : ""}`} aria-current={active ? "page" : undefined} onClick={() => actions.openThread(t)}>
                  <Avatar id={t.kind === "group" ? t.thread_id : others[0]?.id ?? t.thread_id} name={t.title} kind={t.kind === "group" ? "group" : "agent"} />
                  <span className="min-w-0 flex-1 text-left">
                    <span className="flex items-baseline gap-2">
                      <span className={`ag-row-title ag-truncate flex-1${unread ? " is-unread" : ""}`}>{t.title}</span>
                      <span className="ag-time">{relativeTime(t.last_message_at, now)}</span>
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="ag-sub ag-truncate flex-1">
                        {t.kind === "group" ? `${others.length} agents · ` : ""}{t.last_preview || "No messages yet"}
                      </span>
                      {unread ? <span className="ag-unread" aria-label={`${unread} unread`}>{unread}</span> : null}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
