import { dayDiff, startOfDay } from "../../design/format";
export const STATUS_META = {
    analyzed: { label: "Analyzed", tone: "ok" },
    analyzing: { label: "Analyzing", tone: "accent", pulse: true },
    queued: { label: "Queued", tone: "info" },
    stale: { label: "Stale", tone: "warn" },
    failed: { label: "Failed", tone: "err" },
    not_analyzed: { label: "Not analyzed", tone: "neutral" },
};
export function statusMeta(s) {
    return STATUS_META[s] ?? { label: s, tone: "neutral" };
}
export const TIER_META = {
    A: { label: "A", tone: "accent", hint: "Key file: read and summarized in full" },
    B: { label: "B", tone: "info", hint: "Supporting file: summarized" },
    C: { label: "C", tone: "neutral", hint: "Structure only: path and symbols" },
    gate: { label: "gate", tone: "warn", hint: "Skipped: vendored, generated or lockfile" },
};
export function tierMeta(tier) {
    return TIER_META[tier] ?? TIER_META[tier?.toUpperCase?.()] ?? { label: tier || "?", tone: "neutral", hint: "" };
}
const BUCKET_LABEL = {
    today: "Today",
    yesterday: "Yesterday",
    this_week: "Earlier this week",
    earlier: "Earlier",
};
export function bucketOf(iso, now) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime()))
        return "earlier";
    const diff = dayDiff(d, now);
    if (diff <= 0)
        return "today";
    if (diff === 1)
        return "yesterday";
    if (diff < 7)
        return "this_week";
    return "earlier";
}
/** Group changed files into Today / Yesterday / Earlier this week / Earlier, newest first. */
export function bucketChanges(changed, now = new Date()) {
    const order = ["today", "yesterday", "this_week", "earlier"];
    const groups = new Map(order.map((b) => [b, []]));
    const sorted = [...changed].sort((a, b) => (Date.parse(b.mtime) || 0) - (Date.parse(a.mtime) || 0));
    for (const c of sorted)
        groups.get(bucketOf(c.mtime, now)).push(c);
    return order.filter((b) => groups.get(b).length).map((b) => ({ bucket: b, label: BUCKET_LABEL[b], items: groups.get(b) }));
}
function isoDay(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
}
/** Contiguous `days` bars ending today (missing days = 0). Accepts "YYYY-MM-DD" or ISO dates. */
export function dayBars(byDay, now = new Date(), days = 7) {
    const counts = new Map();
    for (const d of byDay ?? []) {
        const key = /^\d{4}-\d{2}-\d{2}$/.test(d.date) ? d.date : isoDay(new Date(d.date));
        counts.set(key, (counts.get(key) ?? 0) + (Number(d.count) || 0));
    }
    const end = startOfDay(now);
    const out = [];
    for (let i = days - 1; i >= 0; i--) {
        const d = new Date(end);
        d.setDate(end.getDate() - i);
        const key = isoDay(d);
        out.push({ date: key, count: counts.get(key) ?? 0, label: i === 0 ? "Today" : d.toLocaleDateString(undefined, { weekday: "short" }), isToday: i === 0 });
    }
    return out;
}
/** "inside commontasks" / "contains 3 folders" phrases for a project's place in the hierarchy. */
export function hierarchyPhrases(parentName, childCount) {
    const out = [];
    if (parentName)
        out.push(`inside ${parentName}`);
    if (childCount)
        out.push(`contains ${childCount} ${childCount === 1 ? "folder" : "folders"}`);
    return out;
}
