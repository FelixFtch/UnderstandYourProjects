// Notification bell (2026-10-15): the top-bar entry for household notices
// (settings changes, enrollments, …). Unread-count badge on the bell; the
// dropdown lists recent items with relative time + kind chip, and a
// "Mark all read" footer. Polls every 30 s and refreshes when the tab becomes
// visible again. Offline fixtures (VITE_STUDIO_FIXTURES=true) come from app/fixtures.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { NotificationList, StudioNotification } from "../api/contracts";
import { relativeTime } from "../design/format";
import { Icon } from "../design/icons";
import { Button, Chip, cx, Spinner, type Tone } from "../design/primitives";

const POLL_MS = 30_000;
const LIMIT = 20;

/** kind → chip tone; unknown kinds fall back to neutral so new kinds render fine. */
const KIND_TONE: Record<string, Tone> = { settings: "accent", system: "info", warn: "warn", error: "err" };

async function fetchNotifications(signal?: AbortSignal): Promise<NotificationList> {
  // inline env check (not the shared FIXTURES const) so production builds drop the fixture chunk
  if (import.meta.env.VITE_STUDIO_FIXTURES === "true") {
    const f = await import("./fixtures");
    return f.notifications();
  }
  return api.notifications(LIMIT, signal);
}

async function postMarkRead(req: { all: true } | { ids: number[] }): Promise<{ ok: boolean }> {
  if (import.meta.env.VITE_STUDIO_FIXTURES === "true") {
    const f = await import("./fixtures");
    return f.markNotificationsRead(req);
  }
  return api.markNotificationsRead(req);
}

function errText(e: unknown): string {
  return e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
}

export function NotificationBell() {
  const [list, setList] = useState<NotificationList | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [marking, setMarking] = useState(false);
  const [markError, setMarkError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await fetchNotifications();
      setList(next);
      setLoadError(null);
    } catch (e) {
      setLoadError(errText(e));
    }
  }, []);

  // Initial load + 30 s polling (skipped while the tab is hidden) + refresh on
  // visibility return, so the badge is fresh without hammering the hub.
  useEffect(() => {
    void refresh();
    const tick = () => { if (document.visibilityState === "visible") void refresh(); };
    const t = window.setInterval(tick, POLL_MS);
    document.addEventListener("visibilitychange", tick);
    return () => { window.clearInterval(t); document.removeEventListener("visibilitychange", tick); };
  }, [refresh]);

  // Close the dropdown on outside click / Escape — same pattern as ProfileMenu.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  async function markRead(req: { all: true } | { ids: number[] }) {
    if (marking) return;
    setMarking(true);
    setMarkError(null);
    try {
      await postMarkRead(req);
      // the POST only answers {ok:true} — fold the change into local state
      setList((cur) => {
        if (!cur) return cur;
        const ids = "all" in req ? null : new Set(req.ids);
        const items = cur.items.map((n) => (ids === null || ids.has(n.id) ? { ...n, read: 1 as const } : n));
        return { items, unread: items.filter((n) => !n.read).length };
      });
    } catch (e) {
      setMarkError(errText(e));
    } finally {
      setMarking(false);
    }
  }

  const unread = list?.unread ?? 0;
  const label = unread > 0 ? `Notifications, ${unread} unread` : "Notifications";
  return (
    <div ref={root} className="relative shrink-0">
      <button
        type="button"
        onClick={() => { setOpen((v) => !v); if (!open) void refresh(); }}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={label}
        title={loadError ? `${label} — ${loadError}` : label}
        className="relative inline-flex size-8 items-center justify-center rounded-control text-muted transition-colors hover:bg-sunk hover:text-ink"
      >
        <Icon name="bell" size={17} />
        {unread > 0 ? (
          <span className="absolute -top-0.5 -right-0.5 grid min-w-4 place-items-center rounded-full bg-err px-1 text-[10px] leading-4 font-semibold text-on-accent tabular-nums">
            {unread > 99 ? "99+" : unread}
          </span>
        ) : loadError ? (
          <span className="absolute top-0 right-0 size-2 rounded-full bg-warn" aria-label="Couldn't load notifications" />
        ) : null}
      </button>

      {open ? (
        <div role="dialog" aria-label="Notifications" className="j-rise absolute top-[calc(100%+8px)] right-0 z-40 flex max-h-[min(430px,calc(100dvh-90px))] w-[min(350px,calc(100vw-24px))] flex-col overflow-hidden rounded-card border border-line bg-surface shadow-pop">
          <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
            <span className="text-[13px] font-semibold text-ink">Notifications</span>
            <span className="text-[11.5px] text-muted">{unread > 0 ? `${unread} unread` : "All read"}</span>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
            {loadError && !list ? (
              <div className="flex items-center gap-2 px-4 py-6 text-[12.5px] text-err" role="alert">
                <Icon name="alert" size={14} className="shrink-0" />
                <span className="min-w-0 flex-1">{loadError}</span>
                <button type="button" className="shrink-0 font-medium underline underline-offset-2" onClick={() => void refresh()}>Retry</button>
              </div>
            ) : !list ? (
              <div className="flex items-center justify-center gap-2 px-4 py-8 text-[12.5px] text-muted"><Spinner size={14} /> Loading…</div>
            ) : list.items.length === 0 ? (
              <div className="flex flex-col items-center px-6 py-8 text-center">
                <span className="mb-2 grid size-9 place-items-center rounded-full border border-line bg-sunk text-muted"><Icon name="bell" size={16} /></span>
                <span className="text-[13px] font-medium text-ink">All caught up</span>
                <span className="mt-0.5 text-[12px] text-muted">Nothing new — settings changes and household events will land here.</span>
              </div>
            ) : (
              <ul role="list" className="divide-y divide-line/60">
                {list.items.map((n) => <NotificationRow key={n.id} n={n} onMarkRead={(id) => void markRead({ ids: [id] })} />)}
              </ul>
            )}
          </div>

          {markError ? (
            <p role="alert" className="border-t border-line bg-err-soft px-4 py-1.5 text-[12px] text-err">{markError}</p>
          ) : null}
          <div className="flex items-center justify-between gap-2 border-t border-line bg-canvas/50 px-3 py-2">
            <span className="text-[11px] text-faint">Refreshes every 30 s</span>
            <Button size="sm" variant="ghost" icon="check" disabled={unread === 0} loading={marking} onClick={() => void markRead({ all: true })}>
              Mark all read
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function NotificationRow({ n, onMarkRead }: { n: StudioNotification; onMarkRead: (id: number) => void }) {
  const unread = !n.read;
  const body = (
    <>
      <span className="flex items-center gap-2">
        <Chip tone={KIND_TONE[n.kind] ?? "neutral"}>{n.kind}</Chip>
        <span className="ml-auto shrink-0 text-[11px] text-faint tabular-nums">{relativeTime(n.ts)}</span>
      </span>
      <span className="mt-1.5 flex items-start gap-1.5 text-[13px] font-medium text-ink">
        {unread ? <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent" aria-label="Unread" /> : null}
        <span className="min-w-0">{n.title}</span>
      </span>
      {n.body ? <span className={cx("mt-0.5 block text-[12.5px] text-muted", unread && "pl-3")}>{n.body}</span> : null}
    </>
  );
  const cls = cx("block w-full px-4 py-2.5 text-left transition-colors", unread ? "bg-accent-soft/35 hover:bg-accent-soft/60" : "hover:bg-sunk");
  // unread rows are buttons (click = mark just this one read); read rows are inert
  return (
    <li>
      {unread ? (
        <button type="button" className={cls} onClick={() => onMarkRead(n.id)} title="Mark read">{body}</button>
      ) : (
        <div className={cls}>{body}</div>
      )}
    </li>
  );
}
