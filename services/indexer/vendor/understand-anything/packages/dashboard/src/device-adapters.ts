/**
 * Device transport choices shown by the Studio connector draft.
 *
 * These are descriptions only.  A selected option creates a local draft in
 * SourcesWorkspace; it does not pair hardware, issue a HomeHub grant, or
 * claim that a transport is available.  HomeHub must publish the authorized
 * adapter projection before any device can be read or controlled.
 */

export type DeviceAdapterId = "espnow" | "govee_lan" | "matter";

export type DeviceAdapterState = "contract_pending" | "unsupported";

export interface DeviceAdapterOption {
  id: DeviceAdapterId;
  label: string;
  transport: string;
  description: string;
  capabilities: string[];
  state: DeviceAdapterState;
}

/**
 * Keep this list deliberately small.  It is the Studio's stable vocabulary;
 * HomeHub may later return a filtered catalog with the same IDs and richer
 * availability metadata.
 */
export const DEVICE_ADAPTER_OPTIONS: readonly DeviceAdapterOption[] = [
  {
    id: "espnow",
    label: "ESP-NOW device adapter",
    transport: "ESP32 / ESP-NOW",
    description: "Pair an approved ESP32 receiver and expose readback-confirmed device actions.",
    capabilities: ["discover", "read_state", "turn_on", "turn_off"],
    state: "contract_pending",
  },
  {
    id: "govee_lan",
    label: "Govee LAN device adapter",
    transport: "Local UDP",
    description: "Use a verified local Govee LAN device after HomeHub registers its stable device ID.",
    capabilities: ["discover", "read_state", "turn_on", "turn_off"],
    state: "contract_pending",
  },
  {
    id: "matter",
    label: "Matter device adapter",
    transport: "Matter / IPv6",
    description: "Commission a Matter device through an approved controller; setup codes never enter Studio state.",
    capabilities: ["commission", "read_state", "execute"],
    state: "unsupported",
  },
] as const;

export function deviceAdapterOption(id: DeviceAdapterId): DeviceAdapterOption {
  return DEVICE_ADAPTER_OPTIONS.find((option) => option.id === id) ?? DEVICE_ADAPTER_OPTIONS[0];
}
