import { useEffect, useState, type ReactElement, type ReactNode } from "react";

import { fetchCurrentUser } from "@infrastructure/api/auth";

/**
 * AuthGate — client-side guard for pages that need a session. The site is
 * statically built (no SSR middleware), so the check happens in the
 * browser: no valid session → redirect to /login with a `next` back-link.
 */

interface Props {
  apiBaseUrl: string;
  children: ReactNode;
}

export function AuthGate({ apiBaseUrl, children }: Props): ReactElement {
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchCurrentUser(apiBaseUrl, controller.signal).then(
      (me) => {
        if (me === null) {
          const next = encodeURIComponent(window.location.pathname + window.location.search);
          window.location.assign(`/login?next=${next}`);
          return;
        }
        setAuthed(true);
      },
      () => {
        /* network error — leave the loading state; the page islands will
           surface their own errors if the user stays */
        setAuthed(true);
      },
    );
    return () => controller.abort();
  }, [apiBaseUrl]);

  if (!authed) {
    return <p className="text-sm text-muted-foreground">Comprobando tu sesión…</p>;
  }
  return <>{children}</>;
}
