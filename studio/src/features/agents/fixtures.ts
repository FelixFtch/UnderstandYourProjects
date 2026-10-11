// Offline fixtures for the Agents feature (VITE_STUDIO_FIXTURES=true only). An in-memory fake of
// the §4 endpoints with enough behaviour to exercise every interaction: paging, polling arrivals,
// partial delivery failures, locked share-card items and a simulated save failure
// (add a share-card item whose label contains "#fail").
import { ApiError } from "../../api/client";
import type {
  Contact, DirectoryEntry, Me, Message, Participant, SendResult, ShareCard, ShareCardItem, Thread,
} from "../../api/contracts";
import type { AgentsApi } from "./adapter";

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const wait = (ms = 180) => new Promise((r) => setTimeout(r, ms));
const iso = (msAgo: number) => new Date(Date.now() - msAgo).toISOString();
const MIN = 60_000;
const HOUR = 60 * MIN;
let seq = 1000;
const nextId = (p: string) => `${p}_${(seq++).toString(36)}`;

const ME: Me = {
  member_id: "robin", role: "owner", display_name: "Robin", household_id: "household",
  jarvis: {
    node_id: "hub_7f3a", display_name: "Robin's Jarvis", number: "J-4829-1300",
    urn: "urn:ai:domain:robin.jarvis.home", town: { run_id: "run-2026-10", participant: "clinic" },
  },
  agent_box: { enrolled: true, box_id: "box_jetson1" },
};

const meP: Participant = { kind: "member", id: "robin", display: "Robin" };
const myJarvis: Participant = { kind: "jarvis", id: "jarvis", display: "Robin's Jarvis" };

function contact(id: string, name: string, num: string | null, status: Contact["status"], transport: Contact["transport"] = "town", seenAgo: number | null = 2 * HOUR, note = ""): Contact {
  return {
    contact_id: id, display_name: name, number: num, status, transport, note,
    urn: `urn:ai:domain:${id.replace(/^c_/, "")}.jarvis`,
    town: transport === "town" ? { run_id: "run-2026-10", participant: id.replace(/^c_/, "") } : null,
    last_seen: seenAgo === null ? null : iso(seenAgo),
  };
}

const contacts: Contact[] = [
  contact("c_felix", "Felix's Jarvis", "J-1234-5678", "verified", "town", 5 * MIN, "Felix, college roommate"),
  contact("c_lee", "Dr. Lee's Jarvis", "J-5521-0093", "verified", "a2a", 3 * HOUR, "Clinic scheduling"),
  contact("c_frontdesk", "Clinic Front Desk", "J-7700-1824", "invited", "contracts-v1", null),
  contact("c_ana", "Ana's Jarvis", "J-3090-4471", "unverified", "town", 26 * HOUR),
  contact("c_mira", "Mira's Jarvis", "J-8812-2047", "pending_acceptance", "town", 12 * MIN),
  contact("c_promo", "PromoBot 3000", null, "blocked", "a2a", 9 * 24 * HOUR),
];

const directory: DirectoryEntry[] = [
  { urn: "urn:ai:domain:sam.jarvis", display_name: "Sam's Jarvis", transport: "town", town: { run_id: "run-2026-10", participant: "sam" }, source: "town" },
  { urn: "urn:ai:domain:library.cambridge", display_name: "Cambridge Library Agent", transport: "a2a", town: null, source: "gateway" },
  { urn: "urn:ai:domain:pharmacy.cvs-central", display_name: "Central Pharmacy", transport: "contracts-v1", town: null, source: "gateway" },
  { urn: "urn:ai:domain:jordan.jarvis", display_name: "Jordan's Jarvis", transport: "town", town: { run_id: "run-2026-10", participant: "jordan" }, source: "town" },
];

const agentP = (c: Contact): Participant => ({ kind: "agent", id: c.contact_id, display: c.display_name });
const byId = (id: string) => contacts.find((c) => c.contact_id === id)!;

function msg(thread_id: string, author: Participant, text: string, msAgo: number, status: Message["status"] = "delivered", meta: Message["meta"] = {}): Message {
  return { message_id: nextId("m"), thread_id, author, text, created_at: iso(msAgo), status, meta };
}

const threads: Thread[] = [
  { thread_id: "jarvis", kind: "jarvis", title: "Jarvis", participants: [meP, myJarvis], last_message_at: iso(2 * MIN), last_preview: "Here is today's project digest…", unread: 0 },
  { thread_id: "t_felix", kind: "direct", title: "Felix's Jarvis", participants: [meP, agentP(byId("c_felix"))], last_message_at: null, last_preview: "", unread: 1 },
  { thread_id: "t_dinner", kind: "group", title: "Friday dinner", participants: [meP, agentP(byId("c_felix")), agentP(byId("c_lee")), agentP(byId("c_ana"))], last_message_at: null, last_preview: "", unread: 0 },
  { thread_id: "t_lee", kind: "direct", title: "Dr. Lee's Jarvis", participants: [meP, agentP(byId("c_lee"))], last_message_at: null, last_preview: "", unread: 0 },
  { thread_id: "t_frontdesk", kind: "direct", title: "Clinic Front Desk", participants: [meP, agentP(byId("c_frontdesk"))], last_message_at: null, last_preview: "", unread: 0 },
];

const messages: Record<string, Message[]> = {
  t_felix: [
    msg("t_felix", myJarvis, "Hi, this is Robin's Jarvis. Robin asked me to check whether Felix is free for lunch on Thursday.", 3 * HOUR, "delivered", { handoff_thread_id: "jarvis", shared_items: ["si_profile", "si_calendar"] }),
    msg("t_felix", agentP(byId("c_felix")), "Felix is free Thursday 12:00–13:30. He suggests the noodle place on Mass Ave.", 3 * HOUR - 40_000),
    msg("t_felix", meP, "Perfect — 12:15 works for me. Can you hold it?", 2 * HOUR, "delivered", { shared_items: ["si_profile", "si_calendar"] }),
    msg("t_felix", agentP(byId("c_felix")), "Held: Thursday 12:15, Mass Ave noodles. Felix says see you there.", 2 * HOUR - 30_000),
    msg("t_felix", agentP(byId("c_felix")), "One more thing: Felix asks whether you still have his bike pump.", 6 * MIN),
  ],
  t_lee: [
    msg("t_lee", meP, "Could Dr. Lee move my follow-up to next week?", 2 * 24 * HOUR),
    msg("t_lee", agentP(byId("c_lee")), "Dr. Lee has Tuesday 9:40 or Wednesday 15:20 next week.", 2 * 24 * HOUR - MIN),
    msg("t_lee", meP, "Wednesday 15:20 please.", 2 * 24 * HOUR - 4 * MIN),
    msg("t_lee", agentP(byId("c_lee")), "Booked. A reminder will reach your Jarvis the day before.", 2 * 24 * HOUR - 5 * MIN),
  ],
  t_frontdesk: [
    msg("t_frontdesk", meP, "Hello — is the clinic open on Columbus Day?", 26 * HOUR, "failed"),
  ],
  t_dinner: [],
};

// A long group thread to exercise "load earlier".
{
  const people = [meP, agentP(byId("c_felix")), agentP(byId("c_lee")), agentP(byId("c_ana"))];
  const lines = [
    "Friday dinner — who's in?", "Felix is in, after 19:00.", "Dr. Lee can join for dessert only.",
    "Ana prefers somewhere walkable from Central.", "How about the Lebanese place?", "Felix: great choice.",
    "Any dietary needs?", "Ana is vegetarian.", "Dr. Lee: no shellfish.", "Noted, I'll pick vegetarian-friendly.",
  ];
  for (let i = 0; i < 72; i++) {
    const p = people[i % people.length];
    messages.t_dinner.push(msg("t_dinner", p, `${lines[i % lines.length]}${i >= lines.length ? ` (${Math.floor(i / lines.length) + 1})` : ""}`, (72 - i) * 37 * MIN));
  }
}

function refreshThread(id: string) {
  const t = threads.find((x) => x.thread_id === id);
  const list = messages[id] ?? [];
  if (!t) return;
  const last = list[list.length - 1];
  t.last_message_at = last?.created_at ?? null;
  t.last_preview = last ? last.text.slice(0, 90) : "";
}
Object.keys(messages).forEach(refreshThread);

function baseShareCard(thread_id: string): ShareCard {
  const items: ShareCardItem[] = [
    { item_id: "si_profile", category: "profile", label: "Name and how to address me", value_preview: "Robin · she/her", ring: "R4", source: "default", enabled: true, locked: false },
    { item_id: "si_calendar", category: "calendar", label: "Free slots (next 3)", value_preview: "Thu 12:00–13:30, Fri 9:…", ring: "R4", source: "default", enabled: true, locked: false },
    { item_id: "si_projects", category: "projects", label: "Current project names", value_preview: "UnderstandYourProjects, …", ring: "R4", source: "default", enabled: thread_id !== "t_lee", locked: false },
    { item_id: "si_reminders", category: "reminders", label: "Upcoming reminders", value_preview: "3 items this week", ring: "R2", source: "default", enabled: false, locked: false },
    { item_id: "si_location", category: "location", label: "Approximate location", value_preview: "Cambridge, MA", ring: "R1", source: "default", enabled: false, locked: false },
    { item_id: "si_health", category: "health", label: "Health notes", value_preview: "••••••", ring: "R1", source: "default", enabled: false, locked: true },
  ];
  if (thread_id === "t_dinner") {
    items.push({ item_id: "si_diet", category: "profile", label: "Dietary preferences", value_preview: "Pescatarian", ring: "R4", source: "added", enabled: true, locked: false });
  }
  return { thread_id, items, updated_at: iso(HOUR) };
}
const shareCards: Record<string, ShareCard> = {};
const cardFor = (id: string) => (shareCards[id] ??= baseShareCard(id));

const CANNED = [
  "Got it — I'll pass that along.",
  "Thanks, noted on our side.",
  "Understood. I'll confirm once they've seen it.",
];

function contactIdsOf(thread: Thread): string[] {
  return thread.participants.filter((p) => p.kind === "agent").map((p) => p.id);
}

export function createFixtureApi(): AgentsApi {
  return {
    async me() { await wait(80); return clone(ME); },
    async contacts() { await wait(); return { contacts: clone(contacts) }; },
    async directory() {
      await wait(250);
      const known = new Set(contacts.map((c) => c.urn));
      return { entries: clone(directory.filter((d) => !known.has(d.urn))) };
    },
    async addContact(c) {
      await wait();
      if (!/^urn:/.test(c.urn)) throw new ApiError(422, "urn must start with 'urn:'");
      if (contacts.some((x) => x.urn === c.urn)) throw new ApiError(409, "That agent is already a contact");
      const created: Contact = {
        contact_id: nextId("c"), display_name: c.display_name, urn: c.urn, number: null,
        transport: (c.transport as Contact["transport"]) ?? "a2a", status: "unverified",
        town: c.town ?? null, last_seen: null, note: "",
      };
      contacts.push(created);
      return clone(created);
    },
    async inviteContact(id) {
      await wait(400);
      const c = contacts.find((x) => x.contact_id === id);
      if (!c) throw new ApiError(404, "contact not found");
      if (c.transport === "contracts-v1") return { ok: true, delivery: { ok: false, error: "gateway timeout (contracts-v1 peer offline)" } };
      c.status = "invited";
      return { ok: true, delivery: { ok: true, error: null } };
    },
    async updateContact(id, patch) {
      await wait();
      const c = contacts.find((x) => x.contact_id === id);
      if (!c) throw new ApiError(404, "contact not found");
      Object.assign(c, patch);
      if (patch.status === "verified" && !c.number) c.number = "J-" + String(Math.floor(Math.random() * 1e8)).padStart(8, "0").replace(/(\d{4})(\d{4})/, "$1-$2");
      return clone(c);
    },
    async acceptContact(code) {
      await wait();
      const c = contacts.find((x) => x.invite?.invite_code === code);
      if (!c) throw new ApiError(404, "unknown, used or expired invite_code");
      c.status = "verified";
      delete c.invite;
      return { contact: clone(c), delivery: { ok: true, error: null } };
    },
    async deleteContact(id) {
      await wait();
      const i = contacts.findIndex((x) => x.contact_id === id);
      if (i >= 0) contacts.splice(i, 1);
      return { ok: true };
    },
    async threads() { await wait(120); return { threads: clone(threads) }; },
    async createThread(kind, ids, title) {
      await wait();
      if (kind === "direct") {
        const existing = threads.find((t) => t.kind === "direct" && contactIdsOf(t)[0] === ids[0]);
        if (existing) return clone(existing);
      }
      if (kind === "group" && ids.length < 2) throw new ApiError(422, "a group needs at least two contacts");
      const ps = ids.map((id) => agentP(byId(id)));
      const t: Thread = {
        thread_id: nextId("t"), kind, participants: [meP, ...ps],
        title: title || ps.map((p) => p.display).join(", "),
        last_message_at: null, last_preview: "", unread: 0,
      };
      threads.push(t);
      messages[t.thread_id] = [];
      return clone(t);
    },
    async deleteThread(id) {
      await wait();
      const i = threads.findIndex((t) => t.thread_id === id);
      if (i >= 0) threads.splice(i, 1);
      return { ok: true };
    },
    async messages(id, opts = {}) {
      await wait(150);
      const t = threads.find((x) => x.thread_id === id);
      if (!t) throw new ApiError(404, "thread not found");
      t.unread = 0;
      const all = messages[id] ?? [];
      const limit = opts.limit ?? 50;
      let end = all.length;
      if (opts.before) {
        const i = all.findIndex((m) => m.message_id === opts.before);
        end = i < 0 ? all.length : i;
      }
      const start = Math.max(0, end - limit);
      return { messages: clone(all.slice(start, end)), has_more: start > 0 };
    },
    async sendMessage(id, text) {
      await wait(600);
      const t = threads.find((x) => x.thread_id === id);
      if (!t) throw new ApiError(404, "thread not found");
      const card = cardFor(id);
      const delivery = contactIdsOf(t).map((cid) => {
        const c = contacts.find((x) => x.contact_id === cid);
        if (!c) return { contact_id: cid, ok: false, error: "contact removed" };
        if (c.status === "blocked") return { contact_id: cid, ok: false, error: "contact is blocked" };
        if (c.status === "invited" || c.status === "unverified") return { contact_id: cid, ok: false, error: "not verified yet: they have not accepted your invite" };
        return { contact_id: cid, ok: true, error: null };
      });
      const okCount = delivery.filter((d) => d.ok).length;
      const status: Message["status"] = okCount === delivery.length ? "delivered" : okCount === 0 ? "failed" : "sent";
      const message = msg(id, meP, text, 0, status, { shared_items: card.items.filter((i) => i.enabled && !i.locked).map((i) => i.item_id) });
      const list = (messages[id] ??= []);
      list.push(message);
      const replies: Message[] = [];
      delivery.filter((d) => d.ok).slice(0, 2).forEach((d, i) => {
        const r = msg(id, agentP(byId(d.contact_id)), CANNED[(list.length + i) % CANNED.length], -1 - i);
        list.push(r);
        replies.push(r);
      });
      // A late inbound reply that only polling will pick up.
      const first = delivery.find((d) => d.ok);
      if (first) {
        setTimeout(() => {
          list.push(msg(id, agentP(byId(first.contact_id)), "Follow-up: they replied — sounds good to them.", 0));
          refreshThread(id);
        }, 7000);
      }
      refreshThread(id);
      return clone<SendResult>({ message, replies, delivery });
    },
    async shareCard(id) { await wait(200); return clone(cardFor(id)); },
    async updateShareCard(id, update) {
      await wait(450);
      const card = cardFor(id);
      if (update.add?.some((a) => a.label.includes("#fail"))) throw new ApiError(500, "Simulated save failure (fixture)");
      const next = clone(card);
      for (const u of update.items ?? []) {
        const it = next.items.find((i) => i.item_id === u.item_id);
        if (!it) throw new ApiError(404, `unknown item ${u.item_id}`);
        if (it.locked && u.enabled) throw new ApiError(409, `${it.label} is locked by your privacy policy`);
        it.enabled = u.enabled;
      }
      if (update.remove?.length) next.items = next.items.filter((i) => !(update.remove!.includes(i.item_id) && i.source === "added"));
      for (const a of update.add ?? []) {
        next.items.push({
          item_id: nextId("si"), category: a.category, label: a.label,
          value_preview: a.value.length > 24 ? a.value.slice(0, 24) + "…" : a.value,
          ring: "R4", source: "added", enabled: true, locked: false,
        });
      }
      next.updated_at = new Date().toISOString();
      shareCards[id] = next;
      return clone(next);
    },
  };
}
