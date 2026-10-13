// Sensors: data source + pure presentation logic for the sensor-hub devices
// shown in the Devices section. The hub (Jetson, :8895 via companion-api
// /api/sensors/*) aggregates the MQTT discovery tree into physical devices,
// each in one of five fixed categories.
import { useEffect, useRef } from "react";
import { api } from "../../api/client";
import type { SensorCategory, SensorDevice, SensorDeviceList, SensorHistoryPoint, SensorStateRow } from "../../api/contracts";
import { useResource, type Resource } from "../../design/hooks";

const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";
const fx = () => import("./fixtures");

export const sensorsData = {
  devices: (s?: AbortSignal): Promise<SensorDeviceList> => (FIXTURES ? fx().then((f) => f.sensorDevices()) : api.sensorDevices(s)),
  states: (s?: AbortSignal): Promise<SensorStateRow[]> => (FIXTURES ? fx().then((f) => f.sensorStates()) : api.sensorStates(s)),
  history: (entityId: string, s?: AbortSignal): Promise<{ points: SensorHistoryPoint[] }> =>
    !entityId
      ? Promise.resolve({ points: [] }) // no hero entity yet: don't poll a malformed url
      : FIXTURES ? fx().then((f) => f.sensorHistory(entityId)) : api.sensorHistory(entityId, 24, s),
};

// ── categories ───────────────────────────────────────────────────────────────
export const SENSOR_CATEGORY_LABEL: Record<SensorCategory, string> = {
  air_quality: "Air quality",
  presence: "Presence",
  checkin: "Check-in",
  meeting_audio: "Meeting audio",
  lighting: "Lighting",
  other: "Other",
};

export const SENSOR_CATEGORY_ORDER: SensorCategory[] = ["air_quality", "presence", "meeting_audio", "lighting", "checkin", "other"];

/** Online devices first, then category, then name — the same order the hub panel uses. */
export function sortSensorDevices(devices: SensorDevice[]): SensorDevice[] {
  return devices.slice().sort((a, b) =>
    (Number(b.online) - Number(a.online)) ||
    SENSOR_CATEGORY_ORDER.indexOf(a.category) - SENSOR_CATEGORY_ORDER.indexOf(b.category) ||
    a.name.localeCompare(b.name));
}

// ── readings & tri-state ─────────────────────────────────────────────────────
export type ReadingStatus = "ok" | "stale" | "unavailable";

/** Three-state health of one state row: offline > stale > ok (hub convention). */
export function readingStatus(row: Pick<SensorStateRow, "state" | "attributes">): ReadingStatus {
  if (row.state === "unavailable") return "unavailable";
  if (row.attributes?.stale) return "stale";
  return "ok";
}

/** Binary "someone is there" vocabulary the hub normalizes to (HA convention). */
export const POSITIVE_STATES = new Set(["on", "person", "detected", "occupied", "home", "yes", "true", "1", "open"]);

export function isPositive(state: string): boolean {
  return POSITIVE_STATES.has(String(state || "").toLowerCase());
}

/**
 * The entity that answers "is someone there right now" for a presence device:
 * a person/motion entity by id first, else the first presence-classified row.
 */
export function pickPresenceHero(dev: Pick<SensorDevice, "entities">, states: Map<string, SensorStateRow>): SensorStateRow | null {
  const rows = dev.entities.map((id) => states.get(id)).filter((r): r is SensorStateRow => Boolean(r));
  return rows.find((r) => /person|motion|occupan|presence/.test(r.entity_id))
    ?? rows.find((r) => r.attributes?.category === "presence")
    ?? rows[0]
    ?? null;
}

// ── 24h line chart geometry (pure SVG, no chart library) ─────────────────────
export interface LineGeometry {
  points: string;       // polyline points
  area: string;         // closed path down to the baseline
  lo: number;
  hi: number;
}

export function numericPoints(history: SensorHistoryPoint[]): Array<{ t: number; v: number }> {
  return (history ?? [])
    .map((p) => ({ t: Date.parse(p.ts), v: parseFloat(p.state) }))
    .filter((p) => Number.isFinite(p.t) && Number.isFinite(p.v));
}

/** Polyline + area path inside a w×h box with `pad` inset; null when not drawable. */
export function buildLine(pts: Array<{ t: number; v: number }>, w = 260, h = 64, pad = 5): LineGeometry | null {
  if (pts.length < 2) return null;
  let lo = Infinity;
  let hi = -Infinity;
  for (const p of pts) { lo = Math.min(lo, p.v); hi = Math.max(hi, p.v); }
  const span = hi - lo || 1;
  const t0 = pts[0].t;
  const ts = pts[pts.length - 1].t - t0 || 1;
  const xy = pts.map((p) => [
    ((p.t - t0) / ts) * (w - 2 * pad) + pad,
    h - pad - ((p.v - lo) / span) * (h - 2 * pad),
  ]);
  const points = xy.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const area = `M${xy[0][0].toFixed(2)},${h - pad} L${points.split(" ").join(" L")} L${xy[xy.length - 1][0].toFixed(2)},${h - pad} Z`;
  return { points, area, lo, hi };
}

// ── 24h presence band ────────────────────────────────────────────────────────
export interface PresenceBand {
  spans: Array<[number, number]>; // [startMs, endMs] clamped to the window
  totalMs: number;
  count: number;
}

/** Merge consecutive positive samples into occupied intervals over [start, end]. */
export function buildPresenceBand(history: SensorHistoryPoint[], start: Date, end: Date): PresenceBand {
  const t0 = start.getTime();
  const t1 = end.getTime();
  const spans: Array<[number, number]> = [];
  let openAt: number | null = null;
  for (const p of history ?? []) {
    const t = Date.parse(p.ts);
    if (!Number.isFinite(t)) continue;
    if (isPositive(p.state)) {
      if (openAt === null) openAt = Math.max(t, t0);
    } else if (openAt !== null) {
      spans.push([openAt, Math.min(t, t1)]);
      openAt = null;
    }
  }
  if (openAt !== null) spans.push([openAt, t1]); // still occupied now
  let totalMs = 0;
  for (const [a, b] of spans) totalMs += Math.max(0, b - a);
  return { spans, totalMs, count: spans.length };
}

/** "3 h 25 m" / "45 m" / "0 m" for occupied-time summaries. */
export function formatDuration(ms: number): string {
  const mins = Math.max(0, Math.round(ms / 60000));
  if (mins < 60) return `${mins} m`;
  return `${Math.floor(mins / 60)} h ${mins % 60} m`;
}

/** Compact numeric display for chart heads: keeps stable decimals per magnitude. */
export function fmtValue(v: number): string {
  if (!Number.isFinite(v)) return "–";
  if (Math.abs(v) >= 100) return v.toFixed(0);
  if (Math.abs(v) >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

/** Parse the string state of a reading into a number for chart heads. */
export function parseState(state: string): number {
  const v = parseFloat(state);
  return Number.isFinite(v) ? v : Number.NaN;
}

// ── polling that never remounts ──────────────────────────────────────────────
/**
 * Calls `fn` every `ms` without tearing anything down: the interval only
 * re-fires the data load (useResource.reload keeps previous data mounted),
 * so expansion states, scroll positions and text selection all survive.
 */
export function usePolling(fn: () => void, ms: number): void {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const id = window.setInterval(() => ref.current(), ms);
    return () => window.clearInterval(id);
  }, [ms]);
}

export const SENSORS_POLL_MS = 20_000;   // device cards + states
export const HISTORY_POLL_MS = 60_000;   // 24h charts inside a detail view

/**
 * useResource + in-place polling. The interval fires reload() (which keeps the
 * previous data mounted) instead of remounting anything, so open views, scroll
 * positions and hover state all survive every refresh.
 */
export function usePolledResource<T>(load: (signal: AbortSignal) => Promise<T>, deps: readonly unknown[], ms: number): Resource<T> {
  const res = useResource(load, deps);
  usePolling(res.reload, ms);
  return res;
}
