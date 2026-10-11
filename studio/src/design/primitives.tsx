// Design primitives for Jarvis Studio. Token-driven (see tokens.css); no third-party UI kit.
// Shared by every feature (FRONTEND-A and FRONTEND-B). Keep them small and boring.
import { useEffect, useId, useRef, type ButtonHTMLAttributes, type CSSProperties, type HTMLAttributes, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon, type IconName } from "./icons";
import { describeError } from "./format";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export type Tone =
  | "neutral" | "accent" | "ok" | "warn" | "err" | "info"
  | "understand" | "retrieve" | "act" | "respond";

const CHIP_TONE: Record<Tone, string> = {
  neutral: "bg-sunk text-ink-2 border-line",
  accent: "bg-accent-soft text-accent-ink border-accent/25",
  ok: "bg-ok-soft text-ok border-ok/25",
  warn: "bg-warn-soft text-warn border-warn/25",
  err: "bg-err-soft text-err border-err/25",
  info: "bg-info-soft text-info border-info/25",
  understand: "bg-g-understand/12 text-g-understand border-g-understand/30",
  retrieve: "bg-g-retrieve/12 text-g-retrieve border-g-retrieve/30",
  act: "bg-g-act/12 text-g-act border-g-act/30",
  respond: "bg-g-respond/12 text-g-respond border-g-respond/30",
};

const DOT_TONE: Record<Tone, string> = {
  neutral: "bg-faint text-faint",
  accent: "bg-accent text-accent",
  ok: "bg-ok text-ok",
  warn: "bg-warn text-warn",
  err: "bg-err text-err",
  info: "bg-info text-info",
  understand: "bg-g-understand text-g-understand",
  retrieve: "bg-g-retrieve text-g-retrieve",
  act: "bg-g-act text-g-act",
  respond: "bg-g-respond text-g-respond",
};

// ── Button ──────────────────────────────────────────────────────────────────
type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const BTN_VARIANT: Record<Variant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-ink border border-transparent",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-sunk",
  ghost: "text-ink-2 border border-transparent hover:bg-sunk hover:text-ink",
  danger: "bg-surface text-err border border-err/35 hover:bg-err-soft",
};
const BTN_SIZE: Record<Size, string> = {
  sm: "h-8 px-2.5 text-[13px] gap-1.5",
  md: "h-9 px-3.5 text-sm gap-2",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: IconName;
  iconRight?: IconName;
  loading?: boolean;
}

export function Button({ variant = "secondary", size = "md", icon, iconRight, loading, className, children, disabled, type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={cx(
        "inline-flex shrink-0 items-center justify-center rounded-control font-medium whitespace-nowrap transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-55",
        BTN_VARIANT[variant], BTN_SIZE[size], className,
      )}
      {...rest}
    >
      {loading ? <Spinner size={size === "sm" ? 13 : 15} /> : icon ? <Icon name={icon} size={size === "sm" ? 15 : 16} /> : null}
      {children}
      {iconRight && !loading ? <Icon name={iconRight} size={size === "sm" ? 15 : 16} /> : null}
    </button>
  );
}

export function IconButton({ icon, label, className, size = 34, ...rest }: { icon: IconName; label: string; size?: number } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children">) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cx("inline-flex shrink-0 items-center justify-center rounded-control text-muted transition-colors hover:bg-sunk hover:text-ink disabled:opacity-50", className)}
      style={{ width: size, height: size }}
      {...rest}
    >
      <Icon name={icon} size={Math.round(size * 0.5)} />
    </button>
  );
}

// ── Chip ────────────────────────────────────────────────────────────────────
export interface ChipProps {
  tone?: Tone;
  icon?: IconName;
  children: ReactNode;
  title?: string;
  href?: string;
  onClick?: () => void;
  className?: string;
  mono?: boolean;
}

export function Chip({ tone = "neutral", icon, children, title, href, onClick, className, mono }: ChipProps) {
  const cls = cx(
    "inline-flex max-w-full min-w-0 items-center gap-1 rounded-full border px-2 py-[1px] text-[12px] leading-[18px] font-medium",
    mono && "font-mono text-[11.5px]",
    CHIP_TONE[tone],
    (href || onClick) && "cursor-pointer transition-[filter] hover:brightness-95 dark:hover:brightness-125",
    className,
  );
  const inner = (
    <>
      {icon ? <Icon name={icon} size={12} strokeWidth={1.8} /> : null}
      <span className="truncate">{children}</span>
    </>
  );
  if (href) return <a href={href} className={cls} title={title}>{inner}</a>;
  if (onClick) return <button type="button" onClick={onClick} className={cls} title={title}>{inner}</button>;
  return <span className={cls} title={title}>{inner}</span>;
}

export function StatusDot({ tone = "neutral", pulse, className, label }: { tone?: Tone; pulse?: boolean; className?: string; label?: string }) {
  return (
    <span
      role={label ? "img" : undefined}
      aria-label={label}
      title={label}
      className={cx("inline-block size-2 shrink-0 rounded-full", DOT_TONE[tone], pulse && "j-pulse", className)}
    />
  );
}

// ── Surfaces ────────────────────────────────────────────────────────────────
export function Card({ children, className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("rounded-card border border-line bg-surface shadow-card", className)} {...rest}>
      {children}
    </div>
  );
}

export function SectionHeader({ eyebrow, title, description, actions, className, level = 2 }: {
  eyebrow?: ReactNode; title: ReactNode; description?: ReactNode; actions?: ReactNode; className?: string; level?: 1 | 2 | 3;
}) {
  const H = (`h${level}`) as "h1" | "h2" | "h3";
  return (
    <div className={cx("flex flex-wrap items-end justify-between gap-x-4 gap-y-3", className)}>
      <div className="min-w-0 max-w-[68ch]">
        {eyebrow ? <div className="mb-1 text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">{eyebrow}</div> : null}
        <H className={cx("font-serif text-ink", level === 1 ? "text-[26px] leading-tight" : level === 2 ? "text-[19px] leading-snug" : "text-base")}>{title}</H>
        {description ? <p className="mt-1 text-[13.5px] text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

// ── Loading / empty / error ─────────────────────────────────────────────────
export function Skeleton({ className, style }: { className?: string; style?: CSSProperties }) {
  return <div aria-hidden="true" className={cx("j-skeleton rounded-md", className ?? "h-4 w-full")} style={style} />;
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cx("space-y-2", className)} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className="h-3.5" style={{ width: `${i === lines - 1 ? 58 : 100 - (i % 3) * 9}%` }} />
      ))}
    </div>
  );
}

export function Spinner({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={cx("animate-spin", className)} aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

export function EmptyState({ icon = "sparkle", title, body, action, className }: {
  icon?: IconName; title: ReactNode; body?: ReactNode; action?: ReactNode; className?: string;
}) {
  return (
    <div className={cx("flex flex-col items-center justify-center px-6 py-10 text-center", className)}>
      <div className="mb-3 grid size-10 place-items-center rounded-full border border-line bg-sunk text-muted">
        <Icon name={icon} size={18} />
      </div>
      <div className="font-serif text-[17px] text-ink">{title}</div>
      {body ? <div className="mt-1 max-w-[46ch] text-[13.5px] text-muted">{body}</div> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ error, service, onRetry, title, compact, className }: {
  error: unknown; service?: string; onRetry?: () => void; title?: string; compact?: boolean; className?: string;
}) {
  const d = describeError(error, service);
  // a network-level diagnosis ("Agent runtime unreachable") is more useful than a caller's generic title
  const unreachable = d.status === 0 || d.status === 502 || d.status === 503 || d.status === 504 || d.title.startsWith("Can't reach");
  const heading = unreachable ? d.title : title ?? d.title;
  if (compact) {
    return (
      <div role="alert" className={cx("flex items-start gap-2 rounded-control border border-err/25 bg-err-soft px-3 py-2 text-[13px] text-err", className)}>
        <Icon name="alert" size={15} className="mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <span className="font-medium">{heading}</span>
          {d.detail ? <span className="text-err/80"> — {d.detail}</span> : null}
        </div>
        {onRetry ? <button type="button" onClick={onRetry} className="shrink-0 font-medium underline underline-offset-2">Retry</button> : null}
      </div>
    );
  }
  return (
    <div role="alert" className={cx("flex flex-col items-center justify-center px-6 py-10 text-center", className)}>
      <div className="mb-3 grid size-10 place-items-center rounded-full border border-err/25 bg-err-soft text-err">
        <Icon name="alert" size={18} />
      </div>
      <div className="font-serif text-[17px] text-ink">{heading}</div>
      {d.detail ? <div className="mt-1 max-w-[52ch] text-[13px] break-words text-muted">{d.detail}{d.status ? ` (HTTP ${d.status})` : ""}</div> : null}
      {onRetry ? <Button className="mt-4" size="sm" icon="refresh" onClick={onRetry}>Try again</Button> : null}
    </div>
  );
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd className={cx("inline-flex h-5 min-w-5 items-center justify-center rounded border border-line-strong bg-surface px-1 font-sans text-[11px] font-medium text-muted", className)}>
      {children}
    </kbd>
  );
}

export function ProgressBar({ value, max = 1, tone = "accent", className, label }: { value: number; max?: number; tone?: Tone; className?: string; label?: string }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      className={cx("h-1.5 w-full overflow-hidden rounded-full bg-sunk", className)}
    >
      <div className={cx("h-full rounded-full transition-[width] duration-500", DOT_TONE[tone])} style={{ width: `${pct}%` }} />
    </div>
  );
}

// ── Segmented control ───────────────────────────────────────────────────────
export function Segmented<T extends string>({ value, options, onChange, label, className }: {
  value: T; options: Array<{ value: T; label: ReactNode }>; onChange: (v: T) => void; label: string; className?: string;
}) {
  return (
    <div role="tablist" aria-label={label} className={cx("inline-flex rounded-control border border-line bg-sunk p-0.5", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            "h-7 rounded-[7px] px-3 text-[13px] font-medium transition-colors",
            o.value === value ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ── Modal ───────────────────────────────────────────────────────────────────
export function Modal({ open, onClose, title, description, children, footer, width = 520 }: {
  open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; children: ReactNode; footer?: ReactNode; width?: number;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const restore = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restore.current = document.activeElement as HTMLElement | null;
    const t = window.setTimeout(() => {
      const p = panel.current;
      const first = p?.querySelector<HTMLElement>("[data-autofocus]") ?? p?.querySelector<HTMLElement>("input, select, textarea") ?? p?.querySelector<HTMLElement>("button");
      first?.focus();
    }, 20);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
      if (e.key === "Tab" && panel.current) {
        const nodes = Array.from(panel.current.querySelectorAll<HTMLElement>("a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex='-1'])"));
        if (!nodes.length) return;
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("keydown", onKey, true);
      restore.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-6">
      <div className="absolute inset-0 bg-[rgb(20_16_8/0.38)] backdrop-blur-[2px]" onClick={onClose} aria-hidden="true" />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="j-rise relative flex max-h-[min(88dvh,760px)] w-full flex-col overflow-hidden rounded-t-card border border-line bg-surface shadow-pop sm:rounded-card"
        style={{ maxWidth: width }}
      >
        <div className="flex items-start gap-3 border-b border-line px-5 pt-4 pb-3">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="font-serif text-[19px] text-ink">{title}</h2>
            {description ? <p className="mt-0.5 text-[13px] text-muted">{description}</p> : null}
          </div>
          <IconButton icon="x" label="Close" onClick={onClose} size={30} />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer ? <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line bg-canvas/50 px-5 py-3">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}

// ── Form field ──────────────────────────────────────────────────────────────
export const inputClass =
  "h-9 w-full min-w-0 rounded-control border border-line-strong bg-raised px-3 text-sm text-ink placeholder:text-faint " +
  "transition-colors focus:border-accent focus:outline-none focus-visible:outline-none focus:ring-2 focus:ring-accent/25";

export function Field({ label, hint, children, htmlFor }: { label: ReactNode; hint?: ReactNode; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-ink-2">{label}</label>
      {children}
      {hint ? <div className="text-[12px] text-muted">{hint}</div> : null}
    </div>
  );
}
