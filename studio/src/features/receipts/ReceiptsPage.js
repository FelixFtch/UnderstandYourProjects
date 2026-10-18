import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
// Receipts — the Phase 0 read-only receipt timeline.
//
// Shows what the hub can prove today: the persisted capability-lifecycle
// audit ledger merged with the volatile governed-action feed.  No buttons
// that change anything exist on this page by design; the only interactions
// are filtering, selecting a row, and paging further back in time.
import { useEffect, useMemo, useState } from "react";
import { relativeTime } from "../../design/format";
import { useResource } from "../../design/hooks";
import { Card, Chip, cx, EmptyState, ErrorState, Segmented, SectionHeader, Skeleton, StatusDot, inputClass } from "../../design/primitives";
import { receiptsData } from "./data";
import { PATH_ORDER, STATE_MACHINE, evidenceLabel, isSimulated, kindLabel, sourceMeta, sourceScopeNote, statusMeta } from "./logic";
const SOURCE_OPTIONS = [
    { value: "", label: "All sources" },
    { value: "studio", label: "Studio" },
    { value: "voice", label: "Voice" },
    { value: "town", label: "Town" },
];
const STATUS_OPTIONS = ["", "accepted", "completed", "denied", "awaiting_confirmation", "dispatched", "queued", "running", "failed", "expired", "cancelled"];
export default function ReceiptsPage(_props) {
    const [source, setSource] = useState("");
    const [status, setStatus] = useState("");
    const [principalText, setPrincipalText] = useState("");
    const [principal, setPrincipal] = useState("");
    const [includeReads, setIncludeReads] = useState(false);
    const [selected, setSelected] = useState(null);
    // debounce the free-text filter so typing does not refetch per keystroke
    useEffect(() => {
        const t = window.setTimeout(() => setPrincipal(principalText.trim()), 300);
        return () => window.clearTimeout(t);
    }, [principalText]);
    const query = useMemo(() => ({
        ...(source ? { source } : {}),
        ...(status ? { status } : {}),
        ...(principal ? { principal } : {}),
        ...(includeReads ? { include_context_reads: true } : {}),
    }), [source, status, principal, includeReads]);
    const page = useResource((s) => receiptsData.list(query, s), [query]);
    // "Load older" accumulates pages locally; any filter change starts clean.
    const [older, setOlder] = useState([]);
    const [cursor, setCursor] = useState(null);
    const [loadingOlder, setLoadingOlder] = useState(false);
    useEffect(() => { setOlder([]); setCursor(null); setSelected(null); }, [query]);
    const rows = useMemo(() => [...(page.data?.receipts ?? []), ...older], [page.data, older]);
    const detail = rows.find((r) => r.receipt_id === selected) ?? null;
    async function loadOlder() {
        const from = page.data?.next_before ?? cursor;
        if (!from || loadingOlder)
            return;
        setLoadingOlder(true);
        try {
            const next = await receiptsData.list({ ...query, before: from });
            setOlder((o) => [...o, ...next.receipts.filter((r) => !o.some((x) => x.receipt_id === r.receipt_id))]);
            setCursor(next.next_before);
        }
        catch {
            setCursor(from); // stay put; the retry button is the page's own reload
        }
        finally {
            setLoadingOlder(false);
        }
    }
    const hasMore = !!(page.data && (page.data.next_before || cursor));
    const feedSource = page.data?.sources.find((s) => s.id === "device_action_feed");
    return (_jsxs("div", { className: "@container mx-auto w-full max-w-[1320px] space-y-6 px-4 py-6 sm:px-8 sm:py-8", children: [_jsx(SectionHeader, { level: 1, eyebrow: "Receipts", title: "Receipt timeline", description: "What was asked of connectors and what actually happened \u2014 read-only. Accepted means the connector took the instruction; only completed is a confirmed outcome." }), _jsx(Legend, {}), page.data ? (_jsxs("div", { className: "flex flex-wrap items-center gap-x-4 gap-y-2 rounded-card border border-line bg-surface px-4 py-3 text-[12.5px] text-muted shadow-card", children: [_jsx("span", { className: "min-w-0 flex-1", children: sourceScopeNote(page.data.sources) }), feedSource && !feedSource.available ? (_jsxs("span", { className: "flex items-center gap-1.5 text-warn", children: [_jsx(StatusDot, { tone: "warn" }), "Live device-action feed unavailable \u2014 showing the persisted ledger only."] })) : null] })) : null, _jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [_jsx(Segmented, { label: "Source", value: source, options: SOURCE_OPTIONS, onChange: (v) => setSource(v) }), _jsx("label", { className: "sr-only", htmlFor: "receipt-status", children: "Status" }), _jsx("select", { id: "receipt-status", className: cx(inputClass, "h-8 w-auto py-0 text-[13px]"), value: status, onChange: (e) => setStatus(e.target.value), children: STATUS_OPTIONS.map((s) => (_jsx("option", { value: s, children: s === "" ? "All statuses" : statusMeta(s).label }, s))) }), _jsx("input", { className: cx(inputClass, "h-8 w-44 py-0 text-[13px]"), placeholder: "Filter by principal\u2026", value: principalText, onChange: (e) => setPrincipalText(e.target.value), "aria-label": "Filter by principal" }), _jsxs("label", { className: "flex cursor-pointer items-center gap-1.5 text-[12.5px] text-muted select-none", children: [_jsx("input", { type: "checkbox", className: "accent-[var(--j-accent)]", checked: includeReads, onChange: (e) => setIncludeReads(e.target.checked) }), "show policy-read audit"] })] }), _jsxs("div", { className: "grid items-start gap-5 @6xl:grid-cols-[minmax(0,1fr)_340px]", children: [_jsxs(Card, { className: "min-w-0 p-2 sm:p-3", children: [page.loading && !page.data ? _jsx(RowsSkeleton, {}) : null, page.error && !page.data ? (_jsx(ErrorState, { error: page.error, service: "companion-api", title: "Couldn't load receipts", onRetry: page.reload })) : null, page.data && rows.length === 0 ? (_jsx(EmptyState, { icon: "activity", title: "No receipts match", body: "Nothing in the audit ledger or the live device-action feed matches these filters. Policy-read audit rows are hidden by default \u2014 enable 'show policy-read audit' to include them." })) : null, rows.length > 0 ? (_jsx("ol", { className: "space-y-1.5", "aria-label": "Receipt timeline", children: rows.map((r) => (_jsx(ReceiptRow, { r: r, selected: selected === r.receipt_id, onSelect: setSelected }, r.receipt_id))) })) : null, page.data && hasMore ? (_jsx("div", { className: "mt-2 flex justify-center border-t border-line pt-2", children: _jsx("button", { type: "button", onClick: () => void loadOlder(), disabled: loadingOlder, className: "rounded-control px-3 py-1.5 text-[13px] font-medium text-accent-ink transition-colors hover:bg-sunk disabled:opacity-55", children: loadingOlder ? "Loading…" : "Load older" }) })) : null] }), _jsx(ReceiptDetail, { r: detail })] })] }));
}
function Legend() {
    const path = STATE_MACHINE.filter((s) => !s.terminal);
    const terminals = STATE_MACHINE.filter((s) => s.terminal);
    return (_jsxs(Card, { className: "p-4", children: [_jsx("div", { className: "flex flex-wrap items-center gap-x-2 gap-y-2", children: path.map((s, i) => {
                    const meta = statusMeta(s.id);
                    const accepted = s.id === "accepted";
                    const completed = s.id === "completed";
                    return (_jsxs("span", { className: "flex items-center gap-2", children: [i > 0 ? _jsx("span", { className: "text-faint", "aria-hidden": "true", children: "\u2192" }) : null, _jsx(Chip, { tone: meta.tone, mono: true, title: meta.note, className: cx(accepted && "border-dashed", completed && "font-semibold"), children: meta.label })] }, s.id));
                }) }), _jsxs("div", { className: "mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-muted", children: [_jsx("span", { children: "Terminal outcomes:" }), terminals.map((s) => _jsx(Chip, { tone: statusMeta(s.id).tone, mono: true, title: statusMeta(s.id).note, children: s.label }, s.id))] }), _jsxs("ul", { className: "mt-3 space-y-1.5 text-[12.5px] text-muted", children: [_jsxs("li", { className: "flex items-start gap-2", children: [_jsx(Chip, { tone: "neutral", mono: true, className: "shrink-0 border-dashed", children: "accepted" }), _jsxs("span", { children: ["= the connector took the instruction. ", _jsx("strong", { className: "font-semibold text-ink-2", children: "It is not done yet" }), " \u2014 an accepted action has no completion evidence."] })] }), _jsxs("li", { className: "flex items-start gap-2", children: [_jsx(Chip, { tone: "ok", mono: true, className: "shrink-0 font-semibold", children: "completed" }), _jsx("span", { children: "= the only green confirmation: a confirmed outcome with read-back evidence." })] }), _jsxs("li", { className: "flex items-start gap-2", children: [_jsx(Chip, { tone: "warn", mono: true, className: "shrink-0", children: "SIMULATED" }), _jsx("span", { children: "= executed against a simulated capability (real_device: false). A simulated lock or light never reads as a real device finishing." })] })] })] }));
}
function ReceiptRow({ r, selected, onSelect }) {
    const meta = statusMeta(r.status, r);
    const simulated = isSimulated(r);
    const src = sourceMeta(r.source);
    return (_jsx("li", { children: _jsxs("button", { type: "button", onClick: () => onSelect(r.receipt_id), "aria-pressed": selected, className: cx("block w-full rounded-[12px] border border-line bg-surface px-3 py-2.5 text-left transition-[box-shadow,border-color] hover:border-line-strong", selected && "border-line-strong ring-2 ring-accent/35", simulated && "border-l-[3px] border-l-warn"), children: [_jsxs("div", { className: "flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1", children: [_jsx("span", { className: "shrink-0 text-[12px] text-muted", title: r.requested_at, children: relativeTime(r.requested_at) }), _jsx(Chip, { tone: src.tone, title: `Source: ${src.label}`, children: src.label }), simulated ? _jsx(Chip, { tone: "warn", mono: true, title: "Executed against a simulated capability (real_device: false)", children: "SIMULATED" }) : null, _jsx("span", { className: "min-w-0 flex-1" }), r.kind === "device_action" ? _jsx("span", { className: "shrink-0 font-mono text-[11px] text-faint", children: evidenceLabel(r) }) : null, _jsx(Chip, { tone: meta.tone, mono: true, title: meta.note, className: cx(r.status === "accepted" && "border-dashed", r.status === "completed" && !simulated && "font-semibold"), children: meta.label })] }), _jsxs("div", { className: "mt-1 flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px]", children: [_jsx("span", { className: "min-w-0 truncate font-mono text-[12.5px] text-ink", children: r.capability }), _jsx("span", { className: "text-muted", children: "\u00B7" }), _jsx("span", { className: "truncate text-ink-2", children: r.principal }), r.room ? _jsxs(_Fragment, { children: [_jsx("span", { className: "text-muted", children: "\u00B7" }), _jsx("span", { className: "truncate text-muted", children: r.room })] }) : null, r.risk ? _jsx(Chip, { mono: true, title: `Risk as recorded: ${r.risk}`, children: r.risk }) : null, r.auth_level ? _jsx(Chip, { mono: true, title: "Auth level of the acting member", children: r.auth_level }) : null] }), _jsxs("div", { className: "mt-1 flex min-w-0 items-center gap-2 truncate font-mono text-[11px] text-faint", children: [_jsx("span", { className: "truncate", title: `audit_ref: ${r.audit_ref}`, children: r.audit_ref }), r.request_id ? _jsxs(_Fragment, { children: [_jsx("span", { children: "\u00B7" }), _jsx("span", { className: "truncate", title: `request_id: ${r.request_id}`, children: r.request_id })] }) : null, r.error ? _jsxs(_Fragment, { children: [_jsx("span", { children: "\u00B7" }), _jsx("span", { className: "truncate text-err/80", children: r.error })] }) : null] })] }) }));
}
function ReceiptDetail({ r }) {
    if (!r) {
        return (_jsxs(Card, { className: "h-fit p-4 @6xl:sticky @6xl:top-4", children: [_jsx("div", { className: "text-[13px] font-semibold text-ink", children: "Reading a receipt" }), _jsx("p", { className: "mt-2 text-[12.5px] text-muted", children: "Select a row to see the full receipt: principal, capability, risk, auth level, confirmation state, ack and read-back, audit reference, and where it sits in the state machine." }), _jsx("p", { className: "mt-2 text-[12.5px] text-muted", children: "Remote receipt ids (the far connector's own reference) appear once the full Connector migration lands; until then this view tracks the hub-side truth only." })] }));
    }
    const meta = statusMeta(r.status, r);
    const simulated = isSimulated(r);
    const inPath = PATH_ORDER.includes(r.status);
    return (_jsxs(Card, { className: "h-fit min-w-0 p-4 @6xl:sticky @6xl:top-4", children: [_jsxs("div", { className: "flex items-start justify-between gap-2", children: [_jsxs("div", { className: "min-w-0", children: [_jsx("div", { className: "text-[11px] font-semibold tracking-[0.08em] text-muted uppercase", children: kindLabel(r.kind) }), _jsx("h3", { className: "mt-0.5 truncate font-serif text-[19px] leading-snug text-ink", title: r.capability, children: r.capability }), _jsx("div", { className: "font-mono text-[11.5px] text-muted", children: r.requested_at })] }), _jsx(Chip, { tone: meta.tone, mono: true, title: meta.note, className: cx("shrink-0", r.status === "accepted" && "border-dashed", r.status === "completed" && !simulated && "font-semibold"), children: meta.label })] }), _jsxs("div", { className: "mt-3 flex flex-wrap items-center gap-1.5", children: [PATH_ORDER.map((s, i) => {
                        const m = statusMeta(s);
                        const current = s === r.status;
                        const passed = inPath && PATH_ORDER.indexOf(r.status) > i;
                        return (_jsxs("span", { className: "flex items-center gap-1.5", children: [i > 0 ? _jsx("span", { className: cx("text-[11px]", passed ? "text-accent" : "text-faint"), "aria-hidden": "true", children: "\u2192" }) : null, _jsx("span", { title: m.note, className: cx("rounded-full border px-2 py-[1px] font-mono text-[11px]", current ? "border-accent bg-accent-soft text-accent-ink" : passed ? "border-line bg-sunk text-ink-2" : "border-line bg-surface text-faint"), children: m.label })] }, s));
                    }), !inPath ? (_jsx("span", { title: meta.note, className: "rounded-full border border-accent bg-accent-soft px-2 py-[1px] font-mono text-[11px] text-accent-ink", children: meta.label })) : null] }), meta.note ? _jsx("p", { className: "mt-2 text-[12px] text-muted", children: meta.note }) : null, simulated ? (_jsxs("div", { className: "mt-2 flex items-start gap-2 rounded-control border border-warn/30 bg-warn-soft px-3 py-2 text-[12.5px] text-warn", children: [_jsx(StatusDot, { tone: "warn", className: "mt-1.5" }), _jsxs("span", { children: ["Simulated execution (execution_mode: ", r.execution_mode ?? "—", ", real_device: false). No physical device was touched."] })] })) : null, _jsxs("dl", { className: "mt-4 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[12.5px]", children: [_jsx("dt", { className: "text-muted", children: "Source" }), _jsx("dd", { className: "truncate text-ink-2", children: sourceMeta(r.source).label }), _jsx("dt", { className: "text-muted", children: "Principal" }), _jsx("dd", { className: "truncate text-ink-2", children: r.principal }), _jsx("dt", { className: "text-muted", children: "Auth level" }), _jsx("dd", { className: "truncate text-ink-2", children: r.auth_level ?? "—" }), _jsx("dt", { className: "text-muted", children: "Room" }), _jsx("dd", { className: "truncate text-ink-2", children: r.room ?? "— (not recorded)" }), _jsx("dt", { className: "text-muted", children: "Risk" }), _jsx("dd", { className: "truncate text-ink-2", children: r.risk ?? "—" }), _jsx("dt", { className: "text-muted", children: "Confirmation" }), _jsx("dd", { className: "truncate text-ink-2", children: r.confirmation ?? "—" }), _jsx("dt", { className: "text-muted", children: "Ack" }), _jsx("dd", { className: "truncate text-ink-2", children: r.ack ? `${r.ack.received ? "received" : "not received"}${r.ack.connector ? ` · ${r.ack.connector}` : ""}` : "—" }), _jsx("dt", { className: "text-muted", children: "Read-back" }), _jsx("dd", { className: "text-ink-2", children: r.read_back && Object.keys(r.read_back).length > 0 ? (_jsx("pre", { className: "max-h-[140px] overflow-auto rounded-[10px] border border-line bg-sunk p-2 font-mono text-[11px] leading-relaxed", children: JSON.stringify(r.read_back, null, 2) })) : r.status === "accepted" && r.kind === "device_action" ? (_jsx("span", { className: "text-muted", children: "none \u2014 which is exactly why this is accepted, not completed" })) : (_jsx("span", { className: "text-muted", children: "\u2014" })) }), r.error ? _jsxs(_Fragment, { children: [_jsx("dt", { className: "text-muted", children: "Error" }), _jsx("dd", { className: "break-words font-mono text-[11.5px] text-err", children: r.error })] }) : null, _jsx("dt", { className: "text-muted", children: "Audit ref" }), _jsx("dd", { className: "truncate font-mono text-[11.5px] text-ink-2", title: r.audit_ref, children: r.audit_ref }), _jsx("dt", { className: "text-muted", children: "Request id" }), _jsx("dd", { className: "truncate font-mono text-[11.5px] text-ink-2", children: r.request_id ?? "—" }), _jsx("dt", { className: "text-muted", children: "Remote receipt" }), _jsx("dd", { className: "truncate font-mono text-[11.5px] text-ink-2", title: "Remote receipt ids arrive with the full Connector migration", children: r.remote_receipt_id ?? "—" }), r.expires_at ? _jsxs(_Fragment, { children: [_jsx("dt", { className: "text-muted", children: "Expires" }), _jsx("dd", { className: "truncate font-mono text-[11.5px] text-ink-2", children: r.expires_at })] }) : null] }), r.detail && Object.keys(r.detail).length > 0 ? (_jsxs("div", { className: "mt-4", children: [_jsx("div", { className: "mb-1 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase", children: "Audit detail" }), _jsx("pre", { className: "max-h-[180px] overflow-auto rounded-[10px] border border-line bg-sunk p-2.5 font-mono text-[11.5px] leading-relaxed text-ink-2", children: JSON.stringify(r.detail, null, 2) })] })) : null] }));
}
function RowsSkeleton() {
    return (_jsx("div", { className: "space-y-1.5 p-1", "aria-busy": "true", "aria-label": "Loading receipts", children: Array.from({ length: 6 }, (_, i) => _jsx(Skeleton, { className: "h-[74px] rounded-[12px]" }, i)) }));
}
