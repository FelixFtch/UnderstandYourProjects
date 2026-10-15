// Voice profile card (2026-10-15): the Model tab card between the mode switch
// and the Cloud provider card — it bundles the voice chain (STT/LLM/TTS) into
// switchable profiles (GET/PUT /api/settings/voice-profiles). The two builtins
// (Local / Cloud full chain) are one-tap switches; owners can also save custom
// mixes. Switching reports the per-section push result (pushed.llm/stt/tts);
// saving a mix never pushes. Non-owners see everything read-only.
// Note: the *_options lists come from the hub as-is (local + providers with a
// stored key); the hub is capability-agnostic, so e.g. a provider without a TTS
// offering could still be listed — the frontend intentionally does not filter.
import { useEffect, useId, useState } from "react";
import { ApiError } from "../../api/client";
import type { Me, VoiceProfile, VoiceProfilesSettings } from "../../api/contracts";
import { dataApi } from "./adapter";
import { Icon, Spinner } from "./ui";

const NEW_MIX = "__new__";
const SEGMENTS = ["stt", "llm", "tts"] as const;
const SEG_LABEL: Record<(typeof SEGMENTS)[number], string> = { stt: "STT", llm: "LLM", tts: "TTS" };

/** Custom mix names are slugs derived from the label ("My mix" → "my-mix"). */
export function slugifyProfileName(label: string): string {
  const s = label.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return s || "my-mix";
}

function errText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return "Only the household owner can change voice profiles.";
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

function chainSummary(p: VoiceProfile): string {
  return `STT ${p.stt} · LLM ${p.llm} · TTS ${p.tts}`;
}

/** Per-section push feedback, e.g. "LLM: pushed to the voice runtime · STT: pushed … · TTS: applies on the next turn". */
function pushSummary(pushed: { llm: boolean; stt: boolean; tts: boolean }): string {
  return (["llm", "stt", "tts"] as const)
    .map((k) => `${SEG_LABEL[k]}: ${pushed[k] ? "pushed to the voice runtime" : "applies on the next turn"}`)
    .join(" · ");
}

export function VoiceProfileCard({ me, readOnly }: { me: Me | null; readOnly: boolean }) {
  const [settings, setSettings] = useState<VoiceProfilesSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [sel, setSel] = useState<string>(NEW_MIX); // which custom mix is being edited
  const [draft, setDraft] = useState({ stt: "local", llm: "local", tts: "local", label: "" });
  const [busy, setBusy] = useState<string | null>(null); // "save" | "activate" | a builtin name
  const [feedback, setFeedback] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const sttId = useId();
  const llmId = useId();
  const ttsId = useId();
  const labelId = useId();
  const mixId = useId();

  function seedDraft(s: VoiceProfilesSettings, target: VoiceProfile | null) {
    if (target) {
      setDraft({ stt: target.stt, llm: target.llm, tts: target.tts, label: target.label });
    } else {
      setDraft({ stt: s.stt_options[0] ?? "local", llm: s.llm_options[0] ?? "local", tts: s.tts_options[0] ?? "local", label: "" });
    }
  }

  useEffect(() => {
    let alive = true;
    setLoadError(null);
    dataApi.voiceProfiles()
      .then((s) => {
        if (!alive) return;
        setSettings(s);
        // default the editor to the first custom mix, or a fresh one
        const firstCustom = s.profiles.find((p) => !p.builtin) ?? null;
        setSel(firstCustom?.name ?? NEW_MIX);
        seedDraft(s, firstCustom);
      })
      .catch((e) => { if (alive) setLoadError(errText(e)); });
    return () => { alive = false; };
  }, [nonce]);

  const customs = settings?.profiles.filter((p) => !p.builtin) ?? [];
  const builtins = settings?.profiles.filter((p) => p.builtin) ?? [];
  const activeProfile = settings?.profiles.find((p) => p.name === settings.active) ?? null;
  const editing = sel !== NEW_MIX ? customs.find((p) => p.name === sel) ?? null : null;

  function pickMix(name: string) {
    if (!settings) return;
    setSel(name);
    setFeedback(null);
    setActionError(null);
    seedDraft(settings, name === NEW_MIX ? null : customs.find((p) => p.name === name) ?? null);
  }

  const dirty = editing
    ? draft.stt !== editing.stt || draft.llm !== editing.llm || draft.tts !== editing.tts || draft.label.trim() !== editing.label
    : draft.label.trim().length > 0;
  const canSave = !readOnly && busy === null && dirty && (editing !== null || draft.label.trim().length > 0);
  const canActivate = !readOnly && busy === null && editing !== null && !dirty && sel !== settings?.active;

  async function activate(name: string) {
    if (readOnly || busy || !settings || settings.active === name) return;
    setBusy(name === sel ? "activate" : name);
    setActionError(null);
    setFeedback(null);
    try {
      const res = await dataApi.putVoiceProfiles({ active: name });
      setSettings(res);
      const label = res.profiles.find((p) => p.name === res.active)?.label ?? res.active;
      setFeedback(res.pushed
        ? `Active profile: ${label} — ${pushSummary(res.pushed)}.`
        : `Active profile: ${label} — saved; nothing was pushed to the voice runtime.`);
    } catch (e) {
      setActionError(errText(e));
    } finally {
      setBusy(null);
    }
  }

  async function saveCustom() {
    if (readOnly || busy || !settings || !canSave) return;
    const name = editing ? editing.name : slugifyProfileName(draft.label);
    setBusy("save");
    setActionError(null);
    setFeedback(null);
    try {
      const res = await dataApi.putVoiceProfiles({
        name, stt: draft.stt, llm: draft.llm, tts: draft.tts,
        label: draft.label.trim() || name,
      });
      setSettings(res);
      setSel(name);
      const saved = res.profiles.find((p) => p.name === name) ?? null;
      if (saved) setDraft({ stt: saved.stt, llm: saved.llm, tts: saved.tts, label: saved.label });
      // saving never pushes (pushed: null) — say so explicitly
      setFeedback(`Saved "${saved?.label ?? name}" — stored on the hub, not pushed to the voice runtime. Activate it to use it.`);
    } catch (e) {
      setActionError(errText(e));
    } finally {
      setBusy(null);
    }
  }

  if (loadError) {
    return (
      <section className="dm-model-card dm-voice" aria-label="Voice profiles">
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
      <section className="dm-model-card dm-voice" aria-label="Voice profiles">
        <div className="dm-center"><Spinner /> Loading voice profiles…</div>
      </section>
    );
  }

  return (
    <section className="dm-model-card dm-voice" aria-label="Voice profiles">
      <div className="dm-model-head">
        <span className={`dm-model-glyph ${activeProfile?.name === "local" ? "is-local" : "is-cloud"}`} aria-hidden>
          <Icon name="activity" size={22} />
        </span>
        <div className="dm-model-title">
          <h3>
            Voice profiles
            {activeProfile ? (
              <span className={`dm-mode-badge ${activeProfile.name === "local" ? "is-local" : "is-cloud"}`}>
                <Icon name={activeProfile.name === "local" ? "home" : "globe"} size={12} /> {activeProfile.label}
              </span>
            ) : null}
          </h3>
          <p className="dm-muted">One profile bundles the whole voice chain — speech-to-text, the model, and the voice.</p>
        </div>
      </div>

      {/* one-tap builtin switches */}
      <div className="dm-voice-builtins">
        {builtins.map((p) => (
          <button
            key={p.name}
            type="button"
            className="dm-prov-current dm-voice-builtin"
            disabled={readOnly || busy !== null || p.name === settings.active}
            title={p.name === settings.active ? `${p.label} is the active profile` : `Switch to ${p.label}`}
            onClick={() => void activate(p.name)}
          >
            <span className="dm-prov-row-text">
              <span className="dm-prov-label">{busy === p.name ? "Switching…" : p.label}</span>
              <span className="dm-mono dm-prov-model">{chainSummary(p)}</span>
            </span>
            {p.name === settings.active ? <span className="dm-prov-active">Active</span> : null}
          </button>
        ))}
      </div>

      {/* custom mix editor */}
      <div className="dm-field dm-voice-custom">
        <div className="dm-field-head">
          <div className="min-w-0 flex-1">
            <div className="dm-field-title">Custom mix</div>
            <div className="dm-field-hint">Combine any available sections — e.g. local ears, cloud brain, cloud voice.</div>
          </div>
          {customs.length ? (
            <select id={mixId} className="dm-input dm-voice-mixsel" value={sel} onChange={(e) => pickMix(e.target.value)}
              disabled={readOnly || busy !== null} aria-label="Mix to edit">
              {customs.map((p) => <option key={p.name} value={p.name}>{p.label}</option>)}
              <option value={NEW_MIX}>New custom mix…</option>
            </select>
          ) : null}
        </div>
        <div className="dm-field-body">
          <div className="dm-voice-mix">
            {SEGMENTS.map((seg) => {
              const id = seg === "stt" ? sttId : seg === "llm" ? llmId : ttsId;
              return (
                <div className="dm-prov-field" key={seg}>
                  <label className="dm-prov-field-label" htmlFor={id}>{SEG_LABEL[seg]}</label>
                  <select
                    id={id}
                    className="dm-input dm-mono"
                    value={draft[seg]}
                    onChange={(e) => { setDraft((d) => ({ ...d, [seg]: e.target.value })); setFeedback(null); }}
                    disabled={readOnly || busy !== null}
                  >
                    {settings[`${seg}_options`].map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                </div>
              );
            })}
          </div>
          <div className="dm-prov-field" style={{ marginTop: 10 }}>
            <label className="dm-prov-field-label" htmlFor={labelId}>Label</label>
            <input
              id={labelId}
              className="dm-input"
              placeholder="My mix"
              value={draft.label}
              onChange={(e) => { setDraft((d) => ({ ...d, label: e.target.value })); setFeedback(null); }}
              disabled={readOnly || busy !== null}
              maxLength={48}
            />
          </div>
        </div>
        <div className="dm-field-foot dm-prov-actions" style={{ marginTop: 12 }}>
          <button type="button" className="dm-btn dm-btn-sm dm-btn-primary" disabled={!canSave} onClick={() => void saveCustom()}>
            {busy === "save" ? "Saving…" : "Save custom"}
          </button>
          <button
            type="button"
            className="dm-btn dm-btn-sm"
            disabled={!canActivate}
            title={editing ? (dirty ? "Save the mix first" : sel === settings.active ? "This mix is already active" : `Make ${editing.label} the active profile`) : "Save the mix first"}
            onClick={() => void activate(sel)}
          >
            {busy === "activate" ? "Activating…" : "Activate"}
          </button>
        </div>
      </div>

      {feedback && !actionError ? (
        <p className="dm-alert dm-alert-ok" role="status"><Icon name="check" /> {feedback}</p>
      ) : null}
      {actionError ? (
        <p className="dm-alert dm-alert-error" role="alert"><Icon name="alert" /> {actionError}</p>
      ) : null}

      <p className="dm-note dm-note-sm"><Icon name="info" />
        <span><b>Keep local weights warm:</b> Switching never unloads the local models - switching back is instant.</span>
      </p>
      {readOnly ? (
        <p className="dm-note dm-note-sm"><Icon name="lock" size={13} />
          <span>Only the household owner can change voice profiles.{me ? <> You're signed in as <b>{me.role}</b>.</> : null}</span>
        </p>
      ) : null}
    </section>
  );
}
