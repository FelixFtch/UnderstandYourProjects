import type { FlowSpec } from "../../api/contracts";
import { clockTime, dayDiff } from "../../design/format";
import { Icon, type IconName } from "../../design/icons";
import { Markdown } from "../../design/Markdown";
import { Button, Chip, cx, StatusDot } from "../../design/primitives";
import { TracePanel } from "./TracePanel";
import { buildSteps, type Bubble } from "./turn";

const EVIDENCE_ICON: Record<string, IconName> = { file: "file", brain: "brain", project: "project" };

export function MeBubble({ bubble }: { bubble: Bubble }) {
  return (
    <div className="j-rise flex flex-col items-end">
      <div className="max-w-[min(85%,560px)] rounded-[16px] rounded-br-[6px] border border-line bg-raised px-3.5 py-2 text-[15px] leading-relaxed break-words whitespace-pre-wrap text-ink">
        {bubble.text}
      </div>
      <div className="mt-1 pr-1 text-[11.5px] text-faint">
        {bubble.status === "pending" ? "Sending…" : bubble.status === "failed" ? <span className="text-err">Not delivered</span> : clockTime(bubble.createdAt)}
      </div>
    </div>
  );
}

export function JarvisReply({ bubble, spec, live, onRetry }: { bubble: Bubble; spec: FlowSpec | null; live: boolean; onRetry?: () => void }) {
  const streaming = bubble.status === "streaming";
  const current = streaming && !bubble.text ? currentStep(bubble, spec) : null;

  return (
    <article className="j-rise min-w-0" aria-busy={streaming}>
      <header className="mb-1.5 flex items-center gap-2 text-[12px] text-muted">
        <span className="grid size-[22px] place-items-center rounded-full border border-accent/40 font-serif text-[12px] text-accent-ink italic">J</span>
        <span className="font-medium text-ink-2">Jarvis</span>
        <span className="text-faint">{streaming ? "replying…" : clockTime(bubble.createdAt)}</span>
        {bubble.status === "stopped" ? <Chip tone="neutral">stopped</Chip> : null}
      </header>

      <div className="pl-[30px]">
        {bubble.text ? (
          <Markdown text={bubble.text} className={cx("text-[15px] text-ink", streaming && "j-caret")} />
        ) : streaming ? (
          <div className="flex items-center gap-2 py-1 text-[14px] text-muted">
            <StatusDot tone={current?.group ?? "accent"} pulse />
            {current ? `${current.label}…` : "Thinking…"}
          </div>
        ) : null}

        {bubble.errors.map((e, i) => (
          <div key={i} role="alert" className="mt-2 flex items-start gap-2 rounded-control border border-err/30 bg-err-soft px-3 py-2 text-[13px] text-err">
            <Icon name="alert" size={15} className="mt-0.5 shrink-0" />
            <span className="min-w-0 break-words">{e}</span>
          </div>
        ))}

        {bubble.status === "failed" && bubble.question && onRetry ? (
          <Button size="sm" variant="secondary" icon="refresh" className="mt-2" onClick={onRetry}>Try again</Button>
        ) : null}

        {bubble.evidence.length || bubble.handoffs.length ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {bubble.handoffs.map((h, i) => (
              <Chip
                key={`h${i}`}
                tone="accent"
                icon="handoff"
                href={h.thread_id ? `#/agents/${encodeURIComponent(h.thread_id)}` : "#/agents"}
                title={[h.question && `Asked: ${h.question}`, h.answer && `Answer: ${h.answer}`].filter(Boolean).join("\n") || undefined}
              >
                Asked {h.contact} → open chat
              </Chip>
            ))}
            {bubble.evidence.map((e) => (
              <Chip
                key={`${e.kind}|${e.ref}`}
                icon={EVIDENCE_ICON[e.kind] ?? "link"}
                mono={e.kind === "file"}
                href={e.kind === "project" ? `#/devices/${encodeURIComponent(e.ref)}` : undefined}
                title={`${e.kind}: ${e.ref}`}
                className="max-w-[260px]"
              >
                {e.label}
              </Chip>
            ))}
          </div>
        ) : null}

        <TracePanel frames={bubble.frames} spec={spec} live={live} stats={bubble.stats} />
      </div>
    </article>
  );
}

function currentStep(bubble: Bubble, spec: FlowSpec | null) {
  const steps = buildSteps(bubble.frames, spec);
  for (let i = steps.length - 1; i >= 0; i--) if (steps[i].status === "start") return steps[i];
  return steps[steps.length - 1] ?? null;
}

export function DaySeparator({ iso }: { iso: string }) {
  const d = new Date(iso);
  const diff = dayDiff(d, new Date());
  const label = diff === 0 ? "Today" : diff === 1 ? "Yesterday" : d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
  return (
    <div className="flex items-center gap-3 py-1 text-[11px] font-semibold tracking-[0.08em] text-faint uppercase" role="separator">
      <span className="h-px flex-1 bg-line" />
      {label}
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}
