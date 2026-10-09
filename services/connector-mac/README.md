# connector-mac

Thin read-only file service per docs/CONNECTOR_PROTOCOL_V1.md. stdlib only
(http.server + fsevents via `watchdog` when present, else poll). No models,
no analysis. LaunchAgent plist lands at deploy time (see docs/DEVICE_LAYOUT_V1.md).
