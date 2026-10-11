// Hash router: #/<section>/<param?>. The param may itself contain "/" (encoded or not).
import { useSyncExternalStore } from "react";

export interface HashRoute {
  section: string;
  param?: string;
}

export function parseHash(hash: string): HashRoute {
  const raw = hash.replace(/^#/, "").replace(/^\/+/, "");
  if (!raw) return { section: "" };
  const [sectionPart, ...rest] = raw.split("/");
  const section = safeDecode(sectionPart.split("?")[0]).toLowerCase();
  const tail = rest.join("/").replace(/\/+$/, "");
  return tail ? { section, param: safeDecode(tail) } : { section };
}

export function toHash(section: string, param?: string): string {
  return param ? `#/${section}/${encodeURIComponent(param)}` : `#/${section}`;
}

/** Accepts "#/x/y", "/x/y" or "x/y". */
export function normalizeHash(h: string): string {
  if (h.startsWith("#")) return h;
  return "#/" + h.replace(/^\/+/, "");
}

export function navigate(h: string): void {
  const next = normalizeHash(h);
  if (window.location.hash !== next) window.location.hash = next;
}

export function replaceHash(h: string): void {
  const next = normalizeHash(h);
  const url = window.location.pathname + window.location.search + next;
  window.history.replaceState(window.history.state, "", url);
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

function safeDecode(s: string): string {
  try { return decodeURIComponent(s); } catch { return s; }
}

function subscribe(cb: () => void): () => void {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
}
const snapshot = () => window.location.hash;

export function useHash(): string {
  return useSyncExternalStore(subscribe, snapshot, () => "");
}
