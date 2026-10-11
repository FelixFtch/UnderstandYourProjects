// Digest formatting helpers (pure).
import type { ProjectDigest, ProjectStatus } from "../../api/contracts";
import { dayDiff, startOfDay } from "../../design/format";
import type { Tone } from "../../design/primitives";

export const STATUS_META: Record<ProjectStatus, { label: string; tone: Tone; pulse?: boolean }> = {
  analyzed: { label: "Analyzed", tone: "ok" },
  analyzing: { label: "Analyzing", tone: "accent", pulse: true },
  queued: { label: "Queued", tone: "info" },
  stale: { label: "Stale", tone: "warn" },
  failed: { label: "Failed", tone: "err" },
  not_analyzed: { label: "Not analyzed", tone: "neutral" },
};

export function statusMeta(s: string) {
  return STATUS_META[s as ProjectStatus] ?? { label: s, tone: "neutral" as Tone };
}

export const TIER_META: Record<string, { label: string; tone: Tone; hint: string }> = {
  A: { label: "A", tone: "accent", hint: "Key file: read and summarized in full" },
  B: { label: "B", tone: "info", hint: "Supporting file: summarized" },
  C: { label: "C", tone: "neutral", hint: "Structure only: path and symbols" },
  gate: { label: "gate", tone: "warn", hint: "Skipped: vendored, generated or lockfile" },
};

export function tierMeta(tier: string) {
  return TIER_META[tier] ?? TIER_META[tier?.toUpperCase?.()] ?? { label: tier || "?", tone: "neutral" as Tone, hint: "" };
}

export type ChangeBucket = "today" | "yesterday" | "this_week" | "earlier";
const BUCKET_LABEL: Record<ChangeBucket, string> = {
  today: "Today",
  yesterday: "Yesterday",
  this_week: "Earlier this week",
  earlier: "Earlier",
};

type Changed = ProjectDigest["activity"]["changed"][number];

export function bucketOf(iso: string, now: Date): ChangeBucket {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "earlier";
  const diff = dayDiff(d, now);
  if (diff <= 0) return "today";
  if (diff === 1) return "yesterday";
  if (diff < 7) return "this_week";
  return "earlier";
}

/** Group changed files into Today / Yesterday / Earlier this week / Earlier, newest first. */
export function bucketChanges(changed: Changed[], now: Date = new Date()): Array<{ bucket: ChangeBucket; label: string; items: Changed[] }> {
  const order: ChangeBucket[] = ["today", "yesterday", "this_week", "earlier"];
  const groups = new Map<ChangeBucket, Changed[]>(order.map((b) => [b, []]));
  const sorted = [...changed].sort((a, b) => (Date.parse(b.mtime) || 0) - (Date.parse(a.mtime) || 0));
  for (const c of sorted) groups.get(bucketOf(c.mtime, now))!.push(c);
  return order.filter((b) => groups.get(b)!.length).map((b) => ({ bucket: b, label: BUCKET_LABEL[b], items: groups.get(b)! }));
}

function isoDay(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Contiguous `days` bars ending today (missing days = 0). Accepts "YYYY-MM-DD" or ISO dates. */
export function dayBars(byDay: Array<{ date: string; count: number }>, now: Date = new Date(), days = 7) {
  const counts = new Map<string, number>();
  for (const d of byDay ?? []) {
    const key = /^\d{4}-\d{2}-\d{2}$/.test(d.date) ? d.date : isoDay(new Date(d.date));
    counts.set(key, (counts.get(key) ?? 0) + (Number(d.count) || 0));
  }
  const end = startOfDay(now);
  const out: Array<{ date: string; count: number; label: string; isToday: boolean }> = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(end);
    d.setDate(end.getDate() - i);
    const key = isoDay(d);
    out.push({ date: key, count: counts.get(key) ?? 0, label: i === 0 ? "Today" : d.toLocaleDateString(undefined, { weekday: "short" }), isToday: i === 0 });
  }
  return out;
}

/** "inside commontasks" / "contains 3 folders" phrases for a project's place in the hierarchy. */
export function hierarchyPhrases(parentName: string | null, childCount: number): string[] {
  const out: string[] = [];
  if (parentName) out.push(`inside ${parentName}`);
  if (childCount) out.push(`contains ${childCount} ${childCount === 1 ? "folder" : "folders"}`);
  return out;
}
