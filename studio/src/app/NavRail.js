import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Icon } from "../design/icons";
import { cx } from "../design/primitives";
import { Monogram } from "./Brand";
import { MOD_KEY, sectionIcon } from "./nav";
import { toHash } from "./router";
import { ROUTES } from "./routes";
import { useTheme } from "./theme";
export function NavRail({ active, onOpenPalette, className }) {
    const pref = useTheme((s) => s.pref);
    const cycle = useTheme((s) => s.cycle);
    return (_jsxs("nav", { "aria-label": "Sections", className: cx("flex-col items-center border-r border-line bg-canvas py-3", className), children: [_jsx("a", { href: toHash("jarvis"), className: "mb-4 rounded-[12px]", "aria-label": "Jarvis Studio home", children: _jsx(Monogram, { size: 36 }) }), _jsx("ul", { className: "flex w-full flex-col items-center gap-1 px-2", children: ROUTES.map((r) => {
                    const on = r.section === active;
                    return (_jsx("li", { className: "w-full", children: _jsxs("a", { href: toHash(r.section), "aria-current": on ? "page" : undefined, title: r.hint, className: cx("flex w-full flex-col items-center gap-1 rounded-[12px] py-2 text-[11px] font-medium transition-colors", on ? "bg-accent-soft text-accent-ink" : "text-muted hover:bg-sunk hover:text-ink"), children: [_jsx(Icon, { name: sectionIcon(r.section), size: 20, strokeWidth: on ? 1.9 : 1.6 }), r.label] }) }, r.section));
                }) }), _jsxs("div", { className: "mt-auto flex flex-col items-center gap-1", children: [_jsxs("button", { type: "button", onClick: onOpenPalette, className: "flex flex-col items-center gap-0.5 rounded-[10px] px-2 py-1.5 text-muted hover:bg-sunk hover:text-ink", title: `Jump to a section (${MOD_KEY}K)`, "aria-label": "Open section switcher", children: [_jsx(Icon, { name: "search", size: 18 }), _jsxs("span", { className: "text-[10px] font-medium", children: [MOD_KEY, "K"] })] }), _jsx("button", { type: "button", onClick: cycle, className: "rounded-[10px] p-2 text-muted hover:bg-sunk hover:text-ink", title: `Theme: ${pref} (click to change)`, "aria-label": `Theme: ${pref}. Change theme`, children: _jsx(Icon, { name: pref === "dark" ? "moon" : pref === "system" ? "monitor" : "sun", size: 18 }) })] })] }));
}
export function BottomNav({ active, className }) {
    return (_jsx("nav", { "aria-label": "Sections", className: cx("border-t border-line bg-canvas pb-[env(safe-area-inset-bottom)]", className), children: _jsx("ul", { className: "grid", style: { gridTemplateColumns: `repeat(${ROUTES.length}, minmax(0, 1fr))` }, children: ROUTES.map((r) => {
                const on = r.section === active;
                return (_jsx("li", { children: _jsxs("a", { href: toHash(r.section), "aria-current": on ? "page" : undefined, className: cx("flex flex-col items-center gap-0.5 py-2 text-[10.5px] font-medium", on ? "text-accent-ink" : "text-muted"), children: [_jsx(Icon, { name: sectionIcon(r.section), size: 20, strokeWidth: on ? 1.9 : 1.6 }), r.label] }) }, r.section));
            }) }) }));
}
