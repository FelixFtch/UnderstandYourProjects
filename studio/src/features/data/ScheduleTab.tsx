// Scheduling policy: calendar visibility, agent proposals/bookings, quiet hours, reminder lead time.
import type { PolicyDoc, SchedulePolicy } from "../../api/contracts";
import { fieldView, setPath, unsetPath } from "./inherit";
import { FieldShell, Segmented, Toggle } from "./ui";

type Obj = Record<string, unknown>;

export function ScheduleTab({ doc, draft, setDraft, readOnly, parentLabel, isRoot, dirty }: {
  doc: PolicyDoc<SchedulePolicy>;
  draft: Obj;
  setDraft: (v: Obj) => void;
  readOnly: boolean;
  parentLabel: string | null;
  isRoot: boolean;
  dirty: boolean;
}) {
  const f = <K extends keyof SchedulePolicy>(k: K) => fieldView<SchedulePolicy[K]>(draft, doc.inherited, doc.effective, [k]);
  const vis = f("calendar_visibility");
  const propose = f("agents_can_propose");
  const book = f("agents_can_book");
  const quiet = f("quiet_hours");
  const lead = f("reminder_lead_minutes");
  const shell = { parentLabel, readOnly, canInherit: !isRoot };
  const set = (k: keyof SchedulePolicy, v: unknown) => setDraft(setPath(draft, [k], v));
  const reset = (k: keyof SchedulePolicy) => setDraft(unsetPath(draft, [k]));
  const eff = doc.effective;

  return (
    <div className="dm-schedule">
      <div className="dm-summary">
        <span className="dm-summary-k">Effective{dirty ? " (saved)" : ""}</span>
        <span>
          Calendar {eff?.calendar_visibility === "household" ? "visible to the household" : "private"} ·
          {" "}agents {eff?.agents_can_book ? "can book" : eff?.agents_can_propose ? "can propose times" : "can't schedule"} ·
          {" "}{eff?.quiet_hours ? `quiet ${eff.quiet_hours.start}–${eff.quiet_hours.end}` : "no quiet hours"} ·
          {" "}reminders {eff?.reminder_lead_minutes ?? "?"} min ahead
        </span>
      </div>

      <div className="dm-fields">
        <FieldShell title="Calendar visibility" hint="Who at home can ask Jarvis about this calendar." view={vis} {...shell} onReset={() => reset("calendar_visibility")}>
          <Segmented label="Calendar visibility" value={vis.value} disabled={readOnly} onChange={(v) => set("calendar_visibility", v)}
            options={[{ value: "private", label: "Private", hint: "Only the owner of the calendar" }, { value: "household", label: "Household", hint: "Anyone in the household" }]} />
        </FieldShell>

        <FieldShell title="Other agents can propose times" hint="Agents may suggest meeting slots; you confirm." view={propose} {...shell} onReset={() => reset("agents_can_propose")}>
          <label className="dm-inline">
            <Toggle checked={Boolean(propose.value)} disabled={readOnly} label="Agents can propose"
              onChange={(v) => setDraft(v ? setPath(draft, ["agents_can_propose"], true) : setPath(setPath(draft, ["agents_can_propose"], false), ["agents_can_book"], false))} />
            <span>{propose.value ? "Allowed" : "Not allowed"}</span>
          </label>
        </FieldShell>

        <FieldShell title="Other agents can book" hint="Agents may put confirmed events on the calendar without asking. Turning this on also allows proposals." view={book} {...shell} onReset={() => reset("agents_can_book")}>
          <label className="dm-inline">
            <Toggle checked={Boolean(book.value)} disabled={readOnly} label="Agents can book"
              onChange={(v) => setDraft(v ? setPath(setPath(draft, ["agents_can_book"], true), ["agents_can_propose"], true) : setPath(draft, ["agents_can_book"], false))} />
            <span>{book.value ? "Allowed" : "Not allowed"}</span>
          </label>
        </FieldShell>

        <FieldShell title="Quiet hours" hint="Jarvis holds non-urgent reminders and agent messages until they end." view={quiet} {...shell} onReset={() => reset("quiet_hours")}>
          <div className="dm-inline dm-wrap">
            <Toggle checked={Boolean(quiet.value)} disabled={readOnly} label="Quiet hours"
              onChange={(v) => set("quiet_hours", v ? (quiet.value ?? quiet.inherited ?? { start: "22:00", end: "07:00" }) : null)} />
            {quiet.value ? (
              <>
                <label className="dm-time">From <input type="time" className="dm-input" value={quiet.value.start} disabled={readOnly}
                  onChange={(e) => set("quiet_hours", { ...quiet.value!, start: e.target.value })} /></label>
                <label className="dm-time">to <input type="time" className="dm-input" value={quiet.value.end} disabled={readOnly}
                  onChange={(e) => set("quiet_hours", { ...quiet.value!, end: e.target.value })} /></label>
              </>
            ) : <span>Off</span>}
          </div>
        </FieldShell>

        <FieldShell title="Reminder lead time" hint="How long before an event Jarvis reminds you." view={lead} {...shell} onReset={() => reset("reminder_lead_minutes")}>
          <div className="dm-inline dm-wrap">
            <label className="dm-time">
              <input type="number" min={0} max={1440} step={5} className="dm-input dm-num" value={lead.value ?? ""} disabled={readOnly}
                onChange={(e) => set("reminder_lead_minutes", e.target.value === "" ? 0 : Number(e.target.value))} aria-label="Reminder lead minutes" />
              minutes
            </label>
            {!readOnly ? [5, 10, 15, 30, 60].map((m) => (
              <button key={m} type="button" className="dm-btn dm-btn-xs" aria-pressed={lead.value === m} onClick={() => set("reminder_lead_minutes", m)}>{m}</button>
            )) : null}
          </div>
        </FieldShell>
      </div>
    </div>
  );
}
