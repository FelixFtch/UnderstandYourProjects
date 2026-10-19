import { useState } from "react";
import type { KnowledgeEvidenceRecord, KnowledgeQueryResult } from "../../api/contracts";
import { Icon } from "../../design/icons";
import { Chip, type Tone } from "../../design/primitives";

/**
 * Evidence chain panel (Studio B2, 2026-10): renders the contract
 * KnowledgeEvidence records behind ONE knowledge answer.
 *
 * Display-only by construction: it fetches nothing, synthesizes nothing
 * (no second Qwen pass), re-retrieves nothing, and derives no identity —
 * the records arrive with the answer from a single
 * GET /api/studio/knowledge/query, already permission-checked upstream.
 */

const FACT_TYPE: Record<NonNullable<KnowledgeEvidenceRecord["fact_type"]>, { tone: Tone; label: string }> = {
  structural: { tone: "neutral", label: "structural" },
  semantic: { tone: "accent", label: "semantic" },
  inferred: { tone: "info", label: "inferred" },
  runtime: { tone: "warn", label: "runtime" },
};

const FRESHNESS_TONE: Record<NonNullable<KnowledgeEvidenceRecord["freshness"]>, Tone> = {
  fresh: "ok",
  stale: "warn",
  unknown: "neutral",
};

function freshnessLabel(freshness: string | null | undefined, indexAsOf: string | null | undefined): string {
  if (freshness === "stale") return indexAsOf ? `stale · last indexed at ${indexAsOf}` : "stale";
  if (freshness === "fresh") return "fresh";
  return "freshness unknown";
}

function EvidenceRow({ record, index }: { record: KnowledgeEvidenceRecord; index: number }) {
  const [open, setOpen] = useState(false);
  const fact = record.fact_type ? FACT_TYPE[record.fact_type] : undefined;
  const locatorPath = record.locator.split("#")[0];
  const anchor = record.locator.includes("#") ? record.locator.split("#")[1] : null;

  return (
    <li className={`rounded-lg border transition-colors ${open ? "border-accent/40 bg-accent-soft/40" : "border-line bg-sunk/40"}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-2 px-2.5 py-2 text-left"
        title={record.locator}
      >
        <span className="mt-[2px] w-4 shrink-0 text-[11px] tabular-nums text-muted">{index + 1}</span>
        <span className="min-w-0 flex-1">
          <span className="block break-all font-mono text-[12px] text-ink">{locatorPath}</span>
          {anchor ? <span className="block font-mono text-[11px] text-muted">{anchor}</span> : null}
          <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Chip tone="neutral" mono className="max-w-[220px]" title={record.source_id}>{record.source_id}</Chip>
            {fact ? <Chip tone={fact.tone}>{fact.label}</Chip> : null}
            <Chip tone={FRESHNESS_TONE[record.freshness ?? "unknown"]}>
              {freshnessLabel(record.freshness, record.index_as_of)}
            </Chip>
            {record.permission_checked ? (
              <Chip tone="ok" icon="check" title="permission_checked: the scope gate verified this source before retrieval">verified</Chip>
            ) : (
              <Chip tone="err" title="permission_checked=false — must never be surfaced">unverified</Chip>
            )}
          </span>
          <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
            <span className="font-mono" title="source_version: the edition pin of this record">v {record.source_version}</span>
            {record.provider || record.model_id ? (
              <span title="the local pipeline that produced this record">
                {record.provider ?? "unknown provider"} · {record.model_id ?? "unknown model"}
              </span>
            ) : null}
            <span title="retrieved_at">at {record.retrieved_at}</span>
          </span>
          {record.node_ids?.length ? (
            <span className="mt-1.5 flex flex-wrap items-center gap-1">
              <span className="text-[11px] text-muted">graph nodes:</span>
              {record.node_ids.map((id) => (
                <Chip key={id} tone="neutral" mono className="max-w-[200px]" title={record.graph_version ? `graph ${record.graph_version}` : "graph node reference"}>{id}</Chip>
              ))}
            </span>
          ) : null}
        </span>
        <Icon name={open ? "x" : "more"} size={13} className="mt-[3px] shrink-0 text-muted" />
      </button>
      {open ? (
        <div className="border-t border-line px-3 py-2.5">
          <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted">content (verbatim from the index)</div>
          <p className="whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-ink-2">{record.content}</p>
        </div>
      ) : null}
    </li>
  );
}

export function EvidencePanel({ result }: { result: KnowledgeQueryResult }) {
  const [open, setOpen] = useState(true);
  const count = result.evidence.length;
  if (!result.ok) return null;

  return (
    <div className="mt-3 rounded-xl border border-line">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <Icon name="layers" size={14} className="shrink-0 text-muted" />
        <span className="text-[12.5px] font-medium text-ink">Evidence chain</span>
        <Chip tone="neutral">{count === 1 ? "1 record" : `${count} records`}</Chip>
        {result.freshness ? <Chip tone={FRESHNESS_TONE[result.freshness]}>{freshnessLabel(result.freshness, result.index_as_of)}</Chip> : null}
        <span className="ml-auto flex items-center gap-2 text-[11px] text-muted">
          {result.audit_id ? <span className="font-mono" title="audit id">audit {result.audit_id.slice(0, 8)}</span> : null}
          <Icon name={open ? "x" : "more"} size={13} />
        </span>
      </button>
      {open ? (
        count ? (
          <ol className="space-y-1.5 border-t border-line p-2">
            {result.evidence.map((record, i) => (
              <EvidenceRow key={`${record.locator}-${record.source_id}-${i}`} record={record} index={i} />
            ))}
          </ol>
        ) : (
          <div className="border-t border-line px-3 py-2.5 text-[12px] text-muted">
            No evidence records for this answer — nothing was cited inside the authorized scope.
          </div>
        )
      ) : null}
    </div>
  );
}
