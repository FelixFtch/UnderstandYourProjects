// Cloud provider card (2026-10-15): the Model tab's second card, below the
// local ↔ cloud mode switch. Picks which of the vendors serves cloud mode
// (GET/PUT /api/settings/llm-providers), and edits one provider's model + API
// key. The directory is fully server-driven — this card renders whatever the
// hub returns (7 vendors as of 2026-10-15, grok/muse included); only datalist
// suggestions come from the shared static table (providerCatalog.ts).
// Keys are write-only: the server returns has_key + key_hint, never the
// key itself. Owner-only to change; members/guests can inspect but not edit.
// `pushed` feedback mirrors the model-mode switch semantics (ModelModeSwitch.tsx).
import { useEffect, useId, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import type { LlmProvider, LlmProvidersSettings, Me } from "../../api/contracts";
import { dataApi } from "./adapter";
import { MODEL_SUGGESTIONS } from "./providerCatalog";
import { Icon, Spinner } from "./ui";

const KEY_PLACEHOLDER = "Paste the key - stored on the Jetson, never shown in full";

function errText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return "Only the household owner can change cloud provider settings.";
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

function KeyDot({ p }: { p: LlmProvider }) {
  return (
    <span
      className={`dm-prov-dot${p.has_key ? " is-key" : ""}`}
      title={p.has_key ? `Key stored (${p.key_hint ?? "hint unavailable"})` : "No key stored"}
      aria-label={p.has_key ? `Key stored ${p.key_hint ?? ""}` : "No key stored"}
    />
  );
}

export function ProviderCard({ me, readOnly }: { me: Me | null; readOnly: boolean }) {
  const [settings, setSettings] = useState<LlmProvidersSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [sel, setSel] = useState<string | null>(null); // selected provider id (defaults to the active one)
  const [open, setOpen] = useState(false);
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [keyEditing, setKeyEditing] = useState(false);
  const [busy, setBusy] = useState<"save" | "use" | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const pickerRef = useRef<HTMLDivElement>(null);
  const modelId = useId();
  const keyId = useId();
  const listId = useId();

  useEffect(() => {
    let alive = true;
    setLoadError(null);
    dataApi.llmProviders()
      .then((s) => {
        if (!alive) return;
        setSettings(s);
        setSel((cur) => cur ?? s.active); // first load: show the active provider
      })
      .catch((e) => { if (alive) setLoadError(errText(e)); });
    return () => { alive = false; };
  }, [nonce]);

  // Close the provider dropdown on outside click / Escape (ProfileMenu pattern).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!pickerRef.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const provider = settings?.providers.find((p) => p.id === sel) ?? null;
  const active = settings?.providers.find((p) => p.id === settings.active) ?? null;

  function pick(id: string) {
    setOpen(false);
    if (id === sel || !settings) return;
    const p = settings.providers.find((x) => x.id === id);
    if (!p) return;
    setSel(id);
    setModel(p.model);
    setKey("");
    setKeyEditing(false);
    setFeedback(null);
    setActionError(null);
  }

  // Seed the model field when the selection lands (first load → the active
  // provider). pick()/apply() set the form explicitly; this only covers the
  // async first load, and never overwrites mid-edit input (model !== "").
  useEffect(() => {
    if (provider && model === "" && !keyEditing && key === "") setModel(provider.model);
  }, [provider?.id, settings]);

  /** Fold a PUT response into local state and reset the form around the (possibly new) provider values. */
  function apply(res: LlmProvidersSettings) {
    setSettings(res);
    const p = res.providers.find((x) => x.id === sel) ?? null;
    setModel(p?.model ?? "");
    setKey("");
    setKeyEditing(false);
  }

  async function save() {
    if (readOnly || busy || !provider) return;
    const m = model.trim();
    if (!m) return;
    setBusy("save");
    setActionError(null);
    try {
      const res = await dataApi.putLlmProviders({ provider: provider.id, model: m, ...(key ? { api_key: key } : {}) });
      apply(res);
      setFeedback(res.pushed
        ? `Saved ${provider.label} — pushed to the voice runtime, effective immediately.`
        : `Saved ${provider.label} — the voice runtime picks it up on its next turn.`);
    } catch (e) {
      setActionError(errText(e));
    } finally {
      setBusy(null);
    }
  }

  async function useThis() {
    if (readOnly || busy || !provider || !settings || provider.id === settings.active) return;
    setBusy("use");
    setActionError(null);
    try {
      const res = await dataApi.putLlmProviders({ active: provider.id });
      apply(res);
      setFeedback(res.pushed
        ? `Now using ${provider.label} — pushed to the voice runtime, effective immediately.`
        : `Now using ${provider.label} — saved; the voice runtime picks it up on its next turn.`);
    } catch (e) {
      setActionError(errText(e));
    } finally {
      setBusy(null);
    }
  }

  if (loadError) {
    return (
      <section className="dm-model-card dm-prov" aria-label="Cloud provider">
        <div className="dm-alert dm-alert-error" style={{ margin: 0 }}>
          <Icon name="alert" />
          <span className="flex-1">{loadError}</span>
          <button type="button" className="dm-btn dm-btn-xs" onClick={() => setNonce((n) => n + 1)}>Retry</button>
        </div>
      </section>
    );
  }
  if (!settings) {
    return (
      <section className="dm-model-card dm-prov" aria-label="Cloud provider">
        <div className="dm-center"><Spinner /> Loading cloud providers…</div>
      </section>
    );
  }
  if (!provider || !active) {
    return (
      <section className="dm-model-card dm-prov" aria-label="Cloud provider">
        <p className="dm-note dm-note-sm" style={{ margin: 0 }}><Icon name="info" /> <span>No cloud providers are configured on the hub yet.</span></p>
      </section>
    );
  }

  const dirty = model.trim() !== provider.model || key.length > 0;
  const canSave = dirty && model.trim().length > 0 && !readOnly && busy === null;
  const suggestions = [...new Set([provider.model, ...(MODEL_SUGGESTIONS[provider.id] ?? [])])];

  return (
    <section className="dm-model-card dm-prov" aria-label="Cloud provider">
      <div className="dm-model-head">
        <span className="dm-model-glyph is-cloud" aria-hidden>
          <Icon name="server" size={22} />
        </span>
        <div className="dm-model-title">
          <h3>
            Cloud provider
            <span className="dm-mode-badge is-cloud"><Icon name="check" size={12} /> {active.label}</span>
          </h3>
          <p className="dm-muted">Which vendor serves cloud mode, with what model and key. Used when the mode above is Cloud.</p>
        </div>
      </div>

      {/* provider dropdown: every row shows label, current model and key status */}
      <div className="dm-prov-picker" ref={pickerRef}>
        <button
          type="button"
          className="dm-prov-current"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label="Provider"
          onClick={() => setOpen((v) => !v)}
        >
          <KeyDot p={provider} />
          <span className="dm-prov-row-text">
            <span className="dm-prov-label">{provider.label}</span>
            <span className="dm-mono dm-prov-model">{provider.model}</span>
          </span>
          {provider.id === settings.active ? <span className="dm-prov-active">Active</span> : null}
          <Icon name="chevronDown" size={14} />
        </button>
        {open ? (
          <div className="dm-prov-list" role="listbox" aria-label="Cloud providers">
            {settings.providers.map((p) => (
              <button
                key={p.id}
                type="button"
                role="option"
                aria-selected={p.id === provider.id}
                className="dm-prov-row"
                onClick={() => pick(p.id)}
              >
                <KeyDot p={p} />
                <span className="dm-prov-row-text">
                  <span className="dm-prov-label">{p.label}</span>
                  <span className="dm-mono dm-prov-model">{p.model}</span>
                </span>
                {p.id === settings.active ? <span className="dm-prov-active">Active</span> : null}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="dm-prov-form">
        <div className="dm-prov-field">
          <label className="dm-prov-field-label" htmlFor={modelId}>Model</label>
          <input
            id={modelId}
            className="dm-input dm-mono"
            value={model}
            onChange={(e) => { setModel(e.target.value); setFeedback(null); }}
            disabled={readOnly || busy !== null}
            list={listId}
            spellCheck={false}
            autoComplete="off"
          />
          <datalist id={listId}>
            {suggestions.map((m) => <option key={m} value={m} />)}
          </datalist>
        </div>

        <div className="dm-prov-field">
          <label className="dm-prov-field-label" htmlFor={keyId}>API key</label>
          {provider.has_key && !keyEditing ? (
            <div className="dm-prov-keyrow">
              {/* value="" keeps this input controlled — it swaps places with the
                  password field below, and React warns on controlled↔uncontrolled */}
              <input id={keyId} className="dm-input dm-mono" disabled readOnly value="" placeholder={`Stored key ${provider.key_hint ?? ""}`} />
              {!readOnly ? (
                <button type="button" className="dm-btn dm-btn-sm" disabled={busy !== null}
                  onClick={() => { setKeyEditing(true); setFeedback(null); }}>
                  Replace key
                </button>
              ) : null}
            </div>
          ) : (
            <div className="dm-prov-keyrow">
              <input
                id={keyId}
                type="password"
                className="dm-input dm-mono"
                placeholder={KEY_PLACEHOLDER}
                value={key}
                onChange={(e) => { setKey(e.target.value); setFeedback(null); }}
                disabled={readOnly || busy !== null}
                autoComplete="new-password"
              />
              {provider.has_key && keyEditing ? (
                <button type="button" className="dm-btn dm-btn-sm" disabled={busy !== null}
                  onClick={() => { setKeyEditing(false); setKey(""); }}>
                  Cancel
                </button>
              ) : null}
            </div>
          )}
          {/* 2026-10-15: the privacy promise for keys — keep next to the key field */}
          <p className="dm-note dm-note-sm"><Icon name="lock" size={13} /> <span>Keys are stored server-side and never returned in full.</span></p>
        </div>
      </div>

      <div className="dm-prov-actions">
        <button type="button" className="dm-btn dm-btn-sm dm-btn-primary" disabled={!canSave} onClick={() => void save()}>
          {busy === "save" ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          className="dm-btn dm-btn-sm"
          disabled={readOnly || busy !== null || provider.id === settings.active}
          onClick={() => void useThis()}
          title={provider.id === settings.active ? `${provider.label} is already the active provider` : `Make ${provider.label} the active provider for cloud mode`}
        >
          {busy === "use" ? "Switching…" : "Use this provider"}
        </button>
      </div>

      {feedback && !actionError ? (
        <p className="dm-alert dm-alert-ok" role="status"><Icon name="check" /> {feedback}</p>
      ) : null}
      {actionError ? (
        <p className="dm-alert dm-alert-error" role="alert"><Icon name="alert" /> {actionError}</p>
      ) : null}
      {readOnly ? (
        <p className="dm-note dm-note-sm"><Icon name="lock" size={13} />
          <span>Only the household owner can change cloud provider settings.{me ? <> You're signed in as <b>{me.role}</b>.</> : null}</span>
        </p>
      ) : null}
    </section>
  );
}
