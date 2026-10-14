import { useState } from "react";
import type { HomeDevice, HomeDeviceActionResult, HomeDeviceProjection } from "../../api/contracts";
import { relativeTime } from "../../design/format";
import { Icon } from "../../design/icons";
import { Button, Card, Chip, EmptyState, StatusDot, type Tone } from "../../design/primitives";
import { devicesData } from "./data";

function availabilityTone(value: string): Tone {
  if (value === "online") return "ok";
  if (value === "offline" || value === "revoked") return "err";
  if (value === "stale") return "warn";
  return "neutral";
}

function availabilityLabel(value: string): string {
  return value === "online" ? "Online" : value.charAt(0).toUpperCase() + value.slice(1);
}

function can(device: HomeDevice, capability: string): boolean {
  return device.capabilities.includes(capability);
}

function actionMessage(result: HomeDeviceActionResult | null): string | null {
  if (!result) return null;
  if (result.executed) return "Command accepted · state will refresh from HomeHub";
  if (result.status === "dry_run") return "Dry run accepted by HomeHub";
  return result.reasonCode ? `Not executed · ${result.reasonCode}` : "HomeHub did not execute this action";
}

function HomeDeviceCard({ device, projection, onRefresh }: { device: HomeDevice; projection: HomeDeviceProjection; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<HomeDeviceActionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const enabled = !projection.readOnly && projection.controlEnabled && device.availability === "online";

  const run = async (actionId: "home.light.turn_on" | "home.light.turn_off") => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const next = await devicesData.homeDeviceAction(device.homeDeviceId, actionId, "live");
      setResult(next);
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const power = typeof device.state?.power === "string" ? device.state.power : null;
  const room = device.roomId?.replace(/_/g, " ") ?? "Home";
  const disabledReason = projection.readOnly ? "HomeHub session is read-only" : !projection.controlEnabled ? (projection.reason ?? "HomeHub has not enabled control") : device.availability !== "online" ? "Device is not online" : null;

  return (
    <li className="min-w-0">
      <Card className="flex h-full min-w-0 flex-col gap-3 p-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-[10px] border border-accent/30 bg-accent-soft text-accent-ink">
            <Icon name="bulb" size={18} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[14px] font-medium text-ink">{device.displayName}</div>
            <div className="mt-0.5 truncate text-[12px] text-muted">{room} · {device.providerId}</div>
          </div>
          <Chip tone={availabilityTone(device.availability)} icon="activity">{availabilityLabel(device.availability)}</Chip>
        </div>

        <div className="flex items-end justify-between gap-3 border-t border-line pt-3">
          <div>
            <div className="text-[11.5px] text-muted">Power</div>
            <div className="mt-0.5 text-[21px] font-semibold tabular-nums text-ink">{power ?? "—"}</div>
          </div>
          <div className="text-right text-[11.5px] text-muted">
            <div className="flex items-center justify-end gap-1.5"><StatusDot tone={availabilityTone(device.availability)} pulse={device.availability === "online"} />{device.observedAt ? relativeTime(device.observedAt) : "No recent reading"}</div>
            <div className="mt-1 font-mono text-[10.5px] text-faint">{device.homeDeviceId}</div>
          </div>
        </div>

        <div className="mt-auto flex flex-wrap gap-2">
          <Button size="sm" variant="primary" icon="sun" loading={busy} disabled={!enabled || !can(device, "turn_on")} onClick={() => run("home.light.turn_on")}>Turn on</Button>
          <Button size="sm" variant="secondary" icon="moon" loading={busy} disabled={!enabled || !can(device, "turn_off")} onClick={() => run("home.light.turn_off")}>Turn off</Button>
        </div>
        {disabledReason ? <p className="text-[11.5px] leading-relaxed text-muted">{disabledReason}. HomeHub remains the authority for this device.</p> : null}
        {actionMessage(result) ? <p role="status" className="text-[11.5px] leading-relaxed text-ok">{actionMessage(result)}</p> : null}
        {error ? <p role="alert" className="text-[11.5px] leading-relaxed text-err">{error}</p> : null}
      </Card>
    </li>
  );
}

export function HomeDeviceCards({ projection, onRefresh }: { projection: HomeDeviceProjection; onRefresh: () => void }) {
  if (!projection.devices.length) {
    return (
      <Card>
        <EmptyState icon="bulb" title="No HomeHub light projection yet" body={projection.reason ?? "HomeHub has not returned the authorized kitchen and living-room devices."} />
      </Card>
    );
  }
  return <ul className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr))]">{projection.devices.map((device) => <HomeDeviceCard key={device.homeDeviceId} device={device} projection={projection} onRefresh={onRefresh} />)}</ul>;
}

export function HomeDeviceCardsSkeleton() {
  return <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr))]" aria-busy="true"><div className="h-[218px] animate-pulse rounded-card border border-line bg-sunk" /><div className="h-[218px] animate-pulse rounded-card border border-line bg-sunk" /></div>;
}

