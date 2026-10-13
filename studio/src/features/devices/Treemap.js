import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { compact, plural } from "../../design/format";
import { cx, StatusDot } from "../../design/primitives";
import { statusMeta } from "./digest";
/**
 * File counts by folder, with the hierarchy nested inside (slice-and-dice treemap).
 * Wide containers get the treemap; narrow ones get the same data as nested bars.
 */
export function Treemap({ cells: all, selected, onOpen }) {
    // area = files: folders without a file count yet (queued, failed) live in the tree only
    const cells = all.filter((c) => c.files > 0).map((c) => ({ ...c, children: c.children.filter((k) => k.files > 0) }));
    const total = cells.reduce((a, c) => a + c.files, 0);
    if (!cells.length || total === 0) {
        return _jsx("div", { className: "rounded-card border border-dashed border-line-strong px-4 py-8 text-center text-[13px] text-muted", children: "No file counts yet. They appear once a folder finishes its first analysis." });
    }
    return (_jsxs(_Fragment, { children: [_jsx("div", { className: "hidden h-[220px] gap-1.5 @xl:flex", role: "list", "aria-label": "Files by folder", children: cells.map((c) => _jsx(Box, { cell: c, depth: 0, selected: selected, onOpen: onOpen }, c.id)) }), _jsx("ul", { className: "space-y-2.5 @xl:hidden", "aria-label": "Files by folder", children: cells.map((c) => _jsx(BarRow, { cell: c, max: cells[0].files, onOpen: onOpen, selected: selected }, c.id)) })] }));
}
function Box({ cell, depth, selected, onOpen }) {
    const st = statusMeta(cell.status);
    const on = selected === cell.id;
    const hasKids = cell.children.length > 0;
    return (_jsxs("div", { role: "listitem", className: cx("flex min-h-0 min-w-0 overflow-hidden rounded-[10px] border transition-colors", depth === 0 ? "min-w-[44px] flex-col bg-surface p-1.5" : "min-h-[26px] flex-col bg-sunk p-1.5", on ? "border-accent ring-2 ring-accent/20" : "border-line hover:border-line-strong"), style: { flexGrow: Math.max(cell.files, 1), flexBasis: 0 }, title: `${cell.name}: ${plural(cell.files, "file")}${hasKids ? ` · contains ${plural(cell.children.length, "folder")}` : ""}`, children: [_jsxs("button", { type: "button", onClick: () => onOpen(cell.id), className: "flex min-w-0 shrink-0 items-center gap-1.5 rounded-md px-1 py-0.5 text-left hover:bg-canvas/60", children: [_jsx(StatusDot, { tone: st.tone, pulse: st.pulse }), _jsx("span", { className: cx("min-w-0 truncate text-[12.5px]", depth === 0 ? "font-medium text-ink" : "text-ink-2"), children: cell.name }), _jsx("span", { className: "ml-auto shrink-0 font-mono text-[11px] text-faint", children: compact(cell.files) })] }), hasKids ? (_jsxs("div", { className: "mt-1 flex min-h-0 flex-1 flex-col gap-1", children: [cell.children.map((k) => _jsx(Box, { cell: k, depth: depth + 1, selected: selected, onOpen: onOpen }, k.id)), cell.own > 0 ? (_jsx("div", { className: "min-h-0 rounded-md border border-dashed border-line px-1.5 text-[11px] text-faint", style: { flexGrow: cell.own, flexBasis: 0 }, title: `${cell.own} files directly in ${cell.name}`, children: _jsxs("span", { className: "block truncate", children: ["other files \u00B7 ", compact(cell.own)] }) })) : null] })) : null] }));
}
function BarRow({ cell, max, onOpen, selected }) {
    const st = statusMeta(cell.status);
    const width = max > 0 ? Math.max(4, (cell.files / max) * 100) : 0;
    return (_jsxs("li", { className: "min-w-0", children: [_jsxs("button", { type: "button", onClick: () => onOpen(cell.id), className: cx("flex w-full min-w-0 items-center gap-2 text-left", selected === cell.id && "text-accent-ink"), children: [_jsx(StatusDot, { tone: st.tone, pulse: st.pulse }), _jsx("span", { className: "min-w-0 truncate text-[13px] font-medium text-ink", children: cell.name }), _jsx("span", { className: "ml-auto shrink-0 font-mono text-[11.5px] text-muted", children: compact(cell.files) })] }), _jsx("div", { className: "mt-1 h-3 w-full rounded-full bg-sunk", children: _jsx("div", { className: "flex h-full gap-px overflow-hidden rounded-full", style: { width: `${width}%` }, children: cell.children.length ? (_jsxs(_Fragment, { children: [cell.children.map((k, i) => (_jsx("span", { title: `${k.name}: ${plural(k.files, "file")}`, className: cx("h-full", i % 2 ? "bg-accent/55" : "bg-accent/80"), style: { flexGrow: Math.max(k.files, 1), flexBasis: 0 } }, k.id))), cell.own > 0 ? _jsx("span", { className: "h-full bg-line-strong", style: { flexGrow: cell.own, flexBasis: 0 }, title: `${cell.own} other files` }) : null] })) : (_jsx("span", { className: "h-full flex-1 bg-accent/70" })) }) }), cell.children.length ? (_jsxs("div", { className: "mt-1 truncate text-[11.5px] text-muted", children: ["contains ", cell.children.map((k) => k.name).join(" · ")] })) : null] }));
}
