// Presentational primitives for the Data feature (dm- prefixed CSS in data.css).
import { useEffect, useId, useRef, type ReactNode } from "react";
import type { PolicyScope, Ring } from "../../api/contracts";
import { RING_INFO, RING_ORDER, type FieldView } from "./inherit";

const PATHS: Record<string, ReactNode> = {
  globe: <><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.5 2.6 2.5 14.4 0 17M12 3.5c-2.5 2.6-2.5 14.4 0 17" /></>,
  home: <><path d="M4 11l8-6.5 8 6.5" /><path d="M6 10v9.5h12V10" /><path d="M10 19.5v-5h4v5" /></>,
  person: <><circle cx="12" cy="8.5" r="3.5" /><path d="M5 20c.8-3.8 3.6-6 7-6s6.2 2.2 7 6" /></>,
  guest: <><circle cx="12" cy="8.5" r="3.5" strokeDasharray="2.4 2" /><path d="M5 20c.8-3.8 3.6-6 7-6s6.2 2.2 7 6" strokeDasharray="2.4 2" /></>,
  lock: <><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>,
  undo: <path d="M9 7L5 11l4 4M5 11h9a5 5 0 0 1 0 10h-3" />,
  alert: <><path d="M12 4l9 16H3L12 4z" /><path d="M12 10v4M12 17v.5" /></>,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5M12 8v.5" /></>,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  plus: <path d="M12 5v14M5 12h14" />,
  key: <><circle cx="8" cy="15" r="3.5" /><path d="M10.5 12.5L19 4M16 7l2.5 2.5M14 9l2 2" /></>,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  trash: <path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12" />,
  chevron: <path d="M9 6l6 6-6 6" />,
  // 2026-10-15: provider dropdown (Cloud provider card)
  chevronDown: <path d="M6 9.5l6 6 6-6" />,
  server: <><rect x="4.5" y="4.5" width="15" height="6" rx="1.5" /><rect x="4.5" y="13.5" width="15" height="6" rx="1.5" /><path d="M8 7.5h.01M8 16.5h.01" /></>,
};

export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return (
    <svg className="dm-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {PATHS[name] ?? null}
    </svg>
  );
}

export const KIND_ICON: Record<PolicyScope["kind"], string> = { town: "globe", household: "home", member: "person", guest: "guest" };

export function Toggle({ checked, disabled, onChange, label }: { checked: boolean; disabled?: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled}
      className="dm-switch" data-on={checked ? "true" : "false"} onClick={() => onChange(!checked)}>
      <span className="dm-switch-knob" />
    </button>
  );
}

export function Segmented<T extends string>({ value, options, onChange, disabled, label }: {
  value: T | undefined; options: Array<{ value: T; label: string; hint?: string }>; onChange: (v: T) => void; disabled?: boolean; label: string;
}) {
  return (
    <div className="dm-seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} disabled={disabled}
          className="dm-seg-btn" title={o.hint} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

/** Concentric ring mini-glyph: R1 is the centre dot, R4 the outer ring. */
export function RingGlyph({ ring, size = 16 }: { ring: Ring; size?: number }) {
  const idx = RING_ORDER.indexOf(ring);
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden className="dm-ringglyph">
      {[9, 6.6, 4.2, 2].map((r, i) => {
        const level = 3 - i; // 3 = R4 … 0 = R1
        const active = level <= idx;
        return <circle key={r} cx="10" cy="10" r={r} fill={level === 0 ? (active ? "currentColor" : "none") : "none"}
          stroke="currentColor" strokeWidth={level === idx ? 1.8 : 1} opacity={active ? (level === idx ? 1 : 0.45) : 0.18} />;
      })}
    </svg>
  );
}

export function RingControl({ value, onChange, disabled, label }: { value: Ring; onChange: (r: Ring) => void; disabled?: boolean; label: string }) {
  return (
    <div className="dm-rings" role="radiogroup" aria-label={label}>
      {RING_ORDER.map((r) => (
        <button key={r} type="button" role="radio" aria-checked={value === r} disabled={disabled}
          className={`dm-ringbtn dm-ring-${r}`} title={`${r} ${RING_INFO[r].label}: ${RING_INFO[r].who}`} onClick={() => onChange(r)}>
          <RingGlyph ring={r} size={14} />
          <span className="dm-ringbtn-code">{r}</span>
          <span className="dm-ringbtn-label">{RING_INFO[r].label}</span>
        </button>
      ))}
    </div>
  );
}

/** Concentric legend: R1 personal at the centre → R4 external at the edge. */
export function RingLegend({ highlight }: { highlight?: Ring }) {
  const radii = [26, 46, 66, 86];
  return (
    <div className="dm-legend">
      <svg viewBox="0 0 180 180" className="dm-legend-svg" role="img" aria-label="Privacy rings from R1 personal at the centre to R4 external at the edge">
        {[...RING_ORDER].reverse().map((r) => {
          const i = RING_ORDER.indexOf(r);
          return <circle key={r} cx="90" cy="90" r={radii[i]} className={`dm-legend-ring dm-ring-${r}${highlight === r ? " is-hl" : ""}`} />;
        })}
        {RING_ORDER.map((r, i) => (
          <text key={r} x="90" y={i === 0 ? 94 : 90 - radii[i] + 14} textAnchor="middle" className="dm-legend-text">{r}</text>
        ))}
      </svg>
      <ul className="dm-legend-list">
        {RING_ORDER.map((r) => (
          <li key={r} className={`dm-ring-${r}${highlight === r ? " is-hl" : ""}`}>
            <span className="dm-legend-dot" aria-hidden />
            <b>{r} {RING_INFO[r].label}</b>
            <span>{RING_INFO[r].who}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SourceBadge({ view, parentLabel }: { view: Pick<FieldView<unknown>, "source" | "redundant">; parentLabel: string | null }) {
  if (view.source === "own") {
    return <span className="dm-src dm-src-own" title={view.redundant ? "Set here, but identical to the inherited value" : "Set at this level"}>Own setting{view.redundant ? " (same as inherited)" : ""}</span>;
  }
  if (view.source === "inherited") {
    return <span className="dm-src dm-src-inh" title="Merged from the levels above this one">Inherited{parentLabel ? ` via ${parentLabel}` : ""}</span>;
  }
  return <span className="dm-src dm-src-unset">Not set</span>;
}

export function FieldShell({ title, hint, view, parentLabel, readOnly, canInherit, onReset, children, footer }: {
  title: string; hint?: ReactNode; view: Pick<FieldView<unknown>, "source" | "redundant">; parentLabel: string | null; readOnly: boolean;
  canInherit: boolean; onReset: () => void; children: ReactNode; footer?: ReactNode;
}) {
  return (
    <div className={`dm-field is-${view.source}`}>
      <div className="dm-field-head">
        <div className="min-w-0 flex-1">
          <div className="dm-field-title">{title}</div>
          {hint ? <div className="dm-field-hint">{hint}</div> : null}
        </div>
        <div className="dm-field-meta">
          <SourceBadge view={view} parentLabel={parentLabel} />
          {view.source === "own" && canInherit && !readOnly ? (
            <button type="button" className="dm-btn dm-btn-xs" onClick={onReset} title="Remove the own value and use the inherited one">
              <Icon name="undo" size={13} /> Reset to inherited
            </button>
          ) : null}
        </div>
      </div>
      <div className="dm-field-body">{children}</div>
      {footer ? <div className="dm-field-foot">{footer}</div> : null}
    </div>
  );
}

export function ChipsEditor({ values, onChange, disabled, placeholder, suggestions, validate, label }: {
  values: string[]; onChange: (v: string[]) => void; disabled?: boolean; placeholder: string; suggestions?: string[];
  validate?: (v: string) => string | null; label: string;
}) {
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  function commit(fromBlur = false) {
    const el = inputRef.current;
    if (!el) return;
    const v = el.value.trim();
    if (!v) return;
    const err = validate?.(v) ?? null;
    if (err) { el.setCustomValidity(err); if (!fromBlur) el.reportValidity(); return; }
    el.setCustomValidity("");
    if (!values.includes(v)) onChange([...values, v]);
    el.value = "";
  }
  return (
    <div className="dm-chips" aria-label={label}>
      {values.map((v) => (
        <span key={v} className="dm-chip">
          <span className="dm-mono">{v}</span>
          {!disabled ? (
            <button type="button" className="dm-chip-x" aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}><Icon name="x" size={11} /></button>
          ) : null}
        </span>
      ))}
      {values.length === 0 && disabled ? <span className="dm-muted">none</span> : null}
      {!disabled ? (
        <span className="dm-chip-add">
          <input ref={inputRef} className="dm-chip-input dm-mono" placeholder={placeholder} list={suggestions ? listId : undefined}
            aria-label={`Add to ${label}`}
            onInput={(e) => (e.target as HTMLInputElement).setCustomValidity("")}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); } }} onBlur={() => commit(true)} />
          {suggestions ? <datalist id={listId}>{suggestions.filter((s) => !values.includes(s)).map((s) => <option key={s} value={s} />)}</datalist> : null}
        </span>
      ) : null}
    </div>
  );
}

export function Modal({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  const titleId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    (ref.current?.querySelector<HTMLElement>("[data-autofocus]") ?? ref.current?.querySelector<HTMLElement>("button"))?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeRef.current(); };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, []);
  return (
    <div className="dm-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} className="dm-modal" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h2 id={titleId} className="dm-modal-title">{title}</h2>
        <div className="dm-modal-body">{children}</div>
        {footer ? <div className="dm-modal-foot">{footer}</div> : null}
      </div>
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <span className="dm-spinner" role="status" aria-label={label} />;
}
