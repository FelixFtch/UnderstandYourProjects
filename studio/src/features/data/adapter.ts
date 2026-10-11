// Feature-local data adapter: the shared client normally, in-memory fixtures when
// VITE_STUDIO_FIXTURES === "true" (offline dev). The fixture chunk is never loaded otherwise.
import { api } from "../../api/client";
import type { Me, PolicyDoc, PolicyDomain, PolicyTree } from "../../api/contracts";

export interface DataApi {
  me(): Promise<Me>;
  policyTree(): Promise<PolicyTree>;
  policy<T>(scope: string, domain: PolicyDomain): Promise<PolicyDoc<T>>;
  putPolicy<T>(scope: string, domain: PolicyDomain, values: Partial<T>): Promise<PolicyDoc<T>>;
}

export const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";

const live: DataApi = {
  me: () => api.me(),
  policyTree: () => api.policyTree(),
  policy: <T,>(scope: string, domain: PolicyDomain) => api.policy<T>(scope, domain),
  putPolicy: <T,>(scope: string, domain: PolicyDomain, values: Partial<T>) => api.putPolicy<T>(scope, domain, values),
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
};
