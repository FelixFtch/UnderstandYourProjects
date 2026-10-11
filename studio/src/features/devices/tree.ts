// Folder hierarchy logic (pure). Mirrors UYP's registry relation rules (STUDIO_V2 §6.2):
// an ancestor folder becomes the parent of analyzed folders below it; a descendant
// becomes a child of the deepest analyzed folder above it; siblings share a parent.
import type { ProjectList, ProjectSummary, ProjectTreeNode } from "../../api/contracts";
import { tildePath } from "../../design/format";

export interface ProjectForest {
  byId: Map<string, ProjectSummary>;
  roots: string[];
  children: Map<string, string[]>;
  parent: Map<string, string | null>;
}

export function buildForest(list: ProjectList | null | undefined): ProjectForest {
  const byId = new Map<string, ProjectSummary>();
  for (const p of list?.projects ?? []) byId.set(p.project_id, p);
  const children = new Map<string, string[]>();
  const parent = new Map<string, string | null>();
  const roots: string[] = [];

  const attach = (id: string, par: string | null) => {
    parent.set(id, par);
    if (!children.has(id)) children.set(id, []);
    if (par) {
      const list = children.get(par) ?? [];
      list.push(id);
      children.set(par, list);
    } else roots.push(id);
  };

  // 1) the server's tree, if any (unknown ids are skipped; their children lift to the nearest known ancestor)
  const walk = (nodes: ProjectTreeNode[] | undefined, par: string | null) => {
    for (const n of nodes ?? []) {
      if (!n || typeof n.project_id !== "string") continue;
      const known = byId.has(n.project_id) && !parent.has(n.project_id);
      if (known) attach(n.project_id, par);
      walk(n.children, known ? n.project_id : par);
    }
  };
  walk(list?.tree, null);

  // 2) anything the tree did not place: use parent_id once that parent is placed
  //    (a parent_id cycle is broken by promoting one member to a root)
  const createsCycle = (id: string, par: string): boolean => {
    let cur: string | null = par;
    const seen = new Set<string>();
    while (cur) {
      if (cur === id || seen.has(cur)) return true;
      seen.add(cur);
      cur = parent.get(cur) ?? null;
    }
    return false;
  };
  const pending = [...byId.values()].filter((p) => !parent.has(p.project_id));
  while (pending.length) {
    let progress = false;
    for (let i = 0; i < pending.length; i++) {
      const p = pending[i];
      const par = p.parent_id && p.parent_id !== p.project_id && byId.has(p.parent_id) ? p.parent_id : null;
      if (par && !parent.has(par)) continue; // wait for the parent
      attach(p.project_id, par && !createsCycle(p.project_id, par) ? par : null);
      pending.splice(i, 1);
      i--;
      progress = true;
    }
    if (!progress) attach(pending.shift()!.project_id, null);
  }

  return { byId, roots, children, parent };
}

export function ancestors(forest: ProjectForest, id: string): ProjectSummary[] {
  const out: ProjectSummary[] = [];
  const seen = new Set<string>([id]);
  let cur = forest.parent.get(id) ?? null;
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    const p = forest.byId.get(cur);
    if (p) out.unshift(p);
    cur = forest.parent.get(cur) ?? null;
  }
  return out;
}

export function descendantIds(forest: ProjectForest, id: string): string[] {
  const out: string[] = [];
  const stack = [...(forest.children.get(id) ?? [])];
  const seen = new Set<string>();
  while (stack.length) {
    const c = stack.pop()!;
    if (seen.has(c)) continue;
    seen.add(c);
    out.push(c);
    stack.push(...(forest.children.get(c) ?? []));
  }
  return out;
}

export interface TreeRow {
  project: ProjectSummary;
  depth: number;
  parentId: string | null;
  childCount: number;
  expanded: boolean;
  /** false when shown only as context for a matching descendant */
  match: boolean;
}

/** Depth-first visible rows. `expanded` = ids whose children are shown. */
export function visibleRows(forest: ProjectForest, expanded: Set<string>, matches?: (p: ProjectSummary) => boolean): TreeRow[] {
  const rows: TreeRow[] = [];
  const keep = new Map<string, boolean>();
  const keepOf = (id: string, seen = new Set<string>()): boolean => {
    if (keep.has(id)) return keep.get(id)!;
    if (seen.has(id)) return false;
    seen.add(id);
    const p = forest.byId.get(id);
    const self = !matches || (p ? matches(p) : false);
    const any = self || (forest.children.get(id) ?? []).some((c) => keepOf(c, seen));
    keep.set(id, any);
    return any;
  };
  const visit = (id: string, depth: number, seen: Set<string>) => {
    if (seen.has(id)) return;
    seen.add(id);
    const p = forest.byId.get(id);
    if (!p || !keepOf(id)) return;
    const kids = (forest.children.get(id) ?? []).filter((c) => keepOf(c));
    const isOpen = expanded.has(id) || (!!matches && kids.length > 0);
    rows.push({ project: p, depth, parentId: forest.parent.get(id) ?? null, childCount: kids.length, expanded: isOpen, match: !matches || matches(p) });
    if (isOpen) for (const c of kids) visit(c, depth + 1, seen);
  };
  const seen = new Set<string>();
  for (const r of forest.roots) visit(r, 0, seen);
  return rows;
}

// ── relation preview for "Analyze a folder" ────────────────────────────────

export function normalizePath(path: string): string {
  const t = tildePath(path.trim()).replace(/\/+$/, "");
  return t || "/";
}

const isInside = (child: string, par: string) => par !== child && (par === "/" ? child.startsWith("/") : child.startsWith(par + "/"));

export interface RelationPreview {
  existing: ProjectSummary | null;
  parent: ProjectSummary | null;
  children: ProjectSummary[];
}

export function predictRelation(path: string, projects: ProjectSummary[], deviceId?: string | null): RelationPreview {
  const np = normalizePath(path);
  const pool = projects.filter((p) => !deviceId || !p.device_id || p.device_id === deviceId);
  const norm = pool.map((p) => ({ p, n: normalizePath(p.path) }));
  const existing = norm.find((x) => x.n === np)?.p ?? null;
  let parent: { p: ProjectSummary; n: string } | null = null;
  for (const x of norm) if (isInside(np, x.n) && (!parent || x.n.length > parent.n.length)) parent = x;
  const below = norm.filter((x) => isInside(x.n, np));
  const children = below.filter((x) => !below.some((y) => y !== x && isInside(x.n, y.n))).map((x) => x.p);
  return { existing, parent: parent?.p ?? null, children };
}

function names(ps: ProjectSummary[]): string {
  const n = ps.map((p) => p.root_name);
  if (n.length <= 1) return n.join("");
  if (n.length === 2) return `${n[0]} and ${n[1]}`;
  if (n.length === 3) return `${n[0]}, ${n[1]} and ${n[2]}`;
  return `${n[0]}, ${n[1]} and ${n.length - 2} more`;
}

export function relationSentence(r: RelationPreview): string {
  if (r.existing) return `Already analyzed as ${r.existing.root_name}: this refreshes it.`;
  if (r.parent && r.children.length) return `Will be analyzed as a child of ${r.parent.root_name} and become the parent of ${names(r.children)}.`;
  if (r.parent) return `Will be analyzed as a child of ${r.parent.root_name}, with the parent's overview as context.`;
  if (r.children.length) return `Will become the parent of ${names(r.children)}; their analysis is reused, not redone.`;
  return "Will be a new top-level folder.";
}

/** Server-confirmed relation (AnalyzeResult.relation) → sentence. */
export function confirmedRelation(rel: { parent_id: string | null; children: string[] }, byId: Map<string, ProjectSummary>): string {
  const par = rel.parent_id ? byId.get(rel.parent_id) ?? null : null;
  const kids = rel.children.map((id) => byId.get(id) ?? ({ root_name: id } as ProjectSummary));
  return relationSentence({ existing: null, parent: par ?? (rel.parent_id ? ({ root_name: rel.parent_id } as ProjectSummary) : null), children: kids });
}

// ── treemap (slice-and-dice, two levels) ───────────────────────────────────

export interface TreemapCell {
  id: string;
  name: string;
  files: number;
  status: ProjectSummary["status"];
  children: TreemapCell[];
  /** files in this folder not covered by child projects */
  own: number;
}

export function treemapCells(forest: ProjectForest, ids: string[], depth = 0, maxDepth = 2): TreemapCell[] {
  return ids
    .map((id) => forest.byId.get(id))
    .filter((p): p is ProjectSummary => !!p)
    .map((p) => {
      const kidIds = forest.children.get(p.project_id) ?? [];
      const kids = depth + 1 < maxDepth ? treemapCells(forest, kidIds, depth + 1, maxDepth) : [];
      const files = Math.max(0, p.stats?.files ?? 0);
      const kidSum = kids.reduce((a, k) => a + k.files, 0);
      const total = Math.max(files, kidSum);
      return { id: p.project_id, name: p.root_name, files: total, status: p.status, children: kids, own: Math.max(0, total - kidSum) };
    })
    .sort((a, b) => b.files - a.files);
}
