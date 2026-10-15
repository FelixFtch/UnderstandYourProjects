// Model tab (added 2026-10-14): the household-wide local ↔ cloud switch for Jarvis's
// LLM route. One big switch card — not a per-scope policy, so it ignores the scope tree
// and applies immediately on PUT /api/settings/model-mode. Guests/members see it read-only.
// 2026-10-15: the "Cloud provider" card (ProviderCard.tsx) sits below the mode switch —
// which vendor serves cloud mode, its model and API key (PUT /api/settings/llm-providers).
import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import type { Me, ModelMode, ModelModeSettings } from "../../api/contracts";
import { dataApi } from "./adapter";
import { ProviderCard } from "./ProviderCard";
import { Icon, Spinner, Toggle } from "./ui";

// Fixed privacy copy — do not soften: this is the promise the switch makes.
// 2026-10-14: also shown by the quick switch in the Jarvis chat header
// (features/jarvis/ModelModeSwitch.tsx); keep the two in sync by sharing this constant.
export const MODEL_MODE_PRIVACY_NOTE =
  "In cloud mode, turns that involve personal or household-private data still run on the local model (privacy floor); raw voice audio is never uploaded to the cloud.";

function errText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return "Only the household owner can switch the model mode.";
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

function ModeBadge({ mode }: { mode: ModelMode }) {
  return (
    <span className={`dm-mode-badge is-${mode}`}>
      <Icon name={mode === "cloud" ? "globe" : "home"} size={12} />
      {mode === "cloud" ? "Cloud" : "Local"}
    </span>
  );
}

export function ModelTab({ me, readOnly }: { me: Me | null; readOnly: boolean }) {
  const [settings, setSettings] = useState<ModelModeSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);
  // null until the first switch in this view; then mirrors the PUT response's `pushed`.
  const [pushed, setPushed] = useState<boolean | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoadError(null);
    dataApi.modelMode()
      .then((s) => { if (alive) setSettings(s); })
      .catch((e) => { if (alive) setLoadError(errText(e)); });
    return () => { alive = false; };
  }, [nonce]);

  async function switchTo(next: ModelMode) {
    if (readOnly || busy || !settings || settings.mode === next) return;
    setBusy(true);
    setSwitchError(null);
    try {
      const res = await dataApi.putModelMode({ mode: next });
      setSettings({ mode: res.mode, cloud_model_route: res.cloud_model_route, cloud_model_persona: res.cloud_model_persona, updated_at: res.updated_at });
      setPushed(res.pushed);
    } catch (e) {
      setSwitchError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <div className="dm-alert dm-alert-error">
        <Icon name="alert" />
        <span className="flex-1">{loadError}</span>
        <button type="button" className="dm-btn dm-btn-xs" onClick={() => setNonce((n) => n + 1)}>Retry</button>
      </div>
    );
  }
  if (!settings) return <div className="dm-center dm-tall"><Spinner /> Loading model mode…</div>;

  const cloud = settings.mode === "cloud";
  const next: ModelMode = cloud ? "local" : "cloud";
  return (
    <div className="dm-model">
      <section className="dm-model-card" aria-label="Model mode">
        <div className="dm-model-head">
          <span className={`dm-model-glyph is-${settings.mode}`} aria-hidden>
            <Icon name={cloud ? "globe" : "home"} size={22} />
          </span>
          <div className="dm-model-title">
            <h3>
              Model mode <ModeBadge mode={settings.mode} />
            </h3>
            <p className="dm-muted">
              {cloud
                ? "Jarvis routes and replies through the cloud model."
                : "Everything runs on the local model on the Jetson."}
            </p>
          </div>
          <div className="dm-model-switch">
            <Toggle
              checked={cloud}
              disabled={readOnly || busy}
              label="Cloud mode"
              onChange={(v) => void switchTo(v ? "cloud" : "local")}
            />
            <button
              type="button"
              className="dm-btn dm-btn-primary dm-btn-sm"
              disabled={readOnly || busy}
              onClick={() => void switchTo(next)}
            >
              {busy ? "Switching…" : cloud ? "Switch to local" : "Switch to cloud"}
            </button>
          </div>
        </div>

        <dl className="dm-model-specs">
          <div>
            <dt>Cloud route model</dt>
            <dd className="dm-mono">{settings.cloud_model_route}</dd>
          </div>
          <div>
            <dt>Cloud persona model</dt>
            <dd className="dm-mono">{settings.cloud_model_persona}</dd>
          </div>
          <div>
            <dt>Last changed</dt>
            <dd>{settings.updated_at ? new Date(settings.updated_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—"}</dd>
          </div>
        </dl>

        <p className="dm-note dm-note-sm"><Icon name="info" /> <span>{MODEL_MODE_PRIVACY_NOTE}</span></p>

        {pushed !== null && !switchError ? (
          <p className="dm-alert dm-alert-ok" role="status">
            <Icon name="check" />
            {pushed
              ? `Switched to ${cloud ? "cloud" : "local"} — pushed to the voice runtime, effective immediately.`
              : `Switched to ${cloud ? "cloud" : "local"} — saved; the voice runtime picks it up on its next turn.`}
          </p>
        ) : null}
        {switchError ? (
          <p className="dm-alert dm-alert-error" role="alert"><Icon name="alert" /> {switchError}</p>
        ) : null}
        {readOnly ? (
          <p className="dm-note dm-note-sm"><Icon name="lock" size={13} />
            <span>Only the household owner can switch the model mode.{me ? <> You're signed in as <b>{me.role}</b>.</> : null}</span>
          </p>
        ) : null}
      </section>

      {/* 2026-10-15: multi-vendor cloud provider settings, below the mode switch */}
      <ProviderCard me={me} readOnly={readOnly} />
    </div>
  );
}
