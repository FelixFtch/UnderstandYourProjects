// Data source for the Jarvis feature: companion-api, or offline fixtures when
// VITE_STUDIO_FIXTURES=true (the fixture module is only loaded in that mode).
import { api } from "../../api/client";
import type { FlowEvent, FlowSpec, Message } from "../../api/contracts";

const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";
const fx = () => import("./fixtures");

export const jarvisData = {
  messages: (opts: { limit?: number; before?: string }, signal?: AbortSignal): Promise<{ messages: Message[]; has_more: boolean }> =>
    FIXTURES ? fx().then((f) => f.messages(opts)) : api.messages("jarvis", opts, signal),
  chat: (text: string, onEvent: (e: FlowEvent) => void, signal?: AbortSignal): Promise<void> =>
    FIXTURES ? fx().then((f) => f.chat(text, onEvent, signal)) : api.chatJarvis(text, onEvent, signal),
  flow: (): Promise<FlowSpec> => (FIXTURES ? fx().then((f) => f.flowSpec()) : api.flow("studio")),
};
