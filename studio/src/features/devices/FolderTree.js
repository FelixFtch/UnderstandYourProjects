import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { compact, tildePath } from "../../design/format";
import { Icon } from "../../design/icons";
import { cx, StatusDot } from "../../design/primitives";
import { hierarchyPhrases, statusMeta } from "./digest";
export function FolderTree({ rows, forest, selected, onToggle, onOpen, dense }) {
    const onKey = (e) => {
        const items = Array.from(e.currentTarget.querySelectorAll("[data-tree-link]"));
        const i = items.indexOf(document.activeElement);
        if (i < 0)
            return;
        const row = rows[i];
        if (e.key === "ArrowDown") {
            e.preventDefault();
            items[Math.min(items.length - 1, i + 1)]?.focus();
        }
        else if (e.key === "ArrowUp") {
            e.preventDefault();
            items[Math.max(0, i - 1)]?.focus();
        }
        else if (e.key === "ArrowRight" && row?.childCount && !row.expanded) {
            e.preventDefault();
            onToggle(row.project.project_id);
        }
        else if (e.key === "ArrowLeft" && row) {
            e.preventDefault();
            if (row.childCount && row.expanded)
                onToggle(row.project.project_id);
            else if (row.parentId)
                items[rows.findIndex((r) => r.project.project_id === row.parentId)]?.focus();
        }
    };
    return (_jsx("ul", { role: "tree", "aria-label": "Analyzed folders", className: "space-y-px", onKeyDown: onKey, children: rows.map((row) => {
            const p = row.project;
            const st = statusMeta(p.status);
            const on = selected === p.project_id;
            const parentName = row.parentId ? forest.byId.get(row.parentId)?.root_name ?? null : null;
            const phrases = hierarchyPhrases(parentName, (forest.children.get(p.project_id) ?? []).length);
            return (_jsxs("li", { role: "treeitem", "aria-level": row.depth + 1, "aria-expanded": row.childCount ? row.expanded : undefined, "aria-selected": on, className: "relative", children: [Array.from({ length: row.depth }, (_, d) => (_jsx("span", { "aria-hidden": "true", className: "absolute top-0 bottom-0 w-px bg-line", style: { left: 15 + d * 18 } }, d))), _jsxs("div", { className: cx("group relative flex min-w-0 items-center gap-1 rounded-[9px] pr-2 transition-colors", dense ? "py-1" : "py-1.5", on ? "bg-accent-soft" : "hover:bg-sunk", !row.match && "opacity-55"), style: { paddingLeft: 4 + row.depth * 18 }, children: [row.childCount ? (_jsx("button", { type: "button", tabIndex: -1, onClick: () => onToggle(p.project_id), "aria-label": row.expanded ? `Collapse ${p.root_name}` : `Expand ${p.root_name}`, className: "grid size-[22px] shrink-0 place-items-center rounded-md text-muted hover:bg-surface hover:text-ink", children: _jsx(Icon, { name: "chevronRight", size: 13, strokeWidth: 2, className: cx("transition-transform", row.expanded && "rotate-90") }) })) : (_jsx("span", { className: "w-[22px] shrink-0" })), _jsxs("a", { href: `#/devices/${encodeURIComponent(p.project_id)}`, "data-tree-link": "", onClick: (e) => { e.preventDefault(); onOpen(p.project_id); }, title: `${tildePath(p.path)} · ${st.label}`, className: "flex min-w-0 flex-1 items-center gap-2 rounded-md py-0.5 focus-visible:outline-offset-0", children: [_jsx(Icon, { name: row.childCount ? "folderOpen" : "folder", size: 16, className: cx("shrink-0", on ? "text-accent-ink" : "text-muted") }), _jsxs("span", { className: "min-w-0 flex-1", children: [_jsx("span", { className: cx("block truncate text-[13.5px]", on ? "font-medium text-ink" : "text-ink-2"), children: p.root_name }), phrases.length && !dense ? _jsx("span", { className: "block truncate text-[11.5px] text-faint", children: phrases.join(" · ") }) : null] })] }), _jsx("span", { className: "shrink-0 font-mono text-[11px] text-faint tabular-nums", title: `${p.stats.files} files`, children: compact(p.stats.files) }), _jsx(StatusDot, { tone: st.tone, pulse: st.pulse, label: st.label, className: "ml-1" })] })] }, p.project_id));
        }) }));
}
export function TreeLegend() {
    const items = [["Analyzed", "analyzed"], ["Analyzing", "analyzing"], ["Stale", "stale"], ["Failed", "failed"]];
    return (_jsx("div", { className: "flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-muted", children: items.map(([label, s]) => (_jsxs("span", { className: "flex items-center gap-1.5", children: [_jsx(StatusDot, { tone: statusMeta(s).tone }), " ", label] }, s))) }));
}
