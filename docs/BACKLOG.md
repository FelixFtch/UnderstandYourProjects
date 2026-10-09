# Backlog

## Connector App / Studio
- [ ] Jetson hardware monitor (:8890, tegrastats) rendered in the Mac console /
  Connector App instead of the on-device chromium kiosk (display side removed
  2026-10-09; data service kept). Candidate: embed as a Studio "Devices" panel
  via the reverse tunnel.
- [ ] jetson-monitor data also worth feeding the Langfuse/task-visibility layer.

## Ops (jetson home)
- [ ] Remove /var/8GB.swap after long-run stability on qwen3.5-route@2048:
  swapoff, dedupe the triple fstab entry (remove all three), delete the file
  (reclaims 8GB disk + ~2.2G held pages). KEEP the 8x zram (JetPack default).
