// Analyze-a-folder job state: submit, then poll every 3 s until done/failed.
import { useCallback, useEffect, useRef, useState } from "react";
import { devicesData } from "./data";
export const POLL_MS = 3000;
export function isFinished(j) {
    return !!j?.job && (j.job.status === "done" || j.job.status === "failed");
}
export function useAnalyzeJob(onDone) {
    const [state, setState] = useState(null);
    const done = useRef(onDone);
    done.current = onDone;
    const start = useCallback(async (path, deviceId) => {
        const result = await devicesData.analyze(path, deviceId);
        setState({ path, result, job: null, pollError: null });
        return result;
    }, []);
    const jobId = state?.result.job_id;
    const finished = isFinished(state);
    useEffect(() => {
        if (!jobId || finished)
            return;
        let alive = true;
        const tick = async () => {
            try {
                const job = await devicesData.job(jobId);
                if (!alive)
                    return;
                setState((s) => (s && s.result.job_id === jobId ? { ...s, job, pollError: null } : s));
                if (job.status === "done" || job.status === "failed")
                    done.current(job.project_id);
            }
            catch (pollError) {
                if (alive)
                    setState((s) => (s ? { ...s, pollError } : s));
            }
        };
        void tick();
        const t = window.setInterval(tick, POLL_MS);
        return () => { alive = false; window.clearInterval(t); };
    }, [jobId, finished]);
    const clear = useCallback(() => setState(null), []);
    return { state, start, clear };
}
