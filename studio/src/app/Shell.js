import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Skeleton } from "../design/primitives";
import { CommandPalette } from "./CommandPalette";
import { ErrorBoundary } from "./ErrorBoundary";
import { BottomNav, NavRail } from "./NavRail";
import { navigate, parseHash, replaceHash, toHash, useHash } from "./router";
import { ROUTES } from "./routes";
import { TopBar } from "./TopBar";
/**
 * App shell: fixed left rail (bottom bar < 768px) + top bar + main.
 * `main` is the only scroll container at shell level and is a CSS size container
 * (`@container`), so pages can use container queries. Pages that need internal panes
 * should be `h-full min-h-0` and manage their own overflow.
 */
export function Shell() {
    const hash = useHash();
    const route = parseHash(hash);
    const def = ROUTES.find((r) => r.section === route.section);
    const [palette, setPalette] = useState(false);
    useEffect(() => {
        if (!def)
            replaceHash(toHash(ROUTES[0].section));
    }, [def]);
    useEffect(() => {
        const onKey = (e) => {
            if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "k") {
                e.preventDefault();
                setPalette((v) => !v);
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);
    const active = def ?? ROUTES[0];
    const Page = active.page;
    const openPalette = useCallback(() => setPalette(true), []);
    const closePalette = useCallback(() => setPalette(false), []);
    useEffect(() => {
        document.title = `${active.label} · Jarvis Studio`;
    }, [active.label]);
    return (_jsxs("div", { className: "grid h-dvh w-full grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden bg-canvas md:grid-cols-[76px_minmax(0,1fr)] md:grid-rows-[auto_minmax(0,1fr)]", children: [_jsx(NavRail, { className: "hidden md:col-start-1 md:row-span-2 md:row-start-1 md:flex", active: active.section, onOpenPalette: openPalette }), _jsx(TopBar, { className: "md:col-start-2 md:row-start-1", route: active, onOpenPalette: openPalette }), _jsx("main", { id: "main", className: "@container relative min-h-0 min-w-0 overflow-x-hidden overflow-y-auto overscroll-contain md:col-start-2 md:row-start-2", children: _jsx(ErrorBoundary, { children: _jsx(Suspense, { fallback: _jsx(PageSkeleton, {}), children: _jsx(Page, { param: def ? route.param : undefined, navigate: navigate }) }) }, active.section) }), _jsx(BottomNav, { className: "md:hidden", active: active.section }), _jsx(CommandPalette, { open: palette, onClose: closePalette, current: active.section })] }));
}
export function PageSkeleton() {
    return (_jsxs("div", { className: "mx-auto w-full max-w-[1100px] space-y-5 p-5 sm:p-8", "aria-busy": "true", "aria-label": "Loading", children: [_jsx(Skeleton, { className: "h-3 w-24" }), _jsx(Skeleton, { className: "h-7 w-72 max-w-full" }), _jsxs("div", { className: "grid gap-4 sm:grid-cols-3", children: [_jsx(Skeleton, { className: "h-28" }), _jsx(Skeleton, { className: "h-28" }), _jsx(Skeleton, { className: "h-28" })] }), _jsx(Skeleton, { className: "h-64" })] }));
}
