// Data source for Devices: companion-api, or offline fixtures (VITE_STUDIO_FIXTURES=true).
import { api } from "../../api/client";
const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";
const fx = () => import("./fixtures");
export const devicesData = {
    devices: (s) => (FIXTURES ? fx().then((f) => f.devices()) : api.devices(s)),
    homeDevices: (s) => (FIXTURES ? fx().then((f) => f.homeDevices()) : api.homeDevices(s)),
    homeDeviceAction: (homeDeviceId, actionId, executionMode = "live") => FIXTURES ? fx().then((f) => f.homeDeviceAction(homeDeviceId, actionId, executionMode)) : api.homeDeviceAction(homeDeviceId, actionId, executionMode),
    projects: (s) => (FIXTURES ? fx().then((f) => f.projects()) : api.projects(s)),
    project: (id, s) => (FIXTURES ? fx().then((f) => f.project(id)) : api.project(id, s)),
    projectGraph: (id, s) => (FIXTURES ? fx().then((f) => f.projectGraph(id)) : api.projectGraph(id, s)),
    ask: (id, q) => (FIXTURES ? fx().then((f) => f.ask(id, q)) : api.askProject(id, q)),
    // Evidence-chain knowledge search (B2): ONE retrieval + ONE synthesis,
    // answer and its contract evidence arrive together.
    knowledgeAsk: (id, q) => (FIXTURES ? fx().then((f) => f.knowledgeAsk(id, q)) : api.knowledgeQuery(q, id)),
    analyze: (path, deviceId) => FIXTURES ? fx().then((f) => f.analyze(path, deviceId)) : api.analyzeFolder(path, deviceId),
    job: (jobId) => (FIXTURES ? fx().then((f) => f.job(jobId)) : api.analyzeJob(jobId)),
    // 2026-10-14: qwen cloud spend meter (GET /api/studio/cloud-usage).
    cloudUsage: (s) => (FIXTURES ? fx().then((f) => f.cloudUsage()) : api.cloudUsage(s)),
};
