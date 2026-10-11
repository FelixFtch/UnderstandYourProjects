import { useEffect, useMemo, useState, type FormEvent } from "react";
import type { Device, ProjectSummary } from "../../api/contracts";
import { describeError, tildePath } from "../../design/format";
import { Icon } from "../../design/icons";
import { Button, Field, inputClass, Modal, ProgressBar, Spinner, StatusDot } from "../../design/primitives";
import type { JobState } from "./analyzeJob";
import { isFinished, POLL_MS } from "./analyzeJob";
import { confirmedRelation, predictRelation, relationSentence } from "./tree";

export function AnalyzeDialog({ open, onClose, devices, projects, initialPath, job, onStart, onOpenProject, onReset, owner }: {
  open: boolean;
  onClose: () => void;
  devices: Device[];
  projects: ProjectSummary[];
  initialPath?: string;
  job: JobState | null;
  onStart: (path: string, deviceId?: string) => Promise<unknown>;
  onOpenProject: (id: string) => void;
  onReset: () => void;
  owner: boolean;
}) {
  const targets = devices.filter((d) => d.kind !== "phone");
  const defaultDevice = (targets.find((d) => d.kind === "computer" && d.connector?.state === "online") ?? targets[0])?.device_id ?? "";
  const [path, setPath] = useState("");
  const [deviceId, setDeviceId] = useState(defaultDevice);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    if (initialPath !== undefined) setPath(tildePath(initialPath));
    if (!deviceId && defaultDevice) setDeviceId(defaultDevice);
  }, [open, initialPath, defaultDevice, deviceId]);

  const preview = useMemo(() => (path.trim() ? predictRelation(path, projects, deviceId || null) : null), [path, projects, deviceId]);
  const byId = useMemo(() => new Map(projects.map((p) => [p.project_id, p])), [projects]);
  const valid = /^(~|\/)/.test(path.trim());
  const device = devices.find((d) => d.device_id === deviceId);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onStart(path.trim(), deviceId || undefined);
    } catch (err) {
      const d = describeError(err, "Project knowledge (UYP)");
      setError(d.detail ? `${d.title}: ${d.detail}` : d.title);
    } finally {
      setBusy(false);
    }
  }

  const finished = isFinished(job);
  const j = job?.job;
  const pct = j && j.progress.total ? Math.round((j.progress.done / j.progress.total) * 100) : 0;

  return (
    <Modal
      open={open}
      onClose={onClose}
      width={560}
      title={job ? "Analyzing a folder" : "Analyze a folder"}
      description={job ? tildePath(job.path) : "Jarvis reads the folder through its device connector and builds project knowledge."}
      footer={
        job ? (
          <>
            {finished ? <Button variant="ghost" onClick={() => { onReset(); setPath(""); }}>Analyze another</Button> : <span className="mr-auto text-[12px] text-muted">You can close this; it keeps running.</span>}
            {finished && j?.status === "done" ? (
              <Button variant="primary" iconRight="arrowRight" onClick={() => { onClose(); onOpenProject(job.result.project_id); }}>Open digest</Button>
            ) : (
              <Button onClick={onClose}>Close</Button>
            )}
          </>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="primary" type="submit" form="analyze-form" disabled={!valid || !owner} loading={busy}>Start analysis</Button>
          </>
        )
      }
    >
      {!job ? (
        <form id="analyze-form" onSubmit={submit} className="space-y-4">
          {!owner ? (
            <div className="rounded-control border border-warn/25 bg-warn-soft px-3 py-2 text-[13px] text-warn">Only the household owner can start an analysis.</div>
          ) : null}
          <Field label="Folder path" htmlFor="analyze-path" hint="An absolute path on the device, e.g. ~/code/adhd-agent">
            <input
              id="analyze-path"
              data-autofocus=""
              value={path}
              onChange={(e) => { setPath(e.target.value); setError(null); }}
              placeholder="~/code/adhd-agent"
              spellCheck={false}
              autoComplete="off"
              className={`${inputClass} font-mono text-[13px]`}
            />
          </Field>
          <Field label="Device" htmlFor="analyze-device" hint={device?.connector?.state === "offline" ? "This device's connector is offline; the job will wait for it." : undefined}>
            <select id="analyze-device" value={deviceId} onChange={(e) => setDeviceId(e.target.value)} className={inputClass}>
              {targets.length === 0 ? <option value="">No devices with a connector</option> : null}
              {targets.map((d) => (
                <option key={d.device_id} value={d.device_id}>
                  {d.label}{d.connector ? ` · ${d.connector.state}` : " · no connector"}
                </option>
              ))}
            </select>
          </Field>

          {preview && valid ? (
            <div className="rounded-[12px] border border-line bg-canvas/50 p-3.5">
              <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">
                <Icon name="project" size={13} /> Where it fits
              </div>
              <RelationDiagram path={path} parent={preview.parent} kids={preview.children} existing={!!preview.existing} />
              <p className="mt-2.5 text-[13px] text-ink-2">{relationSentence(preview)}</p>
              <p className="mt-1 text-[11.5px] text-faint">Preview from the folders Jarvis knows; the hub confirms it when you start.</p>
            </div>
          ) : null}

          {error ? (
            <div role="alert" className="flex items-start gap-2 rounded-control border border-err/25 bg-err-soft px-3 py-2 text-[13px] text-err">
              <Icon name="alert" size={15} className="mt-0.5 shrink-0" /> {error}
            </div>
          ) : null}
        </form>
      ) : (
        <div className="space-y-4">
          <div className="flex items-start gap-2 rounded-[12px] border border-accent/25 bg-accent-soft px-3.5 py-3 text-[13.5px] text-accent-ink">
            <Icon name="check" size={16} className="mt-0.5 shrink-0" />
            <span>{confirmedRelation(job.result.relation, byId)}</span>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2 text-[13px]">
              <span className="flex min-w-0 items-center gap-2 text-ink">
                {j?.status === "done" ? <StatusDot tone="ok" /> : j?.status === "failed" ? <StatusDot tone="err" /> : <Spinner size={13} />}
                <span className="truncate font-medium">{j ? (j.status === "done" ? "Done" : j.status === "failed" ? "Failed" : j.phase || j.status) : "Queued"}</span>
              </span>
              <span className="shrink-0 font-mono text-[12px] text-muted">
                {j ? `${j.progress.done}/${j.progress.total} · ${pct}%` : "waiting…"}
              </span>
            </div>
            <ProgressBar value={j?.progress.done ?? 0} max={j?.progress.total || 1} tone={j?.status === "failed" ? "err" : j?.status === "done" ? "ok" : "accent"} label="Analysis progress" />
            {!finished ? <div className="mt-1 text-[11.5px] text-faint">Updates every {POLL_MS / 1000} s.</div> : null}
          </div>

          {job.pollError ? (
            <div className="rounded-control border border-warn/25 bg-warn-soft px-3 py-2 text-[12.5px] text-warn">
              Couldn't refresh the job status ({describeError(job.pollError).title}). Retrying…
            </div>
          ) : null}

          {j?.log_tail?.length ? (
            <div>
              <div className="mb-1 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">Log</div>
              <pre className="max-h-[180px] overflow-auto rounded-[10px] border border-line bg-sunk p-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-ink-2">
                {j.log_tail.join("\n")}
              </pre>
            </div>
          ) : null}
        </div>
      )}
    </Modal>
  );
}

function RelationDiagram({ path, parent, kids, existing }: { path: string; parent: ProjectSummary | null; kids: ProjectSummary[]; existing: boolean }) {
  const name = path.trim().replace(/\/+$/, "").split("/").pop() || path;
  const indent = parent ? 1 : 0;
  return (
    <ul className="space-y-1 font-mono text-[12.5px]">
      {parent ? (
        <li className="flex items-center gap-2 text-muted">
          <Icon name="folderOpen" size={14} /> {parent.root_name} <span className="font-sans text-[11px] text-faint">analyzed</span>
        </li>
      ) : null}
      <li className="flex items-center gap-2 text-ink" style={{ paddingLeft: indent * 18 }}>
        {indent ? <span className="text-faint">└</span> : null}
        <Icon name="folder" size={14} className="text-accent-ink" /> {name}
        <span className="rounded-full bg-accent-soft px-1.5 font-sans text-[10.5px] font-semibold text-accent-ink">{existing ? "refresh" : "new"}</span>
      </li>
      {kids.slice(0, 4).map((k) => (
        <li key={k.project_id} className="flex items-center gap-2 text-muted" style={{ paddingLeft: (indent + 1) * 18 }}>
          <span className="text-faint">└</span><Icon name="folder" size={14} /> {k.root_name} <span className="font-sans text-[11px] text-faint">reused</span>
        </li>
      ))}
      {kids.length > 4 ? <li className="pl-12 font-sans text-[11.5px] text-faint">+{kids.length - 4} more</li> : null}
    </ul>
  );
}
