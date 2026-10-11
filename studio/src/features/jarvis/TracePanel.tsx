import { useMemo, useState } from "react";
import type { FlowGroup, FlowSpec } from "../../api/contracts";
import { formatMs, plural } from "../../design/format";
import { Icon } from "../../design/icons";
import { cx, StatusDot } from "../../design/primitives";
import {
  buildSteps, formatArgs, GROUP_LABEL, GROUP_ORDER, groupTotals, toolCount, totalMs,
  type Step, type TraceFrame,
} from "./turn";

export const GROUP_TEXT: Record<FlowGroup, string> = {
  understand: "text-g-understand",
  retrieve: "text-g-retrieve",
  act: "text-g-act",
  respond: "text-g-respond",
};
export const GROUP_BG: Record<FlowGroup, string> = {
  understand: "bg-g-understand",
  retrieve: "bg-g-retrieve",
  act: "bg-g-act",
  respond: "bg-g-respond",
};

export function TracePanel({ frames, spec, live, stats }: {
  frames: TraceFrame[]; spec: FlowSpec | null; live: boolean; stats?: Record<string, unknown>;
}) {
  const steps = useMemo(() => buildSteps(frames, spec), [frames, spec]);
  const [open, setOpen] = useState<boolean | null>(null);
  const isOpen = open ?? live;
  if (!steps.length && !live) return null;

  const total = totalMs(steps, stats);
  const tools = toolCount(steps);
  const touched = new Set(steps.filter((s) => s.status !== "skip").map((s) => s.group));

  return (
    <div className="mt-3 overflow-hidden rounded-[12px] border border-line bg-surface/70">
      <button
        type="button"
        onClick={() => setOpen(!isOpen)}
        aria-expanded={isOpen}
        className="flex w-full min-w-0 items-center gap-2 px-3 py-2 text-left text-[12.5px] text-muted transition-colors hover:text-ink"
      >
        <Icon name="chevronRight" size={14} className={cx("shrink-0 transition-transform", isOpen && "rotate-90")} />
        <span className="shrink-0 font-medium text-ink-2">How Jarvis handled this</span>
        <span className="min-w-0 truncate">
          {live && !steps.length ? "· starting…" : `· ${plural(steps.length, "step")}`}
          {tools ? ` · ${plural(tools, "tool")}` : ""}
          {total && !live ? ` · ${formatMs(total)}` : ""}
        </span>
        <span className="ml-auto hidden shrink-0 items-center gap-1 sm:flex" aria-hidden="true">
          {GROUP_ORDER.map((g) => (
            <span key={g} className={cx("h-1.5 w-4 rounded-full", touched.has(g) ? GROUP_BG[g] : "bg-line")} />
          ))}
        </span>
      </button>
      {isOpen ? (
        <div className="border-t border-line px-3 pt-3 pb-2">
          <GroupBar steps={steps} />
          <ol className="mt-3">
            {steps.map((s, i) => <StepRow key={s.key} step={s} last={i === steps.length - 1} />)}
            {live ? (
              <li className="flex items-center gap-2 py-1 pl-0.5 text-[12px] text-muted">
                <StatusDot tone="accent" pulse /> working…
              </li>
            ) : null}
          </ol>
        </div>
      ) : null}
    </div>
  );
}

function GroupBar({ steps }: { steps: Step[] }) {
  const totals = groupTotals(steps);
  const present = new Set(steps.map((s) => s.group));
  const sum = GROUP_ORDER.reduce((a, g) => a + totals[g], 0);
  return (
    <div>
      <div className="flex h-1.5 gap-0.5 overflow-hidden rounded-full" aria-hidden="true">
        {GROUP_ORDER.map((g) => (
          <span
            key={g}
            className={cx("h-full rounded-full", present.has(g) ? GROUP_BG[g] : "bg-line")}
            style={{ flexGrow: sum ? Math.max(totals[g], sum * 0.04) : 1, flexBasis: 0 }}
          />
        ))}
      </div>
      <div className="mt-1.5 grid grid-cols-4 gap-1 text-[11px]">
        {GROUP_ORDER.map((g) => (
          <div key={g} className={cx("min-w-0 truncate", present.has(g) ? GROUP_TEXT[g] : "text-faint")}>
            <span className="font-semibold tracking-wide uppercase">{GROUP_LABEL[g]}</span>
            {totals[g] ? <span className="ml-1 font-mono text-muted">{formatMs(totals[g])}</span> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function StepRow({ step: s, last }: { step: Step; last: boolean }) {
  const right =
    s.status === "start" ? "running" : s.status === "skip" ? "skipped" : s.status === "error" ? "error" : formatMs(s.ms) || "done";
  return (
    <li className="relative grid grid-cols-[14px_minmax(0,1fr)_auto] gap-x-2.5 py-1">
      {!last ? <span aria-hidden="true" className="absolute top-[18px] bottom-[-6px] left-[6.5px] w-px bg-line" /> : null}
      <span className="relative pt-[6px]">
        <StatusDot tone={s.status === "error" ? "err" : s.group} pulse={s.status === "start"} className={cx("ring-2 ring-surface", s.status === "skip" && "opacity-35")} />
      </span>
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
          <span className={cx("text-[13px] font-medium", s.status === "skip" ? "text-muted" : "text-ink")}>{s.label}</span>
          <span className={cx("text-[10.5px] font-semibold tracking-wider uppercase", GROUP_TEXT[s.group], s.status === "skip" && "opacity-60")}>{s.group}</span>
        </div>
        {s.detail ? <div className="truncate text-[12px] text-muted" title={s.detail}>{s.detail}</div> : null}
        {s.tools.map((t, i) => (
          <div key={i} className="mt-1 flex min-w-0 items-start gap-1.5 rounded-md border border-line bg-sunk px-2 py-1 text-[12px]">
            <Icon name={t.ok ? "check" : "x"} size={13} className={cx("mt-[2px] shrink-0", t.ok ? "text-ok" : "text-err")} />
            <div className="min-w-0">
              <span className="font-mono text-ink-2">{t.name}</span>
              {t.args && Object.keys(t.args).length ? (
                <span className="ml-1.5 font-mono break-all text-faint">{formatArgs(t.args)}</span>
              ) : null}
              {t.summary ? <div className="text-muted">{t.summary}</div> : null}
            </div>
          </div>
        ))}
      </div>
      <span className={cx("pt-[1px] text-right font-mono text-[11.5px] tabular-nums", s.status === "error" ? "text-err" : "text-muted")}>{right}</span>
    </li>
  );
}
