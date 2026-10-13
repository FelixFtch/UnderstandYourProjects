// Data source for Devices: companion-api, or offline fixtures (VITE_STUDIO_FIXTURES=true).
import { api } from "../../api/client";
const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";
const fx = () => import("./fixtures");
export const devicesData = {
    devices: (s) => (FIXTURES ? fx().then((f) => f.devices()) : api.devices(s)),
    projects: (s) => (FIXTURES ? fx().then((f) => f.projects()) : api.projects(s)),
    project: (id, s) => (FIXTURES ? fx().then((f) => f.project(id)) : api.project(id, s)),
    projectGraph: (id, s) => (FIXTURES ? fx().then((f) => f.projectGraph(id)) : api.projectGraph(id, s)),
    ask: (id, q) => (FIXTURES ? fx().then((f) => f.ask(id, q)) : api.askProject(id, q)),
    analyze: (path, deviceId) => FIXTURES ? fx().then((f) => f.analyze(path, deviceId)) : api.analyzeFolder(path, deviceId),
    job: (jobId) => (FIXTURES ? fx().then((f) => f.job(jobId)) : api.analyzeJob(jobId)),
};
