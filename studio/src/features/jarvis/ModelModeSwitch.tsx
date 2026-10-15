// Model mode quick switch (2026-10-14): a compact Local/Cloud badge in the Jarvis chat
// header — the entry point users actually see. Clicking opens a confirm dialog (the
// privacy-floor copy is mandatory), then PUTs the new mode and reflects `pushed`.
// The full settings (model names, last changed) stay in Data → Model.
import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import type { ModelMode, ModelModeResult, ModelModeSettings } from "../../api/contracts";
import { useMe } from "../../app/session";
import { Icon } from "../../design/icons";
import { Button, cx, Modal } from "../../design/primitives";
import { MODEL_MODE_PRIVACY_NOTE } from "../data/ModelTab";
import { jarvisData } from "./data";

function errText(e: unknown): string {
  if (e instanceof ApiError && e.status === 403) return "Only the household owner can switch the model mode.";
  return e instanceof Error ? e.message : String(e);
}

export function ModelModeSwitch() {
  const me = useMe();
  const readOnly = !me || me.role !== "owner";

  const [settings, setSettings] = useState<ModelModeSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [dialog, setDialog] = useState<null | { target: ModelMode }>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ModelModeResult | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoadError(null);
    jarvisData.modelMode()
      .then((s) => { if (alive) setSettings(s); })
      .catch((e) => { if (alive) setLoadError(errText(e)); });
    return () => { alive = false; };
  }, [nonce]);

  function openDialog() {
    if (!settings || readOnly) return;
    setResult(null);
    setSwitchError(null);
    setDialog({ target: settings.mode === "cloud" ? "local" : "cloud" });
  }

  async function confirmSwitch(target: ModelMode) {
    setBusy(true);
    setSwitchError(null);
    try {
      const res = await jarvisData.putModelMode({ mode: target });
      // badge updates immediately from the response, before the dialog closes
      setSettings({ mode: res.mode, cloud_model_route: res.cloud_model_route, cloud_model_persona: res.cloud_model_persona, updated_at: res.updated_at });
      setResult(res);
    } catch (e) {
      setSwitchError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <button type="button" onClick={() => setNonce((n) => n + 1)} title={`${loadError} — tap to retry`}
        className="flex shrink-0 items-center gap-1.5 rounded-full border border-warn/30 bg-warn-soft px-2.5 py-1 text-[12.5px] font-medium text-warn">
        <Icon name="alert" size={13} /> Model mode?
      </button>
    );
  }
  if (!settings) {
    return <span className="flex shrink-0 items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-[12.5px] text-faint" aria-busy="true">…</span>;
  }

  const cloud = settings.mode === "cloud";
  const badge = (
    <button
      type="button"
      onClick={openDialog}
      disabled={readOnly}
      aria-haspopup="dialog"
      aria-label={readOnly ? undefined : `Model mode: ${cloud ? "cloud" : "local"} — select to switch`}
      title={readOnly
        ? `Only the household owner can switch the model mode${me ? ` — you're signed in as ${me.role}` : ""}.`
        : `Model mode: ${cloud ? "cloud" : "local"} — select to switch`}
      className={cx(
        "flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        cloud ? "border-accent/30 bg-accent-soft text-accent-ink" : "border-ok/30 bg-ok-soft text-ok",
      )}
    >
      <Icon name={cloud ? "globe" : "home"} size={13} /> {cloud ? "Cloud" : "Local"}
    </button>
  );

  const target = dialog?.target;
  const targetCloud = target === "cloud";
  return (
    <>
      {badge}
      <Modal
        open={dialog !== null}
        onClose={() => { if (!busy) setDialog(null); }}
        title={result ? "Model mode switched" : targetCloud ? "Switch to cloud mode?" : "Switch back to local mode?"}
        width={460}
        footer={result ? (
          <Button variant="primary" data-autofocus onClick={() => setDialog(null)}>Done</Button>
        ) : (
          <>
            <Button onClick={() => setDialog(null)} disabled={busy}>Cancel</Button>
            <Button variant="primary" data-autofocus loading={busy} onClick={() => target && void confirmSwitch(target)}>
              {targetCloud ? "Switch to cloud" : "Switch to local"}
            </Button>
          </>
        )}
      >
        {result ? (
          <p className="text-[13.5px] text-ink-2" role="status">
            {result.pushed
              ? `Now in ${result.mode} mode — pushed to the voice runtime, effective immediately.`
              : `Now in ${result.mode} mode — saved; the voice runtime picks it up on its next turn.`}
          </p>
        ) : (
          <div className="space-y-2.5 text-[13.5px] text-ink-2">
            <p>
              {targetCloud
                ? <>Jarvis will route and reply through the cloud model (<span className="font-mono text-[12.5px]">{settings.cloud_model_route}</span> / <span className="font-mono text-[12.5px]">{settings.cloud_model_persona}</span>).</>
                : "Everything runs on the local model on the Jetson again."}
            </p>
            <p className="rounded-control border border-line bg-canvas px-3 py-2 text-[12.5px] text-muted">{MODEL_MODE_PRIVACY_NOTE}</p>
            <p className="text-[12.5px] text-muted">Model names and history live under <a className="text-accent-ink hover:underline" href="#/data/household/model">Data → Model</a>.</p>
            {switchError ? <p role="alert" className="rounded-control border border-err/25 bg-err-soft px-3 py-2 text-[12.5px] text-err">{switchError}</p> : null}
          </div>
        )}
      </Modal>
    </>
  );
}
