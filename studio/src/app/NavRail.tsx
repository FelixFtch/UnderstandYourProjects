import { Icon } from "../design/icons";
import { cx } from "../design/primitives";
import { Monogram } from "./Brand";
import { MOD_KEY, sectionIcon } from "./nav";
import { toHash } from "./router";
import { ROUTES } from "./routes";
import { useTheme } from "./theme";

export function NavRail({ active, onOpenPalette, className }: { active: string; onOpenPalette: () => void; className?: string }) {
  const pref = useTheme((s) => s.pref);
  const cycle = useTheme((s) => s.cycle);
  return (
    <nav aria-label="Sections" className={cx("flex-col items-center border-r border-line bg-canvas py-3", className)}>
      <a href={toHash("jarvis")} className="mb-4 rounded-[12px]" aria-label="Jarvis Studio home">
        <Monogram size={36} />
      </a>
      <ul className="flex w-full flex-col items-center gap-1 px-2">
        {ROUTES.map((r) => {
          const on = r.section === active;
          return (
            <li key={r.section} className="w-full">
              <a
                href={toHash(r.section)}
                aria-current={on ? "page" : undefined}
                title={r.hint}
                className={cx(
                  "flex w-full flex-col items-center gap-1 rounded-[12px] py-2 text-[11px] font-medium transition-colors",
                  on ? "bg-accent-soft text-accent-ink" : "text-muted hover:bg-sunk hover:text-ink",
                )}
              >
                <Icon name={sectionIcon(r.section)} size={20} strokeWidth={on ? 1.9 : 1.6} />
                {r.label}
              </a>
            </li>
          );
        })}
      </ul>
      <div className="mt-auto flex flex-col items-center gap-1">
        <button
          type="button"
          onClick={onOpenPalette}
          className="flex flex-col items-center gap-0.5 rounded-[10px] px-2 py-1.5 text-muted hover:bg-sunk hover:text-ink"
          title={`Jump to a section (${MOD_KEY}K)`}
          aria-label="Open section switcher"
        >
          <Icon name="search" size={18} />
          <span className="text-[10px] font-medium">{MOD_KEY}K</span>
        </button>
        <button
          type="button"
          onClick={cycle}
          className="rounded-[10px] p-2 text-muted hover:bg-sunk hover:text-ink"
          title={`Theme: ${pref} (click to change)`}
          aria-label={`Theme: ${pref}. Change theme`}
        >
          <Icon name={pref === "dark" ? "moon" : pref === "system" ? "monitor" : "sun"} size={18} />
        </button>
      </div>
    </nav>
  );
}

export function BottomNav({ active, className }: { active: string; className?: string }) {
  return (
    <nav aria-label="Sections" className={cx("border-t border-line bg-canvas pb-[env(safe-area-inset-bottom)]", className)}>
      <ul className="grid" style={{ gridTemplateColumns: `repeat(${ROUTES.length}, minmax(0, 1fr))` }}>
        {ROUTES.map((r) => {
          const on = r.section === active;
          return (
            <li key={r.section}>
              <a
                href={toHash(r.section)}
                aria-current={on ? "page" : undefined}
                className={cx("flex flex-col items-center gap-0.5 py-2 text-[10.5px] font-medium", on ? "text-accent-ink" : "text-muted")}
              >
                <Icon name={sectionIcon(r.section)} size={20} strokeWidth={on ? 1.9 : 1.6} />
                {r.label}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
