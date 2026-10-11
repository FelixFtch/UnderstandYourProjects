// Home Assistant policy: live control, rooms → entities + allowed actions, guest actions.
import { useState } from "react";
import type { HaPolicy, PolicyDoc } from "../../api/contracts";
import { fieldView, isEntityId, setPath, unsetPath } from "./inherit";
import { ChipsEditor, FieldShell, Icon, Toggle } from "./ui";

type Obj = Record<string, unknown>;
type Rooms = HaPolicy["rooms"];

const ACTIONS = [
  "turn_on", "turn_off", "toggle", "set_brightness", "set_color", "set_temperature", "set_hvac_mode",
  "lock", "unlock", "open_cover", "close_cover", "media_play", "media_pause", "volume_set", "scene_activate",
];

export function HaTab({ doc, draft, setDraft, readOnly, parentLabel, isRoot, dirty }: {
  doc: PolicyDoc<HaPolicy>;
  draft: Obj;
  setDraft: (v: Obj) => void;
  readOnly: boolean;
  parentLabel: string | null;
  isRoot: boolean;
  dirty: boolean;
}) {
  const live = fieldView<boolean>(draft, doc.inherited, doc.effective, ["live"]);
  const rooms = fieldView<Rooms>(draft, doc.inherited, doc.effective, ["rooms"]);
  const guest = fieldView<string[]>(draft, doc.inherited, doc.effective, ["guest_actions"]);
  const [newRoom, setNewRoom] = useState("");

  // Rooms merge per room (leaf) with the levels above: edits write only that room into own values.
  const roomMap: Rooms = rooms.value ?? {};
  const ownRooms: Rooms = rooms.own ?? {};
  const inhRooms: Rooms = rooms.inherited ?? {};
  const setRoom = (room: string, cfg: Rooms[string]) => setDraft(setPath(draft, ["rooms", room], cfg));
  const dropRoom = (room: string) => setDraft(unsetPath(draft, ["rooms", room]));
  const eff = doc.effective;
  const effRooms = Object.keys(eff?.rooms ?? {});
  const effEntities = effRooms.reduce((n, r) => n + (eff.rooms[r]?.entities?.length ?? 0), 0);

  function addRoom() {
    const id = newRoom.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
    if (!id || roomMap[id]) return;
    setRoom(id, { entities: [], allowed_actions: ["turn_on", "turn_off"] });
    setNewRoom("");
  }

  return (
    <div className="dm-ha">
      <p className="dm-note"><Icon name="key" /> <span>The Home Assistant URL and access token are secrets configured on the Jetson. They are never shown here or sent to the browser.</span></p>

      <div className="dm-summary">
        <span className="dm-summary-k">Effective{dirty ? " (saved)" : ""}</span>
        <span>{eff?.live ? "Live control" : "Simulated (not live)"} · {effRooms.length} room{effRooms.length === 1 ? "" : "s"} · {effEntities} entit{effEntities === 1 ? "y" : "ies"} · guests may {eff?.guest_actions?.length ? eff.guest_actions.join(", ") : "do nothing"}</span>
      </div>

      <div className="dm-fields">
        <FieldShell title="Live control" hint="When off, Jarvis plans Home Assistant actions but does not execute them."
          view={live} parentLabel={parentLabel} readOnly={readOnly} canInherit={!isRoot} onReset={() => setDraft(unsetPath(draft, ["live"]))}>
          <label className="dm-inline">
            <Toggle checked={Boolean(live.value)} disabled={readOnly} label="Live control" onChange={(v) => setDraft(setPath(draft, ["live"], v))} />
            <span>{live.value ? "Live: actions change real devices" : "Off: actions are simulated"}</span>
          </label>
        </FieldShell>

        <FieldShell title="Rooms" hint="Which entities Jarvis may control in each room, and with which actions. Rooms combine with the levels above."
          view={rooms} parentLabel={parentLabel} readOnly={readOnly} canInherit={!isRoot} onReset={() => setDraft(unsetPath(draft, ["rooms"]))}>
          {Object.keys(roomMap).length === 0 ? <p className="dm-muted">No rooms configured at this level.</p> : null}
          <div className="dm-rooms">
            {Object.entries(roomMap).sort(([a], [b]) => a.localeCompare(b)).map(([room, cfg]) => {
              const fromAbove = room in inhRooms;
              const own = room in ownRooms;
              const origin = own ? (fromAbove ? "Overrides inherited" : "Own room") : "Inherited";
              return (
                <div key={room} className={`dm-room${own ? " is-own" : ""}`}>
                  <div className="dm-room-head">
                    <span className="dm-room-name">{room.replace(/_/g, " ")}</span>
                    <span className={`dm-src ${own ? "dm-src-own" : "dm-src-inh"}`}>{origin}</span>
                    {!readOnly && own ? (
                      <button type="button" className="dm-iconbtn ml-auto" onClick={() => dropRoom(room)}
                        aria-label={fromAbove ? `Reset room ${room} to inherited` : `Remove room ${room}`}
                        title={fromAbove ? "Reset this room to the inherited setting" : "Remove room"}>
                        <Icon name={fromAbove ? "undo" : "trash"} size={14} />
                      </button>
                    ) : null}
                  </div>
                  <div className="dm-room-grid">
                    <span className="dm-room-k">Entities</span>
                    <ChipsEditor label={`${room} entities`} values={cfg.entities ?? []} disabled={readOnly} placeholder="light.desk"
                      validate={(v) => (isEntityId(v) ? null : "Use a Home Assistant entity id like light.kitchen")}
                      onChange={(entities) => setRoom(room, { ...cfg, entities })} />
                    <span className="dm-room-k">Allowed actions</span>
                    <ChipsEditor label={`${room} actions`} values={cfg.allowed_actions ?? []} disabled={readOnly} placeholder="add action" suggestions={ACTIONS}
                      onChange={(allowed_actions) => setRoom(room, { ...cfg, allowed_actions })} />
                  </div>
                  {!own && !readOnly ? <p className="dm-room-note">Defined {parentLabel ? `via ${parentLabel}` : "above"}. Editing it here creates an override for this level.</p> : null}
                </div>
              );
            })}
          </div>
          {!readOnly ? (
            <form className="dm-addroom" onSubmit={(e) => { e.preventDefault(); addRoom(); }}>
              <input className="dm-input" value={newRoom} onChange={(e) => setNewRoom(e.target.value)} placeholder="New room, e.g. Bedroom" aria-label="New room name" />
              <button type="submit" className="dm-btn" disabled={!newRoom.trim()}><Icon name="plus" size={14} /> Add room</button>
            </form>
          ) : null}
        </FieldShell>

        <FieldShell title="Guest actions" hint="What an unrecognised speaker may ask Jarvis to do, in any allowed room."
          view={guest} parentLabel={parentLabel} readOnly={readOnly} canInherit={!isRoot} onReset={() => setDraft(unsetPath(draft, ["guest_actions"]))}>
          <ChipsEditor label="Guest actions" values={guest.value ?? []} disabled={readOnly} placeholder="add action" suggestions={ACTIONS}
            onChange={(v) => setDraft(setPath(draft, ["guest_actions"], v))} />
        </FieldShell>
      </div>
    </div>
  );
}
