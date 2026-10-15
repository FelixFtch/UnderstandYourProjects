// Offline fixtures for the Data feature (VITE_STUDIO_FIXTURES=true only): an in-memory policy
// store that computes inherited/effective like §5 and validates like the server would.
// Append ?fixtureRole=member to the URL to see the read-only (non-owner) state.
import { ApiError } from "../../api/client";
import { CATEGORIES, deepMerge, getPath, isEntityId, isObj, scopeChain, validatePrivacy, validateSchedule } from "./inherit";
const wait = (ms = 160) => new Promise((r) => setTimeout(r, ms));
const clone = (v) => JSON.parse(JSON.stringify(v));
function role() {
    try {
        const r = new URLSearchParams(window.location.search).get("fixtureRole");
        return r === "member" || r === "guest" ? r : "owner";
    }
    catch {
        return "owner";
    }
}
const SCOPES = [
    { scope: "town_default", label: "Town default", parent: null, kind: "town" },
    { scope: "household", label: "Household", parent: "town_default", kind: "household" },
    { scope: "member:robin", label: "Robin", parent: "household", kind: "member" },
    { scope: "member:dr_lee", label: "Dr. Lee", parent: "household", kind: "member" },
    { scope: "member:mia", label: "Mia", parent: "household", kind: "member" },
    { scope: "guest", label: "Guest", parent: "household", kind: "guest" },
];
const meta = {};
const store = {
    town_default: {
        privacy: {
            categories: Object.fromEntries(CATEGORIES.map((c) => [c, { ring: c === "profile" ? "R4" : "R1", share_with_agents: c === "profile" }])),
        },
        ha: { live: false, rooms: {}, guest_actions: [] },
        schedule: { calendar_visibility: "private", agents_can_propose: false, agents_can_book: false, quiet_hours: null, reminder_lead_minutes: 10 },
    },
    household: {
        privacy: { categories: { calendar: { ring: "R4", share_with_agents: true }, shopping: { ring: "R3", share_with_agents: false }, family_messages: { ring: "R2", share_with_agents: false }, reminders: { ring: "R2", share_with_agents: false } } },
        ha: {
            live: true,
            rooms: {
                living_room: { entities: ["light.living_room", "media_player.tv"], allowed_actions: ["turn_on", "turn_off", "set_brightness"] },
                kitchen: { entities: ["light.kitchen", "switch.kettle"], allowed_actions: ["turn_on", "turn_off"] },
            },
            guest_actions: ["turn_on", "turn_off"],
        },
        schedule: { calendar_visibility: "household", agents_can_propose: true, quiet_hours: { start: "22:00", end: "07:00" } },
    },
    "member:robin": {
        privacy: { categories: { projects: { ring: "R4", share_with_agents: true }, location: { ring: "R2", share_with_agents: false }, health: { ring: "R1", share_with_agents: false } } },
        ha: { rooms: { office: { entities: ["light.office", "climate.office"], allowed_actions: ["turn_on", "turn_off", "set_temperature"] } } },
        schedule: { reminder_lead_minutes: 15 },
    },
    "member:dr_lee": { privacy: { categories: { calendar: { ring: "R3" } } } },
    guest: { privacy: { categories: { profile: { ring: "R3", share_with_agents: false } } }, ha: { guest_actions: ["turn_on"] } },
};
meta["member:robin/privacy"] = { at: new Date(Date.now() - 3 * 86_400_000).toISOString(), by: "robin" };
function doc(scope, domain) {
    const chain = scopeChain(SCOPES, scope);
    if (!chain.length)
        throw new ApiError(404, `unknown scope ${scope}`);
    let inherited = {};
    for (const s of chain.slice(0, -1))
        inherited = deepMerge(inherited, store[s.scope]?.[domain] ?? {});
    const values = clone(store[scope]?.[domain] ?? {});
    let effective = deepMerge(inherited, values);
    if (scope === "guest" && domain === "ha")
        effective = { ...effective, live: Boolean(getPath(inherited, ["live"])) };
    const m = meta[`${scope}/${domain}`];
    return {
        scope, domain, values: values, inherited: inherited, effective: effective,
        updated_at: m?.at ?? null, updated_by: m?.by ?? null,
    };
}
function validate(scope, domain, values) {
    if (!isObj(values))
        throw new ApiError(422, "values must be an object");
    const errs = [];
    if (domain === "privacy") {
        errs.push(...validatePrivacy(values));
        const cats = getPath(values, ["categories"]);
        if (isObj(cats))
            for (const k of Object.keys(cats))
                if (!CATEGORIES.includes(k))
                    errs.push(`unknown privacy category '${k}'`);
    }
    if (domain === "schedule")
        errs.push(...validateSchedule(values));
    if (domain === "ha") {
        const rooms = getPath(values, ["rooms"]);
        if (isObj(rooms)) {
            for (const [room, r] of Object.entries(rooms)) {
                const ents = getPath(r, ["entities"]);
                if (Array.isArray(ents))
                    ents.forEach((e, i) => { if (!isEntityId(String(e)))
                        errs.push(`ha.rooms.${room}.entities[${i}]: '${e}' is not an entity id (domain.object_id)`); });
            }
        }
        if (scope === "guest" && getPath(values, ["live"]) === true)
            errs.push("guest cannot enable live control beyond the household");
    }
    if (errs.length)
        throw new ApiError(422, errs.join("; "));
}
export function createFixtureApi() {
    // 2026-10-14: in-memory model-mode store for the Model tab; starts local, owner-only to change.
    let mode = {
        mode: "local",
        cloud_model_route: "qwen3.8-flash",
        cloud_model_persona: "qwen3.8-flash",
        updated_at: new Date(Date.now() - 26 * 3600_000).toISOString(),
    };
    // 2026-10-15: in-memory multi-vendor provider store for the Model tab's
    // "Cloud provider" card; owner-only to change, keys never leave the fixture.
    let providers = {
        active: "qwen",
        providers: [
            { id: "qwen", label: "Qwen · Alibaba Bailian", model: "qwen3.8-flash", has_key: true, key_hint: "sk-…1a2b" },
            { id: "openai", label: "OpenAI", model: "gpt-5.2", has_key: false, key_hint: null },
            { id: "claude", label: "Claude · Anthropic", model: "claude-sonnet-4-6", has_key: true, key_hint: "sk-…9z8y" },
            { id: "gemini", label: "Gemini · Google", model: "gemini-3-flash", has_key: false, key_hint: null },
            { id: "deepseek", label: "DeepSeek", model: "deepseek-v4-flash", has_key: false, key_hint: null },
        ],
        updated_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
    };
    return {
        async me() {
            await wait(60);
            const r = role();
            return {
                member_id: "robin", role: r, display_name: "Robin", household_id: "household",
                jarvis: { node_id: "hub_7f3a", display_name: "Robin's Jarvis", number: "J-4829-1300", urn: "urn:ai:domain:robin.jarvis.home", town: null },
                agent_box: { enrolled: true, box_id: "box_jetson1" },
            };
        },
        async policyTree() { await wait(); return { scopes: clone(SCOPES), domains: ["privacy", "ha", "schedule"] }; },
        async policy(scope, domain) { await wait(200); return doc(scope, domain); },
        async putPolicy(scope, domain, values) {
            await wait(450);
            if (role() !== "owner")
                throw new ApiError(403, "only the household owner can change policy");
            validate(scope, domain, values);
            (store[scope] ??= {})[domain] = clone(values);
            meta[`${scope}/${domain}`] = { at: new Date().toISOString(), by: "robin" };
            return doc(scope, domain);
        },
        async modelMode() { await wait(); return clone(mode); },
        async putModelMode(update) {
            await wait(380);
            if (role() !== "owner")
                throw new ApiError(403, "only the household owner can switch the model mode");
            mode = {
                mode: update.mode,
                cloud_model_route: update.cloud_model_route ?? mode.cloud_model_route,
                cloud_model_persona: update.cloud_model_persona ?? mode.cloud_model_persona,
                updated_at: new Date().toISOString(),
            };
            return { ...clone(mode), pushed: true };
        },
        async llmProviders() { await wait(); return clone(providers); },
        async putLlmProviders(update) {
            await wait(380);
            if (role() !== "owner")
                throw new ApiError(403, "only the household owner can change cloud provider settings");
            // switching the active provider pushes to the voice runtime; a single-provider
            // update is stored and applies on the next turn (pushed: false)
            if ("active" in update) {
                if (!providers.providers.some((p) => p.id === update.active))
                    throw new ApiError(404, `unknown provider '${update.active}'`);
                providers = { ...providers, active: update.active, updated_at: new Date().toISOString() };
                return { ...clone(providers), pushed: true };
            }
            const idx = providers.providers.findIndex((p) => p.id === update.provider);
            if (idx < 0)
                throw new ApiError(404, `unknown provider '${update.provider}'`);
            const next = clone(providers.providers);
            const p = { ...next[idx] };
            if (update.model !== undefined && update.model.trim())
                p.model = update.model.trim();
            if (update.api_key !== undefined && update.api_key) {
                p.has_key = true;
                p.key_hint = `sk-…${update.api_key.slice(-4)}`;
            }
            next[idx] = p;
            providers = { ...providers, providers: next, updated_at: new Date().toISOString() };
            return { ...clone(providers), pushed: false };
        },
    };
}
