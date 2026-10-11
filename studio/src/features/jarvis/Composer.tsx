import { useEffect, useLayoutEffect, useRef, type FormEvent, type KeyboardEvent } from "react";
import { Icon } from "../../design/icons";
import { cx } from "../../design/primitives";

export function Composer({ value, onChange, onSend, onStop, streaming, autoFocus }: {
  value: string; onChange: (v: string) => void; onSend: (text: string) => void; onStop: () => void; streaming: boolean; autoFocus?: boolean;
}) {
  const ta = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = ta.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  useEffect(() => {
    if (autoFocus && window.matchMedia?.("(pointer: fine)").matches) ta.current?.focus();
  }, [autoFocus]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (streaming || !value.trim()) return;
    onSend(value);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends; Shift+Enter is a newline; never send mid-IME composition (e.g. pinyin).
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      submit();
    }
  };

  const canSend = !!value.trim() && !streaming;

  return (
    <form onSubmit={submit} className="shrink-0 border-t border-line bg-stage px-3 pt-3 pb-3 sm:px-5">
      <div className="mx-auto w-full max-w-[760px]">
        <div className="flex items-end gap-2 rounded-[16px] border border-line-strong bg-surface py-1.5 pr-1.5 pl-3.5 transition-colors focus-within:border-accent/60">
          <label htmlFor="jarvis-composer" className="sr-only">Message Jarvis</label>
          <textarea
            id="jarvis-composer"
            ref={ta}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Message Jarvis…"
            className="max-h-[200px] min-h-[36px] min-w-0 flex-1 resize-none bg-transparent py-[7px] text-[15px] leading-[22px] text-ink placeholder:text-faint focus:outline-none"
          />
          {streaming ? (
            <button
              type="button"
              onClick={onStop}
              className="grid size-9 shrink-0 place-items-center rounded-full border border-line-strong text-ink hover:bg-raised"
              aria-label="Stop Jarvis"
              title="Stop"
            >
              <Icon name="stop" size={14} strokeWidth={2.4} />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!canSend}
              className={cx(
                "grid size-9 shrink-0 place-items-center rounded-full transition-colors",
                canSend ? "bg-accent text-on-accent hover:bg-accent-ink" : "bg-raised text-faint",
              )}
              aria-label="Send"
              title="Send (Enter)"
            >
              <Icon name="arrowUp" size={17} strokeWidth={2.1} />
            </button>
          )}
        </div>
        <div className="mt-1.5 hidden justify-between px-1 text-[11.5px] text-faint sm:flex">
          <span>Enter to send · Shift+Enter for a new line</span>
          <span>Studio flow · answers show how Jarvis handled them</span>
        </div>
      </div>
    </form>
  );
}
