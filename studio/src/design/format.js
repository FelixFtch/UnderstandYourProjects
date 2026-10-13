// Small, dependency-free formatting helpers shared by every view.
import { ApiError } from "../api/client";
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;
function toDate(value) {
    return value instanceof Date ? value : new Date(value);
}
export function startOfDay(d) {
    const x = new Date(d);
    x.setHours(0, 0, 0, 0);
    return x;
}
/** Whole calendar days between two instants in local time (b - a). */
export function dayDiff(a, b) {
    return Math.round((startOfDay(b).getTime() - startOfDay(a).getTime()) / DAY);
}
/** "just now", "4 min ago", "3 h ago", "yesterday", "Tue", "Oct 2", "Oct 2, 2025". */
export function relativeTime(iso, now = new Date()) {
    if (!iso)
        return "never";
    const d = toDate(iso);
    if (Number.isNaN(d.getTime()))
        return "unknown";
    const diff = now.getTime() - d.getTime();
    if (diff < 0)
        return clockTime(iso);
    if (diff < MIN)
        return "just now";
    if (diff < HOUR)
        return `${Math.floor(diff / MIN)} min ago`;
    const days = dayDiff(d, now);
    if (days === 0)
        return `${Math.floor(diff / HOUR)} h ago`;
    if (days === 1)
        return "yesterday";
    if (days < 7)
        return d.toLocaleDateString(undefined, { weekday: "short" });
    if (d.getFullYear() === now.getFullYear())
        return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
export function clockTime(iso) {
    if (!iso)
        return "";
    const d = toDate(iso);
    if (Number.isNaN(d.getTime()))
        return "";
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
export function formatMs(ms) {
    if (ms === null || ms === undefined || Number.isNaN(ms))
        return "";
    if (ms < 1)
        return "<1 ms";
    if (ms < 1000)
        return `${Math.round(ms)} ms`;
    if (ms < 10_000)
        return `${(ms / 1000).toFixed(1)} s`;
    return `${Math.round(ms / 1000)} s`;
}
export function compact(n) {
    if (n === null || n === undefined || Number.isNaN(n))
        return "—";
    if (Math.abs(n) < 1000)
        return String(n);
    if (Math.abs(n) < 10_000)
        return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
    if (Math.abs(n) < 1_000_000)
        return `${Math.round(n / 1000)}k`;
    return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}
export function plural(n, one, many = `${one}s`) {
    return `${n} ${n === 1 ? one : many}`;
}
/** Last path segment, for compact file labels. */
export function basename(path) {
    const clean = path.replace(/\/+$/, "");
    const i = clean.lastIndexOf("/");
    return i >= 0 ? clean.slice(i + 1) : clean;
}
/** Shorten /Users/<name>/… to ~/… for display (metadata only). */
export function tildePath(path) {
    return path.replace(/^\/(Users|home)\/[^/]+/, "~");
}
/**
 * Honest error copy. `service` names what is behind the companion proxy for this view,
 * e.g. "Agent runtime" or "Project knowledge (UYP)".
 */
export function describeError(err, service = "Jarvis Studio API") {
    if (err instanceof ApiError) {
        const s = err.status;
        if (s === 0)
            return { title: "Can't reach the hub", detail: err.message, status: s };
        if (s === 502 || s === 503 || s === 504)
            return { title: `${service} unreachable`, detail: err.message || `HTTP ${s}`, status: s };
        if (s === 403)
            return { title: "Not allowed", detail: err.message || "Your role can't do this.", status: s };
        if (s === 404)
            return { title: "Not found", detail: err.message || "Nothing here (yet).", status: s };
        if (s === 401)
            return { title: "Signed out", detail: "Your session ended. Sign in again.", status: s };
        return { title: "Something went wrong", detail: err.message || `HTTP ${s}`, status: s };
    }
    if (err instanceof DOMException && err.name === "AbortError")
        return { title: "Cancelled", detail: "", status: null };
    if (err instanceof TypeError) {
        return { title: "Can't reach the hub", detail: "The browser could not connect to companion-api. Check the hub or your tunnel to :5120.", status: null };
    }
    return { title: "Something went wrong", detail: err instanceof Error ? err.message : String(err), status: null };
}
