import type { IconName } from "../design/icons";

const ICONS: Record<string, IconName> = {
  jarvis: "chat",
  agents: "agents",
  devices: "devices",
  data: "data",
  flow: "flow",
};

export function sectionIcon(section: string): IconName {
  return ICONS[section] ?? "sparkle";
}

export const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const MOD_KEY = IS_MAC ? "⌘" : "Ctrl";
