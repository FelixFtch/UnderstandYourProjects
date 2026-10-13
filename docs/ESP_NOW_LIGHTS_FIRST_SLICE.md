# ESP-NOW lights: first controlled device slice

**Status:** implementation contract, 2026-10-13

The first device slice is deliberately small: the existing kitchen light and
living-room light are exposed as two HomeHub-owned devices. Jarvis can turn
each one on or off, read the resulting state, and report the evidence. The
Studio and phone see stable HomeHub device records; they never see an ESP32
MAC address, raw frame, local IP address, or Home Assistant entity ID.

## What is already working

The successful kitchen-light turn was observed on the current Jetson voice
path:

```text
voice-local-gateway
  -> STT (127.0.0.1:8866)
  -> agent-runtime
  -> governed hub-stub (127.0.0.1:8869)
  -> HomeHub light executor
  -> existing downstream light bridge
```

The current room mapping is:

| HomeHub device | Room | Existing controlled target | Public capabilities |
| --- | --- | --- | --- |
| `home-device-kitchen-light` | `kitchen` | `switch.stamplc_lamp_2` | `read_state`, `turn_on`, `turn_off` |
| `home-device-living-room-light` | `living_room` | `switch.stamplc_lamp_1` | `read_state`, `turn_on`, `turn_off` |

The target values above are an internal compatibility mapping. They must stay
inside HomeHub and must not be returned by Studio or sent to a remote agent.
The lower-level transport has not yet been proven to be a direct ESP-NOW call
from Jetson, so the product must describe it as an existing light bridge until
the ESP32 receiver and its firmware are inspected.

## First-version behavior

1. Jarvis resolves “厨房灯” and “客厅灯” to the stable HomeHub device ID.
2. HomeHub checks the caller, room/device grant, policy epoch, and lease.
3. The adapter sends one `turn_on` or `turn_off` command.
4. The adapter reads the state back from the same controlled path.
5. Only a matching readback produces a success response and audit event.
6. A timeout or ambiguous readback is reported as `unknown`, never as success.

Brightness, color, scenes, broadcast commands, and arbitrary ESP-NOW frames
are outside this slice.

## Voice turn-end ownership

There is one turn-end authority. The stable local gateway uses an energy/VAD
collector with approximately 1.2 seconds of trailing silence and a 12-second
maximum utterance. ESP32 audio hardware may capture, wake, and forward frames,
but it must not independently decide a second end-of-turn for the same request.
The separate Phase-B voice path remains experimental and is not the light
control path while it reports cloud errors or transport loss.

## ESP-IDF reference boundary

When the actual ESP32 light receiver is inspected, implementation should follow
the official ESP-NOW sequence: start Wi-Fi, initialize ESP-NOW, register send
and receive callbacks, add the paired peer, send a bounded command, and return
an acknowledgement with a sequence number. The official component's pairing,
control, provisioning, and security examples are useful references, but their
raw protocol is not part of the Studio API.

- [ESP-IDF ESP-NOW API](https://docs.espressif.com/projects/esp-idf/en/latest/esp32c6/api-reference/network/esp_now.html)
- [Espressif ESP-NOW component](https://github.com/espressif/esp-now)
- [Official control example](https://github.com/espressif/esp-now/tree/master/examples/control)

## Acceptance evidence

Before calling this a direct ESP-NOW integration, capture all of the following
from an isolated test:

- the ESP32 receiver firmware and board identity;
- the peer/pairing configuration, kept out of Git;
- one kitchen and one living-room command with an acknowledgement;
- a state readback that matches the physical lamp;
- the HomeHub audit record and a denied/revoked-control case;
- a reconnect or unavailable case that returns `unknown`.

Until those artifacts exist, the supported claim is narrower: Jarvis controls
the two existing lights through the governed HomeHub bridge, and the bridge's
physical downstream transport is still being identified.
