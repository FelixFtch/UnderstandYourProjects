// Cloud usage (qwen) card for the Devices page (added 2026-10-14).
// Renders GET /api/studio/cloud-usage: current mode, today/month/total spend in ¥,
// compact token counts, and the per-surface breakdown (route / persona / split).
import type { CloudUsage, CloudUsageBucket } from "../../api/contracts";
import { compact, relativeTime } from "../../design/format";
import { Icon } from "../../design/icons";
import { Button, Card, Chip, Skeleton } from "../../design/primitives";

/** "¥1.23" — CNY with two decimals. */
export function yuan(n: number): string {
  return `¥${n.toFixed(2)}`;
}

/** "913k in · 246k out" — compact token pair for one bucket. */
export function tokenPair(b: CloudUsageBucket): string {
  return `${compact(b.prompt_tokens)} in · ${compact(b.completion_tokens)} out`;
}

const SURFACE_LABEL: Record<string, string> = { route: "Route", persona: "Persona", split: "Split" };

const PERIODS: Array<[label: string, pick: (u: CloudUsage) => CloudUsageBucket]> = [
  ["Today", (u) => u.today],
  ["This month", (u) => u.month],
  ["All time", (u) => u.total],
];

export function CloudUsageCard({ usage, onRefresh }: { usage: CloudUsage; onRefresh?: () => void }) {
  const cloud = usage.mode === "cloud";
  return (
    <Card className="p-4">
      <div className="flex min-w-0 items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-[10px] border border-accent/30 bg-accent-soft text-accent-ink">
          <Icon name="chip" size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[14px] font-medium text-ink">Cloud usage (qwen)</div>
          <div className="mt-0.5 truncate text-[12px] text-muted">Text-only cloud turns, metered by companion-api · {usage.currency}</div>
        </div>
        <Chip tone={cloud ? "accent" : "ok"} icon="activity">{cloud ? "Cloud" : "Local"}</Chip>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 border-t border-line pt-3 sm:grid-cols-3">
        {PERIODS.map(([label, pick]) => {
          const b = pick(usage);
          return (
            <div key={label} className="min-w-0">
              <div className="text-[11.5px] text-muted">{label}</div>
              <div className="mt-0.5 text-[21px] font-semibold tabular-nums text-ink">{yuan(b.cost_yuan)}</div>
              <div className="mt-0.5 text-[11.5px] text-faint tabular-nums">{tokenPair(b)} tokens</div>
            </div>
          );
        })}
      </div>

      {usage.by_surface.length ? (
        <table className="mt-3 w-full border-t border-line text-[12px] tabular-nums">
          <thead>
            <tr className="text-left text-[11px] tracking-[0.06em] text-muted uppercase">
              <th scope="col" className="pt-2.5 pb-1 font-medium">Surface</th>
              <th scope="col" className="pt-2.5 pb-1 font-medium">Tokens in</th>
              <th scope="col" className="pt-2.5 pb-1 font-medium">Tokens out</th>
              <th scope="col" className="pt-2.5 pb-1 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {usage.by_surface.map((row) => (
              <tr key={row.surface} className="border-t border-line/60 text-ink-2">
                <td className="py-1.5 font-medium">{SURFACE_LABEL[row.surface] ?? row.surface}</td>
                <td className="py-1.5">{compact(row.prompt_tokens)}</td>
                <td className="py-1.5">{compact(row.completion_tokens)}</td>
                <td className="py-1.5 text-right">{yuan(row.cost_yuan)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <div className="mt-3 flex items-center justify-between gap-2 border-t border-line pt-2.5 text-[11.5px] text-muted">
        <span>Updated {relativeTime(usage.updated_at)}</span>
        {onRefresh ? <Button size="sm" variant="ghost" icon="refresh" onClick={onRefresh} aria-label="Refresh cloud usage" /> : null}
      </div>
    </Card>
  );
}

export function CloudUsageCardSkeleton() {
  return <Skeleton className="h-[220px] rounded-card" />;
}
