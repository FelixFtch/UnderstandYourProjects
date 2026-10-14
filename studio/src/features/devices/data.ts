// Data source for Devices: companion-api, or offline fixtures (VITE_STUDIO_FIXTURES=true).
import { api } from "../../api/client";
import type { AnalyzeJob, AnalyzeResult, CloudUsage, Device, HomeDeviceActionResult, HomeDeviceProjection, ProjectAnswer, ProjectDigest, ProjectGraph, ProjectList } from "../../api/contracts";

const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";
const fx = () => import("./fixtures");

export const devicesData = {
  devices: (s?: AbortSignal): Promise<{ devices: Device[] }> => (FIXTURES ? fx().then((f) => f.devices()) : api.devices(s)),
  homeDevices: (s?: AbortSignal): Promise<HomeDeviceProjection> => (FIXTURES ? fx().then((f) => f.homeDevices()) : api.homeDevices(s)),
  homeDeviceAction: (homeDeviceId: string, actionId: "home.light.turn_on" | "home.light.turn_off", executionMode: "live" | "dry_run" = "live"): Promise<HomeDeviceActionResult> =>
    FIXTURES ? fx().then((f) => f.homeDeviceAction(homeDeviceId, actionId, executionMode)) : api.homeDeviceAction(homeDeviceId, actionId, executionMode),
  projects: (s?: AbortSignal): Promise<ProjectList> => (FIXTURES ? fx().then((f) => f.projects()) : api.projects(s)),
  project: (id: string, s?: AbortSignal): Promise<ProjectDigest> => (FIXTURES ? fx().then((f) => f.project(id)) : api.project(id, s)),
  projectGraph: (id: string, s?: AbortSignal): Promise<ProjectGraph> => (FIXTURES ? fx().then((f) => f.projectGraph(id)) : api.projectGraph(id, s)),
  ask: (id: string, q: string): Promise<ProjectAnswer> => (FIXTURES ? fx().then((f) => f.ask(id, q)) : api.askProject(id, q)),
  analyze: (path: string, deviceId?: string): Promise<AnalyzeResult> =>
    FIXTURES ? fx().then((f) => f.analyze(path, deviceId)) : api.analyzeFolder(path, deviceId),
  job: (jobId: string): Promise<AnalyzeJob> => (FIXTURES ? fx().then((f) => f.job(jobId)) : api.analyzeJob(jobId)),
  // 2026-10-14: qwen cloud spend meter (GET /api/studio/cloud-usage).
  cloudUsage: (s?: AbortSignal): Promise<CloudUsage> => (FIXTURES ? fx().then((f) => f.cloudUsage()) : api.cloudUsage(s)),
};
