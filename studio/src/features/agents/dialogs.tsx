// "Add contact" and "New group chat" dialogs.
import { useEffect, useMemo, useState } from "react";
import type { Contact, DirectoryEntry, Transport } from "../../api/contracts";
import { agentsApi } from "./adapter";
import { Avatar, Icon, Modal, Spinner, StatusBadge } from "./ui";

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

const TRANSPORT_LABEL: Record<Transport, string> = { town: "NANDA Town", a2a: "A2A", "contracts-v1": "Contracts v1" };

export function AddContactDialog({ onClose, onAdded }: {
  onClose: () => void;
  onAdded: (c: Contact, invite: { sent: boolean; error: string | null } | null) => void;
}) {
  const [tab, setTab] = useState<"directory" | "urn">("directory");
  const [entries, setEntries] = useState<DirectoryEntry[] | null>(null);
  const [dirError, setDirError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sendInvite, setSendInvite] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [urn, setUrn] = useState("");
  const [name, setName] = useState("");
  const [transport, setTransport] = useState<Transport>("a2a");

  useEffect(() => {
    let alive = true;
    agentsApi.directory().then((r) => { if (alive) setEntries(r.entries); }).catch((e) => { if (alive) setDirError(errText(e)); });
    return () => { alive = false; };
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!entries) return [];
    return q ? entries.filter((e) => `${e.display_name} ${e.urn}`.toLowerCase().includes(q)) : entries;
  }, [entries, query]);

  async function add(c: { urn: string; display_name: string; transport?: string; town?: DirectoryEntry["town"] }, key: string) {
    setBusy(key);
    setError(null);
    try {
      const created = await agentsApi.addContact(c);
      let invite: { sent: boolean; error: string | null } | null = null;
      if (sendInvite) {
        try {
          const r = await agentsApi.inviteContact(created.contact_id);
          invite = { sent: r.delivery.ok, error: r.delivery.error };
          if (r.delivery.ok) created.status = "invited";
        } catch (e) {
          invite = { sent: false, error: errText(e) };
        }
      }
      onAdded(created, invite);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(null);
    }
  }

  const urnValid = /^urn:[a-z0-9][a-z0-9-]*:\S+$/i.test(urn.trim());
  const nameValid = name.trim().length > 0;

  return (
    <Modal title="Add a contact" onClose={onClose} wide footer={
      <>
        <label className="ag-check mr-auto">
          <input type="checkbox" checked={sendInvite} onChange={(e) => setSendInvite(e.target.checked)} />
          <span>Send my Jarvis card as an invite</span>
        </label>
        {tab === "urn" ? (
          <button type="button" className="ag-btn ag-btn-primary" disabled={!urnValid || !nameValid || busy !== null}
            onClick={() => add({ urn: urn.trim(), display_name: name.trim(), transport }, "urn")}>
            {busy === "urn" ? "Adding…" : "Add contact"}
          </button>
        ) : null}
      </>
    }>
      <div className="ag-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "directory"} className="ag-tab" onClick={() => setTab("directory")}>Directory</button>
        <button type="button" role="tab" aria-selected={tab === "urn"} className="ag-tab" onClick={() => setTab("urn")}>Enter an address</button>
      </div>
      {error ? <p className="ag-alert ag-alert-error" role="alert"><Icon name="alert" /> {error}</p> : null}
      {tab === "directory" ? (
        <div className="ag-dir">
          <p className="ag-help">Agents your gateway and NANDA Town can see that are not contacts yet.</p>
          <label className="ag-search">
            <Icon name="search" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by name or URN" aria-label="Search directory" />
          </label>
          {dirError ? <p className="ag-alert ag-alert-error"><Icon name="alert" /> Directory unavailable: {dirError}</p> : null}
          {!entries && !dirError ? <div className="ag-center-note"><Spinner /> Looking for agents…</div> : null}
          {entries && filtered.length === 0 ? (
            <p className="ag-empty">{entries.length === 0 ? "No new agents discovered. Enter an address instead." : "No matches."}</p>
          ) : null}
          <ul className="ag-dir-list">
            {filtered.map((e) => (
              <li key={e.urn} className="ag-dir-row">
                <Avatar id={e.urn} name={e.display_name} />
                <div className="ag-dir-main">
                  <div className="ag-row-title">{e.display_name}</div>
                  <div className="ag-mono ag-truncate" title={e.urn}>{e.urn}</div>
                  <div className="ag-tags">
                    <span className="ag-tag">{e.source === "town" ? "Town" : "Gateway"}</span>
                    <span className="ag-tag">{TRANSPORT_LABEL[e.transport] ?? e.transport}</span>
                    {e.town ? <span className="ag-tag ag-mono">{e.town.participant}</span> : null}
                  </div>
                </div>
                <button type="button" className="ag-btn ag-btn-sm" disabled={busy !== null}
                  onClick={() => add({ urn: e.urn, display_name: e.display_name, transport: e.transport, town: e.town }, e.urn)}>
                  {busy === e.urn ? "Adding…" : "Add"}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="ag-form">
          <label className="ag-field">
            <span>Agent URN</span>
            <input className="ag-input ag-mono" value={urn} onChange={(e) => setUrn(e.target.value)} placeholder="urn:ai:domain:felix.jarvis" data-autofocus />
            {urn && !urnValid ? <small className="ag-field-err">Must look like urn:&lt;namespace&gt;:&lt;id&gt;</small> : <small>Ask them for the URN on their Jarvis card.</small>}
          </label>
          <label className="ag-field">
            <span>Display name</span>
            <input className="ag-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Felix's Jarvis" />
          </label>
          <label className="ag-field">
            <span>Transport</span>
            <select className="ag-input" value={transport} onChange={(e) => setTransport(e.target.value as Transport)}>
              {(Object.keys(TRANSPORT_LABEL) as Transport[]).map((t) => <option key={t} value={t}>{TRANSPORT_LABEL[t]}</option>)}
            </select>
          </label>
          <p className="ag-help">New contacts start as <b>unverified</b>. They become verified once their Jarvis accepts your invite.</p>
        </div>
      )}
    </Modal>
  );
}

export function NewGroupDialog({ contacts, onClose, onCreate }: {
  contacts: Contact[];
  onClose: () => void;
  onCreate: (ids: string[], title: string) => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eligible = contacts
    .filter((c) => c.status !== "blocked" && c.status !== "pending_acceptance")
    .sort((a, b) => a.display_name.localeCompare(b.display_name));
  const unverifiedPicked = eligible.filter((c) => picked.has(c.contact_id) && c.status !== "verified");
  const ok = picked.size >= 2 && title.trim().length > 0;

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await onCreate([...picked], title.trim());
    } catch (e) {
      setError(errText(e));
      setBusy(false);
    }
  }

  return (
    <Modal title="New group chat" onClose={onClose} footer={<>
      <span className="ag-help mr-auto">{picked.size} selected{picked.size < 2 ? " · pick at least 2" : ""}</span>
      <button type="button" className="ag-btn" onClick={onClose}>Cancel</button>
      <button type="button" className="ag-btn ag-btn-primary" disabled={!ok || busy} onClick={create}>{busy ? "Creating…" : "Create group"}</button>
    </>}>
      {error ? <p className="ag-alert ag-alert-error" role="alert"><Icon name="alert" /> {error}</p> : null}
      <label className="ag-field">
        <span>Title</span>
        <input className="ag-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Friday dinner" data-autofocus />
      </label>
      <fieldset className="ag-pick">
        <legend>Members</legend>
        {eligible.length === 0 ? <p className="ag-empty">Add at least two contacts first.</p> : null}
        {eligible.map((c) => (
          <label key={c.contact_id} className="ag-pick-row">
            <input type="checkbox" checked={picked.has(c.contact_id)} onChange={() => toggle(c.contact_id)} />
            <Avatar id={c.contact_id} name={c.display_name} size={26} />
            <span className="ag-pick-name">{c.display_name}</span>
            <StatusBadge status={c.status} />
          </label>
        ))}
      </fieldset>
      {unverifiedPicked.length ? (
        <p className="ag-alert ag-alert-warn"><Icon name="info" /> {unverifiedPicked.map((c) => c.display_name).join(", ")} {unverifiedPicked.length === 1 ? "is" : "are"} not verified yet; messages to them may not be delivered.</p>
      ) : null}
      <p className="ag-help">Each group has its own share card. It starts from your privacy defaults.</p>
    </Modal>
  );
}
