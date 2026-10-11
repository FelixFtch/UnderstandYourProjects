// Feature-local data adapter: the shared client in normal builds, in-memory fixtures when
// VITE_STUDIO_FIXTURES === "true" (offline dev). Fixtures are a lazy chunk, never loaded otherwise.
import { api } from "../../api/client";
import type {
  Contact, DirectoryEntry, Me, Message, SendResult, ShareCard, ShareCardUpdate, Thread,
} from "../../api/contracts";

export interface AgentsApi {
  me(): Promise<Me>;
  contacts(): Promise<{ contacts: Contact[] }>;
  directory(): Promise<{ entries: DirectoryEntry[] }>;
  addContact(c: { urn: string; display_name: string; transport?: string; town?: DirectoryEntry["town"] }): Promise<Contact>;
  inviteContact(contact_id: string): Promise<{ ok: boolean; delivery: { ok: boolean; error: string | null } }>;
  updateContact(id: string, patch: Partial<Pick<Contact, "display_name" | "note" | "status">>): Promise<Contact>;
  acceptContact(invite_code: string, card?: Record<string, unknown>): Promise<{ contact: Contact; delivery: { ok: boolean; error: string | null } | null }>;
  deleteContact(id: string): Promise<{ ok: boolean }>;
  threads(): Promise<{ threads: Thread[] }>;
  createThread(kind: "direct" | "group", contact_ids: string[], title?: string): Promise<Thread>;
  deleteThread(id: string): Promise<{ ok: boolean }>;
  messages(id: string, opts?: { limit?: number; before?: string }): Promise<{ messages: Message[]; has_more: boolean }>;
  sendMessage(id: string, text: string): Promise<SendResult>;
  shareCard(id: string): Promise<ShareCard>;
  updateShareCard(id: string, update: ShareCardUpdate): Promise<ShareCard>;
}

export const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";

const live: AgentsApi = {
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

let fixtureImpl: Promise<AgentsApi> | null = null;
function impl(): Promise<AgentsApi> {
  if (!FIXTURES) return Promise.resolve(live);
  fixtureImpl ??= import("./fixtures").then((m) => m.createFixtureApi());
  return fixtureImpl;
}

export const agentsApi = Object.fromEntries(
  (Object.keys(live) as Array<keyof AgentsApi>).map((k) => [
    k,
    async (...args: unknown[]) => ((await impl())[k] as unknown as (...a: unknown[]) => Promise<unknown>)(...args),
  ]),
) as unknown as AgentsApi;
