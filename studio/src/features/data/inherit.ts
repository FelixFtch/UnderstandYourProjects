// Pure policy-inheritance helpers for the Data feature (§5). Unit-tested.
// A scope's own `values` override the merged `inherited` values of its ancestors per leaf key.
import type { PolicyDomain, PolicyScope, PrivacyCategory, Ring } from "../../api/contracts";

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
type Obj = Record<string, unknown>;

export const DOMAINS: PolicyDomain[] = ["privacy", "ha", "schedule"];
export const DOMAIN_LABEL: Record<PolicyDomain, string> = { privacy: "Privacy rings", ha: "Home Assistant", schedule: "Scheduling" };

// 2026-10-14: "Model" is a page-level tab next to the policy domains (the local/cloud
// switch is one household-wide setting, not a per-scope inheritable policy domain).
export type DataTab = PolicyDomain | "model";
export const TAB_LABEL: Record<DataTab, string> = { ...DOMAIN_LABEL, model: "Model" };

export const CATEGORIES: PrivacyCategory[] = [
  "profile", "calendar", "reminders", "shopping", "family_messages", "projects", "location", "health", "contacts",
];

export const CATEGORY_INFO: Record<PrivacyCategory, { label: string; hint: string }> = {
  profile: { label: "Profile", hint: "Name, pronouns, how to address you" },
  calendar: { label: "Calendar", hint: "Events and free/busy times" },
  reminders: { label: "Reminders", hint: "Your reminders and to-dos" },
  shopping: { label: "Shopping", hint: "Shopping lists" },
  family_messages: { label: "Family messages", hint: "Messages between household members" },
  projects: { label: "Projects", hint: "Analyzed folders, digests and activity" },
  location: { label: "Location", hint: "Where you are, roughly" },
  health: { label: "Health", hint: "Health notes and appointments" },
  contacts: { label: "Contacts", hint: "People and agents you know" },
};

export const RING_INFO: Record<Ring, { label: string; who: string; long: string }> = {
  R1: { label: "Personal", who: "only you", long: "Only you. Jarvis uses it when it recognises you, and never mentions it to anyone else." },
  R2: { label: "Family", who: "you and family", long: "You and your family members." },
  R3: { label: "Household", who: "everyone at home", long: "Anyone in the household, including guests Jarvis doesn't recognise." },
  R4: { label: "External", who: "agents outside", long: "Can leave the house: other Jarvis agents (NANDA Town) may receive it." },
};
export const RING_ORDER: Ring[] = ["R1", "R2", "R3", "R4"];

// ── Generic object helpers ───────────────────────────────────────────────

export function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => deepEqual(x, b[i]));
  if (isObj(a) && isObj(b)) {
    const ka = Object.keys(a).filter((k) => a[k] !== undefined);
    const kb = Object.keys(b).filter((k) => b[k] !== undefined);
    return ka.length === kb.length && ka.every((k) => deepEqual(a[k], b[k]));
  }
  return false;
}

/** Child-over-parent merge: objects merge per key; arrays, scalars and null replace. */
export function deepMerge<T>(base: unknown, over: unknown): T {
  if (over === undefined) return clone(base) as T;
  if (!isObj(base) || !isObj(over)) return clone(over) as T;
  const out: Obj = { ...(clone(base) as Obj) };
  for (const [k, v] of Object.entries(over)) {
    if (v === undefined) continue;
    out[k] = isObj(out[k]) && isObj(v) ? deepMerge(out[k], v) : clone(v);
  }
  return out as T;
}

export function clone<T>(v: T): T {
  return v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T);
}

export function getPath(obj: unknown, path: string[]): unknown {
  let cur: unknown = obj;
  for (const k of path) {
    if (!isObj(cur)) return undefined;
    cur = cur[k];
  }
  return cur;
}

/** Immutable set; creates intermediate objects. */
export function setPath<T extends Obj>(obj: T | undefined, path: string[], value: unknown): T {
  const root: Obj = isObj(obj) ? { ...obj } : {};
  let cur = root;
  path.forEach((k, i) => {
    if (i === path.length - 1) { cur[k] = clone(value); return; }
    const next = isObj(cur[k]) ? { ...(cur[k] as Obj) } : {};
    cur[k] = next;
    cur = next;
  });
  return root as T;
}

/** Immutable delete; prunes objects left empty so "reset" really removes the override. */
export function unsetPath<T extends Obj>(obj: T | undefined, path: string[]): T {
  if (!isObj(obj)) return {} as T;
  const [head, ...rest] = path;
  const copy: Obj = { ...obj };
  if (!rest.length) {
    delete copy[head];
  } else if (isObj(copy[head])) {
    const child = unsetPath(copy[head] as Obj, rest);
    if (Object.keys(child).length) copy[head] = child; else delete copy[head];
  }
  return copy as T;
}

// ── Field views (own vs inherited vs effective) ──────────────────────────

export type Source = "own" | "inherited" | "unset";

export interface FieldView<V> {
  /** Value to show in the editor (local draft): own if set, else inherited. */
  value: V | undefined;
  own: V | undefined;
  inherited: V | undefined;
  /** Server-computed effective value for the saved state. */
  effective: V | undefined;
  source: Source;
  /** Own value set and different from what would be inherited. */
  overrides: boolean;
  /** Own value set but identical to the inherited one (reset is a no-op for the result). */
  redundant: boolean;
}

export function fieldView<V>(own: unknown, inherited: unknown, effective: unknown, path: string[]): FieldView<V> {
  const o = getPath(own, path) as V | undefined;
  const inh = getPath(inherited, path) as V | undefined;
  const eff = getPath(effective, path) as V | undefined;
  const source: Source = o !== undefined ? "own" : inh !== undefined ? "inherited" : "unset";
  const merged = o === undefined ? clone(inh) : inh === undefined ? clone(o) : deepMerge<V>(inh, o);
  return {
    value: merged,
    own: o, inherited: inh, effective: eff, source,
    overrides: o !== undefined && inh !== undefined && !deepEqual(merged, inh),
    redundant: o !== undefined && inh !== undefined && deepEqual(merged, inh),
  };
}

// ── Privacy ──────────────────────────────────────────────────────────────

export interface RingSetting { ring: Ring; share_with_agents: boolean }

export interface PrivacyRow extends FieldView<Partial<RingSetting>> {
  category: PrivacyCategory;
  /** Local result (inherited merged with the draft's own value), completed with safe defaults. */
  local: RingSetting;
  /** Own entry sets only some keys (e.g. only `ring`); the rest still comes from above. */
  partial: boolean;
}

export const SAFE_DEFAULT: RingSetting = { ring: "R1", share_with_agents: false };

export function privacyRows(own: unknown, inherited: unknown, effective: unknown): PrivacyRow[] {
  return CATEGORIES.map((category) => {
    const v = fieldView<Partial<RingSetting>>(own, inherited, effective, ["categories", category]);
    const local = { ...SAFE_DEFAULT, ...(v.value ?? {}) } as RingSetting;
    const ownKeys = v.own ? Object.keys(v.own).filter((k) => (v.own as Obj)[k] !== undefined) : [];
    return { ...v, category, local, partial: v.source === "own" && ownKeys.length < 2 };
  });
}

/**
 * Next own values after choosing a ring and/or the share flag for one category.
 * Always writes a complete {ring, share_with_agents} pair and enforces "share only at R4".
 */
export function setPrivacy(own: unknown, inherited: unknown, category: PrivacyCategory, patch: Partial<RingSetting>): Obj {
  const current = { ...SAFE_DEFAULT, ...(fieldView<Partial<RingSetting>>(own, inherited, undefined, ["categories", category]).value ?? {}) };
  const next: RingSetting = { ...current, ...patch } as RingSetting;
  if (next.ring !== "R4") next.share_with_agents = false;
  return setPath(isObj(own) ? own : {}, ["categories", category], next);
}

export function validatePrivacy(values: unknown): string[] {
  const cats = getPath(values, ["categories"]);
  if (!isObj(cats)) return [];
  const errors: string[] = [];
  for (const [cat, v] of Object.entries(cats)) {
    if (isObj(v) && v.share_with_agents === true && v.ring !== undefined && v.ring !== "R4") {
      errors.push(`${CATEGORY_INFO[cat as PrivacyCategory]?.label ?? cat}: “share with agents” needs ring R4`);
    }
  }
  return errors;
}

export function explainPrivacy(s: Partial<RingSetting> | undefined): { headline: string; detail: string } {
  if (!s || !s.ring) return { headline: "Not set anywhere", detail: "No level defines it, so Jarvis keeps it private." };
  const info = RING_INFO[s.ring];
  const headline = `${s.ring} ${info.label}${s.ring === "R4" ? (s.share_with_agents ? " · shared with agents" : " · not on share cards") : ""}`;
  let detail = info.long;
  if (s.ring === "R4") {
    detail += s.share_with_agents
      ? " It is switched on by default on every new agent chat's share card."
      : " It starts switched off on share cards; you can enable it per chat.";
  } else {
    detail += " Agent chats offer it switched off.";
  }
  return { headline, detail };
}

// ── Scope tree & routing ─────────────────────────────────────────────────

const KIND_RANK: Record<PolicyScope["kind"], number> = { town: 0, household: 1, member: 2, guest: 3 };

export interface ScopeNode { scope: PolicyScope; depth: number }

/** Depth-first order: Town default → Household → members (alphabetical) → Guest. */
export function flattenScopes(scopes: PolicyScope[]): ScopeNode[] {
  const ids = new Set(scopes.map((s) => s.scope));
  const children = new Map<string | null, PolicyScope[]>();
  for (const s of scopes) {
    const parent = s.parent && ids.has(s.parent) ? s.parent : null;
    const list = children.get(parent) ?? [];
    list.push(s);
    children.set(parent, list);
  }
  const sort = (xs: PolicyScope[]) => xs.slice().sort((a, b) => KIND_RANK[a.kind] - KIND_RANK[b.kind] || a.label.localeCompare(b.label));
  const out: ScopeNode[] = [];
  const walk = (parent: string | null, depth: number, seen: Set<string>) => {
    for (const s of sort(children.get(parent) ?? [])) {
      if (seen.has(s.scope)) continue;
      seen.add(s.scope);
      out.push({ scope: s, depth });
      walk(s.scope, depth + 1, seen);
    }
  };
  walk(null, 0, new Set());
  return out;
}

/** Ancestors from the root down to (and including) `scope`. */
export function scopeChain(scopes: PolicyScope[], scope: string): PolicyScope[] {
  const byId = new Map(scopes.map((s) => [s.scope, s]));
  const chain: PolicyScope[] = [];
  let cur = byId.get(scope);
  const guard = new Set<string>();
  while (cur && !guard.has(cur.scope)) {
    guard.add(cur.scope);
    chain.unshift(cur);
    cur = cur.parent ? byId.get(cur.parent) : undefined;
  }
  return chain;
}

export const KIND_INFO: Record<PolicyScope["kind"], { title: string; text: string }> = {
  town: { title: "NANDA Town default", text: "What any external Jarvis may get. The root every other level inherits from." },
  household: { title: "Household baseline", text: "Applies to everyone at home unless a person overrides it." },
  member: { title: "Person", text: "Inherits the household, then overrides individual settings." },
  guest: { title: "Guests", text: "Unregistered speakers. Never more than the household allows; guests can't change anything." },
};

/** Route param of #/data/<scope>/<domain?> → parts. Scope ids may contain ':' (member:robin). */
export function parseDataRoute(raw: string | undefined): { scope?: string; domain?: DataTab } {
  if (!raw) return {};
  const [s, d] = raw.replace(/^\/+/, "").split(/[/?]/);
  let scope: string | undefined;
  try { scope = s ? decodeURIComponent(s) : undefined; } catch { scope = s; }
  const domain = DOMAINS.includes(d as PolicyDomain) ? (d as PolicyDomain) : d === "model" ? "model" : undefined;
  return { scope, domain };
}

export function dataHash(scope: string, domain: DataTab): string {
  return `#/data/${scope}/${domain}`;
}

// ── Schedule / HA helpers ────────────────────────────────────────────────

export function validateSchedule(values: unknown): string[] {
  const errors: string[] = [];
  const lead = getPath(values, ["reminder_lead_minutes"]);
  if (lead !== undefined && (typeof lead !== "number" || !Number.isInteger(lead) || lead < 0 || lead > 1440)) {
    errors.push("Reminder lead time must be a whole number of minutes between 0 and 1440");
  }
  const qh = getPath(values, ["quiet_hours"]);
  if (isObj(qh)) {
    const ok = (t: unknown) => typeof t === "string" && /^([01]\d|2[0-3]):[0-5]\d$/.test(t);
    if (!ok(qh.start) || !ok(qh.end)) errors.push("Quiet hours need a start and end time (HH:MM)");
  }
  return errors;
}

export function isEntityId(s: string): boolean {
  return /^[a-z_]+\.[a-z0-9_]+$/.test(s);
}
