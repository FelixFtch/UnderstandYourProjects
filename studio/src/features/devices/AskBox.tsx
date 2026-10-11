import { useState, type FormEvent } from "react";
import type { ProjectAnswer } from "../../api/contracts";
import { Icon } from "../../design/icons";
import { Markdown } from "../../design/Markdown";
import { Button, Chip, ErrorState, inputClass, SkeletonText, type Tone } from "../../design/primitives";
import { devicesData } from "./data";

const CONFIDENCE: Record<ProjectAnswer["confidence"], { tone: Tone; label: string }> = {
  high: { tone: "ok", label: "high confidence" },
  medium: { tone: "info", label: "medium confidence" },
  low: { tone: "warn", label: "low confidence" },
  none: { tone: "neutral", label: "no supporting knowledge" },
  unavailable: { tone: "err", label: "knowledge unavailable" },
};

const SUGGESTIONS = ["What changed this week?", "Where is the entry point?", "What is still unfinished?"];

interface Turn { q: string; a?: ProjectAnswer; error?: unknown }

export function AskBox({ projectId, name }: { projectId: string; name: string }) {
  const [q, setQ] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);

  async function ask(question: string) {
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    setQ("");
    setTurns((t) => [...t, { q: text }]);
    try {
      const a = await devicesData.ask(projectId, text);
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, a } : x)));
    } catch (error) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error } : x)));
    } finally {
      setBusy(false);
    }
  }

  const submit = (e: FormEvent) => { e.preventDefault(); void ask(q); };

  return (
    <div>
      {turns.length ? (
        <ol className="mb-4 space-y-4">
          {turns.map((t, i) => (
            <li key={i} className="min-w-0">
              <div className="flex items-start gap-2 text-[13.5px] font-medium text-ink">
                <Icon name="search" size={14} className="mt-[3px] shrink-0 text-muted" />
                <span className="min-w-0 break-words">{t.q}</span>
              </div>
              <div className="mt-1.5 pl-[22px]">
                {t.a ? (
                  <>
                    <Markdown text={t.a.answer || "_No answer._"} className="text-[14px] text-ink-2" />
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <Chip tone={CONFIDENCE[t.a.confidence]?.tone ?? "neutral"}>{CONFIDENCE[t.a.confidence]?.label ?? t.a.confidence}</Chip>
                      {t.a.sources.map((s) => <Chip key={s.file} icon="file" mono title={s.file} className="max-w-[240px]">{s.file}</Chip>)}
                    </div>
                  </>
                ) : t.error ? (
                  <ErrorState compact error={t.error} service="Project knowledge (UYP)" onRetry={() => { setTurns((x) => x.filter((_, j) => j !== i)); void ask(t.q); }} />
                ) : (
                  <div>
                    <div className="mb-2 text-[12.5px] text-muted">Reading what Jarvis knows about {name}…</div>
                    <SkeletonText lines={3} />
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      ) : null}

      <form onSubmit={submit} className="flex gap-2">
        <label htmlFor={`ask-${projectId}`} className="sr-only">Ask about {name}</label>
        <input
          id={`ask-${projectId}`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={`Ask about ${name}…`}
          className={inputClass}
          autoComplete="off"
        />
        <Button type="submit" variant="primary" disabled={!q.trim()} loading={busy}>Ask</Button>
      </form>
      {!turns.length ? (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((s) => <Chip key={s} onClick={() => void ask(s)}>{s}</Chip>)}
        </div>
      ) : null}
    </div>
  );
}
