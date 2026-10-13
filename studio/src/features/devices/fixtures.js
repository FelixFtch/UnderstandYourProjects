// Offline fixtures for Devices (VITE_STUDIO_FIXTURES=true only).
import { ApiError } from "../../api/client";
import { basename } from "../../design/format";
import { buildForest, predictRelation } from "./tree";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const ago = (h) => new Date(Date.now() - h * 3600_000).toISOString();
const DEVICES = [
    { device_id: "d_mbp", kind: "computer", label: "Robin's MacBook Pro", hostname: "robins-mbp.local", os: "macOS 26.4",
        connector: { state: "online", watcher: "fsevents", grants: 6, last_seen: ago(0.03) }, paired_at: ago(24 * 40), project_count: 7 },
    { device_id: "d_jetson", kind: "jetson", label: "Clinic Jetson", hostname: "jetson-clinic", os: "Ubuntu 22.04 · JetPack 6",
        connector: { state: "online", watcher: "inotify", grants: 1, last_seen: ago(0.01) }, paired_at: ago(24 * 90), project_count: 1 },
    { device_id: "d_nas", kind: "nas", label: "Home NAS", hostname: "nas.local", os: "DSM 7.2",
        connector: { state: "offline", watcher: null, grants: 2, last_seen: ago(74) }, paired_at: ago(24 * 60), project_count: 0 },
    { device_id: "d_iphone", kind: "phone", label: "Robin's iPhone", hostname: "iPhone", os: "iOS 26",
        connector: null, paired_at: ago(24 * 30), project_count: 0 },
];
function proj(p) {
    return {
        device_id: "d_mbp", parent_id: null, children: [], status: "analyzed", analyzed_at: ago(20),
        stats: { files: 100, summarized: 40, nodes: 300, edges: 600, languages: ["Python"] },
        tiers: { A: 12, B: 25, C: 60, gate: 3 }, embedded_roots: [], ...p,
    };
}
let PROJECTS = [
    proj({ project_id: "code", root_name: "code", path: "/Users/robin/code", analyzed_at: ago(30),
        children: ["commontasks", "UnderstandYourProjects", "jarvis-homehub", "MultiAgentFamilyTaskOrganizer"],
        stats: { files: 5120, summarized: 1260, nodes: 18400, edges: 41200, languages: ["TypeScript", "Python", "Swift"] },
        tiers: { A: 410, B: 850, C: 3700, gate: 160 } }),
    proj({ project_id: "commontasks", root_name: "commontasks", path: "/Users/robin/code/commontasks", parent_id: "code", children: ["commontasks-backend"], analyzed_at: ago(9),
        stats: { files: 860, summarized: 248, nodes: 3120, edges: 7340, languages: ["TypeScript", "Python"] }, tiers: { A: 74, B: 174, C: 590, gate: 22 } }),
    proj({ project_id: "commontasks-backend", root_name: "backend", path: "/Users/robin/code/commontasks/backend", parent_id: "commontasks", analyzed_at: ago(9),
        stats: { files: 310, summarized: 96, nodes: 1180, edges: 2610, languages: ["Python"] }, tiers: { A: 28, B: 68, C: 206, gate: 8 } }),
    proj({ project_id: "UnderstandYourProjects", root_name: "UnderstandYourProjects", path: "/Users/robin/code/UnderstandYourProjects", parent_id: "code", analyzed_at: ago(3),
        stats: { files: 1430, summarized: 352, nodes: 5210, edges: 11800, languages: ["Python", "TypeScript"] }, tiers: { A: 120, B: 232, C: 1010, gate: 68 } }),
    proj({ project_id: "jarvis-homehub", root_name: "jarvis-homehub", path: "/Users/robin/code/jarvis-homehub", parent_id: "code", status: "analyzing", analyzed_at: ago(50),
        stats: { files: 2040, summarized: 410, nodes: 6900, edges: 15200, languages: ["Python", "Swift"] }, tiers: { A: 150, B: 260, C: 1580, gate: 50 } }),
    proj({ project_id: "MultiAgentFamilyTaskOrganizer", root_name: "MultiAgentFamilyTaskOrganizer", path: "/Users/robin/code/MultiAgentFamilyTaskOrganizer", parent_id: "code", status: "stale", analyzed_at: ago(24 * 19),
        stats: { files: 380, summarized: 110, nodes: 1300, edges: 2900, languages: ["Python"] }, tiers: { A: 30, B: 80, C: 262, gate: 8 } }),
    proj({ project_id: "gsd-works", root_name: "GSD Works", path: "/Users/robin/Documents/GSD Works", analyzed_at: ago(52),
        stats: { files: 640, summarized: 180, nodes: 900, edges: 1400, languages: ["Markdown", "PDF"] }, tiers: { A: 40, B: 140, C: 440, gate: 20 } }),
    proj({ project_id: "jetson-services", root_name: "services", path: "/home/robin/jetson/services", device_id: "d_jetson", status: "failed", analyzed_at: null,
        stats: { files: 0, summarized: 0, nodes: 0, edges: 0, languages: [] }, tiers: { A: 0, B: 0, C: 0, gate: 0 } }),
];
function list() {
    const forest = buildForest({ projects: PROJECTS, tree: [] });
    const toNode = (id) => ({ project_id: id, children: (forest.children.get(id) ?? []).map(toNode) });
    return { projects: PROJECTS.map((p) => ({ ...p, children: forest.children.get(p.project_id) ?? [] })), tree: forest.roots.map(toNode) };
}
export async function devices() { await wait(420); return { devices: DEVICES }; }
export async function projects() { await wait(520); return list(); }
const day = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
export async function project(id) {
    await wait(480);
    const all = list();
    const p = all.projects.find((x) => x.project_id === id);
    if (!p)
        throw new ApiError(404, `No analyzed folder called “${id}”`);
    if (p.status === "failed")
        throw new ApiError(502, "UYP query_api unreachable: connector read timed out on the Jetson");
    const byId = new Map(all.projects.map((x) => [x.project_id, x]));
    const parent = p.parent_id ? byId.get(p.parent_id) ?? null : null;
    const kids = p.children.map((c) => byId.get(c)).filter(Boolean);
    const siblings = parent ? parent.children.filter((c) => c !== id).map((c) => byId.get(c)).filter(Boolean) : [];
    const ct = id === "commontasks";
    return {
        project: p,
        overview: ct
            ? "**commontasks** is a shared task board for the household and clinic. A FastAPI backend (`backend/`) stores tasks and expands recurring rules; a React web app (`web/`) renders the board and calendar.\n\nThis week the work centred on **recurring tasks**: weekly rules, next-occurrence display, and timezone handling (still open)."
            : `**${p.root_name}** lives at \`${p.path.replace(/^\/(Users|home)\/[^/]+/, "~")}\`. Jarvis summarized ${p.stats.summarized} of ${p.stats.files} files; the rest are indexed by structure only.\n\n${kids.length ? `It contains ${kids.length} analyzed folder${kids.length > 1 ? "s" : ""}, whose analysis is reused here.` : "It has no analyzed sub-folders."}`,
        key_files: ct
            ? [
                { file: "backend/app/scheduler.py", tier: "A", purpose: "Expands recurring task rules into dated occurrences.", key_points: ["Weekly and monthly RRULE subset", "Runs on task save and nightly", "Timezone: stores UTC, TODO local DST"] },
                { file: "backend/app/api/tasks.py", tier: "A", purpose: "REST endpoints for tasks, assignments and completion.", key_points: ["Role checks via household membership", "Soft delete with audit row"] },
                { file: "web/src/TaskBoard.tsx", tier: "A", purpose: "The board UI with columns per person.", key_points: ["Shows next occurrence for recurring tasks", "Drag to reassign"] },
                { file: "web/src/api.ts", tier: "B", purpose: "Typed fetch client for the backend.", key_points: [] },
                { file: "backend/tests/test_scheduler.py", tier: "B", purpose: "Scheduler unit tests.", key_points: ["Covers weekly rules; monthly pending"] },
                { file: "web/pnpm-lock.yaml", tier: "gate", purpose: "Lockfile (structure only).", key_points: [] },
            ]
            : [
                { file: "README.md", tier: "A", purpose: "What the project is and how to run it.", key_points: ["Setup", "Architecture overview"] },
                { file: `src/${basename(p.path).toLowerCase()}/main.py`, tier: "A", purpose: "Entry point.", key_points: [] },
                { file: "tests/test_core.py", tier: "B", purpose: "Core tests.", key_points: [] },
            ],
        areas: ct
            ? [
                { folder: "backend/", files: 310, summary: "FastAPI service: tasks, members, recurring rules, notifications." },
                { folder: "web/", files: 420, summary: "React app: task board, calendar, settings." },
                { folder: "docs/", files: 34, summary: "Design notes and ADRs, including the recurring-tasks decision." },
                { folder: "scripts/", files: 18, summary: "Dev and deploy helpers." },
            ]
            : [
                { folder: "src/", files: Math.round(p.stats.files * 0.6), summary: "Main source." },
                { folder: "tests/", files: Math.round(p.stats.files * 0.2), summary: "Tests." },
                { folder: "docs/", files: Math.round(p.stats.files * 0.1), summary: "Documentation." },
            ],
        activity: {
            window: "7d",
            changed: ct
                ? [
                    { file: "backend/app/scheduler.py", mtime: ago(20), purpose: "Expands recurring task rules" },
                    { file: "web/src/TaskBoard.tsx", mtime: ago(22), purpose: "Board UI" },
                    { file: "backend/tests/test_scheduler.py", mtime: ago(23), purpose: "Scheduler tests" },
                    { file: "web/src/api.ts", mtime: ago(2), purpose: "Typed client" },
                    { file: "docs/adr/0007-recurring-tasks.md", mtime: ago(70), purpose: "Recurring tasks ADR" },
                    { file: "backend/app/models.py", mtime: ago(96), purpose: "ORM models" },
                ]
                : [{ file: "README.md", mtime: ago(30), purpose: "Docs" }],
            by_day: ct
                ? [{ date: day(6), count: 1 }, { date: day(4), count: 3 }, { date: day(3), count: 2 }, { date: day(1), count: 6 }, { date: day(0), count: 1 }]
                : [{ date: day(1), count: 1 }],
        },
        graph: {
            layers: ct
                ? [{ name: "API", files: 42 }, { name: "Domain", files: 61 }, { name: "UI", files: 188 }, { name: "Tests", files: 96 }, { name: "Docs", files: 34 }]
                : [{ name: "Source", files: Math.round(p.stats.files * 0.6) }, { name: "Tests", files: Math.round(p.stats.files * 0.2) }],
            top_nodes: ct
                ? [
                    { name: "expand_rule", type: "function", file: "backend/app/scheduler.py" },
                    { name: "Task", type: "class", file: "backend/app/models.py" },
                    { name: "TaskBoard", type: "component", file: "web/src/TaskBoard.tsx" },
                    { name: "create_task", type: "function", file: "backend/app/api/tasks.py" },
                ]
                : [{ name: "main", type: "function", file: "src/main.py" }],
        },
        related: { parent, children: kids, siblings },
        generated_at: ago(1),
    };
}
export async function projectGraph(id) {
    const d = await project(id);
    const node = (name, type, file) => ({ id: `${id}:${name}`, name, type, filePath: file, summary: `${name} in ${file}` });
    const nodes = d.graph.top_nodes.map((n) => node(n.name, n.type, n.file));
    const layers = d.graph.layers.map((layer, i) => ({ id: `${id}:layer:${i}`, name: layer.name, description: `${layer.files} files grouped by the project digest`, nodeIds: nodes.slice(0, Math.max(1, Math.ceil(nodes.length / d.graph.layers.length))).map((n) => n.id) }));
    const edges = nodes.slice(1).map((n, i) => ({ source: nodes[i].id, target: n.id, type: "relates_to", description: "Extracted relation" }));
    return { projectId: id, version: "fixture", kind: "codebase", project: { name: d.project.root_name, languages: d.project.stats.languages }, nodes, edges, layers, tour: layers.slice(0, 4).map((layer, i) => ({ order: i + 1, title: `Start with ${layer.name}`, description: layer.description, nodeIds: layer.nodeIds })), counts: { nodes: nodes.length, edges: edges.length, layers: layers.length, tour: Math.min(4, layers.length) }, truncated: { nodes: false, edges: false, layers: false, tour: false } };
}
export async function ask(id, question) {
    await wait(1100);
    if (/fail|error/i.test(question))
        throw new ApiError(503, "knowledge-service (gbrain) unreachable");
    return {
        answer: id === "commontasks"
            ? `Recurring tasks are expanded in \`backend/app/scheduler.py\` by **expand_rule**, called on save and nightly. The board shows the next occurrence (\`web/src/TaskBoard.tsx\`). Timezones are stored in UTC; local DST handling is still a TODO.`
            : `From the knowledge Jarvis has for **${id}**: the entry point is \`src/main.py\` and the README describes setup. Ask something more specific for a sharper answer.`,
        sources: id === "commontasks" ? [{ file: "backend/app/scheduler.py" }, { file: "web/src/TaskBoard.tsx" }, { file: "docs/adr/0007-recurring-tasks.md" }] : [{ file: "README.md" }],
        confidence: id === "commontasks" ? "high" : "low",
    };
}
const JOBS = new Map();
const PHASES = ["scanning folder", "classifying key files", "enriching tier A (Laya → qwen)", "building knowledge graph", "writing digest"];
export async function analyze(path, deviceId) {
    await wait(700);
    if (!path.trim().startsWith("/") && !path.trim().startsWith("~"))
        throw new ApiError(400, "Path must be absolute (start with / or ~)");
    const rel = predictRelation(path, PROJECTS, deviceId);
    const clean = path.trim().replace(/\/+$/, "");
    const name = basename(clean);
    const id = rel.existing?.project_id ?? name;
    if (!rel.existing) {
        PROJECTS = [...PROJECTS, proj({
                project_id: id, root_name: name, path: clean.replace(/^~/, "/Users/robin"), device_id: deviceId ?? "d_mbp",
                parent_id: rel.parent?.project_id ?? null, status: "queued", analyzed_at: null,
                stats: { files: 0, summarized: 0, nodes: 0, edges: 0, languages: [] }, tiers: { A: 0, B: 0, C: 0, gate: 0 },
            })];
        for (const c of rel.children)
            PROJECTS = PROJECTS.map((p) => (p.project_id === c.project_id ? { ...p, parent_id: id } : p));
    }
    const job_id = `j_${Math.random().toString(36).slice(2, 7)}`;
    JOBS.set(job_id, { polls: 0, job: { job_id, project_id: id, status: "queued", phase: "queued", progress: { done: 0, total: 120 }, log_tail: ["queued: waiting for the agent box"] } });
    return { job_id, project_id: id, relation: { parent_id: rel.parent?.project_id ?? null, children: rel.children.map((c) => c.project_id) }, status: "queued" };
}
export async function job(jobId) {
    await wait(200);
    const j = JOBS.get(jobId);
    if (!j)
        throw new ApiError(404, "Unknown job");
    j.polls += 1;
    const total = j.job.progress.total;
    const done = Math.min(total, j.polls * 24);
    const phase = PHASES[Math.min(PHASES.length - 1, Math.floor((done / total) * PHASES.length))];
    const finished = done >= total;
    j.job = {
        ...j.job,
        status: finished ? "done" : "running",
        phase: finished ? "done" : phase,
        progress: { done, total },
        log_tail: [...j.job.log_tail, finished ? `done: ${total} files, digest written` : `${phase}: ${done}/${total}`].slice(-8),
    };
    if (finished) {
        PROJECTS = PROJECTS.map((p) => (p.project_id === j.job.project_id
            ? { ...p, status: "analyzed", analyzed_at: new Date().toISOString(), stats: { files: total, summarized: 38, nodes: 410, edges: 880, languages: ["Python", "TypeScript"] }, tiers: { A: 14, B: 24, C: 78, gate: 4 } }
            : p));
    }
    return j.job;
}
// ── sensors (sensor-hub on the Jetson, via companion-api /api/sensors/*) ─────
const AIR_ENTITIES = [
    ["sensor.air_station_co2", "CO2", "ppm", 497, 120],
    ["sensor.air_station_tvoc", "TVOC", "ppm", 0.351, 0.25],
    ["sensor.air_station_temperature", "Indoor Temperature", "°C", 25.1, 3],
    ["sensor.air_station_humidity", "Indoor Humidity", "%", 36.9, 8],
];
const SENSOR_DEVICES = {
    count: 4,
    devices: [
        {
            device_id: "air_station", name: "Air Station", manufacturer: "Seeed", model: "XIAO ESP32C3 + DHT20 + SCD41",
            category: "air_quality", entities: AIR_ENTITIES.map(([id]) => id), entity_count: 4, online: true,
            unavailable: 0, stale: 0, last_changed: ago(0.02),
            readings: AIR_ENTITIES.map(([entity_id, label, unit, base]) => ({
                entity_id, label, value: String(base), unit, category: "air_quality",
            })),
        },
        {
            device_id: "room_radar", name: "ESP32-S3 WiFi CSI Room Radar", manufacturer: "Felix Lab",
            model: "ESP32-S3 CSI presence", category: "presence",
            entities: ["binary_sensor.room_radar_person", "sensor.room_radar_score"],
            entity_count: 2, online: true, unavailable: 0, stale: 1, last_changed: ago(0.05),
            readings: [{ entity_id: "binary_sensor.room_radar_person", label: "Person State", value: "on", category: "presence" }],
        },
        {
            device_id: "xvf3800_satellites", name: "XVF3800 语音卫星", manufacturer: "XMOS", model: "XVF3800",
            category: "meeting_audio", entities: [], entity_count: 0, online: true, source: "http-status-poll",
            status_url: "http://127.0.0.1:8766/phase-b/status", last_changed: ago(0.01),
            readings: [
                { label: "链路状态", value: "listening" },
                { label: "在线卫星", value: "2", unit: "台" },
                { label: "覆盖房间", value: "room_kitchen、room_living_room" },
            ],
            detail_note: "XVF3800 在线状态来自 127.0.0.1:8766/phase-b/status；最近语音活动时间该端点暂不提供，数据源待接。",
        },
        {
            device_id: "door_bridge_000000", name: "Door Bridge", category: "other",
            entities: ["binary_sensor.door_bridge_locked", "sensor.door_bridge_rssi"], entity_count: 2,
            online: false, unavailable: 2, stale: 0, last_changed: ago(26),
            readings: [{ entity_id: "binary_sensor.door_bridge_locked", label: "Door Locked", value: "unavailable" }],
        },
    ],
    placeholders: [
        { category: "checkin", note: "Check-in devices will arrive through Home Assistant; this category is reserved for them." },
        { category: "lighting", note: "Waiting for the StampPLC firmware to dual-publish MQTT (~10 lines of ESPHome YAML); lights still speak native API today." },
    ],
};
const SENSOR_STATES = [
    ...AIR_ENTITIES.map(([entity_id, label, unit, base]) => ({
        entity_id,
        state: String(base),
        attributes: { friendly_name: label, category: "air_quality", device_id: "air_station", unit_of_measurement: unit },
        last_changed: ago(0.02),
    })),
    {
        entity_id: "binary_sensor.room_radar_person", state: "on",
        attributes: { friendly_name: "Person State", category: "presence", device_id: "room_radar" },
        last_changed: ago(0.05),
    },
    {
        entity_id: "sensor.room_radar_score", state: "0.83",
        attributes: { friendly_name: "Presence Score", category: "presence", device_id: "room_radar", stale: true },
        last_changed: ago(1.4),
    },
    {
        entity_id: "binary_sensor.door_bridge_locked", state: "unavailable",
        attributes: { friendly_name: "Door Locked", category: "other", device_id: "door_bridge_000000", device_class: "lock" },
        last_changed: ago(26),
    },
];
export async function sensorDevices() {
    await wait(380);
    return SENSOR_DEVICES;
}
export async function sensorStates() {
    await wait(380);
    return SENSOR_STATES;
}
/** Deterministic 24h series: numeric sensors get a slow wave, presence gets occupied spans. */
export async function sensorHistory(entityId) {
    await wait(300);
    const now = Date.now();
    const point = (minutesAgo, state) => ({
        ts: new Date(now - minutesAgo * 60_000).toISOString(), state,
    });
    if (entityId.startsWith("binary_sensor.")) {
        const points = [];
        let state = "off";
        for (let m = 24 * 60; m >= 0; m -= 5) {
            // occupied 09:00-10:30-ish and 15:00-16:00-ish windows, open tail
            const hour = (new Date(now - m * 60_000).getHours());
            state = (hour >= 9 && hour < 11) || hour === 15 ? "on" : "off";
            points.push(point(m, state));
        }
        points.push(point(0, "on"));
        return { points, count: points.length };
    }
    const base = parseFloat(SENSOR_STATES.find((r) => r.entity_id === entityId)?.state ?? "1") || 1;
    const wave = Number.isInteger(base) ? 0.08 : 0.15; // ppm drifts less than small values
    const points = [];
    for (let m = 24 * 60; m >= 0; m -= 15) {
        const v = base * (1 + wave * Math.sin((m / 180) * Math.PI));
        points.push(point(m, v.toFixed(Number.isInteger(base) ? 1 : 3)));
    }
    return { points, count: points.length };
}
