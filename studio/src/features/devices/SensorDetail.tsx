// Sensor device detail (#/devices/sensors/<device_id>): one view per hub
// category — air quality gets a 24h line chart per metric, presence gets a
// 24h occupied band, meeting audio shows the link status, reserved and misc
// categories reuse the Studio's empty states. Charts are hand-rolled SVG in
// Studio tokens; every view polls in place (usePolledResource → reload) so
// refreshes update data without remounting anything.
import { useMemo } from "react";
import type { SensorDevice, SensorDeviceList, SensorPlaceholder, SensorStateRow } from "../../api/contracts";
import { relativeTime } from "../../design/format";
import type { Resource } from "../../design/hooks";
import { Icon } from "../../design/icons";
import { Button, Card, Chip, cx, EmptyState, ErrorState, Skeleton, StatusDot } from "../../design/primitives";
import {
  buildLine, buildPresenceBand, fmtValue, formatDuration, HISTORY_POLL_MS, isPositive, numericPoints,
  parseState, pickPresenceHero, readingStatus, SENSOR_CATEGORY_LABEL, sensorsData, usePolledResource,
} from "./sensors";

export function SensorDetailView({ id, sensors, states, onBack }: {
  id: string;
  sensors: Resource<SensorDeviceList>;
  states: Resource<SensorStateRow[]>;
  onBack: () => void;
}) {
  const dev = sensors.data?.devices.find((d) => d.device_id === id) ?? null;
  const statesMap = useMemo(() => new Map((states.data ?? []).map((r) => [r.entity_id, r])), [states.data]);
  const reload = () => { sensors.reload(); states.reload(); };

  return (
    <div className="mx-auto w-full max-w-[1120px] px-4 py-5 sm:px-8 sm:py-7">
      <nav aria-label="Breadcrumb" className="mb-4 flex min-w-0 items-center gap-1 text-[12.5px] text-muted">
        <a href="#/devices" onClick={(e) => { e.preventDefault(); onBack(); }} className="flex items-center gap-1 rounded px-1 hover:text-ink">
          <Icon name="arrowLeft" size={13} /> Devices
        </a>
        <Icon name="chevronRight" size={12} className="text-faint" />
        <span className="truncate px-1 text-ink-2">{dev?.name ?? id}</span>
      </nav>

      {sensors.loading && !sensors.data ? <Skeleton className="h-[220px] rounded-card" /> : null}
      {sensors.error && !sensors.data ? (
        <Card><ErrorState error={sensors.error} service="Sensor hub" title="Couldn't load sensors" onRetry={reload} /></Card>
      ) : null}
      {sensors.data && !dev ? (
        <Card>
          <EmptyState
            icon="devices"
            title="This sensor isn't registered"
            body={`No sensor device with the id “${id}” is publishing right now. It may have dropped off the MQTT discovery tree.`}
            action={<Button size="sm" variant="secondary" icon="arrowLeft" onClick={onBack}>Back to devices</Button>}
          />
        </Card>
      ) : null}

      {dev ? <SensorDeviceBody dev={dev} statesMap={statesMap} placeholders={sensors.data?.placeholders ?? []} onReload={reload} /> : null}
    </div>
  );
}

function SensorDeviceBody({ dev, statesMap, placeholders, onReload }: {
  dev: SensorDevice;
  statesMap: Map<string, SensorStateRow>;
  placeholders: SensorPlaceholder[];
  onReload: () => void;
}) {
  const rows = dev.entities.map((eid) => statesMap.get(eid)).filter((r): r is SensorStateRow => Boolean(r));
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
            <Chip tone={dev.online ? "ok" : "err"}>
              <span className="flex items-center gap-1.5"><StatusDot tone={dev.online ? "ok" : "err"} pulse={dev.online} />{dev.online ? "Online" : "Offline"}</span>
            </Chip>
            <Chip tone="neutral">{SENSOR_CATEGORY_LABEL[dev.category]}</Chip>
            <span>· updated {relativeTime(dev.last_changed ?? null)}</span>
          </div>
          <h1 className="mt-2 font-serif text-[28px] leading-tight break-words text-ink">{dev.name}</h1>
          <div className="mt-1 text-[12.5px] text-muted">
            {[dev.manufacturer, dev.model].filter(Boolean).join(" · ") || `${dev.entity_count} entities`}
            <span className="mx-1.5" aria-hidden="true">·</span>
            <span className="font-mono text-[12px]">{dev.device_id}</span>
          </div>
        </div>
        <Button size="sm" variant="ghost" icon="refresh" onClick={onReload}>Refresh</Button>
      </header>

      {(!!dev.unavailable || !!dev.stale) ? (
        <div className="flex flex-wrap items-center gap-2">
          {!!dev.unavailable && <Chip tone="err" icon="alert">{dev.unavailable} of {dev.entity_count} entities unavailable</Chip>}
          {!!dev.stale && <Chip tone="warn" icon="clock">{dev.stale} possibly stale</Chip>}
        </div>
      ) : null}

      {dev.category === "air_quality" ? <AirQualityCharts rows={rows.filter((r) => r.attributes?.category === "air_quality")} /> : null}
      {dev.category === "presence" ? <PresenceBandView dev={dev} statesMap={statesMap} /> : null}
      {dev.category === "meeting_audio" ? <MeetingAudioView dev={dev} /> : null}
      {(dev.category === "checkin" || dev.category === "lighting") ? (
        <ReservedView category={dev.category} placeholders={placeholders} />
      ) : null}
      {dev.category === "other" ? <EntityRows rows={rows} /> : null}
    </div>
  );
}

// ── air quality: one 24h line chart per metric ───────────────────────────────
function AirQualityCharts({ rows }: { rows: SensorStateRow[] }) {
  const metrics = rows.filter((r) => Number.isFinite(parseState(r.state)) && r.state !== "unavailable").slice(0, 8);
  if (!metrics.length) {
    return (
      <Card>
        <EmptyState icon="activity" title="No air-quality readings yet"
          body="This device is registered but hasn't published temperature, CO2, TVOC or humidity values." />
      </Card>
    );
  }
  return (
    <section aria-label="Air quality, last 24 hours" className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr))]">
      {metrics.map((row) => <MetricChart key={row.entity_id} row={row} />)}
    </section>
  );
}

function MetricChart({ row }: { row: SensorStateRow }) {
  const res = usePolledResource((s) => sensorsData.history(row.entity_id, s), [row.entity_id], HISTORY_POLL_MS);
  const unit = row.attributes?.unit_of_measurement ?? "";
  const current = parseState(row.state);
  const geo = res.data ? buildLine(numericPoints(res.data.points)) : null;
  return (
    <Card className="p-3">
      <div className="flex items-baseline gap-2">
        <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink-2" title={row.entity_id}>{row.attributes?.friendly_name ?? row.entity_id}</span>
        <span className="text-[17px] font-semibold text-ink tabular-nums">{Number.isFinite(current) ? fmtValue(current) : "–"}</span>
        {unit ? <span className="text-[11px] text-muted">{unit}</span> : null}
        {geo ? <span className="ml-auto text-[10.5px] text-faint tabular-nums">{fmtValue(geo.lo)} ~ {fmtValue(geo.hi)}</span> : null}
      </div>
      <div className="mt-2" aria-hidden="true">
        {res.loading && !res.data ? <Skeleton className="h-16 w-full" /> : null}
        {res.error && !res.data ? <div className="flex h-16 items-center text-[12px] text-faint">24h history unavailable right now.</div> : null}
        {res.data && geo ? (
          <svg className="h-16 w-full text-accent" viewBox="0 0 260 64" preserveAspectRatio="none">
            <path d={geo.area} className="fill-accent/10 stroke-none" />
            <polyline points={geo.points} fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinejoin="round" />
          </svg>
        ) : null}
        {res.data && !geo ? <div className="flex h-16 items-center text-[12px] text-faint">Collecting 24h data…</div> : null}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-faint tabular-nums" aria-hidden="true">
        <span>–24h</span><span>–12h</span><span>now</span>
      </div>
    </Card>
  );
}

// ── presence: 24h occupied band ──────────────────────────────────────────────
function PresenceBandView({ dev, statesMap }: { dev: SensorDevice; statesMap: Map<string, SensorStateRow> }) {
  const hero = pickPresenceHero(dev, statesMap);
  const res = usePolledResource((s) => sensorsData.history(hero?.entity_id ?? "", s), [hero?.entity_id], HISTORY_POLL_MS);
  const end = useMemo(() => new Date(), [res.data]); // re-anchor the window when fresh data lands
  const start = useMemo(() => new Date(end.getTime() - 24 * 3600_000), [end]);
  const band = res.data ? buildPresenceBand(res.data.points, start, end) : null;
  const live = hero ? (hero.state === "unavailable" ? "offline" : isPositive(hero.state) ? "occupied" : "empty") : null;

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[14px] font-medium text-ink">
          <StatusDot tone={live === "occupied" ? "accent" : live === "offline" ? "err" : "neutral"} pulse={live === "occupied"} />
          {live === "occupied" ? "Someone is there now" : live === "offline" ? "Presence sensor offline" : live === "empty" ? "No one detected right now" : "No presence entity"}
        </div>
        {band ? (
          <div className="text-[13px] text-ink-2">
            Occupied <b className="font-semibold text-accent-ink tabular-nums">{formatDuration(band.totalMs)}</b> in the last 24h
            <span className="mx-1.5 text-faint" aria-hidden="true">·</span>
            <span className="tabular-nums">{band.count}</span> {band.count === 1 ? "span" : "spans"}
          </div>
        ) : null}
      </div>

      <div className="mt-3">
        {res.loading && !res.data ? <Skeleton className="h-[34px] w-full" /> : null}
        {res.error && !res.data ? <div className="flex h-[34px] items-center text-[12px] text-faint">24h presence history unavailable right now.</div> : null}
        {res.data ? (
          band ? (
            <>
              <svg className="h-[34px] w-full" viewBox="0 0 1000 34" preserveAspectRatio="none" aria-hidden="true">
                <rect className="fill-sunk" x={0} y={7} width={1000} height={14} rx={3} />
                {[6, 12, 18].map((h) => (
                  <line key={h} className="stroke-line-strong" strokeDasharray="2 3" x1={(h / 24) * 1000} y1={3} x2={(h / 24) * 1000} y2={25} />
                ))}
                {band.spans.map(([a, b], i) => {
                  const x1 = ((a - start.getTime()) / (end.getTime() - start.getTime())) * 1000;
                  const x2 = ((b - start.getTime()) / (end.getTime() - start.getTime())) * 1000;
                  if (x2 - x1 < 0.8) return null;
                  return <rect key={i} className="fill-accent" x={x1.toFixed(1)} y={7} width={(x2 - x1).toFixed(1)} height={14} rx={2} />;
                })}
              </svg>
              <div className="mt-1 flex justify-between text-[10px] text-faint tabular-nums" aria-hidden="true">
                <span>{start.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</span>
                <span>–18h</span><span>–12h</span><span>–6h</span><span>now</span>
              </div>
            </>
          ) : <div className="flex h-[34px] items-center text-[12px] text-faint">Collecting presence history…</div>
        ) : null}
      </div>
    </Card>
  );
}

// ── meeting audio: link status readings ──────────────────────────────────────
function MeetingAudioView({ dev }: { dev: SensorDevice }) {
  return (
    <div className="space-y-3">
      {dev.readings?.length ? (
        <Card className="divide-y divide-line">
          {dev.readings.map((r, i) => (
            <div key={`${r.label}-${i}`} className="flex min-w-0 items-baseline justify-between gap-4 px-4 py-3">
              <span className="shrink-0 text-[13px] text-muted">{r.label}</span>
              <span className="min-w-0 truncate text-right text-[14px] font-medium text-ink tabular-nums">
                {r.value}{r.unit ? <span className="ml-1 text-[12px] font-normal text-muted">{r.unit}</span> : null}
              </span>
            </div>
          ))}
        </Card>
      ) : (
        <Card><EmptyState icon="chat" title="No link readings" body="The status endpoint did not report any readings for this device." /></Card>
      )}
      {dev.detail_note ? (
        <div className="flex items-start gap-2 rounded-control border border-info/25 bg-info-soft px-3 py-2.5 text-[13px] text-info">
          <Icon name="info" size={15} className="mt-0.5 shrink-0" />
          <span className="min-w-0 flex-1">{dev.detail_note}</span>
        </div>
      ) : null}
      {dev.status_url ? <div className="font-mono text-[12px] break-all text-faint">{dev.status_url}</div> : null}
    </div>
  );
}

// ── reserved categories: placeholder note, Studio empty style ────────────────
function ReservedView({ category, placeholders }: { category: SensorDevice["category"]; placeholders: SensorPlaceholder[] }) {
  const note = placeholders.find((p) => p.category === category)?.note;
  return (
    <Card>
      <EmptyState
        icon={category === "lighting" ? "bulb" : "key"}
        title={`${SENSOR_CATEGORY_LABEL[category]} is reserved`}
        body={note ?? "Devices for this category are not connected yet; they will appear here automatically once they publish."}
      />
    </Card>
  );
}

// ── misc devices: every entity as a current-value row ────────────────────────
function EntityRows({ rows }: { rows: SensorStateRow[] }) {
  if (!rows.length) {
    return <Card><EmptyState icon="devices" title="No entities" body="This device has no live entities right now." /></Card>;
  }
  return (
    <section aria-label="Entities" className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(min(100%,220px),1fr))]">
      {rows.map((r) => {
        const status = readingStatus(r);
        return (
          <div key={r.entity_id} className="flex min-w-0 items-baseline justify-between gap-2 rounded-control border border-line bg-raised px-3 py-2 text-[13px]" title={r.entity_id}>
            <span className={cx("min-w-0 truncate", status === "unavailable" ? "text-faint" : "text-muted")}>{r.attributes?.friendly_name ?? r.entity_id}</span>
            <span className={cx(
              "max-w-[55%] truncate text-right tabular-nums",
              status === "unavailable" ? "text-faint" : status === "stale" ? "text-warn" : "text-ink",
            )}>
              {status === "unavailable" ? "unavailable" : r.state}
              {r.attributes?.unit_of_measurement ? <span className="ml-1 text-[11px] text-muted">{r.attributes.unit_of_measurement}</span> : null}
            </span>
          </div>
        );
      })}
    </section>
  );
}
