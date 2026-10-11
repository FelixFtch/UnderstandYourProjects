import type { Device } from "../../api/contracts";
import { plural, relativeTime } from "../../design/format";
import { Icon, type IconName } from "../../design/icons";
import { cx, Skeleton, StatusDot, type Tone } from "../../design/primitives";

const KIND_ICON: Record<Device["kind"], IconName> = { computer: "laptop", nas: "server", jetson: "chip", phone: "phone" };

function connectorLine(d: Device): { tone: Tone; text: string } {
  const c = d.connector;
  if (!c) return { tone: "neutral", text: d.kind === "phone" ? "Paired app · no folder connector" : "No connector" };
  if (c.state === "online") return { tone: "ok", text: `Connector online${c.watcher ? ` · ${c.watcher}` : ""}` };
  if (c.state === "offline") return { tone: "err", text: `Connector offline · seen ${relativeTime(c.last_seen)}` };
  return { tone: "warn", text: `Connector state unknown${c.last_seen ? ` · seen ${relativeTime(c.last_seen)}` : ""}` };
}

export function DeviceCards({ devices, selected, onSelect }: { devices: Device[]; selected: string | null; onSelect: (id: string | null) => void }) {
  return (
    <ul className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr))]">
      {devices.map((d) => {
        const line = connectorLine(d);
        const on = selected === d.device_id;
        return (
          <li key={d.device_id} className="min-w-0">
            <button
              type="button"
              onClick={() => onSelect(on ? null : d.device_id)}
              aria-pressed={on}
              title={on ? "Show folders from every device" : `Show only folders on ${d.label}`}
              className={cx(
                "flex h-full w-full min-w-0 flex-col gap-3 rounded-card border bg-surface p-4 text-left shadow-card transition-colors",
                on ? "border-accent ring-2 ring-accent/20" : "border-line hover:border-line-strong",
              )}
            >
              <div className="flex min-w-0 items-start gap-3">
                <span className={cx("grid size-9 shrink-0 place-items-center rounded-[10px] border", on ? "border-accent/30 bg-accent-soft text-accent-ink" : "border-line bg-sunk text-ink-2")}>
                  <Icon name={KIND_ICON[d.kind] ?? "devices"} size={18} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-medium text-ink">{d.label}</span>
                  <span className="block truncate text-[12px] text-muted">{[d.hostname, d.os].filter(Boolean).join(" · ")}</span>
                </span>
              </div>
              <div className="flex min-w-0 items-center gap-2 text-[12.5px] text-ink-2">
                <StatusDot tone={line.tone} pulse={d.connector?.state === "online"} />
                <span className="truncate">{line.text}</span>
              </div>
              <div className="mt-auto flex items-center justify-between gap-2 border-t border-line pt-2.5 text-[12px] text-muted">
                <span>{plural(d.project_count, "folder")}{d.connector ? ` · ${plural(d.connector.grants, "grant")}` : ""}</span>
                <span className="truncate">{d.paired_at ? `paired ${relativeTime(d.paired_at)}` : "not paired"}</span>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function DeviceCardsSkeleton() {
  return (
    <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr))]" aria-busy="true">
      {[0, 1, 2].map((i) => <Skeleton key={i} className="h-[132px] rounded-card" />)}
    </div>
  );
}
