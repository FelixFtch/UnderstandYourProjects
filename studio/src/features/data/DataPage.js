import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// Data: principal tree (Town default → Household → members, Guest) × domain tabs
// (Privacy rings | Home Assistant | Scheduling). Route: #/data/<scope>/<domain?>.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { dataApi } from "./adapter";
import { HaTab } from "./HaTab";
import { DOMAINS, KIND_INFO, TAB_LABEL, clone, dataHash, deepEqual, flattenScopes, parseDataRoute, scopeChain, validatePrivacy, validateSchedule, } from "./inherit";
import { ModelTab } from "./ModelTab";
import { PrivacyTab } from "./PrivacyTab";
import { ScheduleTab } from "./ScheduleTab";
import { Icon, KIND_ICON, Modal, Spinner } from "./ui";
const DOMAIN_PHRASE = { privacy: "privacy rings", ha: "Home Assistant", schedule: "scheduling" };
import "./data.css";
const WIDE = 700;
function errText(e) {
    if (e instanceof ApiError) {
        if (e.status === 403)
            return "Only the household owner can change policy.";
        if (e.status === 422 || e.status === 400)
            return `The hub rejected these values: ${e.message}`;
        return e.message;
    }
    return e instanceof Error ? e.message : String(e);
}
/** The shell passes the decoded tail ("member:robin/privacy"); fall back to the hash if it doesn't. */
function routeRaw(param) {
    if (param)
        return param;
    const h = typeof window !== "undefined" ? window.location.hash : "";
    if (!h.startsWith("#/data/"))
        return undefined;
    try {
        return decodeURIComponent(h.slice("#/data/".length));
    }
    catch {
        return h.slice("#/data/".length);
    }
}
function useWide(ref) {
    const [wide, setWide] = useState(true);
    useLayoutEffect(() => {
        const el = ref.current;
        if (!el)
            return;
        const measure = () => setWide(el.clientWidth >= WIDE);
        measure();
        const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
        ro?.observe(el);
        return () => ro?.disconnect();
    }, [ref]);
    return wide;
}
export default function DataPage({ param, navigate }) {
    const rootRef = useRef(null);
    const wide = useWide(rootRef);
    const route = parseDataRoute(routeRaw(param));
    const [me, setMe] = useState(null);
    const [meError, setMeError] = useState(null);
    const [tree, setTree] = useState(null);
    const [treeError, setTreeError] = useState(null);
    const [doc, setDoc] = useState(null);
    const [draft, setDraft] = useState({});
    const [loadError, setLoadError] = useState(null);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState(null);
    const [justSaved, setJustSaved] = useState(false);
    const [pendingHash, setPendingHash] = useState(null);
    const [nonce, setNonce] = useState(0);
    useEffect(() => {
        dataApi.me().then(setMe).catch((e) => setMeError(errText(e)));
        dataApi.policyTree().then(setTree).catch((e) => setTreeError(errText(e)));
    }, []);
    const nodes = useMemo(() => (tree ? flattenScopes(tree.scopes) : []), [tree]);
    const domains = tree?.domains?.length ? tree.domains.filter((d) => DOMAINS.includes(d)) : DOMAINS;
    // 2026-10-14: the policy domains plus the household-wide "Model" switch tab.
    const tabs = [...domains, "model"];
    const myScope = me ? `member:${me.member_id}` : null;
    const scope = route.scope && (!tree || nodes.some((n) => n.scope.scope === route.scope))
        ? route.scope
        : nodes.find((n) => n.scope.scope === myScope)?.scope.scope ?? nodes.find((n) => n.scope.kind === "household")?.scope.scope ?? nodes[0]?.scope.scope;
    const domain = route.domain && tabs.includes(route.domain) ? route.domain : "privacy";
    const unknownScope = Boolean(route.scope && tree && !nodes.some((n) => n.scope.scope === route.scope));
    const domainPhrase = domain === "model" ? "model mode" : DOMAIN_PHRASE[domain];
    const chain = useMemo(() => (tree && scope ? scopeChain(tree.scopes, scope) : []), [tree, scope]);
    const current = chain[chain.length - 1];
    const parent = chain.length > 1 ? chain[chain.length - 2] : null;
    const isRoot = !current?.parent;
    // Load the policy document for scope × domain. The Model tab is not a policy
    // domain: it loads its own household-wide setting, so there is no doc to fetch.
    useEffect(() => {
        if (!scope || domain === "model") {
            setDoc(null);
            setLoadError(null);
            setSaveError(null);
            return;
        }
        let alive = true;
        setDoc(null);
        setLoadError(null);
        setSaveError(null);
        setJustSaved(false);
        dataApi.policy(scope, domain)
            .then((d) => { if (alive) {
            setDoc(d);
            setDraft(clone((d.values ?? {})));
        } })
            .catch((e) => { if (alive)
            setLoadError(errText(e)); });
        return () => { alive = false; };
    }, [scope, domain, nonce]);
    useEffect(() => {
        if (!justSaved)
            return;
        const t = window.setTimeout(() => setJustSaved(false), 3000);
        return () => window.clearTimeout(t);
    }, [justSaved]);
    const readOnly = !me || me.role !== "owner";
    const dirty = Boolean(doc) && !deepEqual(doc?.values ?? {}, draft);
    const clientErrors = domain === "privacy" ? validatePrivacy(draft) : domain === "schedule" ? validateSchedule(draft) : [];
    const go = useCallback((hash) => {
        if (dirty && !readOnly)
            setPendingHash(hash);
        else
            navigate(hash);
    }, [dirty, readOnly, navigate]);
    // Warn before closing the tab with unsaved edits.
    useEffect(() => {
        if (!dirty || readOnly)
            return;
        const onBefore = (e) => { e.preventDefault(); };
        window.addEventListener("beforeunload", onBefore);
        return () => window.removeEventListener("beforeunload", onBefore);
    }, [dirty, readOnly]);
    async function save() {
        // the Model tab has no policy doc, so `doc` is only set for real policy domains
        if (!scope || !doc || domain === "model" || readOnly || clientErrors.length)
            return;
        setSaving(true);
        setSaveError(null);
        try {
            const next = await dataApi.putPolicy(scope, domain, draft);
            setDoc(next);
            setDraft(clone((next.values ?? {})));
            setJustSaved(true);
        }
        catch (e) {
            setSaveError(errText(e));
        }
        finally {
            setSaving(false);
        }
    }
    const tabProps = { draft, setDraft: (v) => { setDraft(v); setSaveError(null); }, readOnly, parentLabel: parent?.label ?? null, isRoot, dirty };
    return (_jsxs("div", { className: "dm-root", ref: rootRef, children: [_jsxs("div", { className: "dm-layout", "data-layout": wide ? "two" : "one", children: [_jsxs("nav", { className: "dm-tree", "aria-label": "Who the settings apply to", children: [_jsxs("div", { className: "dm-tree-head", children: [_jsx("h2", { children: "Who it applies to" }), _jsx("p", { children: "Settings flow down the tree: each level inherits from the one above and can override single settings." })] }), treeError ? _jsxs("p", { className: "dm-alert dm-alert-error", children: [_jsx(Icon, { name: "alert" }), " ", treeError] }) : null, !tree && !treeError ? _jsxs("div", { className: "dm-center", children: [_jsx(Spinner, {}), " Loading\u2026"] }) : null, _jsx("ul", { className: "dm-nodes", role: "list", children: nodes.map(({ scope: s, depth }) => {
                                    const active = s.scope === scope;
                                    return (_jsx("li", { className: depth === 0 ? "is-top" : undefined, style: { ["--dm-depth"]: String(depth) }, children: _jsxs("button", { type: "button", className: `dm-node dm-node-${s.kind}${active ? " is-active" : ""}`, "aria-current": active ? "page" : undefined, onClick: () => go(dataHash(s.scope, domain)), children: [_jsx("span", { className: "dm-node-icon", children: _jsx(Icon, { name: KIND_ICON[s.kind], size: 15 }) }), _jsxs("span", { className: "dm-node-text", children: [_jsxs("span", { className: "dm-node-label", children: [s.label, s.scope === myScope ? _jsx("span", { className: "dm-you", children: "you" }) : null] }), _jsx("span", { className: "dm-node-desc", children: KIND_INFO[s.kind].text })] })] }) }, s.scope));
                                }) })] }), _jsxs("main", { className: "dm-main", children: [_jsxs("header", { className: "dm-head", children: [_jsx("ol", { className: "dm-crumbs", "aria-label": "Inheritance chain", children: chain.map((c, i) => (_jsxs("li", { children: [i ? _jsx(Icon, { name: "chevron", size: 12 }) : null, _jsx("button", { type: "button", className: "dm-crumb", disabled: c.scope === scope, onClick: () => go(dataHash(c.scope, domain)), children: c.label })] }, c.scope))) }), _jsxs("div", { className: "dm-head-row", children: [_jsxs("h2", { className: "dm-title", children: [current ? _jsx(Icon, { name: KIND_ICON[current.kind], size: 20 }) : null, _jsx("span", { children: current?.label ?? "…" }), current ? _jsx("span", { className: "dm-kind", children: KIND_INFO[current.kind].title }) : null] }), readOnly && me ? _jsxs("span", { className: "dm-ro", children: [_jsx(Icon, { name: "lock", size: 13 }), " Read-only"] }) : null] }), current?.kind === "guest" ? _jsxs("p", { className: "dm-note dm-note-sm", children: [_jsx(Icon, { name: "info" }), " ", _jsx("span", { children: "The hub clamps guest values: guests never get more than the household allows, and can't change settings by voice." })] }) : null, isRoot && current ? _jsxs("p", { className: "dm-note dm-note-sm", children: [_jsx(Icon, { name: "info" }), " ", _jsx("span", { children: "This is the root: everything below inherits from here, and there is nothing above it to inherit." })] }) : null, unknownScope ? _jsxs("p", { className: "dm-alert dm-alert-warn", children: [_jsx(Icon, { name: "alert" }), " Unknown scope \u201C", route.scope, "\u201D. Showing ", current?.label, "."] }) : null, _jsx("div", { className: "dm-tabs", role: "tablist", "aria-label": "Domain", children: tabs.map((d) => (_jsx("button", { type: "button", role: "tab", "aria-selected": d === domain, className: "dm-tab", onClick: () => scope && go(dataHash(scope, d)), children: TAB_LABEL[d] }, d))) })] }), _jsx("div", { className: "dm-scroll", role: "tabpanel", "aria-label": TAB_LABEL[domain], children: domain === "model" ? (_jsx(ModelTab, { me: me, readOnly: readOnly })) : (_jsxs(_Fragment, { children: [loadError ? (_jsxs("div", { className: "dm-alert dm-alert-error", children: [_jsx(Icon, { name: "alert" }), " ", _jsx("span", { className: "flex-1", children: loadError }), _jsx("button", { type: "button", className: "dm-btn dm-btn-xs", onClick: () => setNonce((n) => n + 1), children: "Retry" })] })) : null, !doc && !loadError && scope ? _jsxs("div", { className: "dm-center dm-tall", children: [_jsx(Spinner, {}), " Loading ", domainPhrase, "\u2026"] }) : null, doc && doc.scope === scope && doc.domain === domain ? (domain === "privacy" ? _jsx(PrivacyTab, { doc: doc, ...tabProps })
                                            : domain === "ha" ? _jsx(HaTab, { doc: doc, ...tabProps })
                                                : _jsx(ScheduleTab, { doc: doc, ...tabProps })) : null] })) }), _jsx("footer", { className: `dm-savebar${dirty && !readOnly ? " is-dirty" : ""}${saveError ? " is-error" : ""}`, children: domain === "model" ? (_jsxs("span", { className: "dm-savebar-msg dm-muted", children: [_jsx(Icon, { name: "info", size: 14 }), " Model mode applies the moment you switch it \u2014 nothing to save here."] })) : readOnly ? (_jsxs("span", { className: "dm-savebar-msg", children: [_jsx(Icon, { name: "lock", size: 14 }), me ? _jsxs(_Fragment, { children: ["Only the household owner can change policy. You're signed in as ", _jsx("b", { children: me.role }), "."] }) : meError ? _jsxs(_Fragment, { children: ["Couldn't confirm your role (", meError, "); editing is disabled."] }) : _jsx(_Fragment, { children: "Checking your role\u2026" })] })) : saveError || clientErrors.length ? (_jsxs(_Fragment, { children: [_jsxs("span", { className: "dm-savebar-msg", role: "alert", children: [_jsx(Icon, { name: "alert", size: 14 }), " ", saveError ?? clientErrors.join(" · ")] }), _jsx("button", { type: "button", className: "dm-btn dm-btn-sm", onClick: () => { setDraft(clone((doc?.values ?? {}))); setSaveError(null); }, children: "Discard" }), _jsx("button", { type: "button", className: "dm-btn dm-btn-sm dm-btn-primary", disabled: saving || clientErrors.length > 0, onClick: () => void save(), children: saving ? "Saving…" : "Try again" })] })) : dirty ? (_jsxs(_Fragment, { children: [_jsxs("span", { className: "dm-savebar-msg", children: ["Unsaved changes to ", domainPhrase, " for ", current?.label] }), _jsx("button", { type: "button", className: "dm-btn dm-btn-sm", disabled: saving, onClick: () => setDraft(clone((doc?.values ?? {}))), children: "Discard" }), _jsx("button", { type: "button", className: "dm-btn dm-btn-sm dm-btn-primary", disabled: saving, onClick: () => void save(), children: saving ? "Saving…" : "Save" })] })) : doc ? (_jsxs("span", { className: "dm-savebar-msg dm-muted", children: [justSaved ? _jsxs(_Fragment, { children: [_jsx(Icon, { name: "check", size: 14 }), " Saved."] }) : null, " ", doc.updated_at ? _jsxs(_Fragment, { children: ["Last changed ", new Date(doc.updated_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }), doc.updated_by ? ` by ${doc.updated_by}` : "", "."] })
                                            : Object.keys(doc.values ?? {}).length ? _jsx(_Fragment, { children: "No unsaved changes." }) : _jsx(_Fragment, { children: "Nothing set at this level yet; everything is inherited." })] })) : _jsx("span", { className: "dm-savebar-msg dm-muted", children: "\u00A0" }) })] })] }), pendingHash ? (_jsx(Modal, { title: "Discard unsaved changes?", onClose: () => setPendingHash(null), footer: _jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "dm-btn", "data-autofocus": true, onClick: () => setPendingHash(null), children: "Keep editing" }), _jsx("button", { type: "button", className: "dm-btn dm-btn-danger", onClick: () => { const h = pendingHash; setPendingHash(null); setDraft(clone((doc?.values ?? {}))); navigate(h); }, children: "Discard" })] }), children: _jsxs("p", { children: ["You changed ", domainPhrase, " for ", current?.label, " without saving."] }) })) : null] }));
}
