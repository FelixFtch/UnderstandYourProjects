// Session: bearer token (api/client) + /api/studio/me. The shell renders from `status`.
//   anon     → LoginScreen (no token, or a 401 anywhere: client.onAuthLost → expire())
//   booting  → loading /me
//   ready    → Shell
//   error    → hub unreachable screen (token kept; Retry or sign out)
import { create } from "zustand";
import { api, ApiError, getToken, setToken } from "../api/client";
import type { Me } from "../api/contracts";

export const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";
// Inline the env check at each call site so production builds drop the fixture chunk.
const fx = () => import("./fixtures");

export type SessionStatus = "anon" | "booting" | "ready" | "error";

interface SessionState {
  status: SessionStatus;
  me: Me | null;
  error: unknown;
  /** true when we fell back to login because the hub rejected the token */
  expired: boolean;
  enrolling: boolean;
  enrollError: string | null;
  boot: () => Promise<void>;
  signIn: (code: string) => Promise<void>;
  signOut: () => void;
  expire: () => void;
  refreshMe: () => Promise<void>;
  enroll: () => Promise<void>;
}

/** Strip spaces/dashes; the hub upper-cases codes itself, we do it for display. */
export function normalizeInviteCode(raw: string): string {
  return raw.replace(/[\s-]/g, "").toUpperCase();
}
export function isValidInviteCode(code: string): boolean {
  return /^[0-9A-Z]{8}$/.test(code);
}

async function fetchMe(): Promise<Me> {
  if (import.meta.env.VITE_STUDIO_FIXTURES === "true") {
    const f = await fx();
    await f.delay(350);
    return f.me();
  }
  return api.me();
}

export const useSession = create<SessionState>((set, get) => ({
  status: getToken() ? "booting" : "anon",
  me: null,
  error: null,
  expired: false,
  enrolling: false,
  enrollError: null,

  boot: async () => {
    if (!getToken()) { set({ status: "anon", me: null }); return; }
    set({ status: "booting", error: null });
    try {
      const me = await fetchMe();
      if (!getToken()) return; // a 401 raced us
      set({ status: "ready", me, expired: false });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { get().expire(); return; }
      set({ status: "error", error: err });
    }
  },

  signIn: async (raw) => {
    const code = normalizeInviteCode(raw);
    const res = import.meta.env.VITE_STUDIO_FIXTURES === "true"
      ? await fx().then(async (f) => { await f.delay(500); return f.pair(code); })
      : await api.pair(code);
    setToken(res.token);
    set({ expired: false });
    await get().boot();
  },

  signOut: () => {
    setToken(null);
    set({ status: "anon", me: null, expired: false, error: null });
  },

  expire: () => {
    setToken(null);
    const wasIn = get().status !== "anon";
    set({ status: "anon", me: null, expired: wasIn || get().expired });
  },

  refreshMe: async () => {
    try {
      const me = await fetchMe();
      set({ me });
    } catch { /* keep the last good identity; 401 is handled by onAuthLost */ }
  },

  enroll: async () => {
    set({ enrolling: true, enrollError: null });
    try {
      const res = import.meta.env.VITE_STUDIO_FIXTURES === "true"
        ? await fx().then(async (f) => { await f.delay(900); return f.enroll(); })
        : await api.enrollAgentBox();
      const me = get().me;
      if (me) set({ me: { ...me, agent_box: { enrolled: res.enrolled, box_id: res.box_id ?? null } } });
      set({ enrolling: false });
      void get().refreshMe();
    } catch (err) {
      set({ enrolling: false, enrollError: err instanceof Error ? err.message : String(err) });
    }
  },
}));

/** The signed-in member (null only while booting). Features may read this. */
export function useMe(): Me | null {
  return useSession((s) => s.me);
}
