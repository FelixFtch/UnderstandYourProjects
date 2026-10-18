// Receipts — the Phase 0 read-only receipt timeline.
//
// Shows what the hub can prove today: the persisted capability-lifecycle
// audit ledger merged with the volatile governed-action feed.  No buttons
// that change anything exist on this page by design; the only interactions
// are filtering, selecting a row, and paging further back in time.
import { useEffect, useMemo, useState } from "react";
import type { FeaturePageProps } from "../../app/routes";
import type { StudioReceipt } from "../../api/contracts";
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

export default function ReceiptsPage(_props: FeaturePageProps) {
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");
  const [principalText, setPrincipalText] = useState("");
  const [principal, setPrincipal] = useState("");
  const [includeReads, setIncludeReads] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

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
  const [older, setOlder] = useState<StudioReceipt[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  useEffect(() => { setOlder([]); setCursor(null); setSelected(null); }, [query]);

  const rows = useMemo(() => [...(page.data?.receipts ?? []), ...older], [page.data, older]);
  const detail = rows.find((r) => r.receipt_id === selected) ?? null;

  async function loadOlder(): Promise<void> {
    const from = page.data?.next_before ?? cursor;
    if (!from || loadingOlder) return;
    setLoadingOlder(true);
    try {
      const next = await receiptsData.list({ ...query, before: from });
      setOlder((o) => [...o, ...next.receipts.filter((r) => !o.some((x) => x.receipt_id === r.receipt_id))]);
      setCursor(next.next_before);
    } catch {
      setCursor(from); // stay put; the retry button is the page's own reload
    } finally {
      setLoadingOlder(false);
    }
  }

  const hasMore = !!(page.data && (page.data.next_before || cursor));
  const feedSource = page.data?.sources.find((s) => s.id === "device_action_feed");

  return (
    <div className="@container mx-auto w-full max-w-[1320px] space-y-6 px-4 py-6 sm:px-8 sm:py-8">
      <SectionHeader
        level={1}
        eyebrow="Receipts"
        title="Receipt timeline"
        description="What was asked of connectors and what actually happened — read-only. Accepted means the connector took the instruction; only completed is a confirmed outcome."
      />

      <Legend />

      {page.data ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-card border border-line bg-surface px-4 py-3 text-[12.5px] text-muted shadow-card">
          <span className="min-w-0 flex-1">{sourceScopeNote(page.data.sources)}</span>
          {feedSource && !feedSource.available ? (
            <span className="flex items-center gap-1.5 text-warn">
              <StatusDot tone="warn" />
              Live device-action feed unavailable — showing the persisted ledger only.
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Segmented label="Source" value={source} options={SOURCE_OPTIONS} onChange={(v) => setSource(v)} />
        <label className="sr-only" htmlFor="receipt-status">Status</label>
        <select
          id="receipt-status"
          className={cx(inputClass, "h-8 w-auto py-0 text-[13px]")}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s === "" ? "All statuses" : statusMeta(s).label}</option>
          ))}
        </select>
        <input
          className={cx(inputClass, "h-8 w-44 py-0 text-[13px]")}
          placeholder="Filter by principal…"
          value={principalText}
          onChange={(e) => setPrincipalText(e.target.value)}
          aria-label="Filter by principal"
        />
        <label className="flex cursor-pointer items-center gap-1.5 text-[12.5px] text-muted select-none">
          <input type="checkbox" className="accent-[var(--j-accent)]" checked={includeReads}
            onChange={(e) => setIncludeReads(e.target.checked)} />
          show policy-read audit
        </label>
      </div>

      <div className="grid items-start gap-5 @6xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="min-w-0 p-2 sm:p-3">
          {page.loading && !page.data ? <RowsSkeleton /> : null}
          {page.error && !page.data ? (
            <ErrorState error={page.error} service="companion-api" title="Couldn't load receipts" onRetry={page.reload} />
          ) : null}
          {page.data && rows.length === 0 ? (
            <EmptyState
              icon="activity"
              title="No receipts match"
              body="Nothing in the audit ledger or the live device-action feed matches these filters. Policy-read audit rows are hidden by default — enable 'show policy-read audit' to include them."
            />
          ) : null}
          {rows.length > 0 ? (
            <ol className="space-y-1.5" aria-label="Receipt timeline">
              {rows.map((r) => (
                <ReceiptRow key={r.receipt_id} r={r} selected={selected === r.receipt_id} onSelect={setSelected} />
              ))}
            </ol>
          ) : null}
          {page.data && hasMore ? (
            <div className="mt-2 flex justify-center border-t border-line pt-2">
              <button
                type="button"
                onClick={() => void loadOlder()}
                disabled={loadingOlder}
                className="rounded-control px-3 py-1.5 text-[13px] font-medium text-accent-ink transition-colors hover:bg-sunk disabled:opacity-55"
              >
                {loadingOlder ? "Loading…" : "Load older"}
              </button>
            </div>
          ) : null}
        </Card>
        <ReceiptDetail r={detail} />
      </div>
    </div>
  );
}

function Legend() {
  const path = STATE_MACHINE.filter((s) => !s.terminal);
  const terminals = STATE_MACHINE.filter((s) => s.terminal);
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
        {path.map((s, i) => {
          const meta = statusMeta(s.id);
          const accepted = s.id === "accepted";
          const completed = s.id === "completed";
          return (
            <span key={s.id} className="flex items-center gap-2">
              {i > 0 ? <span className="text-faint" aria-hidden="true">→</span> : null}
              <Chip tone={meta.tone} mono title={meta.note}
                className={cx(accepted && "border-dashed", completed && "font-semibold")}>
                {meta.label}
              </Chip>
            </span>
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-muted">
        <span>Terminal outcomes:</span>
        {terminals.map((s) => <Chip key={s.id} tone={statusMeta(s.id).tone} mono title={statusMeta(s.id).note}>{s.label}</Chip>)}
      </div>
      <ul className="mt-3 space-y-1.5 text-[12.5px] text-muted">
        <li className="flex items-start gap-2">
          <Chip tone="neutral" mono className="shrink-0 border-dashed">accepted</Chip>
          <span>= the connector took the instruction. <strong className="font-semibold text-ink-2">It is not done yet</strong> — an accepted action has no completion evidence.</span>
        </li>
        <li className="flex items-start gap-2">
          <Chip tone="ok" mono className="shrink-0 font-semibold">completed</Chip>
          <span>= the only green confirmation: a confirmed outcome with read-back evidence.</span>
        </li>
        <li className="flex items-start gap-2">
          <Chip tone="warn" mono className="shrink-0">SIMULATED</Chip>
          <span>= executed against a simulated capability (real_device: false). A simulated lock or light never reads as a real device finishing.</span>
        </li>
      </ul>
    </Card>
  );
}

function ReceiptRow({ r, selected, onSelect }: { r: StudioReceipt; selected: boolean; onSelect: (id: string) => void }) {
  const meta = statusMeta(r.status, r);
  const simulated = isSimulated(r);
  const src = sourceMeta(r.source);
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(r.receipt_id)}
        aria-pressed={selected}
        className={cx(
          "block w-full rounded-[12px] border border-line bg-surface px-3 py-2.5 text-left transition-[box-shadow,border-color] hover:border-line-strong",
          selected && "border-line-strong ring-2 ring-accent/35",
          simulated && "border-l-[3px] border-l-warn",
        )}
      >
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <span className="shrink-0 text-[12px] text-muted" title={r.requested_at}>{relativeTime(r.requested_at)}</span>
          <Chip tone={src.tone} title={`Source: ${src.label}`}>{src.label}</Chip>
          {simulated ? <Chip tone="warn" mono title="Executed against a simulated capability (real_device: false)">SIMULATED</Chip> : null}
          <span className="min-w-0 flex-1" />
          {r.kind === "device_action" ? <span className="shrink-0 font-mono text-[11px] text-faint">{evidenceLabel(r)}</span> : null}
          <Chip tone={meta.tone} mono title={meta.note} className={cx(r.status === "accepted" && "border-dashed", r.status === "completed" && !simulated && "font-semibold")}>
            {meta.label}
          </Chip>
        </div>
        <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px]">
          <span className="min-w-0 truncate font-mono text-[12.5px] text-ink">{r.capability}</span>
          <span className="text-muted">·</span>
          <span className="truncate text-ink-2">{r.principal}</span>
          {r.room ? <><span className="text-muted">·</span><span className="truncate text-muted">{r.room}</span></> : null}
          {r.risk ? <Chip mono title={`Risk as recorded: ${r.risk}`}>{r.risk}</Chip> : null}
          {r.auth_level ? <Chip mono title="Auth level of the acting member">{r.auth_level}</Chip> : null}
        </div>
        <div className="mt-1 flex min-w-0 items-center gap-2 truncate font-mono text-[11px] text-faint">
          <span className="truncate" title={`audit_ref: ${r.audit_ref}`}>{r.audit_ref}</span>
          {r.request_id ? <><span>·</span><span className="truncate" title={`request_id: ${r.request_id}`}>{r.request_id}</span></> : null}
          {r.error ? <><span>·</span><span className="truncate text-err/80">{r.error}</span></> : null}
        </div>
      </button>
    </li>
  );
}

function ReceiptDetail({ r }: { r: StudioReceipt | null }) {
  if (!r) {
    return (
      <Card className="h-fit p-4 @6xl:sticky @6xl:top-4">
        <div className="text-[13px] font-semibold text-ink">Reading a receipt</div>
        <p className="mt-2 text-[12.5px] text-muted">Select a row to see the full receipt: principal, capability, risk, auth level, confirmation state, ack and read-back, audit reference, and where it sits in the state machine.</p>
        <p className="mt-2 text-[12.5px] text-muted">Remote receipt ids (the far connector's own reference) appear once the full Connector migration lands; until then this view tracks the hub-side truth only.</p>
      </Card>
    );
  }
  const meta = statusMeta(r.status, r);
  const simulated = isSimulated(r);
  const inPath = PATH_ORDER.includes(r.status);
  return (
    <Card className="h-fit min-w-0 p-4 @6xl:sticky @6xl:top-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">{kindLabel(r.kind)}</div>
          <h3 className="mt-0.5 truncate font-serif text-[19px] leading-snug text-ink" title={r.capability}>{r.capability}</h3>
          <div className="font-mono text-[11.5px] text-muted">{r.requested_at}</div>
        </div>
        <Chip tone={meta.tone} mono title={meta.note} className={cx("shrink-0", r.status === "accepted" && "border-dashed", r.status === "completed" && !simulated && "font-semibold")}>
          {meta.label}
        </Chip>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {PATH_ORDER.map((s, i) => {
          const m = statusMeta(s);
          const current = s === r.status;
          const passed = inPath && PATH_ORDER.indexOf(r.status) > i;
          return (
            <span key={s} className="flex items-center gap-1.5">
              {i > 0 ? <span className={cx("text-[11px]", passed ? "text-accent" : "text-faint")} aria-hidden="true">→</span> : null}
              <span
                title={m.note}
                className={cx(
                  "rounded-full border px-2 py-[1px] font-mono text-[11px]",
                  current ? "border-accent bg-accent-soft text-accent-ink" : passed ? "border-line bg-sunk text-ink-2" : "border-line bg-surface text-faint",
                )}
              >
                {m.label}
              </span>
            </span>
          );
        })}
        {!inPath ? (
          <span title={meta.note} className="rounded-full border border-accent bg-accent-soft px-2 py-[1px] font-mono text-[11px] text-accent-ink">{meta.label}</span>
        ) : null}
      </div>
      {meta.note ? <p className="mt-2 text-[12px] text-muted">{meta.note}</p> : null}
      {simulated ? (
        <div className="mt-2 flex items-start gap-2 rounded-control border border-warn/30 bg-warn-soft px-3 py-2 text-[12.5px] text-warn">
          <StatusDot tone="warn" className="mt-1.5" />
          <span>Simulated execution (execution_mode: {r.execution_mode ?? "—"}, real_device: false). No physical device was touched.</span>
        </div>
      ) : null}

      <dl className="mt-4 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[12.5px]">
        <dt className="text-muted">Source</dt><dd className="truncate text-ink-2">{sourceMeta(r.source).label}</dd>
        <dt className="text-muted">Principal</dt><dd className="truncate text-ink-2">{r.principal}</dd>
        <dt className="text-muted">Auth level</dt><dd className="truncate text-ink-2">{r.auth_level ?? "—"}</dd>
        <dt className="text-muted">Room</dt><dd className="truncate text-ink-2">{r.room ?? "— (not recorded)"}</dd>
        <dt className="text-muted">Risk</dt><dd className="truncate text-ink-2">{r.risk ?? "—"}</dd>
        <dt className="text-muted">Confirmation</dt><dd className="truncate text-ink-2">{r.confirmation ?? "—"}</dd>
        <dt className="text-muted">Ack</dt>
        <dd className="truncate text-ink-2">
          {r.ack ? `${r.ack.received ? "received" : "not received"}${r.ack.connector ? ` · ${r.ack.connector}` : ""}` : "—"}
        </dd>
        <dt className="text-muted">Read-back</dt>
        <dd className="text-ink-2">
          {r.read_back && Object.keys(r.read_back).length > 0 ? (
            <pre className="max-h-[140px] overflow-auto rounded-[10px] border border-line bg-sunk p-2 font-mono text-[11px] leading-relaxed">{JSON.stringify(r.read_back, null, 2)}</pre>
          ) : r.status === "accepted" && r.kind === "device_action" ? (
            <span className="text-muted">none — which is exactly why this is accepted, not completed</span>
          ) : (
            <span className="text-muted">—</span>
          )}
        </dd>
        {r.error ? <><dt className="text-muted">Error</dt><dd className="break-words font-mono text-[11.5px] text-err">{r.error}</dd></> : null}
        <dt className="text-muted">Audit ref</dt><dd className="truncate font-mono text-[11.5px] text-ink-2" title={r.audit_ref}>{r.audit_ref}</dd>
        <dt className="text-muted">Request id</dt><dd className="truncate font-mono text-[11.5px] text-ink-2">{r.request_id ?? "—"}</dd>
        <dt className="text-muted">Remote receipt</dt><dd className="truncate font-mono text-[11.5px] text-ink-2" title="Remote receipt ids arrive with the full Connector migration">{r.remote_receipt_id ?? "—"}</dd>
        {r.expires_at ? <><dt className="text-muted">Expires</dt><dd className="truncate font-mono text-[11.5px] text-ink-2">{r.expires_at}</dd></> : null}
      </dl>

      {r.detail && Object.keys(r.detail).length > 0 ? (
        <div className="mt-4">
          <div className="mb-1 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">Audit detail</div>
          <pre className="max-h-[180px] overflow-auto rounded-[10px] border border-line bg-sunk p-2.5 font-mono text-[11.5px] leading-relaxed text-ink-2">{JSON.stringify(r.detail, null, 2)}</pre>
        </div>
      ) : null}
    </Card>
  );
}

function RowsSkeleton() {
  return (
    <div className="space-y-1.5 p-1" aria-busy="true" aria-label="Loading receipts">
      {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-[74px] rounded-[12px]" />)}
    </div>
  );
}
