import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// App root: session gate (login / connecting / hub unreachable / shell).
import { useEffect } from "react";
import { onAuthLost } from "../api/client";
import { Button, ErrorState, Spinner } from "../design/primitives";
import { Monogram } from "./Brand";
import { LoginScreen } from "./LoginScreen";
import { useSession } from "./session";
import { Shell } from "./Shell";
export default function App() {
    const status = useSession((s) => s.status);
    useEffect(() => {
        // Any 401 from any feature clears the token (client.ts) and lands here.
        const off = onAuthLost(() => useSession.getState().expire());
        void useSession.getState().boot();
        return () => { off(); };
    }, []);
    if (status === "anon")
        return _jsx(LoginScreen, {});
    if (status === "booting")
        return _jsx(Connecting, {});
    if (status === "error")
        return _jsx(HubUnreachable, {});
    return _jsx(Shell, {});
}
function Connecting() {
    return (_jsx("div", { className: "grid h-dvh place-items-center bg-canvas", "aria-busy": "true", children: _jsxs("div", { className: "flex flex-col items-center gap-4 text-muted", children: [_jsx(Monogram, { size: 44 }), _jsxs("div", { className: "flex items-center gap-2 text-[13.5px]", children: [_jsx(Spinner, { size: 14 }), " Connecting to your hub\u2026"] })] }) }));
}
function HubUnreachable() {
    const error = useSession((s) => s.error);
    const boot = useSession((s) => s.boot);
    const signOut = useSession((s) => s.signOut);
    return (_jsx("div", { className: "grid h-dvh place-items-center overflow-y-auto bg-canvas px-4", children: _jsxs("div", { className: "w-full max-w-[460px] rounded-card border border-line bg-surface p-2 shadow-card", children: [_jsx(ErrorState, { error: error, title: "Can't reach your hub", service: "companion-api", onRetry: () => void boot() }), _jsx("div", { className: "flex justify-center border-t border-line p-3", children: _jsx(Button, { variant: "ghost", size: "sm", icon: "key", onClick: signOut, children: "Use a different invite code" }) })] }) }));
}
