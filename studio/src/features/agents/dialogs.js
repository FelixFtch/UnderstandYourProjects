import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// "Add contact" and "New group chat" dialogs.
import { useEffect, useMemo, useState } from "react";
import { agentsApi } from "./adapter";
import { Avatar, Icon, Modal, Spinner, StatusBadge } from "./ui";
function errText(e) {
    return e instanceof Error ? e.message : String(e);
}
const TRANSPORT_LABEL = { town: "NANDA Town", a2a: "A2A", "contracts-v1": "Contracts v1" };
export function AddContactDialog({ onClose, onAdded }) {
    const [tab, setTab] = useState("directory");
    const [entries, setEntries] = useState(null);
    const [dirError, setDirError] = useState(null);
    const [query, setQuery] = useState("");
    const [sendInvite, setSendInvite] = useState(true);
    const [busy, setBusy] = useState(null);
    const [error, setError] = useState(null);
    const [urn, setUrn] = useState("");
    const [name, setName] = useState("");
    const [transport, setTransport] = useState("a2a");
    useEffect(() => {
        let alive = true;
        agentsApi.directory().then((r) => { if (alive)
            setEntries(r.entries); }).catch((e) => { if (alive)
            setDirError(errText(e)); });
        return () => { alive = false; };
    }, []);
    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!entries)
            return [];
        return q ? entries.filter((e) => `${e.display_name} ${e.urn}`.toLowerCase().includes(q)) : entries;
    }, [entries, query]);
    async function add(c, key) {
        setBusy(key);
        setError(null);
        try {
            const created = await agentsApi.addContact(c);
            let invite = null;
            if (sendInvite) {
                try {
                    const r = await agentsApi.inviteContact(created.contact_id);
                    invite = { sent: r.delivery.ok, error: r.delivery.error };
                    if (r.delivery.ok)
                        created.status = "invited";
                }
                catch (e) {
                    invite = { sent: false, error: errText(e) };
                }
            }
            onAdded(created, invite);
        }
        catch (e) {
            setError(errText(e));
        }
        finally {
            setBusy(null);
        }
    }
    const urnValid = /^urn:[a-z0-9][a-z0-9-]*:\S+$/i.test(urn.trim());
    const nameValid = name.trim().length > 0;
    return (_jsxs(Modal, { title: "Add a contact", onClose: onClose, wide: true, footer: _jsxs(_Fragment, { children: [_jsxs("label", { className: "ag-check mr-auto", children: [_jsx("input", { type: "checkbox", checked: sendInvite, onChange: (e) => setSendInvite(e.target.checked) }), _jsx("span", { children: "Send my Jarvis card as an invite" })] }), tab === "urn" ? (_jsx("button", { type: "button", className: "ag-btn ag-btn-primary", disabled: !urnValid || !nameValid || busy !== null, onClick: () => add({ urn: urn.trim(), display_name: name.trim(), transport }, "urn"), children: busy === "urn" ? "Adding…" : "Add contact" })) : null] }), children: [_jsxs("div", { className: "ag-tabs", role: "tablist", children: [_jsx("button", { type: "button", role: "tab", "aria-selected": tab === "directory", className: "ag-tab", onClick: () => setTab("directory"), children: "Directory" }), _jsx("button", { type: "button", role: "tab", "aria-selected": tab === "urn", className: "ag-tab", onClick: () => setTab("urn"), children: "Enter an address" })] }), error ? _jsxs("p", { className: "ag-alert ag-alert-error", role: "alert", children: [_jsx(Icon, { name: "alert" }), " ", error] }) : null, tab === "directory" ? (_jsxs("div", { className: "ag-dir", children: [_jsx("p", { className: "ag-help", children: "Agents your gateway and NANDA Town can see that are not contacts yet." }), _jsxs("label", { className: "ag-search", children: [_jsx(Icon, { name: "search" }), _jsx("input", { value: query, onChange: (e) => setQuery(e.target.value), placeholder: "Search by name or URN", "aria-label": "Search directory" })] }), dirError ? _jsxs("p", { className: "ag-alert ag-alert-error", children: [_jsx(Icon, { name: "alert" }), " Directory unavailable: ", dirError] }) : null, !entries && !dirError ? _jsxs("div", { className: "ag-center-note", children: [_jsx(Spinner, {}), " Looking for agents\u2026"] }) : null, entries && filtered.length === 0 ? (_jsx("p", { className: "ag-empty", children: entries.length === 0 ? "No new agents discovered. Enter an address instead." : "No matches." })) : null, _jsx("ul", { className: "ag-dir-list", children: filtered.map((e) => (_jsxs("li", { className: "ag-dir-row", children: [_jsx(Avatar, { id: e.urn, name: e.display_name }), _jsxs("div", { className: "ag-dir-main", children: [_jsx("div", { className: "ag-row-title", children: e.display_name }), _jsx("div", { className: "ag-mono ag-truncate", title: e.urn, children: e.urn }), _jsxs("div", { className: "ag-tags", children: [_jsx("span", { className: "ag-tag", children: e.source === "town" ? "Town" : "Gateway" }), _jsx("span", { className: "ag-tag", children: TRANSPORT_LABEL[e.transport] ?? e.transport }), e.town ? _jsx("span", { className: "ag-tag ag-mono", children: e.town.participant }) : null] })] }), _jsx("button", { type: "button", className: "ag-btn ag-btn-sm", disabled: busy !== null, onClick: () => add({ urn: e.urn, display_name: e.display_name, transport: e.transport, town: e.town }, e.urn), children: busy === e.urn ? "Adding…" : "Add" })] }, e.urn))) })] })) : (_jsxs("div", { className: "ag-form", children: [_jsxs("label", { className: "ag-field", children: [_jsx("span", { children: "Agent URN" }), _jsx("input", { className: "ag-input ag-mono", value: urn, onChange: (e) => setUrn(e.target.value), placeholder: "urn:ai:domain:felix.jarvis", "data-autofocus": true }), urn && !urnValid ? _jsx("small", { className: "ag-field-err", children: "Must look like urn:<namespace>:<id>" }) : _jsx("small", { children: "Ask them for the URN on their Jarvis card." })] }), _jsxs("label", { className: "ag-field", children: [_jsx("span", { children: "Display name" }), _jsx("input", { className: "ag-input", value: name, onChange: (e) => setName(e.target.value), placeholder: "Felix's Jarvis" })] }), _jsxs("label", { className: "ag-field", children: [_jsx("span", { children: "Transport" }), _jsx("select", { className: "ag-input", value: transport, onChange: (e) => setTransport(e.target.value), children: Object.keys(TRANSPORT_LABEL).map((t) => _jsx("option", { value: t, children: TRANSPORT_LABEL[t] }, t)) })] }), _jsxs("p", { className: "ag-help", children: ["New contacts start as ", _jsx("b", { children: "unverified" }), ". They become verified once their Jarvis accepts your invite."] })] }))] }));
}
export function NewGroupDialog({ contacts, onClose, onCreate }) {
    const [title, setTitle] = useState("");
    const [picked, setPicked] = useState(new Set());
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const eligible = contacts
        .filter((c) => c.status !== "blocked" && c.status !== "pending_acceptance")
        .sort((a, b) => a.display_name.localeCompare(b.display_name));
    const unverifiedPicked = eligible.filter((c) => picked.has(c.contact_id) && c.status !== "verified");
    const ok = picked.size >= 2 && title.trim().length > 0;
    function toggle(id) {
        setPicked((prev) => {
            const next = new Set(prev);
            if (next.has(id))
                next.delete(id);
            else
                next.add(id);
            return next;
        });
    }
    async function create() {
        setBusy(true);
        setError(null);
        try {
            await onCreate([...picked], title.trim());
        }
        catch (e) {
            setError(errText(e));
            setBusy(false);
        }
    }
    return (_jsxs(Modal, { title: "New group chat", onClose: onClose, footer: _jsxs(_Fragment, { children: [_jsxs("span", { className: "ag-help mr-auto", children: [picked.size, " selected", picked.size < 2 ? " · pick at least 2" : ""] }), _jsx("button", { type: "button", className: "ag-btn", onClick: onClose, children: "Cancel" }), _jsx("button", { type: "button", className: "ag-btn ag-btn-primary", disabled: !ok || busy, onClick: create, children: busy ? "Creating…" : "Create group" })] }), children: [error ? _jsxs("p", { className: "ag-alert ag-alert-error", role: "alert", children: [_jsx(Icon, { name: "alert" }), " ", error] }) : null, _jsxs("label", { className: "ag-field", children: [_jsx("span", { children: "Title" }), _jsx("input", { className: "ag-input", value: title, onChange: (e) => setTitle(e.target.value), placeholder: "Friday dinner", "data-autofocus": true })] }), _jsxs("fieldset", { className: "ag-pick", children: [_jsx("legend", { children: "Members" }), eligible.length === 0 ? _jsx("p", { className: "ag-empty", children: "Add at least two contacts first." }) : null, eligible.map((c) => (_jsxs("label", { className: "ag-pick-row", children: [_jsx("input", { type: "checkbox", checked: picked.has(c.contact_id), onChange: () => toggle(c.contact_id) }), _jsx(Avatar, { id: c.contact_id, name: c.display_name, size: 26 }), _jsx("span", { className: "ag-pick-name", children: c.display_name }), _jsx(StatusBadge, { status: c.status })] }, c.contact_id)))] }), unverifiedPicked.length ? (_jsxs("p", { className: "ag-alert ag-alert-warn", children: [_jsx(Icon, { name: "info" }), " ", unverifiedPicked.map((c) => c.display_name).join(", "), " ", unverifiedPicked.length === 1 ? "is" : "are", " not verified yet; messages to them may not be delivered."] })) : null, _jsx("p", { className: "ag-help", children: "Each group has its own share card. It starts from your privacy defaults." })] }));
}
