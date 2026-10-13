// Data source for the Jarvis feature: companion-api, or offline fixtures when
// VITE_STUDIO_FIXTURES=true (the fixture module is only loaded in that mode).
import { api } from "../../api/client";
const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";
const fx = () => import("./fixtures");
export const jarvisData = {
    messages: (opts, signal) => FIXTURES ? fx().then((f) => f.messages(opts)) : api.messages("jarvis", opts, signal),
    chat: (text, onEvent, signal) => FIXTURES ? fx().then((f) => f.chat(text, onEvent, signal)) : api.chatJarvis(text, onEvent, signal),
    flow: () => (FIXTURES ? fx().then((f) => f.flowSpec()) : api.flow("studio")),
};
