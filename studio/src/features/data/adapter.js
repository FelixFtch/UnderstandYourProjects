// Feature-local data adapter: the shared client normally, in-memory fixtures when
// VITE_STUDIO_FIXTURES === "true" (offline dev). The fixture chunk is never loaded otherwise.
import { api } from "../../api/client";
export const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";
const live = {
    me: () => api.me(),
    policyTree: () => api.policyTree(),
    policy: (scope, domain) => api.policy(scope, domain),
    putPolicy: (scope, domain, values) => api.putPolicy(scope, domain, values),
};
let fixtureImpl = null;
function impl() {
    if (!FIXTURES)
        return Promise.resolve(live);
    fixtureImpl ??= import("./fixtures").then((m) => m.createFixtureApi());
    return fixtureImpl;
}
export const dataApi = {
    me: async () => (await impl()).me(),
    policyTree: async () => (await impl()).policyTree(),
    policy: async (scope, domain) => (await impl()).policy(scope, domain),
    putPolicy: async (scope, domain, values) => (await impl()).putPolicy(scope, domain, values),
};
