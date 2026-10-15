// Feature-local data adapter: the shared client normally, in-memory fixtures when
// VITE_STUDIO_FIXTURES === "true" (offline dev). The fixture chunk is never loaded otherwise.
import { api } from "../../api/client";
import type {
  LlmProvidersResult, LlmProvidersSettings, LlmProvidersUpdate,
  Me, ModelModeResult, ModelModeSettings, ModelModeUpdate, PolicyDoc, PolicyDomain, PolicyTree,
} from "../../api/contracts";

export interface DataApi {
  me(): Promise<Me>;
  policyTree(): Promise<PolicyTree>;
  policy<T>(scope: string, domain: PolicyDomain): Promise<PolicyDoc<T>>;
  putPolicy<T>(scope: string, domain: PolicyDomain, values: Partial<T>): Promise<PolicyDoc<T>>;
  // 2026-10-14: household-wide local/cloud model switch (Model tab).
  modelMode(): Promise<ModelModeSettings>;
  putModelMode(update: ModelModeUpdate): Promise<ModelModeResult>;
  // 2026-10-15: multi-vendor cloud provider settings (Model tab, "Cloud provider" card).
  llmProviders(): Promise<LlmProvidersSettings>;
  putLlmProviders(update: LlmProvidersUpdate): Promise<LlmProvidersResult>;
}

export const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";

const live: DataApi = {
  me: () => api.me(),
  policyTree: () => api.policyTree(),
  policy: <T,>(scope: string, domain: PolicyDomain) => api.policy<T>(scope, domain),
  putPolicy: <T,>(scope: string, domain: PolicyDomain, values: Partial<T>) => api.putPolicy<T>(scope, domain, values),
  modelMode: () => api.modelMode(),
  putModelMode: (update) => api.putModelMode(update),
  llmProviders: () => api.llmProviders(),
  putLlmProviders: (update) => api.putLlmProviders(update),
};

let fixtureImpl: Promise<DataApi> | null = null;
function impl(): Promise<DataApi> {
  if (!FIXTURES) return Promise.resolve(live);
  fixtureImpl ??= import("./fixtures").then((m) => m.createFixtureApi());
  return fixtureImpl;
}

export const dataApi: DataApi = {
  me: async () => (await impl()).me(),
  policyTree: async () => (await impl()).policyTree(),
  policy: async <T,>(scope: string, domain: PolicyDomain) => (await impl()).policy<T>(scope, domain),
  putPolicy: async <T,>(scope: string, domain: PolicyDomain, values: Partial<T>) => (await impl()).putPolicy<T>(scope, domain, values),
  modelMode: async () => (await impl()).modelMode(),
  putModelMode: async (update) => (await impl()).putModelMode(update),
  llmProviders: async () => (await impl()).llmProviders(),
  putLlmProviders: async (update) => (await impl()).putLlmProviders(update),
};
