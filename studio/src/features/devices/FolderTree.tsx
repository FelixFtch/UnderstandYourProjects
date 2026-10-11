import type { KeyboardEvent } from "react";
import { compact, tildePath } from "../../design/format";
import { Icon } from "../../design/icons";
import { cx, StatusDot } from "../../design/primitives";
import { hierarchyPhrases, statusMeta } from "./digest";
import type { ProjectForest, TreeRow } from "./tree";

export function FolderTree({ rows, forest, selected, onToggle, onOpen, dense }: {
  rows: TreeRow[];
  forest: ProjectForest;
  selected: string | null;
  onToggle: (id: string) => void;
  onOpen: (id: string) => void;
  dense?: boolean;
}) {
  const onKey = (e: KeyboardEvent<HTMLUListElement>) => {
    const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>("[data-tree-link]"));
    const i = items.indexOf(document.activeElement as HTMLElement);
    if (i < 0) return;
    const row = rows[i];
    if (e.key === "ArrowDown") { e.preventDefault(); items[Math.min(items.length - 1, i + 1)]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[Math.max(0, i - 1)]?.focus(); }
    else if (e.key === "ArrowRight" && row?.childCount && !row.expanded) { e.preventDefault(); onToggle(row.project.project_id); }
    else if (e.key === "ArrowLeft" && row) {
      e.preventDefault();
      if (row.childCount && row.expanded) onToggle(row.project.project_id);
      else if (row.parentId) items[rows.findIndex((r) => r.project.project_id === row.parentId)]?.focus();
    }
  };

  return (
    <ul role="tree" aria-label="Analyzed folders" className="space-y-px" onKeyDown={onKey}>
      {rows.map((row) => {
        const p = row.project;
        const st = statusMeta(p.status);
        const on = selected === p.project_id;
        const parentName = row.parentId ? forest.byId.get(row.parentId)?.root_name ?? null : null;
        const phrases = hierarchyPhrases(parentName, (forest.children.get(p.project_id) ?? []).length);
        return (
          <li
            key={p.project_id}
            role="treeitem"
            aria-level={row.depth + 1}
            aria-expanded={row.childCount ? row.expanded : undefined}
            aria-selected={on}
            className="relative"
          >
            {Array.from({ length: row.depth }, (_, d) => (
              <span key={d} aria-hidden="true" className="absolute top-0 bottom-0 w-px bg-line" style={{ left: 15 + d * 18 }} />
            ))}
            <div
              className={cx(
                "group relative flex min-w-0 items-center gap-1 rounded-[9px] pr-2 transition-colors",
                dense ? "py-1" : "py-1.5",
                on ? "bg-accent-soft" : "hover:bg-sunk",
                !row.match && "opacity-55",
              )}
              style={{ paddingLeft: 4 + row.depth * 18 }}
            >
              {row.childCount ? (
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={() => onToggle(p.project_id)}
                  aria-label={row.expanded ? `Collapse ${p.root_name}` : `Expand ${p.root_name}`}
                  className="grid size-[22px] shrink-0 place-items-center rounded-md text-muted hover:bg-surface hover:text-ink"
                >
                  <Icon name="chevronRight" size={13} strokeWidth={2} className={cx("transition-transform", row.expanded && "rotate-90")} />
                </button>
              ) : (
                <span className="w-[22px] shrink-0" />
              )}
              <a
                href={`#/devices/${encodeURIComponent(p.project_id)}`}
                data-tree-link=""
                onClick={(e) => { e.preventDefault(); onOpen(p.project_id); }}
                title={`${tildePath(p.path)} · ${st.label}`}
                className="flex min-w-0 flex-1 items-center gap-2 rounded-md py-0.5 focus-visible:outline-offset-0"
              >
                <Icon name={row.childCount ? "folderOpen" : "folder"} size={16} className={cx("shrink-0", on ? "text-accent-ink" : "text-muted")} />
                <span className="min-w-0 flex-1">
                  <span className={cx("block truncate text-[13.5px]", on ? "font-medium text-ink" : "text-ink-2")}>{p.root_name}</span>
                  {phrases.length && !dense ? <span className="block truncate text-[11.5px] text-faint">{phrases.join(" · ")}</span> : null}
                </span>
              </a>
              <span className="shrink-0 font-mono text-[11px] text-faint tabular-nums" title={`${p.stats.files} files`}>{compact(p.stats.files)}</span>
              <StatusDot tone={st.tone} pulse={st.pulse} label={st.label} className="ml-1" />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function TreeLegend() {
  const items: Array<[string, Parameters<typeof statusMeta>[0]]> = [["Analyzed", "analyzed"], ["Analyzing", "analyzing"], ["Stale", "stale"], ["Failed", "failed"]];
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-muted">
      {items.map(([label, s]) => (
        <span key={s} className="flex items-center gap-1.5"><StatusDot tone={statusMeta(s).tone} /> {label}</span>
      ))}
    </div>
  );
}

