// Theme preference: light (default) | dark | system. Applied as <html data-theme>.
// index.html applies the stored value before first paint to avoid a flash.
import { create } from "zustand";
const KEY = "jarvis.studio.theme";
function read() {
    try {
        const v = window.localStorage.getItem(KEY);
        return v === "dark" || v === "system" || v === "light" ? v : "light";
    }
    catch {
        return "light";
    }
}
function resolve(pref) {
    if (pref !== "system")
        return pref;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function apply(pref) {
    const theme = resolve(pref);
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#11100d" : "#f4f0e8");
}
export const useTheme = create((set, get) => ({
    pref: typeof window === "undefined" ? "light" : read(),
    setPref: (pref) => {
        try {
            window.localStorage.setItem(KEY, pref);
        }
        catch { /* ignore */ }
        apply(pref);
        set({ pref });
    },
    cycle: () => {
        const order = ["light", "dark", "system"];
        const next = order[(order.indexOf(get().pref) + 1) % order.length];
        get().setPref(next);
    },
}));
export function initTheme() {
    apply(read());
    window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
        if (useTheme.getState().pref === "system")
            apply("system");
    });
}
