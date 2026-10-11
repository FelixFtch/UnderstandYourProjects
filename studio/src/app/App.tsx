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

  if (status === "anon") return <LoginScreen />;
  if (status === "booting") return <Connecting />;
  if (status === "error") return <HubUnreachable />;
  return <Shell />;
}

function Connecting() {
  return (
    <div className="grid h-dvh place-items-center bg-canvas" aria-busy="true">
      <div className="flex flex-col items-center gap-4 text-muted">
        <Monogram size={44} />
        <div className="flex items-center gap-2 text-[13.5px]"><Spinner size={14} /> Connecting to your hub…</div>
      </div>
    </div>
  );
}

function HubUnreachable() {
  const error = useSession((s) => s.error);
  const boot = useSession((s) => s.boot);
  const signOut = useSession((s) => s.signOut);
  return (
    <div className="grid h-dvh place-items-center overflow-y-auto bg-canvas px-4">
      <div className="w-full max-w-[460px] rounded-card border border-line bg-surface p-2 shadow-card">
        <ErrorState error={error} title="Can't reach your hub" service="companion-api" onRetry={() => void boot()} />
        <div className="flex justify-center border-t border-line p-3">
          <Button variant="ghost" size="sm" icon="key" onClick={signOut}>Use a different invite code</Button>
        </div>
      </div>
    </div>
  );
}
