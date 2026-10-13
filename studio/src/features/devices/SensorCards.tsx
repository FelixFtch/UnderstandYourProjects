// Sensor device cards for the Devices section: one card per physical device the
// sensor-hub discovered (MQTT HA-discovery tree), plus dashed placeholder cards
// for the reserved categories (check-in, lighting). Clicking opens the detail
// view at #/devices/sensors/<device_id> — open state lives in the URL, so
// polling never has to preserve it.
import type { SensorCategory, SensorDevice, SensorPlaceholder, SensorStateRow } from "../../api/contracts";
import { relativeTime } from "../../design/format";
import { Icon, type IconName } from "../../design/icons";
import { Chip, cx, Skeleton, StatusDot, type Tone } from "../../design/primitives";
import { isPositive, pickPresenceHero, readingStatus, SENSOR_CATEGORY_LABEL } from "./sensors";

const CATEGORY_ICON: Record<SensorCategory, IconName> = {
  air_quality: "activity",
  presence: "agents",
  meeting_audio: "chat",
  checkin: "key",
  lighting: "bulb",
  other: "devices",
};

function presenceLine(dev: SensorDevice, states: Map<string, SensorStateRow>): { tone: Tone; text: string } | null {
  const hero = pickPresenceHero(dev, states);
  if (!hero) return null;
  if (hero.state === "unavailable") return { tone: "err", text: "Presence sensor offline" };
  return isPositive(hero.state) ? { tone: "accent", text: "Someone is there now" } : { tone: "neutral", text: "No one detected" };
}

export function SensorCards({ devices, placeholders, states, openId, onOpen }: {
  devices: SensorDevice[];
  placeholders: SensorPlaceholder[];
  states: Map<string, SensorStateRow>;
  openId: string | null;
  onOpen: (id: string | null) => void;
}) {
  return (
    <ul className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,240px),1fr))]">
      {devices.map((dev) => {
        const on = openId === dev.device_id;
        const presence = dev.category === "presence" ? presenceLine(dev, states) : null;
        return (
          <li key={dev.device_id} className="min-w-0">
            <button
              type="button"
              onClick={() => onOpen(dev.device_id)}
              aria-pressed={on}
              title={`Open ${dev.name} readings`}
              className={cx(
                "flex h-full w-full min-w-0 flex-col gap-3 rounded-card border bg-surface p-4 text-left shadow-card transition-colors",
                on ? "border-accent ring-2 ring-accent/20" : "border-line hover:border-line-strong",
                !dev.online && "opacity-75",
              )}
            >
              <div className="flex min-w-0 items-start gap-3">
                <span className={cx("grid size-9 shrink-0 place-items-center rounded-[10px] border", on ? "border-accent/30 bg-accent-soft text-accent-ink" : "border-line bg-sunk text-ink-2")}>
                  <Icon name={CATEGORY_ICON[dev.category] ?? "devices"} size={18} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-medium text-ink">{dev.name}</span>
                  <span className="block truncate text-[12px] text-muted">
                    {[dev.manufacturer, dev.model].filter(Boolean).join(" · ") || `${dev.entity_count} entities`}
                  </span>
                </span>
              </div>

              <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5">
                {(dev.readings ?? []).slice(0, 4).map((r, i) => {
                  const row = r.entity_id ? states.get(r.entity_id) : undefined;
                  const status = row ? readingStatus(row) : "ok";
                  return (
                    <span key={`${r.entity_id ?? r.label}-${i}`} className="min-w-0">
                      <span className="block max-w-[150px] truncate text-[11.5px] text-muted">{r.label}</span>
                      <span className={cx(
                        "text-[19px] leading-tight font-semibold tabular-nums",
                        status === "unavailable" ? "text-faint" : status === "stale" ? "text-warn" : "text-ink",
                      )}>
                        {status === "unavailable" ? "—" : r.value}
                        {status !== "unavailable" && r.unit ? <span className="ml-0.5 text-[11.5px] font-normal text-muted">{r.unit}</span> : null}
                      </span>
                    </span>
                  );
                })}
                {!dev.readings?.length && !presence ? <span className="text-[13px] text-faint">No key readings</span> : null}
              </div>

              <div className="mt-auto flex min-w-0 flex-wrap items-center gap-2 border-t border-line pt-2.5 text-[12px] text-muted">
                {presence ? (
                  <span className={cx("flex min-w-0 items-center gap-1.5 font-medium", presence.tone === "accent" ? "text-accent-ink" : presence.tone === "err" ? "text-err" : "text-muted")}>
                    <StatusDot tone={presence.tone} pulse={presence.tone === "accent"} />
                    <span className="truncate">{presence.text}</span>
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5">
                    <StatusDot tone={dev.online ? "ok" : "err"} pulse={dev.online} />
                    <span>{dev.online ? "Online" : "Offline"}</span>
                  </span>
                )}
                <span className="ml-auto flex items-center gap-1.5">
                  {!!dev.unavailable && <Chip tone="err" className="px-1.5">{dev.unavailable} off</Chip>}
                  {!!dev.stale && <Chip tone="warn" className="px-1.5">{dev.stale} stale</Chip>}
                  <span className="truncate">{SENSOR_CATEGORY_LABEL[dev.category]}</span>
                  <span aria-hidden="true">·</span>
                  <span className="whitespace-nowrap">{relativeTime(dev.last_changed ?? null)}</span>
                </span>
              </div>
            </button>
          </li>
        );
      })}

      {placeholders.map((p) => (
        <li key={`placeholder_${p.category}`} className="min-w-0">
          <div
            aria-disabled="true"
            title="Reserved category — no devices yet"
            className="flex h-full w-full min-w-0 flex-col gap-3 rounded-card border border-dashed border-line-strong bg-surface/50 p-4 text-left"
          >
            <div className="flex min-w-0 items-start gap-3 opacity-70">
              <span className="grid size-9 shrink-0 place-items-center rounded-[10px] border border-line bg-sunk text-muted">
                <Icon name={CATEGORY_ICON[p.category]} size={18} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium text-ink-2">{SENSOR_CATEGORY_LABEL[p.category]}</span>
                <span className="block text-[12px] text-faint">reserved</span>
              </span>
            </div>
            <p className="text-[12.5px] leading-relaxed text-muted">{p.note}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function SensorCardsSkeleton() {
  return (
    <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,240px),1fr))]" aria-busy="true">
      {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[168px] rounded-card" />)}
    </div>
  );
}
