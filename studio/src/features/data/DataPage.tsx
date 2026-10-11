// Data: principal tree (Town default → Household → members, Guest) × domain tabs
// (Privacy rings | Home Assistant | Scheduling). Route: #/data/<scope>/<domain?>.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { FeaturePageProps } from "../../app/routes";
import { ApiError } from "../../api/client";
import type { HaPolicy, Me, PolicyDoc, PolicyDomain, PolicyTree, PrivacyPolicy, SchedulePolicy } from "../../api/contracts";
import { dataApi } from "./adapter";
import { HaTab } from "./HaTab";
import {
  DOMAINS, DOMAIN_LABEL, KIND_INFO, clone, dataHash, deepEqual, flattenScopes, parseDataRoute, scopeChain,
  validatePrivacy, validateSchedule,
} from "./inherit";
import { PrivacyTab } from "./PrivacyTab";
import { ScheduleTab } from "./ScheduleTab";
import { Icon, KIND_ICON, Modal, Spinner } from "./ui";

const DOMAIN_PHRASE: Record<PolicyDomain, string> = { privacy: "privacy rings", ha: "Home Assistant", schedule: "scheduling" };
import "./data.css";

type Obj = Record<string, unknown>;
const WIDE = 700;

function errText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return "Only the household owner can change policy.";
    if (e.status === 422 || e.status === 400) return `The hub rejected these values: ${e.message}`;
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

/** The shell passes the decoded tail ("member:robin/privacy"); fall back to the hash if it doesn't. */
function routeRaw(param: string | undefined): string | undefined {
  if (param) return param;
  const h = typeof window !== "undefined" ? window.location.hash : "";
  if (!h.startsWith("#/data/")) return undefined;
  try { return decodeURIComponent(h.slice("#/data/".length)); } catch { return h.slice("#/data/".length); }
}

function useWide(ref: React.RefObject<HTMLElement | null>): boolean {
  const [wide, setWide] = useState(true);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setWide(el.clientWidth >= WIDE);
    measure();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [ref]);
  return wide;
}

export default function DataPage({ param, navigate }: FeaturePageProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const wide = useWide(rootRef);
  const route = parseDataRoute(routeRaw(param));

  const [me, setMe] = useState<Me | null>(null);
  const [meError, setMeError] = useState<string | null>(null);
  const [tree, setTree] = useState<PolicyTree | null>(null);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [doc, setDoc] = useState<PolicyDoc | null>(null);
  const [draft, setDraft] = useState<Obj>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);
  const [pendingHash, setPendingHash] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    dataApi.me().then(setMe).catch((e) => setMeError(errText(e)));
    dataApi.policyTree().then(setTree).catch((e) => setTreeError(errText(e)));
  }, []);

  const nodes = useMemo(() => (tree ? flattenScopes(tree.scopes) : []), [tree]);
  const domains = tree?.domains?.length ? tree.domains.filter((d) => DOMAINS.includes(d)) : DOMAINS;
  const myScope = me ? `member:${me.member_id}` : null;
  const scope = route.scope && (!tree || nodes.some((n) => n.scope.scope === route.scope))
    ? route.scope
    : nodes.find((n) => n.scope.scope === myScope)?.scope.scope ?? nodes.find((n) => n.scope.kind === "household")?.scope.scope ?? nodes[0]?.scope.scope;
  const domain: PolicyDomain = route.domain && domains.includes(route.domain) ? route.domain : "privacy";
  const unknownScope = Boolean(route.scope && tree && !nodes.some((n) => n.scope.scope === route.scope));

  const chain = useMemo(() => (tree && scope ? scopeChain(tree.scopes, scope) : []), [tree, scope]);
  const current = chain[chain.length - 1];
  const parent = chain.length > 1 ? chain[chain.length - 2] : null;
  const isRoot = !current?.parent;

  // Load the policy document for scope × domain.
  useEffect(() => {
    if (!scope) return;
    let alive = true;
    setDoc(null); setLoadError(null); setSaveError(null); setJustSaved(false);
    dataApi.policy<Obj>(scope, domain)
      .then((d) => { if (alive) { setDoc(d as PolicyDoc); setDraft(clone((d.values ?? {}) as Obj)); } })
      .catch((e) => { if (alive) setLoadError(errText(e)); });
    return () => { alive = false; };
  }, [scope, domain, nonce]);

  useEffect(() => {
    if (!justSaved) return;
    const t = window.setTimeout(() => setJustSaved(false), 3000);
    return () => window.clearTimeout(t);
  }, [justSaved]);

  const readOnly = !me || me.role !== "owner";
  const dirty = Boolean(doc) && !deepEqual(doc?.values ?? {}, draft);
  const clientErrors = domain === "privacy" ? validatePrivacy(draft) : domain === "schedule" ? validateSchedule(draft) : [];

  const go = useCallback((hash: string) => {
    if (dirty && !readOnly) setPendingHash(hash); else navigate(hash);
  }, [dirty, readOnly, navigate]);

  // Warn before closing the tab with unsaved edits.
  useEffect(() => {
    if (!dirty || readOnly) return;
    const onBefore = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", onBefore);
    return () => window.removeEventListener("beforeunload", onBefore);
  }, [dirty, readOnly]);

  async function save() {
    if (!scope || !doc || readOnly || clientErrors.length) return;
    setSaving(true);
    setSaveError(null);
    try {
      const next = await dataApi.putPolicy<Obj>(scope, domain, draft);
      setDoc(next as PolicyDoc);
      setDraft(clone((next.values ?? {}) as Obj));
      setJustSaved(true);
    } catch (e) {
      setSaveError(errText(e));
    } finally {
      setSaving(false);
    }
  }

  const tabProps = { draft, setDraft: (v: Obj) => { setDraft(v); setSaveError(null); }, readOnly, parentLabel: parent?.label ?? null, isRoot, dirty };

  return (
    <div className="dm-root" ref={rootRef}>
      <div className="dm-layout" data-layout={wide ? "two" : "one"}>
        <nav className="dm-tree" aria-label="Who the settings apply to">
          <div className="dm-tree-head">
            <h2>Who it applies to</h2>
            <p>Settings flow down the tree: each level inherits from the one above and can override single settings.</p>
          </div>
          {treeError ? <p className="dm-alert dm-alert-error"><Icon name="alert" /> {treeError}</p> : null}
          {!tree && !treeError ? <div className="dm-center"><Spinner /> Loading…</div> : null}
          <ul className="dm-nodes" role="list">
            {nodes.map(({ scope: s, depth }) => {
              const active = s.scope === scope;
              return (
                <li key={s.scope} className={depth === 0 ? "is-top" : undefined} style={{ ["--dm-depth" as string]: String(depth) }}>
                  <button type="button" className={`dm-node dm-node-${s.kind}${active ? " is-active" : ""}`} aria-current={active ? "page" : undefined}
                    onClick={() => go(dataHash(s.scope, domain))}>
                    <span className="dm-node-icon"><Icon name={KIND_ICON[s.kind]} size={15} /></span>
                    <span className="dm-node-text">
                      <span className="dm-node-label">{s.label}{s.scope === myScope ? <span className="dm-you">you</span> : null}</span>
                      <span className="dm-node-desc">{KIND_INFO[s.kind].text}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <main className="dm-main">
          <header className="dm-head">
            <ol className="dm-crumbs" aria-label="Inheritance chain">
              {chain.map((c, i) => (
                <li key={c.scope}>
                  {i ? <Icon name="chevron" size={12} /> : null}
                  <button type="button" className="dm-crumb" disabled={c.scope === scope} onClick={() => go(dataHash(c.scope, domain))}>{c.label}</button>
                </li>
              ))}
            </ol>
            <div className="dm-head-row">
              <h2 className="dm-title">
                {current ? <Icon name={KIND_ICON[current.kind]} size={20} /> : null}
                <span>{current?.label ?? "…"}</span>
                {current ? <span className="dm-kind">{KIND_INFO[current.kind].title}</span> : null}
              </h2>
              {readOnly && me ? <span className="dm-ro"><Icon name="lock" size={13} /> Read-only</span> : null}
            </div>
            {current?.kind === "guest" ? <p className="dm-note dm-note-sm"><Icon name="info" /> <span>The hub clamps guest values: guests never get more than the household allows, and can't change settings by voice.</span></p> : null}
            {isRoot && current ? <p className="dm-note dm-note-sm"><Icon name="info" /> <span>This is the root: everything below inherits from here, and there is nothing above it to inherit.</span></p> : null}
            {unknownScope ? <p className="dm-alert dm-alert-warn"><Icon name="alert" /> Unknown scope “{route.scope}”. Showing {current?.label}.</p> : null}
            <div className="dm-tabs" role="tablist" aria-label="Domain">
              {domains.map((d) => (
                <button key={d} type="button" role="tab" aria-selected={d === domain} className="dm-tab"
                  onClick={() => scope && go(dataHash(scope, d))}>{DOMAIN_LABEL[d]}</button>
              ))}
            </div>
          </header>

          <div className="dm-scroll" role="tabpanel" aria-label={DOMAIN_LABEL[domain]}>
            {loadError ? (
              <div className="dm-alert dm-alert-error"><Icon name="alert" /> <span className="flex-1">{loadError}</span>
                <button type="button" className="dm-btn dm-btn-xs" onClick={() => setNonce((n) => n + 1)}>Retry</button></div>
            ) : null}
            {!doc && !loadError && scope ? <div className="dm-center dm-tall"><Spinner /> Loading {DOMAIN_PHRASE[domain]}…</div> : null}
            {doc && doc.scope === scope && doc.domain === domain ? (
              domain === "privacy" ? <PrivacyTab doc={doc as unknown as PolicyDoc<PrivacyPolicy>} {...tabProps} />
                : domain === "ha" ? <HaTab doc={doc as unknown as PolicyDoc<HaPolicy>} {...tabProps} />
                : <ScheduleTab doc={doc as unknown as PolicyDoc<SchedulePolicy>} {...tabProps} />
            ) : null}
          </div>

          <footer className={`dm-savebar${dirty && !readOnly ? " is-dirty" : ""}${saveError ? " is-error" : ""}`}>
            {readOnly ? (
              <span className="dm-savebar-msg"><Icon name="lock" size={14} />
                {me ? <>Only the household owner can change policy. You're signed in as <b>{me.role}</b>.</> : meError ? <>Couldn't confirm your role ({meError}); editing is disabled.</> : <>Checking your role…</>}
              </span>
            ) : saveError || clientErrors.length ? (
              <>
                <span className="dm-savebar-msg" role="alert"><Icon name="alert" size={14} /> {saveError ?? clientErrors.join(" · ")}</span>
                <button type="button" className="dm-btn dm-btn-sm" onClick={() => { setDraft(clone((doc?.values ?? {}) as Obj)); setSaveError(null); }}>Discard</button>
                <button type="button" className="dm-btn dm-btn-sm dm-btn-primary" disabled={saving || clientErrors.length > 0} onClick={() => void save()}>{saving ? "Saving…" : "Try again"}</button>
              </>
            ) : dirty ? (
              <>
                <span className="dm-savebar-msg">Unsaved changes to {DOMAIN_PHRASE[domain]} for {current?.label}</span>
                <button type="button" className="dm-btn dm-btn-sm" disabled={saving} onClick={() => setDraft(clone((doc?.values ?? {}) as Obj))}>Discard</button>
                <button type="button" className="dm-btn dm-btn-sm dm-btn-primary" disabled={saving} onClick={() => void save()}>{saving ? "Saving…" : "Save"}</button>
              </>
            ) : doc ? (
              <span className="dm-savebar-msg dm-muted">
                {justSaved ? <><Icon name="check" size={14} /> Saved.</> : null}{" "}
                {doc.updated_at ? <>Last changed {new Date(doc.updated_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}{doc.updated_by ? ` by ${doc.updated_by}` : ""}.</>
                  : Object.keys(doc.values ?? {}).length ? <>No unsaved changes.</> : <>Nothing set at this level yet; everything is inherited.</>}
              </span>
            ) : <span className="dm-savebar-msg dm-muted">&nbsp;</span>}
          </footer>
        </main>
      </div>

      {pendingHash ? (
        <Modal title="Discard unsaved changes?" onClose={() => setPendingHash(null)} footer={<>
          <button type="button" className="dm-btn" data-autofocus onClick={() => setPendingHash(null)}>Keep editing</button>
          <button type="button" className="dm-btn dm-btn-danger" onClick={() => { const h = pendingHash; setPendingHash(null); setDraft(clone((doc?.values ?? {}) as Obj)); navigate(h); }}>Discard</button>
        </>}>
          <p>You changed {DOMAIN_PHRASE[domain]} for {current?.label} without saving.</p>
        </Modal>
      ) : null}
    </div>
  );
}
