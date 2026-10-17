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
- gBrain retention gardener (owner ask 2026-10-16): a periodic, HomeHub-audited
  job where Laya triages aged project-brain pages into keep/forget candidates
  (mirroring the index-side skip/structure/summary/deep contract), so the mirror
  store does not grow unbounded after the 0.60 quota true-up. Forget actions go
  through the publisher's revoke path, never direct deletes. Design before code.
- SOLVED 2026-10-16 (d5879f6): 0.60 rejects slugs ending in .md/.mdx; the
  publisher now drops the source extension. The manifest invalid_params errors
  were item-page failures misreported under the manifest slug.
