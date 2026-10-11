// Small presentational primitives for the Agents feature (ag- prefixed CSS in agents.css).
import { useEffect, useId, useRef, type ReactNode } from "react";
import type { ContactStatus, Ring } from "../../api/contracts";
import { RINGS, STATUS_HINT, STATUS_LABEL, hueFor, initials } from "./logic";

const PATHS: Record<string, ReactNode> = {
  chat: <path d="M4 5h16v11H8l-4 4V5z" />,
  plus: <path d="M12 5v14M5 12h14" />,
  users: <><circle cx="9" cy="8" r="3.2" /><path d="M3 19c.6-3.2 3-5 6-5s5.4 1.8 6 5" /><path d="M16 5.2a3 3 0 0 1 0 5.6M18 14.4c1.6.7 2.7 2.3 3 4.6" /></>,
  back: <path d="M15 5l-7 7 7 7" />,
  lock: <><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  checks: <><path d="M2.5 12.5l4.5 4.5L16.5 7.5" /><path d="M11.5 16.5l.5.5L21.5 7.5" /></>,
  alert: <><path d="M12 4l9 16H3L12 4z" /><path d="M12 10v4M12 17v.5" /></>,
  clock: <><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></>,
  trash: <path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12" />,
  send: <path d="M4 12l16-7-6 16-2.5-6.5L4 12z" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  mail: <><rect x="3.5" y="6" width="17" height="12" rx="2" /><path d="M4 7l8 6 8-6" /></>,
  ban: <><circle cx="12" cy="12" r="8" /><path d="M6.5 6.5l11 11" /></>,
  search: <><circle cx="11" cy="11" r="6" /><path d="M16 16l4 4" /></>,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5M12 8v.5" /></>,
  card: <><rect x="3.5" y="5" width="17" height="14" rx="2" /><path d="M7 10h6M7 14h10" /></>,
  spark: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" />,
  globe: <><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.5 2.6 2.5 14.4 0 17M12 3.5c-2.5 2.6-2.5 14.4 0 17" /></>,
  more: <><circle cx="6" cy="12" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="18" cy="12" r="1.2" /></>,
  undo: <path d="M9 7L5 11l4 4M5 11h9a5 5 0 0 1 0 10h-3" />,
};

export function Icon({ name, size = 16, title }: { name: keyof typeof PATHS | string; size?: number; title?: string }) {
  return (
    <svg className="ag-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden={title ? undefined : true} role={title ? "img" : undefined}>
      {title ? <title>{title}</title> : null}
      {PATHS[name] ?? null}
    </svg>
  );
}

export function Avatar({ id, name, kind = "agent", size = 32 }: { id: string; name: string; kind?: "agent" | "group" | "jarvis" | "member"; size?: number }) {
  const hue = hueFor(id);
  return (
    <span className={`ag-avatar ag-avatar-${kind}`} style={{ width: size, height: size, ["--ag-hue" as string]: String(hue) }} aria-hidden>
      {kind === "group" ? <Icon name="users" size={Math.round(size * 0.5)} /> : kind === "jarvis" ? <Icon name="spark" size={Math.round(size * 0.5)} /> : initials(name)}
    </span>
  );
}

export function StatusBadge({ status }: { status: ContactStatus }) {
  return <span className={`ag-status ag-status-${status}`} title={STATUS_HINT[status]}>{STATUS_LABEL[status]}</span>;
}

export function RingBadge({ ring, compact = false }: { ring: Ring; compact?: boolean }) {
  const info = RINGS.find((r) => r.ring === ring);
  return (
    <span className={`ag-ring ag-ring-${ring}`} title={info ? `${ring} ${info.label}: ${info.who}` : ring}>
      <span className="ag-ring-dot" aria-hidden />
      {ring}{compact || !info ? "" : ` ${info.label}`}
    </span>
  );
}

export function Toggle({ checked, disabled, onChange, label }: { checked: boolean; disabled?: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled}
      className="ag-switch" data-on={checked ? "true" : "false"} onClick={() => onChange(!checked)}>
      <span className="ag-switch-knob" />
    </button>
  );
}

export function Modal({ title, onClose, children, footer, wide = false }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const titleId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>("[data-autofocus]")
      ?? ref.current?.querySelector<HTMLElement>("input, select, textarea, button:not([data-close])");
    first?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeRef.current(); };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, []);
  return (
    <div className="ag-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} className={`ag-modal${wide ? " ag-modal-wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header className="ag-modal-head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="ag-iconbtn" data-close aria-label="Close" onClick={onClose}><Icon name="x" /></button>
        </header>
        <div className="ag-modal-body">{children}</div>
        {footer ? <footer className="ag-modal-foot">{footer}</footer> : null}
      </div>
    </div>
  );
}

export function ConfirmDialog({ title, body, confirmLabel, danger, busy, onConfirm, onCancel }: {
  title: string; body: ReactNode; confirmLabel: string; danger?: boolean; busy?: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <Modal title={title} onClose={onCancel} footer={<>
      <button type="button" className="ag-btn" onClick={onCancel}>Cancel</button>
      <button type="button" className={`ag-btn ${danger ? "ag-btn-danger" : "ag-btn-primary"}`} data-autofocus={danger ? undefined : true} disabled={busy} onClick={onConfirm}>
        {busy ? "Working…" : confirmLabel}
      </button>
    </>}>
      <div className="ag-confirm-body">{body}</div>
    </Modal>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <span className="ag-spinner" role="status" aria-label={label} />;
}
