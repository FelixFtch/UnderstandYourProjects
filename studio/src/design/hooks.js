// Tiny data hook shared by views: load on mount / deps change, keep stale data while reloading.
import { useCallback, useEffect, useRef, useState } from "react";
export function useResource(load, deps) {
    const [state, setState] = useState({ data: undefined, error: null, loading: true });
    const [nonce, setNonce] = useState(0);
    const loader = useRef(load);
    loader.current = load;
    const lastNonce = useRef(nonce);
    useEffect(() => {
        const ctrl = new AbortController();
        const isReload = lastNonce.current !== nonce;
        lastNonce.current = nonce;
        // a reload keeps showing the previous data; new deps start clean
        setState((s) => ({ data: isReload ? s.data : undefined, loading: true, error: null }));
        loader.current(ctrl.signal).then((data) => { if (!ctrl.signal.aborted)
            setState({ data, error: null, loading: false }); }, (error) => {
            if (ctrl.signal.aborted || (error instanceof DOMException && error.name === "AbortError"))
                return;
            setState((s) => ({ data: s.data, error, loading: false }));
        });
        return () => ctrl.abort();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [...deps, nonce]);
    const reload = useCallback(() => setNonce((n) => n + 1), []);
    return { ...state, reload };
}
