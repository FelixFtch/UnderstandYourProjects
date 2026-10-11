import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { Icon, type IconName } from "../design/icons";
import { cx, Kbd } from "../design/primitives";
import { sectionIcon } from "./nav";
import { navigate, toHash } from "./router";
import { ROUTES } from "./routes";
import { useSession } from "./session";
import { useTheme } from "./theme";

interface Item {
  id: string;
  icon: IconName;
  label: string;
  hint: string;
  group: "Go to" | "Actions";
  run: () => void;
}

export function CommandPalette({ open, onClose, current }: { open: boolean; onClose: () => void; current: string }) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const pref = useTheme((s) => s.pref);
  const cycle = useTheme((s) => s.cycle);
  const signOut = useSession((s) => s.signOut);

  const items = useMemo<Item[]>(() => {
    const all: Item[] = [
      ...ROUTES.map<Item>((r) => ({
        id: `go:${r.section}`, icon: sectionIcon(r.section), label: r.label, hint: r.hint, group: "Go to",
        run: () => navigate(toHash(r.section)),
      })),
      { id: "theme", icon: pref === "dark" ? "sun" : "moon", label: "Change theme", hint: `Currently ${pref}`, group: "Actions", run: cycle },
      { id: "signout", icon: "logout", label: "Sign out", hint: "Forget this browser's token", group: "Actions", run: signOut },
    ];
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter((it) => `${it.label} ${it.hint} ${it.id}`.toLowerCase().includes(q));
  }, [query, pref, cycle, signOut]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setIndex(Math.max(0, ROUTES.findIndex((r) => r.section === current)));
    const t = window.setTimeout(() => input.current?.focus(), 10);
    return () => window.clearTimeout(t);
  }, [open, current]);

  useEffect(() => { if (index >= items.length) setIndex(Math.max(0, items.length - 1)); }, [items.length, index]);
  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-index="${index}"]`)?.scrollIntoView({ block: "nearest" });
  }, [index]);

  if (!open) return null;

  const choose = (it: Item | undefined) => { if (!it) return; onClose(); it.run(); };

  const onKey = (e: ReactKeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => (items.length ? (i + 1) % items.length : 0)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => (items.length ? (i - 1 + items.length) % items.length : 0)); }
    else if (e.key === "Enter") { e.preventDefault(); choose(items[index]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };

  let lastGroup = "";
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center px-3 pt-[12dvh]" onKeyDown={onKey}>
      <div className="absolute inset-0 bg-[rgb(20_16_8/0.32)] backdrop-blur-[2px]" onClick={onClose} aria-hidden="true" />
      <div role="dialog" aria-modal="true" aria-label="Jump to a section" className="j-rise relative w-full max-w-[560px] overflow-hidden rounded-card border border-line bg-surface shadow-pop">
        <div className="flex items-center gap-2 border-b border-line px-4">
          <Icon name="search" size={17} className="text-muted" />
          <input
            ref={input}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setIndex(0); }}
            placeholder="Jump to a section or run an action…"
            className="h-12 min-w-0 flex-1 bg-transparent text-[15px] text-ink placeholder:text-faint focus:outline-none"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={items[index] ? `palette-${items[index].id}` : undefined}
          />
          <Kbd>esc</Kbd>
        </div>
        <ul ref={list} id="palette-list" role="listbox" className="max-h-[min(52dvh,420px)] overflow-y-auto p-1.5">
          {items.length === 0 ? <li className="px-3 py-6 text-center text-[13px] text-muted">Nothing matches “{query}”.</li> : null}
          {items.map((it, i) => {
            const header = it.group !== lastGroup ? it.group : null;
            lastGroup = it.group;
            return (
              <li key={it.id} role="presentation">
                {header ? <div className="px-3 pt-2 pb-1 text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">{header}</div> : null}
                <div
                  id={`palette-${it.id}`}
                  role="option"
                  aria-selected={i === index}
                  data-index={i}
                  onMouseMove={() => setIndex(i)}
                  onClick={() => choose(it)}
                  className={cx("flex cursor-pointer items-center gap-3 rounded-control px-3 py-2", i === index ? "bg-accent-soft" : "")}
                >
                  <span className={cx("grid size-8 place-items-center rounded-[9px] border", i === index ? "border-accent/30 bg-surface text-accent-ink" : "border-line bg-sunk text-muted")}>
                    <Icon name={it.icon} size={16} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[14px] font-medium text-ink">{it.label}</span>
                    <span className="block truncate text-[12.5px] text-muted">{it.hint}</span>
                  </span>
                  {it.id === `go:${current}` ? <span className="text-[11.5px] text-muted">current</span> : null}
                </div>
              </li>
            );
          })}
        </ul>
        <div className="flex items-center gap-4 border-t border-line bg-canvas/50 px-4 py-2 text-[11.5px] text-muted">
          <span className="flex items-center gap-1"><Kbd>↑</Kbd><Kbd>↓</Kbd> move</span>
          <span className="flex items-center gap-1"><Kbd>↵</Kbd> open</span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
