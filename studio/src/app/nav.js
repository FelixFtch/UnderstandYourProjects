const ICONS = {
    jarvis: "chat",
    agents: "agents",
    devices: "devices",
    understanding: "brain",
    data: "data",
    flow: "flow",
};
export function sectionIcon(section) {
    return ICONS[section] ?? "sparkle";
}
export const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const MOD_KEY = IS_MAC ? "⌘" : "Ctrl";
