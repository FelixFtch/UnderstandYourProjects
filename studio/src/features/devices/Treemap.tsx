import { compact, plural } from "../../design/format";
import { cx, StatusDot } from "../../design/primitives";
import { statusMeta } from "./digest";
import type { TreemapCell } from "./tree";

/**
 * File counts by folder, with the hierarchy nested inside (slice-and-dice treemap).
 * Wide containers get the treemap; narrow ones get the same data as nested bars.
 */
export function Treemap({ cells: all, selected, onOpen }: { cells: TreemapCell[]; selected: string | null; onOpen: (id: string) => void }) {
  // area = files: folders without a file count yet (queued, failed) live in the tree only
  const cells = all.filter((c) => c.files > 0).map((c) => ({ ...c, children: c.children.filter((k) => k.files > 0) }));
  const total = cells.reduce((a, c) => a + c.files, 0);
  if (!cells.length || total === 0) {
    return <div className="rounded-card border border-dashed border-line-strong px-4 py-8 text-center text-[13px] text-muted">No file counts yet. They appear once a folder finishes its first analysis.</div>;
  }
  return (
    <>
      <div className="hidden h-[220px] gap-1.5 @xl:flex" role="list" aria-label="Files by folder">
        {cells.map((c) => <Box key={c.id} cell={c} depth={0} selected={selected} onOpen={onOpen} />)}
      </div>
      <ul className="space-y-2.5 @xl:hidden" aria-label="Files by folder">
        {cells.map((c) => <BarRow key={c.id} cell={c} max={cells[0].files} onOpen={onOpen} selected={selected} />)}
      </ul>
    </>
  );
}

function Box({ cell, depth, selected, onOpen }: { cell: TreemapCell; depth: number; selected: string | null; onOpen: (id: string) => void }) {
  const st = statusMeta(cell.status);
  const on = selected === cell.id;
  const hasKids = cell.children.length > 0;
  return (
    <div
      role="listitem"
      className={cx(
        "flex min-h-0 min-w-0 overflow-hidden rounded-[10px] border transition-colors",
        depth === 0 ? "min-w-[44px] flex-col bg-surface p-1.5" : "min-h-[26px] flex-col bg-sunk p-1.5",
        on ? "border-accent ring-2 ring-accent/20" : "border-line hover:border-line-strong",
      )}
      style={{ flexGrow: Math.max(cell.files, 1), flexBasis: 0 }}
      title={`${cell.name}: ${plural(cell.files, "file")}${hasKids ? ` · contains ${plural(cell.children.length, "folder")}` : ""}`}
    >
      <button type="button" onClick={() => onOpen(cell.id)} className="flex min-w-0 shrink-0 items-center gap-1.5 rounded-md px-1 py-0.5 text-left hover:bg-canvas/60">
        <StatusDot tone={st.tone} pulse={st.pulse} />
        <span className={cx("min-w-0 truncate text-[12.5px]", depth === 0 ? "font-medium text-ink" : "text-ink-2")}>{cell.name}</span>
        <span className="ml-auto shrink-0 font-mono text-[11px] text-faint">{compact(cell.files)}</span>
      </button>
      {hasKids ? (
        <div className="mt-1 flex min-h-0 flex-1 flex-col gap-1">
          {cell.children.map((k) => <Box key={k.id} cell={k} depth={depth + 1} selected={selected} onOpen={onOpen} />)}
          {cell.own > 0 ? (
            <div className="min-h-0 rounded-md border border-dashed border-line px-1.5 text-[11px] text-faint" style={{ flexGrow: cell.own, flexBasis: 0 }} title={`${cell.own} files directly in ${cell.name}`}>
              <span className="block truncate">other files · {compact(cell.own)}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function BarRow({ cell, max, onOpen, selected }: { cell: TreemapCell; max: number; onOpen: (id: string) => void; selected: string | null }) {
  const st = statusMeta(cell.status);
  const width = max > 0 ? Math.max(4, (cell.files / max) * 100) : 0;
  return (
    <li className="min-w-0">
      <button type="button" onClick={() => onOpen(cell.id)} className={cx("flex w-full min-w-0 items-center gap-2 text-left", selected === cell.id && "text-accent-ink")}>
        <StatusDot tone={st.tone} pulse={st.pulse} />
        <span className="min-w-0 truncate text-[13px] font-medium text-ink">{cell.name}</span>
        <span className="ml-auto shrink-0 font-mono text-[11.5px] text-muted">{compact(cell.files)}</span>
      </button>
      <div className="mt-1 h-3 w-full rounded-full bg-sunk">
        <div className="flex h-full gap-px overflow-hidden rounded-full" style={{ width: `${width}%` }}>
          {cell.children.length ? (
            <>
              {cell.children.map((k, i) => (
                <span
                  key={k.id}
                  title={`${k.name}: ${plural(k.files, "file")}`}
                  className={cx("h-full", i % 2 ? "bg-accent/55" : "bg-accent/80")}
                  style={{ flexGrow: Math.max(k.files, 1), flexBasis: 0 }}
                />
              ))}
              {cell.own > 0 ? <span className="h-full bg-line-strong" style={{ flexGrow: cell.own, flexBasis: 0 }} title={`${cell.own} other files`} /> : null}
            </>
          ) : (
            <span className="h-full flex-1 bg-accent/70" />
          )}
        </div>
      </div>
      {cell.children.length ? (
        <div className="mt-1 truncate text-[11.5px] text-muted">contains {cell.children.map((k) => k.name).join(" · ")}</div>
      ) : null}
    </li>
  );
}
