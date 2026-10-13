// ── Routing ────────────────────────────────────────────────────────────────
/** `param` of #/agents/<thread_id?>; only the first path segment counts. */
export function parseThreadId(param) {
    if (!param)
        return undefined;
    const first = param.split(/[/?]/)[0];
    if (!first)
        return undefined;
    try {
        return decodeURIComponent(first);
    }
    catch {
        return first;
    }
}
// ── Threads ────────────────────────────────────────────────────────────────
function ts(iso) {
    if (!iso)
        return Number.NEGATIVE_INFINITY;
    const t = Date.parse(iso);
    return Number.isNaN(t) ? Number.NEGATIVE_INFINITY : t;
}
/**
 * Chats list order: the Jarvis thread is excluded (it lives in the Jarvis tab); the rest by
 * last_message_at descending, threads without messages last, ties broken by title then id.
 */
export function sortChats(threads) {
    return threads
        .filter((t) => t.kind !== "jarvis")
        .slice()
        .sort((a, b) => {
        const d = ts(b.last_message_at) - ts(a.last_message_at);
        if (d !== 0 && !Number.isNaN(d))
            return d > 0 ? 1 : -1;
        const byTitle = a.title.localeCompare(b.title);
        return byTitle !== 0 ? byTitle : a.thread_id.localeCompare(b.thread_id);
    });
}
/** Insert or replace a thread (e.g. after createThread or a local send) without re-fetching. */
export function upsertThread(threads, next) {
    const i = threads.findIndex((t) => t.thread_id === next.thread_id);
    if (i < 0)
        return [...threads, next];
    const copy = threads.slice();
    copy[i] = next;
    return copy;
}
// ── Messages ───────────────────────────────────────────────────────────────
/** Merge pages / poll results by message_id (incoming wins), ordered oldest → newest. */
export function mergeMessages(existing, incoming) {
    const byId = new Map();
    for (const m of existing)
        byId.set(m.message_id, m);
    for (const m of incoming)
        byId.set(m.message_id, m);
    return [...byId.values()].sort((a, b) => {
        const d = ts(a.created_at) - ts(b.created_at);
        if (d !== 0 && !Number.isNaN(d))
            return d;
        return a.message_id.localeCompare(b.message_id);
    });
}
/** Who wrote a message, from the viewer's perspective. */
export function authorRole(author, meId) {
    if (author.kind === "member")
        return author.id === meId ? "me" : "member";
    if (author.kind === "jarvis")
        return "my-jarvis";
    return "agent";
}
/** A direct thread that Jarvis opened on the member's behalf (handoff from the Jarvis chat). */
export function handoffOrigin(messages) {
    return messages.find((m) => m.author.kind === "jarvis" || Boolean(m.meta?.handoff_thread_id)) ?? null;
}
// ── Contacts ───────────────────────────────────────────────────────────────
const STATUS_RANK = {
    pending_acceptance: 0, verified: 1, invited: 2, unverified: 3, blocked: 4,
};
export function splitContacts(contacts) {
    const byName = (a, b) => a.display_name.localeCompare(b.display_name);
    const pending = contacts.filter((c) => c.status === "pending_acceptance").sort(byName);
    const others = contacts
        .filter((c) => c.status !== "pending_acceptance")
        .sort((a, b) => (a.status === "blocked" ? 1 : 0) - (b.status === "blocked" ? 1 : 0) || byName(a, b));
    return { pending, others };
}
export const STATUS_LABEL = {
    verified: "Verified",
    unverified: "Unverified",
    invited: "Invited",
    pending_acceptance: "Wants to connect",
    blocked: "Blocked",
};
export const STATUS_HINT = {
    verified: "Exchanged signed cards: messages are delivered.",
    unverified: "Known address only. Send an invite so they can verify you.",
    invited: "Invite sent; waiting for their Jarvis to accept.",
    pending_acceptance: "Their Jarvis invited you. Accept to verify them.",
    blocked: "Blocked: nothing is sent or received.",
};
export function statusRank(s) { return STATUS_RANK[s]; }
// ── Share card ─────────────────────────────────────────────────────────────
export const RINGS = [
    { ring: "R1", label: "Personal", who: "only you" },
    { ring: "R2", label: "Family", who: "you and family" },
    { ring: "R3", label: "Household", who: "everyone at home" },
    { ring: "R4", label: "External", who: "agents outside (NANDA)" },
];
export const CATEGORY_LABEL = {
    profile: "Profile",
    calendar: "Calendar",
    reminders: "Reminders",
    shopping: "Shopping",
    family_messages: "Family messages",
    projects: "Projects",
    location: "Location",
    health: "Health",
    contacts: "Contacts",
};
export const CATEGORY_ORDER = Object.keys(CATEGORY_LABEL);
export function categoryLabel(c) {
    return CATEGORY_LABEL[c] ?? c.replace(/_/g, " ").replace(/^./, (x) => x.toUpperCase());
}
export const NEW_PREFIX = "new:";
export function makeNewItem(category, label, value, ring = "R4") {
    const preview = value.length > 28 ? value.slice(0, 28) + "…" : value;
    return {
        item_id: NEW_PREFIX + Math.random().toString(36).slice(2, 10),
        category, label, value, value_preview: preview, ring,
        source: "added", enabled: true, locked: false, isNew: true,
    };
}
/**
 * Minimal PUT body turning `base` (server card) into `draft` (local edits):
 * enabled flips on existing items, additions, and removals of previously added items.
 * Returns null when nothing changed.
 */
export function diffShareCard(base, draft) {
    const baseById = new Map(base.map((i) => [i.item_id, i]));
    const draftIds = new Set(draft.map((i) => i.item_id));
    const items = [];
    const add = [];
    const remove = [];
    for (const d of draft) {
        if (d.isNew || d.item_id.startsWith(NEW_PREFIX)) {
            add.push({ category: d.category, label: d.label, value: d.value ?? "" });
            continue;
        }
        const b = baseById.get(d.item_id);
        if (b && b.enabled !== d.enabled && !(d.locked && d.enabled))
            items.push({ item_id: d.item_id, enabled: d.enabled });
    }
    for (const b of base) {
        if (!draftIds.has(b.item_id) && b.source === "added")
            remove.push(b.item_id);
    }
    if (!items.length && !add.length && !remove.length)
        return null;
    const update = {};
    if (items.length)
        update.items = items;
    if (add.length)
        update.add = add;
    if (remove.length)
        update.remove = remove;
    return update;
}
/** Number of individual edits in an update (for the "N unsaved changes" label). */
export function countChanges(u) {
    if (!u)
        return 0;
    return (u.items?.length ?? 0) + (u.add?.length ?? 0) + (u.remove?.length ?? 0);
}
/** Items grouped by category in canonical category order; unknown categories last (alpha). */
export function groupByCategory(items) {
    const groups = new Map();
    for (const it of items) {
        const g = groups.get(it.category);
        if (g)
            g.push(it);
        else
            groups.set(it.category, [it]);
    }
    const rank = (c) => {
        const i = CATEGORY_ORDER.indexOf(c);
        return i < 0 ? CATEGORY_ORDER.length : i;
    };
    return [...groups.entries()].sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
}
/** What other agents will receive: enabled, unlocked items. */
export function visibleToAgents(items) {
    return items.filter((i) => i.enabled && !i.locked);
}
// ── Formatting ─────────────────────────────────────────────────────────────
export function relativeTime(iso, now = Date.now()) {
    const t = ts(iso);
    if (!Number.isFinite(t))
        return "";
    const s = Math.round((now - t) / 1000);
    if (s < 45)
        return "now";
    const m = Math.round(s / 60);
    if (m < 60)
        return `${m}m`;
    const h = Math.round(m / 60);
    if (h < 24)
        return `${h}h`;
    const d = Math.round(h / 24);
    if (d < 7)
        return `${d}d`;
    return new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
export function clockTime(iso) {
    const t = Date.parse(iso);
    if (Number.isNaN(t))
        return "";
    return new Date(t).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
export function dayLabel(iso, now = Date.now()) {
    const d = new Date(iso);
    const today = new Date(now);
    const yesterday = new Date(now - 86_400_000);
    const same = (a, b) => a.toDateString() === b.toDateString();
    if (same(d, today))
        return "Today";
    if (same(d, yesterday))
        return "Yesterday";
    return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}
/** Two-letter avatar initials ("Felix's Jarvis" → "FJ"). */
export function initials(name) {
    const words = name.replace(/['’]s\b/g, "").split(/\s+/).filter(Boolean);
    return (words.slice(0, 2).map((w) => w[0]).join("") || "?").toUpperCase();
}
/** Stable hue per author id, so agents keep their colour across renders. */
export function hueFor(id) {
    let h = 0;
    for (let i = 0; i < id.length; i++)
        h = (h * 31 + id.charCodeAt(i)) % 360;
    return h;
}
export function meLink(me) {
    return me ? `#/data/member:${me.member_id}/privacy` : "#/data";
}
