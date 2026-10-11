// Inline stroke icons (24px grid, currentColor). No icon library: keeps the bundle lean.
import type { SVGProps } from "react";

const PATHS = {
  jarvis: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Zm0 4.2v4.6l3 1.8",
  chat: "M4.5 5.5h15v10h-8l-4.5 3.5v-3.5H4.5z",
  agents: "M8.5 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7 1.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM3.5 19c.6-3 2.6-5 5-5s4.4 2 5 5M14 14.6c.5-.2 1-.3 1.5-.3 2 0 3.6 1.6 4 4.2",
  devices: "M4 6h16v9H4zM2.5 18h19M9 15v3m6-3v3",
  data: "M12 3.5 4.5 7v5c0 4.2 3.2 7.6 7.5 8.5 4.3-.9 7.5-4.3 7.5-8.5V7zM9 12l2.2 2.2L15.5 10",
  flow: "M5 6.5h4v4H5zM15 13.5h4v4h-4zM9 8.5h3.5v7H15M15 6.5h4v4h-4M12.5 8.5H15",
  search: "M11 4.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Zm4.8 11.3 3.7 3.7",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-4.5v2m0 13v2M3.5 12h2m13 0h2M6 6l1.4 1.4m9.2 9.2L18 18M6 18l1.4-1.4m9.2-9.2L18 6",
  moon: "M19.5 14.5A7.5 7.5 0 0 1 9.5 4.5a7.5 7.5 0 1 0 10 10Z",
  monitor: "M4 5h16v11H4zM9 20h6m-3-4v4",
  plus: "M12 5v14M5 12h14",
  arrowRight: "M5 12h14m-5-5 5 5-5 5",
  arrowLeft: "M19 12H5m5-5-5 5 5 5",
  arrowUp: "M12 19V5m-5 5 5-5 5 5",
  arrowDown: "M12 5v14m-5-5 5 5 5-5",
  chevronRight: "m9.5 6 6 6-6 6",
  chevronDown: "m6 9.5 6 6 6-6",
  chevronLeft: "m14.5 6-6 6 6 6",
  folder: "M3.5 6.5a1 1 0 0 1 1-1h4.6l2 2h8.4a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1z",
  folderOpen: "M3.5 18.5v-12a1 1 0 0 1 1-1h4.6l2 2h7.4a1 1 0 0 1 1 1V10M3.5 18.5 6 11h15.5L19 18.5z",
  file: "M6.5 3.5h7l4 4v13h-11zM13.5 3.5v4h4",
  brain: "M9 4.5a3 3 0 0 0-3 3 3 3 0 0 0-1.5 5.5A3 3 0 0 0 9 18.5V4.5Zm6 0a3 3 0 0 1 3 3 3 3 0 0 1 1.5 5.5 3 3 0 0 1-4.5 5.5V4.5ZM9 4.5a2.5 2.5 0 0 1 3 0m0 0v15",
  project: "M4 7.5 12 3.5l8 4-8 4zM4 12l8 4 8-4M4 16.5l8 4 8-4",
  laptop: "M5 6h14v9H5zM3 18h18",
  server: "M4.5 4.5h15v6h-15zM4.5 13.5h15v6h-15zM8 7.5h.01M8 16.5h.01",
  phone: "M8 3.5h8a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1ZM11 17.5h2",
  chip: "M7 7h10v10H7zM9.5 3.5V7m5-3.5V7m-5 10v3.5m5-3.5v3.5M3.5 9.5H7m-3.5 5H7m10-5h3.5m-3.5 5h3.5",
  check: "m5 12.5 4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6 6 18",
  alert: "M12 4 2.8 19.5h18.4zM12 10v4.5m0 2.5h.01",
  info: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17ZM12 11v5.5M12 8h.01",
  send: "M4.5 12 19.5 5l-5 15-3-6.5z M11.5 13.5 19.5 5",
  stop: "M7 7h10v10H7z",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  external: "M14 4.5h5.5V10M19.5 4.5 11 13M18 14v5.5H4.5V6H10",
  sparkle: "M12 3.5c.6 4.2 2.3 5.9 6.5 6.5-4.2.6-5.9 2.3-6.5 6.5-.6-4.2-2.3-5.9-6.5-6.5 4.2-.6 5.9-2.3 6.5-6.5ZM18.5 15.5c.3 1.6.9 2.2 2.5 2.5-1.6.3-2.2.9-2.5 2.5-.3-1.6-.9-2.2-2.5-2.5 1.6-.3 2.2-.9 2.5-2.5Z",
  refresh: "M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4",
  copy: "M8.5 8.5h11v11h-11zM15.5 8.5v-4h-11v11h4",
  logout: "M14 4.5H5.5v15H14M10 12h10m-3.5-3.5L20 12l-3.5 3.5",
  key: "M14.5 9.5a4 4 0 1 0-3.4 3.96L10 14.5H8v2H6v2H3.5V16l6-6",
  bulb: "M9 17.5h6M10 20.5h4M12 3.5a6 6 0 0 0-3.5 10.9V17h7v-2.6A6 6 0 0 0 12 3.5Z",
  clock: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17ZM12 7.5V12l3 2",
  handoff: "M4.5 12h11m-4-4 4 4-4 4M19.5 5v14",
  layers: "M12 4 3.5 8.5 12 13l8.5-4.5zM3.5 12.5 12 17l8.5-4.5M3.5 16.5 12 21l8.5-4.5",
  activity: "M3.5 12h4l2.5-6.5 4 13 2.5-6.5h4",
  more: "M5.5 12h.01M12 12h.01M18.5 12h.01",
  command: "M9 6.5a2.5 2.5 0 1 0-2.5 2.5H9zm0 0V9m0 0h6m-6 0v6m6-6V6.5A2.5 2.5 0 1 1 17.5 9H15zm0 0v6m0 0h2.5A2.5 2.5 0 1 1 15 17.5zm0 0H9m0 0v2.5A2.5 2.5 0 1 1 6.5 15H9z",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 18, strokeWidth = 1.6, ...rest }: { name: IconName; size?: number; strokeWidth?: number } & Omit<SVGProps<SVGSVGElement>, "name">) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
