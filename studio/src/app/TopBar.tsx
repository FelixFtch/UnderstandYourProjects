import { useEffect, useRef, useState } from "react";
import { Icon } from "../design/icons";
import { Button, Chip, cx, Kbd, Segmented, Spinner, StatusDot } from "../design/primitives";
import type { Me } from "../api/contracts";
import { Monogram } from "./Brand";
import { MOD_KEY } from "./nav";
import { NotificationBell } from "./NotificationBell";
import type { RouteDef } from "./routes";
import { FIXTURES, useSession } from "./session";
import { useTheme, type ThemePref } from "./theme";

export function TopBar({ route, onOpenPalette, className }: { route: RouteDef; onOpenPalette: () => void; className?: string }) {
  const me = useSession((s) => s.me);
  return (
    <header className={cx("flex h-14 min-w-0 items-center gap-3 border-b border-line bg-canvas px-3 sm:px-5", className)}>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="md:hidden"><Monogram size={28} /></span>
        <div className="flex min-w-0 items-baseline gap-3">
          <h1 className="shrink-0 font-serif text-[18px] text-ink">{route.label}</h1>
          <p className="hidden truncate text-[13px] text-muted lg:block">{route.hint}</p>
        </div>
        {FIXTURES ? <Chip tone="info" className="hidden sm:inline-flex" title="VITE_STUDIO_FIXTURES=true: offline sample data">Fixtures</Chip> : null}
      </div>

      <button
        type="button"
        onClick={onOpenPalette}
        className="hidden h-8 items-center gap-2 rounded-control border border-line bg-surface pr-1.5 pl-2.5 text-[13px] text-muted hover:border-line-strong hover:text-ink xl:flex"
      >
        <Icon name="search" size={15} />
        Jump to…
        <span className="ml-3 flex gap-0.5"><Kbd>{MOD_KEY}</Kbd><Kbd>K</Kbd></span>
      </button>

      {me ? <AgentBoxStatus me={me} /> : null}
      {me ? (
        <div className="hidden min-w-0 items-center gap-2 lg:flex" title={me.jarvis.urn ?? undefined}>
          <span className="truncate text-[13px] text-ink-2">{me.jarvis.display_name}</span>
          <span className="rounded-md border border-line bg-surface px-1.5 py-0.5 font-mono text-[12px] text-ink">{me.jarvis.number}</span>
        </div>
      ) : null}
      {/* 2026-10-15: notification bell — the top-right entry, left of the profile menu */}
      {me ? <NotificationBell /> : null}
      {me ? <ProfileMenu me={me} /> : null}
    </header>
  );
}

function AgentBoxStatus({ me }: { me: Me }) {
  const enrolling = useSession((s) => s.enrolling);
  const enrollError = useSession((s) => s.enrollError);
  const enroll = useSession((s) => s.enroll);
  if (me.agent_box.enrolled) {
    return (
      <span className="hidden items-center gap-1.5 text-[12.5px] text-muted sm:flex" title={`Agent box ${me.agent_box.box_id ?? ""}: this Jetson's project worker is enrolled`}>
        <StatusDot tone="ok" />
        Agent box enrolled
      </span>
    );
  }
  return (
    <div className="hidden items-center gap-2 sm:flex">
      <span className="flex items-center gap-1.5 text-[12.5px] text-warn" title={enrollError ?? "This Jetson's project worker has no HomeHub token yet"}>
        <StatusDot tone={enrollError ? "err" : "warn"} />
        <span className="hidden md:inline">{enrollError ? "Enroll failed" : "Agent box not enrolled"}</span>
      </span>
      {me.role === "owner" ? (
        <Button size="sm" variant="secondary" onClick={() => void enroll()} loading={enrolling} title="Enroll this Jetson's UYP worker with HomeHub">
          {enrollError ? "Retry" : "Enroll"}
        </Button>
      ) : null}
    </div>
  );
}

function ProfileMenu({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const signOut = useSession((s) => s.signOut);
  const enroll = useSession((s) => s.enroll);
  const enrolling = useSession((s) => s.enrolling);
  const enrollError = useSession((s) => s.enrollError);
  const pref = useTheme((s) => s.pref);
  const setPref = useTheme((s) => s.setPref);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const copyNumber = async () => {
    try { await navigator.clipboard.writeText(me.jarvis.number); setCopied(true); window.setTimeout(() => setCopied(false), 1400); } catch { /* ignore */ }
  };

  return (
    <div ref={root} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="flex items-center gap-2 rounded-full border border-line bg-surface py-0.5 pr-2.5 pl-0.5 hover:border-line-strong"
      >
        <span className="grid size-7 place-items-center rounded-full bg-accent-soft font-serif text-[14px] text-accent-ink">
          {me.display_name.slice(0, 1).toUpperCase()}
        </span>
        <span className="text-[13px] text-ink-2">
          <span className="font-medium text-ink">{me.display_name}</span>
          <span className="hidden sm:inline"> · {me.role}</span>
        </span>
        {!me.agent_box.enrolled ? <StatusDot tone="warn" className="sm:hidden" label="Agent box not enrolled" /> : null}
      </button>

      {open ? (
        <div role="dialog" aria-label="Profile" className="j-rise absolute top-[calc(100%+8px)] right-0 z-40 w-[min(320px,calc(100vw-24px))] rounded-card border border-line bg-surface p-4 shadow-pop">
          <div className="text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">Signed in as</div>
          <div className="mt-1 font-serif text-[18px] text-ink">{me.display_name} <span className="font-sans text-[13px] text-muted">· {me.role}</span></div>
          <div className="text-[12px] text-muted">member <span className="font-mono">{me.member_id}</span> · {me.household_id}</div>

          <div className="mt-4 rounded-control border border-line bg-canvas/60 p-3">
            <div className="text-[12.5px] font-medium text-ink-2">{me.jarvis.display_name}</div>
            <button type="button" onClick={copyNumber} className="mt-1 flex items-center gap-2 font-mono text-[17px] tracking-wide text-ink hover:text-accent-ink" title="Copy Jarvis number">
              {me.jarvis.number}
              <Icon name={copied ? "check" : "copy"} size={14} className="text-muted" />
            </button>
            {me.jarvis.urn ? <div className="mt-1 truncate font-mono text-[11px] text-muted" title={me.jarvis.urn}>{me.jarvis.urn}</div> : null}
            <div className="mt-1 text-[12px] text-muted">
              {me.jarvis.town ? <>NANDA Town · {me.jarvis.town.participant} <span className="font-mono">({me.jarvis.town.run_id})</span></> : "Not joined to NANDA Town"}
            </div>
          </div>

          <div className="mt-3 flex items-center justify-between gap-2 rounded-control border border-line p-3">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-ink-2">
                <StatusDot tone={me.agent_box.enrolled ? "ok" : "warn"} /> Agent box
              </div>
              <div className="truncate text-[12px] text-muted">
                {me.agent_box.enrolled ? <>Enrolled · <span className="font-mono">{me.agent_box.box_id}</span></> : enrollError ? `Enroll failed: ${enrollError}` : "This Jetson's project worker is not enrolled"}
              </div>
            </div>
            {!me.agent_box.enrolled && me.role === "owner" ? (
              <Button size="sm" onClick={() => void enroll()} disabled={enrolling}>{enrolling ? <Spinner size={13} /> : "Enroll"}</Button>
            ) : null}
          </div>

          <div className="mt-3 flex items-center justify-between gap-2">
            <span className="text-[12.5px] text-ink-2">Theme</span>
            <Segmented<ThemePref>
              label="Theme"
              value={pref}
              onChange={setPref}
              options={[{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }, { value: "system", label: "Auto" }]}
            />
          </div>

          <Button variant="ghost" icon="logout" className="mt-3 w-full justify-start" onClick={() => { setOpen(false); signOut(); }}>
            Sign out of this browser
          </Button>
        </div>
      ) : null}
    </div>
  );
}
