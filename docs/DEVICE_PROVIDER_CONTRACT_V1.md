# UnderstandYourProjects device provider contract

UnderstandYourProjects and HomeHub expose a small device interface of their
own. Home Assistant is a reference for naming, freshness, and capability
patterns; it is not a runtime dependency and its entity IDs never cross the
Studio boundary.

The path is:

```text
device adapter → HomeHub registry/policy/audit → Studio, Jarvis, and phone
```

Every adapter implements the same four operations:

```text
discover()                 # find or announce devices
list_devices()             # return normalized records
read_state(homeDeviceId)   # return one fresh state
execute(homeDeviceId, op)  # policy-gated command, with audit and readback
```

The normalized record is deliberately small:

```json
{
  "homeDeviceId": "device_govee_…",
  "provider": "govee_lan",
  "uniqueId": "opaque-stable-id",
  "displayName": "Living room lamp",
  "aliases": ["客厅灯", "H60B0"],
  "roomId": "living_room",
  "kind": "light",
  "capabilities": ["read_state", "turn_on", "turn_off"],
  "state": "off",
  "availability": "online",
  "observedAt": "2026-10-13T23:00:00Z"
}
```

The record never contains a Home Assistant `entity_id`, local IP address,
MQTT topic, access token, or Matter setup code. A setup code is consumed once
by the pairing flow and is not stored in the repository or returned to Studio.

The first adapters stay intentionally narrow:

- `govee_lan`: H60B0 local LAN power control. It must confirm discovery,
  read the current state, send one on/off operation, then read back the state
  before Studio reports success. Brightness, color, and Matter commissioning
  wait until the device and transport are verified.
- `espnow_presence`: read-only online, area, and presence state. It cannot
  expose light-control operations.

The existing kitchen and living-room lights are a separate first-version
compatibility slice. They are exposed as HomeHub-owned light records with
`read_state`, `turn_on`, and `turn_off`; the adapter may call the currently
validated HomeHub light executor while the physical downstream ESP32/ESP-NOW
transport is being identified. This keeps the public interface stable without
claiming that Jetson already sends raw ESP-NOW frames. See
[ESP_NOW_LIGHTS_FIRST_SLICE.md](./ESP_NOW_LIGHTS_FIRST_SLICE.md).

The existing HomeHub action IDs remain the public vocabulary:
`home.device.list`, `home.device.read_state`, `home.light.turn_on`,
`home.light.turn_off`, and `home.sensor.read`. HomeHub decides whether a
caller may invoke them; an adapter only performs the device-specific transport
after that decision.

Until a provider reports a fresh state, Studio must show `unknown`, `offline`,
or `pairing_required`. It must not show a demo device as online and must not
enable a command from a label alone.
