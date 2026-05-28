import { useEffect, useState } from "react";
import { fetchHealth, type Health } from "@infrastructure/api/health";

interface Props {
  apiBaseUrl: string;
}

type State =
  | { kind: "loading" }
  | { kind: "ok"; health: Health }
  | { kind: "error"; message: string };

/**
 * Tiny React island that pings the backend's /healthz endpoint and renders the
 * result. Lives here as a smoke test of the wiring; will be replaced by real
 * widgets in later milestones.
 */
export default function HelloIsland({ apiBaseUrl }: Props): JSX.Element {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchHealth(apiBaseUrl)
      .then((health) => {
        if (!cancelled) setState({ kind: "ok", health });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl]);

  return (
    <div className="mt-2 font-mono text-sm">
      {state.kind === "loading" && <span className="text-slate-500">pinging API…</span>}
      {state.kind === "ok" && (
        <span className="text-emerald-700 dark:text-emerald-400">
          ✓ API ok — version {state.health.version}
        </span>
      )}
      {state.kind === "error" && (
        <span className="text-rose-700 dark:text-rose-400">
          ✗ API unreachable: {state.message}
        </span>
      )}
    </div>
  );
}
