// Feature-local data adapter: the shared client in normal builds, in-memory fixtures when
// VITE_STUDIO_FIXTURES === "true" (offline dev). Fixtures are a lazy chunk, never loaded otherwise.
import { api } from "../../api/client";
export const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";
const live = {
    me: () => api.me(),
    contacts: () => api.contacts(),
    directory: () => api.directory(),
    addContact: (c) => api.addContact(c),
    inviteContact: (id) => api.inviteContact(id),
    updateContact: (id, patch) => api.updateContact(id, patch),
    acceptContact: (code, card) => api.acceptContact(code, card),
    deleteContact: (id) => api.deleteContact(id),
    threads: () => api.threads(),
    createThread: (kind, ids, title) => api.createThread(kind, ids, title),
    deleteThread: (id) => api.deleteThread(id),
    messages: (id, opts) => api.messages(id, opts),
    sendMessage: (id, text) => api.sendMessage(id, text),
    shareCard: (id) => api.shareCard(id),
    updateShareCard: (id, u) => api.updateShareCard(id, u),
};
let fixtureImpl = null;
function impl() {
    if (!FIXTURES)
        return Promise.resolve(live);
    fixtureImpl ??= import("./fixtures").then((m) => m.createFixtureApi());
    return fixtureImpl;
}
export const agentsApi = Object.fromEntries(Object.keys(live).map((k) => [
    k,
    async (...args) => (await impl())[k](...args),
]));
