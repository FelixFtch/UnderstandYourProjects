// UA analysis mode card (2026-10-15): the bottom card of the Model tab — which
// engine runs Understand Anything's deep analysis (GET/PUT /api/settings/ua-mode).
// Local is the default; cloud targets one of the seven vendors. The response's
// `written` flag tells whether the indexer config file was actually updated.
// Owner-only to change; members/guests read-only.
import { useEffect, useId, useState } from "react";
import { ApiError } from "../../api/client";
import type { Me, UaMode, UaModeSettings } from "../../api/contracts";
import { dataApi } from "./adapter";
import { MODEL_SUGGESTIONS, UA_PROVIDERS } from "./providerCatalog";
import { Icon, Spinner } from "./ui";

function errText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return "Only the household owner can change the analysis mode.";
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export function UaModeCard({ me, readOnly }: { me: Me | null; readOnly: boolean }) {
  const [settings, setSettings] = useState<UaModeSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [mode, setMode] = useState<UaMode>("local");
  const [provider, setProvider] = useState("qwen");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const providerId = useId();
  const modelId = useId();
  const listId = useId();

  useEffect(() => {
    let alive = true;
    setLoadError(null);
    dataApi.uaMode()
      .then((s) => {
        if (!alive) return;
        setSettings(s);
        setMode(s.mode);
        setProvider(s.provider);
        setModel(s.model);
      })
      .catch((e) => { if (alive) setLoadError(errText(e)); });
    return () => { alive = false; };
  }, [nonce]);

  if (loadError) {
    return (
      <section className="dm-model-card dm-ua" aria-label="UA analysis mode">
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
      <section className="dm-model-card dm-ua" aria-label="UA analysis mode">
        <div className="dm-center"><Spinner /> Loading analysis mode…</div>
      </section>
    );
  }

  const cloud = mode === "cloud";
  const dirty = mode !== settings.mode
    || (cloud && (provider !== settings.provider || model.trim() !== settings.model));
  const canSave = !readOnly && !busy && dirty && (!cloud || model.trim().length > 0);
  const suggestions = [...new Set([model || settings.model, ...(MODEL_SUGGESTIONS[provider] ?? [])])].filter(Boolean);

  async function save() {
    if (!canSave) return;
    setBusy(true);
    setActionError(null);
    setFeedback(null);
    try {
      const res = await dataApi.putUaMode(cloud
        ? { mode: "cloud", provider, model: model.trim() }
        : { mode: "local" });
      setSettings(res);
      setMode(res.mode);
      setProvider(res.provider);
      setModel(res.model);
      const what = res.mode === "cloud" ? `cloud analysis via ${res.provider} (${res.model})` : "local analysis";
      // `written` = the indexer config file was updated by the hub
      setFeedback(res.written
        ? `Saved — ${what}; written to the indexer config, effective on the next analysis run.`
        : `Saved — ${what}; the indexer config was not written, so the running indexer keeps its previous mode.`);
    } catch (e) {
      setActionError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="dm-model-card dm-ua" aria-label="UA analysis mode">
      <div className="dm-model-head">
        <span className={`dm-model-glyph ${settings.mode === "cloud" ? "is-cloud" : "is-local"}`} aria-hidden>
          <Icon name="brain" size={22} />
        </span>
        <div className="dm-model-title">
          <h3>
            UA analysis mode
            <span className={`dm-mode-badge ${settings.mode === "cloud" ? "is-cloud" : "is-local"}`}>
              <Icon name={settings.mode === "cloud" ? "globe" : "home"} size={12} />
              {settings.mode === "cloud" ? "Cloud analysis" : "Local analysis"}
            </span>
          </h3>
          <p className="dm-muted">Which engine runs Understand Anything's deep analysis over your folders.</p>
        </div>
      </div>

      <div className="dm-seg dm-ua-mode" role="radiogroup" aria-label="Analysis mode">
        {(["local", "cloud"] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={mode === m}
            className="dm-seg-btn"
            disabled={readOnly || busy}
            onClick={() => { setMode(m); setFeedback(null); }}
          >
            {m === "local" ? "Local analysis" : "Cloud analysis"}
          </button>
        ))}
      </div>

      {cloud ? (
        <div className="dm-prov-form">
          <div className="dm-prov-field">
            <label className="dm-prov-field-label" htmlFor={providerId}>Provider</label>
            <select
              id={providerId}
              className="dm-input"
              value={provider}
              onChange={(e) => { setProvider(e.target.value); setFeedback(null); }}
              disabled={readOnly || busy}
            >
              {UA_PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </div>
          <div className="dm-prov-field">
            <label className="dm-prov-field-label" htmlFor={modelId}>Model</label>
            <input
              id={modelId}
              className="dm-input dm-mono"
              value={model}
              onChange={(e) => { setModel(e.target.value); setFeedback(null); }}
              disabled={readOnly || busy}
              list={listId}
              spellCheck={false}
              autoComplete="off"
              placeholder={MODEL_SUGGESTIONS[provider]?.[0] ?? "model name"}
            />
            <datalist id={listId}>
              {suggestions.map((m) => <option key={m} value={m} />)}
            </datalist>
          </div>
        </div>
      ) : null}

      <div className="dm-prov-actions">
        <button type="button" className="dm-btn dm-btn-sm dm-btn-primary" disabled={!canSave} onClick={() => void save()}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>

      {feedback && !actionError ? (
        <p className="dm-alert dm-alert-ok" role="status"><Icon name="check" /> {feedback}</p>
      ) : null}
      {actionError ? (
        <p className="dm-alert dm-alert-error" role="alert"><Icon name="alert" /> {actionError}</p>
      ) : null}

      <p className="dm-note dm-note-sm"><Icon name="info" />
        <span>Laya pre-filtering always stays local; only the deep-analysis step moves to the chosen cloud model.</span>
      </p>
      {readOnly ? (
        <p className="dm-note dm-note-sm"><Icon name="lock" size={13} />
          <span>Only the household owner can change the analysis mode.{me ? <> You're signed in as <b>{me.role}</b>.</> : null}</span>
        </p>
      ) : null}
    </section>
  );
}
