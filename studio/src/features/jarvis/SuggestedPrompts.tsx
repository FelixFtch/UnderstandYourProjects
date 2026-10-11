import { Icon, type IconName } from "../../design/icons";

const PROMPTS: Array<{ text: string; kind: string; icon: IconName }> = [
  { text: "What did I work on yesterday in commontasks?", kind: "Projects", icon: "activity" },
  { text: "Analyze ~/code/adhd-agent", kind: "Analyze a folder", icon: "folder" },
  { text: "Turn on the clinic lights", kind: "Home", icon: "bulb" },
  { text: "Ask Felix's Jarvis if he is free tomorrow", kind: "Other Jarvises", icon: "handoff" },
];

function greeting(d = new Date()): string {
  const h = d.getHours();
  if (h < 5) return "Still up";
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export function SuggestedPrompts({ name, onPick }: { name: string | null; onPick: (text: string) => void }) {
  return (
    <div className="flex min-h-full flex-col items-center justify-center py-8 text-center">
      <span className="grid size-12 place-items-center rounded-full border border-accent/40 font-serif text-[24px] text-accent-ink italic">J</span>
      <h2 className="mt-4 font-serif text-[26px] leading-tight text-ink">{greeting()}{name ? `, ${name}` : ""}.</h2>
      <p className="mt-2 max-w-[44ch] text-[14px] text-muted">
        Ask about your projects, your home, or other Jarvises. Every answer shows how Jarvis handled it:
        what it understood, what it looked up, and what it did.
      </p>
      <div className="mt-7 grid w-full max-w-[640px] gap-2 sm:grid-cols-2">
        {PROMPTS.map((p) => (
          <button
            key={p.text}
            type="button"
            onClick={() => onPick(p.text)}
            className="group flex min-w-0 items-start gap-3 rounded-[14px] border border-line bg-surface p-3.5 text-left transition-colors hover:border-line-strong hover:bg-raised"
          >
            <span className="grid size-8 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-ink">
              <Icon name={p.icon} size={16} />
            </span>
            <span className="min-w-0">
              <span className="block text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">{p.kind}</span>
              <span className="mt-0.5 block text-[14px] leading-snug text-ink">{p.text}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
