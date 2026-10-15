// Offline dev fixtures for the shell (VITE_STUDIO_FIXTURES=true only).
import type { MarkReadRequest, Me, NotificationList, PairResponse, StudioNotification } from "../api/contracts";

let enrolled = false;

export function me(): Me {
  return {
    member_id: "robin",
    role: "owner",
    display_name: "Robin",
    household_id: "household",
    jarvis: {
      node_id: "hub_7f3c2a91",
      display_name: "Robin's Jarvis",
      number: "J-4829-1300",
      urn: "urn:ai:domain:clinic.jarvis.local:robin",
      town: { run_id: "run-2026-10-11", participant: "clinic" },
    },
    agent_box: enrolled ? { enrolled: true, box_id: "box_q8Zt1fKx" } : { enrolled: false, box_id: null },
  };
}

export function pair(code: string): PairResponse {
  if (code.toUpperCase() === "00000000") throw new Error("Unknown or already-used pairing code");
  return { token: "cat_fixture_token", member_id: "robin", role: "owner", display_name: "Robin" };
}

export function enroll(): { enrolled: boolean; box_id: string } {
  enrolled = true;
  return { enrolled: true, box_id: "box_q8Zt1fKx" };
}

export const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

// 2026-10-15: in-memory notifications for the top-bar bell (fixtures mode only).
// Newest first; `read` mirrors the server's 0/1 flag.
let NOTES: StudioNotification[] = [
  {
    id: 3, ts: new Date(Date.now() - 22 * 60_000).toISOString(), kind: "settings", read: 0,
    title: "Model mode switched to cloud",
    body: "Robin switched Jarvis to cloud mode — qwen3.8-flash now serves route and persona.",
  },
  {
    id: 2, ts: new Date(Date.now() - 3 * 3600_000).toISOString(), kind: "settings", read: 0,
    title: "Cloud provider key updated",
    body: "The Qwen · Alibaba Bailian key was replaced (sk-…1a2b).",
  },
  {
    id: 1, ts: new Date(Date.now() - 26 * 3600_000).toISOString(), kind: "system", read: 1,
    title: "Agent box enrolled",
    body: "This Jetson's project worker enrolled with HomeHub as box_q8Zt1fKx.",
  },
];

export async function notifications(): Promise<NotificationList> {
  await delay(120);
  return { items: NOTES.map((n) => ({ ...n })), unread: NOTES.filter((n) => !n.read).length };
}

export async function markNotificationsRead(req: MarkReadRequest): Promise<{ ok: boolean }> {
  await delay(160);
  const ids = "all" in req ? null : new Set(req.ids);
  NOTES = NOTES.map((n) => (ids === null || ids.has(n.id) ? { ...n, read: 1 } : n));
  return { ok: true };
}
