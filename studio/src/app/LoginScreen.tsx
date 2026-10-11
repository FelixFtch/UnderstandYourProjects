import { useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { Icon } from "../design/icons";
import { Button, cx } from "../design/primitives";
import { Monogram } from "./Brand";
import { FIXTURES, isValidInviteCode, normalizeInviteCode, useSession } from "./session";

const JETSON_CMD = "cd ~/jetson/services/companion-api && PYTHONPATH=src venv/bin/python -m companion_api.studio_admin invite";

export function LoginScreen() {
  const signIn = useSession((s) => s.signIn);
  const expired = useSession((s) => s.expired);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const normalized = normalizeInviteCode(code);
  const valid = isValidInviteCode(normalized);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(normalized);
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) setError("Can't reach the hub. Check that companion-api is running.");
      else if (err instanceof TypeError) setError("Can't reach the hub. Check that companion-api is running (or your tunnel to :5120).");
      else setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(JETSON_CMD);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch { /* clipboard blocked: the command is selectable */ }
  }

  return (
    <div className="h-dvh overflow-y-auto bg-canvas">
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-x-0 top-0 h-[42vh] opacity-80"
        style={{ background: "radial-gradient(60% 100% at 50% 0%, color-mix(in oklab, var(--j-accent) 16%, transparent), transparent)" }}
      />
      <main className="relative mx-auto flex min-h-full w-full max-w-[460px] flex-col justify-center px-4 py-10 sm:px-6">
        <div className="mb-6 flex items-center gap-3">
          <Monogram size={38} />
          <div>
            <div className="font-serif text-[17px] leading-tight text-ink">Jarvis Studio</div>
            <div className="text-[12.5px] text-muted">The console for your household Jarvis</div>
          </div>
        </div>

        <section className="rounded-card border border-line bg-surface p-5 shadow-card sm:p-7">
          <h1 className="font-serif text-[26px] leading-tight text-ink">Sign in to Jarvis Studio</h1>
          <p className="mt-2 text-[14px] text-muted">
            Studio pairs with your HomeHub the way a phone does. Enter a one-time invite code: it works once and
            expires after a few minutes.
          </p>

          {expired ? (
            <div className="mt-4 flex items-start gap-2 rounded-control border border-info/25 bg-info-soft px-3 py-2 text-[13px] text-info">
              <Icon name="info" size={15} className="mt-0.5 shrink-0" />
              Your session ended (the hub no longer accepts this browser's token). Pair again to continue.
            </div>
          ) : null}

          <form onSubmit={submit} className="mt-5 space-y-3" noValidate>
            <label htmlFor="invite" className="block text-[13px] font-medium text-ink-2">Invite code</label>
            <input
              id="invite"
              value={code}
              onChange={(e) => { setCode(e.target.value.slice(0, 12)); setError(null); }}
              autoFocus
              autoComplete="one-time-code"
              autoCapitalize="characters"
              autoCorrect="off"
              spellCheck={false}
              inputMode="text"
              placeholder="A1B2C3D4"
              aria-invalid={!!error}
              aria-describedby="invite-hint"
              className={cx(
                "h-14 w-full rounded-control border bg-raised px-4 text-center font-mono text-[24px] tracking-[0.32em] text-ink uppercase",
                "placeholder:text-faint/70 focus:ring-2 focus:ring-accent/25 focus:outline-none",
                error ? "border-err/60" : "border-line-strong focus:border-accent",
              )}
            />
            <div id="invite-hint" className="flex items-center justify-between text-[12px] text-muted">
              <span>8 characters, from the hub. Spaces and dashes are ignored.</span>
              <span className={cx("font-mono", valid ? "text-ok" : "")}>{normalized.length}/8</span>
            </div>
            {error ? (
              <div role="alert" className="flex items-start gap-2 rounded-control border border-err/25 bg-err-soft px-3 py-2 text-[13px] text-err">
                <Icon name="alert" size={15} className="mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            ) : null}
            <Button type="submit" variant="primary" className="h-11 w-full text-[15px]" disabled={!valid} loading={busy}>
              {busy ? "Pairing…" : "Pair this browser"}
            </Button>
          </form>

          <div className="mt-7 border-t border-line pt-5">
            <h2 className="text-[13px] font-semibold text-ink-2">Where does the code come from?</h2>
            <ol className="mt-3 space-y-4 text-[13.5px] text-ink-2">
              <li className="flex gap-3">
                <span className="grid size-6 shrink-0 place-items-center rounded-full bg-sunk text-[12px] font-semibold text-muted">1</span>
                <span>On your phone: open the <strong className="font-semibold text-ink">JarvisHub</strong> app and tap <strong className="font-semibold text-ink">Invite</strong>.</span>
              </li>
              <li className="flex min-w-0 gap-3">
                <span className="grid size-6 shrink-0 place-items-center rounded-full bg-sunk text-[12px] font-semibold text-muted">2</span>
                <div className="min-w-0 flex-1">
                  Or on the Jetson, run:
                  <div className="mt-2 flex items-start gap-2 rounded-control border border-line bg-sunk p-2.5">
                    <code className="min-w-0 flex-1 font-mono text-[12px] leading-relaxed [overflow-wrap:anywhere] text-ink select-all">{JETSON_CMD}</code>
                    <button
                      type="button"
                      onClick={copy}
                      className="shrink-0 rounded-md p-1 text-muted hover:bg-surface hover:text-ink"
                      aria-label="Copy command"
                      title="Copy command"
                    >
                      <Icon name={copied ? "check" : "copy"} size={15} />
                    </button>
                  </div>
                  <div className="mt-1.5 text-[12px] text-muted">It prints an 8-character code (add <code className="font-mono">--ttl 900</code> for 15 minutes).</div>
                </div>
              </li>
            </ol>
          </div>
        </section>

        <p className="mt-4 px-1 text-[12px] text-muted">
          The token stays in this browser only. Sign out any time from your profile menu.
          {FIXTURES ? " Fixture mode: any code works except 00000000." : ""}
        </p>
      </main>
    </div>
  );
}
