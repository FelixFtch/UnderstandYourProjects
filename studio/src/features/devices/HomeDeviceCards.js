import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { relativeTime } from "../../design/format";
import { Icon } from "../../design/icons";
import { Button, Card, Chip, EmptyState, StatusDot } from "../../design/primitives";
import { devicesData } from "./data";
/** Stable HomeHub catalog IDs shown while the authorized projection is pending.
 * These cards are read-only placeholders; they never imply that a provider or
 * current state is online. The real GET projection replaces them automatically.
 */
export const HOME_DEVICE_CONTRACT_PENDING = {
    status: "contract_pending",
    schema_version: "homehub-home-devices-v1",
    provider: "homehub",
    state: "contract_pending",
    readOnly: true,
    controlEnabled: false,
    reason: "HomeHub has not returned an authorized device projection yet",
    devices: [
        { homeDeviceId: "home-device-kitchen-light", providerId: "espnow-lights-v1", displayName: "Kitchen light", roomId: "kitchen", kind: "switch", capabilities: ["read_state", "turn_on", "turn_off"], availability: "unknown", state: { power: "unknown" } },
        { homeDeviceId: "home-device-living-room-light", providerId: "espnow-lights-v1", displayName: "Living room light", roomId: "living_room", kind: "switch", capabilities: ["read_state", "turn_on", "turn_off"], availability: "unknown", state: { power: "unknown" } },
    ],
};
function availabilityTone(value) {
    if (value === "online")
        return "ok";
    if (value === "offline" || value === "revoked")
        return "err";
    if (value === "stale")
        return "warn";
    return "neutral";
}
function availabilityLabel(value) {
    return value === "online" ? "Online" : value.charAt(0).toUpperCase() + value.slice(1);
}
function can(device, capability) {
    return device.capabilities.includes(capability);
}
function actionMessage(result) {
    if (!result)
        return null;
    if (result.executed)
        return "Command accepted · state will refresh from HomeHub";
    if (result.status === "dry_run")
        return "Dry run accepted by HomeHub";
    return result.reasonCode ? `Not executed · ${result.reasonCode}` : "HomeHub did not execute this action";
}
function HomeDeviceCard({ device, projection, onRefresh }) {
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);
    const enabled = !projection.readOnly && projection.controlEnabled && device.availability === "online";
    const run = async (actionId) => {
        setBusy(true);
        setError(null);
        setResult(null);
        try {
            const next = await devicesData.homeDeviceAction(device.homeDeviceId, actionId, "live");
            setResult(next);
            onRefresh();
        }
        catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        }
        finally {
            setBusy(false);
        }
    };
    const power = typeof device.state?.power === "string" ? device.state.power : null;
    const room = device.roomId?.replace(/_/g, " ") ?? "Home";
    const disabledReason = projection.readOnly ? "HomeHub session is read-only" : !projection.controlEnabled ? (projection.reason ?? "HomeHub has not enabled control") : device.availability !== "online" ? "Device is not online" : null;
    return (_jsx("li", { className: "min-w-0", children: _jsxs(Card, { className: "flex h-full min-w-0 flex-col gap-3 p-4", children: [_jsxs("div", { className: "flex min-w-0 items-start gap-3", children: [_jsx("span", { className: "grid size-9 shrink-0 place-items-center rounded-[10px] border border-accent/30 bg-accent-soft text-accent-ink", children: _jsx(Icon, { name: "bulb", size: 18 }) }), _jsxs("div", { className: "min-w-0 flex-1", children: [_jsx("div", { className: "truncate text-[14px] font-medium text-ink", children: device.displayName }), _jsxs("div", { className: "mt-0.5 truncate text-[12px] text-muted", children: [room, " \u00B7 ", device.providerId] })] }), _jsx(Chip, { tone: availabilityTone(device.availability), icon: "activity", children: availabilityLabel(device.availability) })] }), _jsxs("div", { className: "flex items-end justify-between gap-3 border-t border-line pt-3", children: [_jsxs("div", { children: [_jsx("div", { className: "text-[11.5px] text-muted", children: "Power" }), _jsx("div", { className: "mt-0.5 text-[21px] font-semibold tabular-nums text-ink", children: power ?? "—" })] }), _jsxs("div", { className: "text-right text-[11.5px] text-muted", children: [_jsxs("div", { className: "flex items-center justify-end gap-1.5", children: [_jsx(StatusDot, { tone: availabilityTone(device.availability), pulse: device.availability === "online" }), device.observedAt ? relativeTime(device.observedAt) : "No recent reading"] }), _jsx("div", { className: "mt-1 font-mono text-[10.5px] text-faint", children: device.homeDeviceId })] })] }), _jsxs("div", { className: "mt-auto flex flex-wrap gap-2", children: [_jsx(Button, { size: "sm", variant: "primary", icon: "sun", loading: busy, disabled: !enabled || !can(device, "turn_on"), onClick: () => run("home.light.turn_on"), children: "Turn on" }), _jsx(Button, { size: "sm", variant: "secondary", icon: "moon", loading: busy, disabled: !enabled || !can(device, "turn_off"), onClick: () => run("home.light.turn_off"), children: "Turn off" })] }), disabledReason ? _jsxs("p", { className: "text-[11.5px] leading-relaxed text-muted", children: [disabledReason, ". HomeHub remains the authority for this device."] }) : null, actionMessage(result) ? _jsx("p", { role: "status", className: "text-[11.5px] leading-relaxed text-ok", children: actionMessage(result) }) : null, error ? _jsx("p", { role: "alert", className: "text-[11.5px] leading-relaxed text-err", children: error }) : null] }) }));
}
export function HomeDeviceCards({ projection, onRefresh }) {
    if (!projection.devices.length) {
        return (_jsx(Card, { children: _jsx(EmptyState, { icon: "bulb", title: "No HomeHub light projection yet", body: projection.reason ?? "HomeHub has not returned the authorized kitchen and living-room devices." }) }));
    }
    return _jsx("ul", { className: "grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr))]", children: projection.devices.map((device) => _jsx(HomeDeviceCard, { device: device, projection: projection, onRefresh: onRefresh }, device.homeDeviceId)) });
}
export function HomeDeviceCardsSkeleton() {
    return _jsxs("div", { className: "grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr))]", "aria-busy": "true", children: [_jsx("div", { className: "h-[218px] animate-pulse rounded-card border border-line bg-sunk" }), _jsx("div", { className: "h-[218px] animate-pulse rounded-card border border-line bg-sunk" })] });
}
