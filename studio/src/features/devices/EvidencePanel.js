import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { Icon } from "../../design/icons";
import { Chip } from "../../design/primitives";
/**
 * Evidence chain panel (Studio B2, 2026-10): renders the contract
 * KnowledgeEvidence records behind ONE knowledge answer.
 *
 * Display-only by construction: it fetches nothing, synthesizes nothing
 * (no second Qwen pass), re-retrieves nothing, and derives no identity —
 * the records arrive with the answer from a single
 * GET /api/studio/knowledge/query, already permission-checked upstream.
 */
const FACT_TYPE = {
    structural: { tone: "neutral", label: "structural" },
    semantic: { tone: "accent", label: "semantic" },
    inferred: { tone: "info", label: "inferred" },
    runtime: { tone: "warn", label: "runtime" },
};
const FRESHNESS_TONE = {
    fresh: "ok",
    stale: "warn",
    unknown: "neutral",
};
function freshnessLabel(freshness, indexAsOf) {
    if (freshness === "stale")
        return indexAsOf ? `stale · last indexed at ${indexAsOf}` : "stale";
    if (freshness === "fresh")
        return "fresh";
    return "freshness unknown";
}
function EvidenceRow({ record, index }) {
    const [open, setOpen] = useState(false);
    const fact = record.fact_type ? FACT_TYPE[record.fact_type] : undefined;
    const locatorPath = record.locator.split("#")[0];
    const anchor = record.locator.includes("#") ? record.locator.split("#")[1] : null;
    return (_jsxs("li", { className: `rounded-lg border transition-colors ${open ? "border-accent/40 bg-accent-soft/40" : "border-line bg-sunk/40"}`, children: [_jsxs("button", { type: "button", onClick: () => setOpen((v) => !v), className: "flex w-full items-start gap-2 px-2.5 py-2 text-left", title: record.locator, children: [_jsx("span", { className: "mt-[2px] w-4 shrink-0 text-[11px] tabular-nums text-muted", children: index + 1 }), _jsxs("span", { className: "min-w-0 flex-1", children: [_jsx("span", { className: "block break-all font-mono text-[12px] text-ink", children: locatorPath }), anchor ? _jsx("span", { className: "block font-mono text-[11px] text-muted", children: anchor }) : null, _jsxs("span", { className: "mt-1.5 flex flex-wrap items-center gap-1.5", children: [_jsx(Chip, { tone: "neutral", mono: true, className: "max-w-[220px]", title: record.source_id, children: record.source_id }), fact ? _jsx(Chip, { tone: fact.tone, children: fact.label }) : null, _jsx(Chip, { tone: FRESHNESS_TONE[record.freshness ?? "unknown"], children: freshnessLabel(record.freshness, record.index_as_of) }), record.permission_checked ? (_jsx(Chip, { tone: "ok", icon: "check", title: "permission_checked: the scope gate verified this source before retrieval", children: "verified" })) : (_jsx(Chip, { tone: "err", title: "permission_checked=false \u2014 must never be surfaced", children: "unverified" }))] }), _jsxs("span", { className: "mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted", children: [_jsxs("span", { className: "font-mono", title: "source_version: the edition pin of this record", children: ["v ", record.source_version] }), record.provider || record.model_id ? (_jsxs("span", { title: "the local pipeline that produced this record", children: [record.provider ?? "unknown provider", " \u00B7 ", record.model_id ?? "unknown model"] })) : null, _jsxs("span", { title: "retrieved_at", children: ["at ", record.retrieved_at] })] }), record.node_ids?.length ? (_jsxs("span", { className: "mt-1.5 flex flex-wrap items-center gap-1", children: [_jsx("span", { className: "text-[11px] text-muted", children: "graph nodes:" }), record.node_ids.map((id) => (_jsx(Chip, { tone: "neutral", mono: true, className: "max-w-[200px]", title: record.graph_version ? `graph ${record.graph_version}` : "graph node reference", children: id }, id)))] })) : null] }), _jsx(Icon, { name: open ? "x" : "more", size: 13, className: "mt-[3px] shrink-0 text-muted" })] }), open ? (_jsxs("div", { className: "border-t border-line px-3 py-2.5", children: [_jsx("div", { className: "mb-1 text-[11px] font-medium uppercase tracking-wide text-muted", children: "content (verbatim from the index)" }), _jsx("p", { className: "whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-ink-2", children: record.content })] })) : null] }));
}
export function EvidencePanel({ result }) {
    const [open, setOpen] = useState(true);
    const count = result.evidence.length;
    if (!result.ok)
        return null;
    return (_jsxs("div", { className: "mt-3 rounded-xl border border-line", children: [_jsxs("button", { type: "button", onClick: () => setOpen((v) => !v), className: "flex w-full items-center gap-2 px-3 py-2 text-left", children: [_jsx(Icon, { name: "layers", size: 14, className: "shrink-0 text-muted" }), _jsx("span", { className: "text-[12.5px] font-medium text-ink", children: "Evidence chain" }), _jsx(Chip, { tone: "neutral", children: count === 1 ? "1 record" : `${count} records` }), result.freshness ? _jsx(Chip, { tone: FRESHNESS_TONE[result.freshness], children: freshnessLabel(result.freshness, result.index_as_of) }) : null, _jsxs("span", { className: "ml-auto flex items-center gap-2 text-[11px] text-muted", children: [result.audit_id ? _jsxs("span", { className: "font-mono", title: "audit id", children: ["audit ", result.audit_id.slice(0, 8)] }) : null, _jsx(Icon, { name: open ? "x" : "more", size: 13 })] })] }), open ? (count ? (_jsx("ol", { className: "space-y-1.5 border-t border-line p-2", children: result.evidence.map((record, i) => (_jsx(EvidenceRow, { record: record, index: i }, `${record.locator}-${record.source_id}-${i}`))) })) : (_jsx("div", { className: "border-t border-line px-3 py-2.5 text-[12px] text-muted", children: "No evidence records for this answer \u2014 nothing was cited inside the authorized scope." }))) : null] }));
}
