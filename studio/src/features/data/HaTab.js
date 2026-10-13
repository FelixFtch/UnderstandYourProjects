import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// Home Assistant policy: live control, rooms → entities + allowed actions, guest actions.
import { useState } from "react";
import { fieldView, isEntityId, setPath, unsetPath } from "./inherit";
import { ChipsEditor, FieldShell, Icon, Toggle } from "./ui";
const ACTIONS = [
    "turn_on", "turn_off", "toggle", "set_brightness", "set_color", "set_temperature", "set_hvac_mode",
    "lock", "unlock", "open_cover", "close_cover", "media_play", "media_pause", "volume_set", "scene_activate",
];
export function HaTab({ doc, draft, setDraft, readOnly, parentLabel, isRoot, dirty }) {
    const live = fieldView(draft, doc.inherited, doc.effective, ["live"]);
    const rooms = fieldView(draft, doc.inherited, doc.effective, ["rooms"]);
    const guest = fieldView(draft, doc.inherited, doc.effective, ["guest_actions"]);
    const [newRoom, setNewRoom] = useState("");
    // Rooms merge per room (leaf) with the levels above: edits write only that room into own values.
    const roomMap = rooms.value ?? {};
    const ownRooms = rooms.own ?? {};
    const inhRooms = rooms.inherited ?? {};
    const setRoom = (room, cfg) => setDraft(setPath(draft, ["rooms", room], cfg));
    const dropRoom = (room) => setDraft(unsetPath(draft, ["rooms", room]));
    const eff = doc.effective;
    const effRooms = Object.keys(eff?.rooms ?? {});
    const effEntities = effRooms.reduce((n, r) => n + (eff.rooms[r]?.entities?.length ?? 0), 0);
    function addRoom() {
        const id = newRoom.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
        if (!id || roomMap[id])
            return;
        setRoom(id, { entities: [], allowed_actions: ["turn_on", "turn_off"] });
        setNewRoom("");
    }
    return (_jsxs("div", { className: "dm-ha", children: [_jsxs("p", { className: "dm-note", children: [_jsx(Icon, { name: "key" }), " ", _jsx("span", { children: "The Home Assistant URL and access token are secrets configured on the Jetson. They are never shown here or sent to the browser." })] }), _jsxs("div", { className: "dm-summary", children: [_jsxs("span", { className: "dm-summary-k", children: ["Effective", dirty ? " (saved)" : ""] }), _jsxs("span", { children: [eff?.live ? "Live control" : "Simulated (not live)", " \u00B7 ", effRooms.length, " room", effRooms.length === 1 ? "" : "s", " \u00B7 ", effEntities, " entit", effEntities === 1 ? "y" : "ies", " \u00B7 guests may ", eff?.guest_actions?.length ? eff.guest_actions.join(", ") : "do nothing"] })] }), _jsxs("div", { className: "dm-fields", children: [_jsx(FieldShell, { title: "Live control", hint: "When off, Jarvis plans Home Assistant actions but does not execute them.", view: live, parentLabel: parentLabel, readOnly: readOnly, canInherit: !isRoot, onReset: () => setDraft(unsetPath(draft, ["live"])), children: _jsxs("label", { className: "dm-inline", children: [_jsx(Toggle, { checked: Boolean(live.value), disabled: readOnly, label: "Live control", onChange: (v) => setDraft(setPath(draft, ["live"], v)) }), _jsx("span", { children: live.value ? "Live: actions change real devices" : "Off: actions are simulated" })] }) }), _jsxs(FieldShell, { title: "Rooms", hint: "Which entities Jarvis may control in each room, and with which actions. Rooms combine with the levels above.", view: rooms, parentLabel: parentLabel, readOnly: readOnly, canInherit: !isRoot, onReset: () => setDraft(unsetPath(draft, ["rooms"])), children: [Object.keys(roomMap).length === 0 ? _jsx("p", { className: "dm-muted", children: "No rooms configured at this level." }) : null, _jsx("div", { className: "dm-rooms", children: Object.entries(roomMap).sort(([a], [b]) => a.localeCompare(b)).map(([room, cfg]) => {
                                    const fromAbove = room in inhRooms;
                                    const own = room in ownRooms;
                                    const origin = own ? (fromAbove ? "Overrides inherited" : "Own room") : "Inherited";
                                    return (_jsxs("div", { className: `dm-room${own ? " is-own" : ""}`, children: [_jsxs("div", { className: "dm-room-head", children: [_jsx("span", { className: "dm-room-name", children: room.replace(/_/g, " ") }), _jsx("span", { className: `dm-src ${own ? "dm-src-own" : "dm-src-inh"}`, children: origin }), !readOnly && own ? (_jsx("button", { type: "button", className: "dm-iconbtn ml-auto", onClick: () => dropRoom(room), "aria-label": fromAbove ? `Reset room ${room} to inherited` : `Remove room ${room}`, title: fromAbove ? "Reset this room to the inherited setting" : "Remove room", children: _jsx(Icon, { name: fromAbove ? "undo" : "trash", size: 14 }) })) : null] }), _jsxs("div", { className: "dm-room-grid", children: [_jsx("span", { className: "dm-room-k", children: "Entities" }), _jsx(ChipsEditor, { label: `${room} entities`, values: cfg.entities ?? [], disabled: readOnly, placeholder: "light.desk", validate: (v) => (isEntityId(v) ? null : "Use a Home Assistant entity id like light.kitchen"), onChange: (entities) => setRoom(room, { ...cfg, entities }) }), _jsx("span", { className: "dm-room-k", children: "Allowed actions" }), _jsx(ChipsEditor, { label: `${room} actions`, values: cfg.allowed_actions ?? [], disabled: readOnly, placeholder: "add action", suggestions: ACTIONS, onChange: (allowed_actions) => setRoom(room, { ...cfg, allowed_actions }) })] }), !own && !readOnly ? _jsxs("p", { className: "dm-room-note", children: ["Defined ", parentLabel ? `via ${parentLabel}` : "above", ". Editing it here creates an override for this level."] }) : null] }, room));
                                }) }), !readOnly ? (_jsxs("form", { className: "dm-addroom", onSubmit: (e) => { e.preventDefault(); addRoom(); }, children: [_jsx("input", { className: "dm-input", value: newRoom, onChange: (e) => setNewRoom(e.target.value), placeholder: "New room, e.g. Bedroom", "aria-label": "New room name" }), _jsxs("button", { type: "submit", className: "dm-btn", disabled: !newRoom.trim(), children: [_jsx(Icon, { name: "plus", size: 14 }), " Add room"] })] })) : null] }), _jsx(FieldShell, { title: "Guest actions", hint: "What an unrecognised speaker may ask Jarvis to do, in any allowed room.", view: guest, parentLabel: parentLabel, readOnly: readOnly, canInherit: !isRoot, onReset: () => setDraft(unsetPath(draft, ["guest_actions"])), children: _jsx(ChipsEditor, { label: "Guest actions", values: guest.value ?? [], disabled: readOnly, placeholder: "add action", suggestions: ACTIONS, onChange: (v) => setDraft(setPath(draft, ["guest_actions"], v)) }) })] })] }));
}
