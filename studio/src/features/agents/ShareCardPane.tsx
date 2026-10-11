// Right pane: the per-thread share card (§4.3). Edits are local until "Save"; the save is
// optimistic (the card shows the new state immediately) and rolls back if the server rejects it.
import { useEffect, useRef, useState } from "react";
import type { Me, Ring, ShareCard, Thread } from "../../api/contracts";
import { agentsApi } from "./adapter";
import {
  CATEGORY_ORDER, RINGS, categoryLabel, countChanges, diffShareCard, groupByCategory, makeNewItem, meLink,
  visibleToAgents, type DraftItem,
} from "./logic";
import { Icon, RingBadge, Spinner, Toggle } from "./ui";

function errText(e: unknown): string { return e instanceof Error ? e.message : String(e); }

export interface ShareCardState {
  card: ShareCard | null;
  draft: DraftItem[] | null;
  loadError: string | null;
  saving: boolean;
  saveError: { message: string; attempted: DraftItem[] } | null;
  setDraft: (fn: (d: DraftItem[]) => DraftItem[]) => void;
  save: () => Promise<void>;
  discard: () => void;
  restoreAttempt: () => void;
  reload: () => void;
}

export function useShareCard(threadId: string | undefined): ShareCardState {
  const [card, setCard] = useState<ShareCard | null>(null);
  const [draft, setDraftState] = useState<DraftItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ShareCardState["saveError"]>(null);
  const [nonce, setNonce] = useState(0);
  const current = useRef(threadId);
  current.current = threadId;

  useEffect(() => {
    setCard(null); setDraftState(null); setLoadError(null); setSaveError(null); setSaving(false);
    if (!threadId || threadId === "jarvis") return;
    let alive = true;
    agentsApi.shareCard(threadId)
      .then((c) => { if (alive) { setCard(c); setDraftState(c.items); } })
      .catch((e) => { if (alive) setLoadError(errText(e)); });
    return () => { alive = false; };
  }, [threadId, nonce]);

  async function save() {
    if (!threadId || !card || !draft) return;
    const update = diffShareCard(card.items, draft);
    if (!update) return;
    const previous = card;
    const attempted = draft;
    setSaving(true);
    setSaveError(null);
    // Optimistic: what you see is what will be shared.
    setCard({ ...card, items: draft.map(({ isNew: _n, value: _v, ...item }) => item) });
    try {
      const next = await agentsApi.updateShareCard(threadId, update);
      if (current.current !== threadId) return;
      setCard(next);
      setDraftState(next.items);
    } catch (e) {
      if (current.current !== threadId) return;
      setCard(previous);
      setDraftState(previous.items);
      setSaveError({ message: errText(e), attempted });
    } finally {
      if (current.current === threadId) setSaving(false);
    }
  }

  return {
    card, draft, loadError, saving, saveError,
    setDraft: (fn) => setDraftState((d) => (d ? fn(d) : d)),
    save,
    discard: () => { if (card) setDraftState(card.items); setSaveError(null); },
    restoreAttempt: () => { if (saveError) setDraftState(saveError.attempted); setSaveError(null); },
    reload: () => setNonce((n) => n + 1),
  };
}

export function ShareCardPane({ state, thread, me, onBack }: {
  state: ShareCardState;
  thread: Thread | undefined;
  me: Me | null;
  onBack: () => void;
}) {
  const { card, draft, loadError, saving, saveError } = state;
  const [adding, setAdding] = useState(false);
  const [cat, setCat] = useState<string>("profile");
  const [label, setLabel] = useState("");
  const [value, setValue] = useState("");

  const update = card && draft ? diffShareCard(card.items, draft) : null;
  const changes = countChanges(update);
  const visible = draft ? groupByCategory(visibleToAgents(draft)).flatMap(([, xs]) => xs) : [];
  const recipients = (thread?.participants ?? []).filter((p) => p.kind === "agent").map((p) => p.display);
  const privacyHref = meLink(me);

  function toggle(id: string, enabled: boolean) {
    state.setDraft((d) => d.map((i) => (i.item_id === id ? { ...i, enabled } : i)));
  }
  function remove(id: string) {
    state.setDraft((d) => d.filter((i) => i.item_id !== id));
  }
  function addItem() {
    if (!label.trim() || !value.trim()) return;
    state.setDraft((d) => [...d, makeNewItem(cat, label.trim(), value.trim())]);
    setLabel(""); setValue(""); setAdding(false);
  }

  return (
    <div className="ag-card">
      <header className="ag-pane-head">
        <button type="button" className="ag-iconbtn ag-back" aria-label="Back to conversation" onClick={onBack}><Icon name="back" /></button>
        <div className="min-w-0 flex-1">
          <h2 className="ag-head-title">Share card</h2>
          <div className="ag-sub ag-truncate">What Jarvis may tell {recipients.length ? recipients.join(", ") : "agents"} in this chat</div>
        </div>
      </header>

      <div className="ag-scroll ag-card-scroll">
        <p className="ag-card-intro">
          <Icon name="info" size={14} />
          <span>Defaults come from your privacy rings in <a className="ag-link" href={privacyHref}>Data → Privacy</a>. Edits here apply to this chat only.</span>
        </p>
        <ul className="ag-ringlegend" aria-label="Privacy rings">
          {RINGS.map((r) => (
            <li key={r.ring}><RingBadge ring={r.ring as Ring} compact /> <b>{r.label}</b> <small>{r.who}</small></li>
          ))}
        </ul>

        {loadError ? (
          <div className="ag-alert ag-alert-error" role="alert"><Icon name="alert" /> {loadError}
            <button type="button" className="ag-btn ag-btn-sm ml-auto" onClick={state.reload}>Retry</button>
          </div>
        ) : null}
        {!card && !loadError ? <div className="ag-center-note"><Spinner /> Loading share card…</div> : null}

        {draft ? groupByCategory(draft).map(([category, items]) => (
          <section key={category} className="ag-cat">
            <h4 className="ag-cat-head">{categoryLabel(category)}</h4>
            <ul className="ag-list">
              {items.map((it) => {
                const ringInfo = RINGS.find((r) => r.ring === it.ring);
                return (
                  <li key={it.item_id} className={`ag-item${it.enabled && !it.locked ? " is-on" : ""}${it.locked ? " is-locked" : ""}`}>
                    <Toggle checked={it.enabled && !it.locked} disabled={it.locked || saving || it.isNew}
                      label={`Share ${it.label}`} onChange={(v) => toggle(it.item_id, v)} />
                    <div className="min-w-0 flex-1">
                      <div className="ag-item-label">
                        <span className="ag-break">{it.label}</span>
                        {it.isNew ? <span className="ag-tag ag-tag-new">Unsaved</span> : it.source === "added" ? <span className="ag-tag">Added</span> : null}
                      </div>
                      <div className="ag-item-value ag-mono ag-break">{it.value_preview || "—"}</div>
                      {it.locked ? (
                        <div className="ag-item-note"><Icon name="lock" size={12} /> Locked: your privacy policy never shares {categoryLabel(it.category).toLowerCase()} with agents. Change it in <a className="ag-link" href={privacyHref}>Data → Privacy</a>.</div>
                      ) : it.enabled && it.ring !== "R4" ? (
                        <div className="ag-item-note is-warn"><Icon name="alert" size={12} /> {it.ring} {ringInfo?.label.toLowerCase()}: normally {ringInfo?.who}. Sharing it here is an exception for this chat.</div>
                      ) : null}
                    </div>
                    <div className="ag-item-side">
                      <RingBadge ring={it.ring} compact />
                      {it.source === "added" ? (
                        <button type="button" className="ag-iconbtn ag-iconbtn-sm" aria-label={`Remove ${it.label}`} title="Remove" disabled={saving} onClick={() => remove(it.item_id)}><Icon name="trash" size={14} /></button>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        )) : null}

        {draft ? (
          adding ? (
            <form className="ag-additem" onSubmit={(e) => { e.preventDefault(); addItem(); }}>
              <h4 className="ag-cat-head">Add an item</h4>
              <label className="ag-field">
                <span>Category</span>
                <select className="ag-input" value={cat} onChange={(e) => setCat(e.target.value)}>
                  {CATEGORY_ORDER.map((c) => <option key={c} value={c}>{categoryLabel(c)}</option>)}
                </select>
              </label>
              <label className="ag-field">
                <span>Label</span>
                <input className="ag-input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Dietary preferences" autoFocus />
              </label>
              <label className="ag-field">
                <span>Value</span>
                <textarea className="ag-input" rows={2} value={value} onChange={(e) => setValue(e.target.value)} placeholder="Vegetarian, no peanuts" />
                <small>Stored on your hub; agents receive it only with messages in this chat.</small>
              </label>
              <div className="ag-actions">
                <button type="submit" className="ag-btn ag-btn-sm ag-btn-primary" disabled={!label.trim() || !value.trim()}>Add to card</button>
                <button type="button" className="ag-btn ag-btn-sm" onClick={() => setAdding(false)}>Cancel</button>
              </div>
            </form>
          ) : (
            <button type="button" className="ag-btn ag-btn-sm ag-addbtn" disabled={saving} onClick={() => setAdding(true)}><Icon name="plus" size={14} /> Add an item</button>
          )
        ) : null}

        {draft ? (
          <section className="ag-preview" aria-label="What the other agents will see">
            <h4 className="ag-cat-head">
              What the other agents will see
              {changes ? <span className="ag-tag ag-tag-new">after you save</span> : null}
            </h4>
            {visible.length === 0 ? (
              <p className="ag-sub">Nothing beyond the text of your messages.</p>
            ) : (
              <ul className="ag-preview-list">
                {visible.map((i) => (
                  <li key={i.item_id}>
                    <span className="ag-preview-k">{categoryLabel(i.category)} · {i.label}</span>
                    <span className="ag-preview-v ag-mono ag-break">{i.value_preview || "—"}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="ag-help">Values are resolved on your hub when a message is sent; previews are redacted.</p>
          </section>
        ) : null}
      </div>

      {saveError ? (
        <div className="ag-card-foot is-error" role="alert">
          <Icon name="alert" />
          <span className="min-w-0 flex-1">Not saved: {saveError.message}. The card was rolled back.</span>
          <button type="button" className="ag-btn ag-btn-sm" onClick={state.restoreAttempt}>Restore my edits</button>
        </div>
      ) : saving ? (
        <div className="ag-card-foot"><Spinner label="Saving" /> <span className="flex-1">Saving…</span></div>
      ) : changes ? (
        <div className="ag-card-foot is-dirty">
          <span className="flex-1">{changes} unsaved change{changes > 1 ? "s" : ""}</span>
          <button type="button" className="ag-btn ag-btn-sm" onClick={state.discard}>Discard</button>
          <button type="button" className="ag-btn ag-btn-sm ag-btn-primary" onClick={() => void state.save()}>Save</button>
        </div>
      ) : card ? (
        <div className="ag-card-foot is-clean"><Icon name="check" size={14} /> <span className="flex-1 ag-sub">Saved{card.updated_at ? ` · ${new Date(card.updated_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}` : ""}</span></div>
      ) : null}
    </div>
  );
}
