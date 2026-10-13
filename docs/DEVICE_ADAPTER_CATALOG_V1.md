# Device adapter catalog V1

**Status:** design guidance, 2026-10-13

Studio should expose one adapter catalog, but it should not pretend that all
physical transports share one wire protocol.  The catalog is a HomeHub-owned
projection of approved adapters.  It gives Studio, the iPhone app, and Jarvis
the same stable names and capabilities; it does not issue grants or call a
device directly.

## What we can reuse

| Reference | What it gives us | Decision for UYP/HomeHub |
| --- | --- | --- |
| [W3C Web of Things Thing Description](https://github.com/w3c/wot-thing-description) | A protocol-neutral JSON description of properties, actions, events, schemas, and security forms. | Use the vocabulary as inspiration for our small manifest; do not embed a full WoT runtime in the Jetson first slice. |
| [Eclipse Thingweb node-wot](https://github.com/eclipse-thingweb/node-wot) | A pluggable implementation with HTTP, CoAP, MQTT, WebSocket, OPC-UA, and Modbus bindings. | Keep it as a future interoperability option; HomeHub still owns the adapter registry and authorization. |
| [Espressif ESP-NOW component](https://github.com/espressif/esp-now) | An application-level ESP-NOW layer with pairing, control, provisioning, debug, OTA, and security examples. | Use as the ESP32 firmware reference. Keep its frames behind our `espnow` adapter. |
| [ESP-IDF ESP-NOW API](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/network/esp_now.html) | Low-level peer registration, callbacks, bounded send payloads, and delivery status. | Use for the receiver/bridge implementation and acknowledgement/readback tests. |
| [Matter connectedhomeip](https://github.com/project-chip/connectedhomeip) | A standardized IP/IPv6 data model and commissioning flow for interoperable devices. | Offer a future `matter` adapter; it does not replace ESP-NOW and requires a Matter controller/fabric. |
| [ESPHome native API client](https://github.com/esphome/aioesphomeapi) | A practical device API with discovery/state/services and encrypted transport. | Optional future `esphome_native` adapter. Do not make Home Assistant or its entity registry a runtime dependency. |

There is no single GitHub project that safely turns ESP-NOW, Matter, Govee LAN,
and arbitrary sensors into one authorization boundary.  The reusable part is
the device-model vocabulary. We will borrow the W3C Thing Description idea of
properties/actions/events, then expose a smaller `uyp.device.manifest.v1`.
HomeHub must still own identity, pairing, policy, revocation, and audit.

## Our stable adapter contract

Each adapter implements the contract in
[`DEVICE_PROVIDER_CONTRACT_V1.md`](./DEVICE_PROVIDER_CONTRACT_V1.md):

```text
discover()                 -> candidates (unpaired, no control)
list_devices()             -> HomeHub-owned normalized records
read_state(homeDeviceId)   -> fresh state or unknown/offline
execute(homeDeviceId, op)  -> policy-gated command + readback
```

The manifest is intentionally a small, transport-neutral projection. It is
inspired by W3C Thing Description, but it is owned by HomeHub and contains no
credential or network handle:

```json
{
  "schema": "uyp.device.manifest.v1",
  "homeDeviceId": "home-device-kitchen-light",
  "provider": "espnow",
  "title": "Kitchen light",
  "room": "kitchen",
  "kind": "light",
  "capabilities": {
    "state": {"type": "string", "enum": ["on", "off", "unknown"]},
    "actions": {"turn_on": {}, "turn_off": {}}
  },
  "availability": {"source": "read_state", "maxAgeSeconds": 15},
  "transport": {"kind": "espnow", "endpointRef": "opaque", "ackRequired": true}
}
```

`endpointRef` is resolved inside HomeHub/provider storage. Studio and the
phone receive only the public projection and the current HomeHub grant.

The Studio catalog uses these IDs:

| Adapter ID | Transport | Initial capabilities | State |
| --- | --- | --- | --- |
| `espnow` | ESP32 / ESP-NOW | discover, read_state, turn_on, turn_off | contract pending |
| `govee_lan` | local UDP | discover, read_state, turn_on, turn_off | contract pending |
| `matter` | Matter / IPv6 | commission, read_state, execute | unsupported until a controller is installed |

The current Studio Add connector menu only creates a local draft.  It does not
pair the ESP32, persist a peer key, store a Matter setup code, or claim that a
device is online.  Those transitions must come from a HomeHub projection.

## First implementation choice

Use the existing kitchen and living-room light path as the compatibility
adapter first.  Keep the public IDs and actions stable while we inspect the
actual ESP32 receiver firmware and bridge.  Only after a command acknowledgement
and physical readback are captured should the compatibility adapter be backed by
direct ESP-NOW frames.  The upper Jarvis, Studio, and phone contracts then stay
unchanged.
