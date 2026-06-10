import { useEffect, useState, type ReactElement } from "react";

import { fetchCurrentUser, type User } from "@infrastructure/api/auth";

/**
 * UserMenu — header island: "Entrar" when logged out, the account link when
 * logged in. Renders the logged-out state immediately and upgrades when
 * /api/auth/me answers, so the header never blocks on the network.
 */

interface Props {
  apiBaseUrl: string;
}

export function UserMenu({ apiBaseUrl }: Props): ReactElement {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchCurrentUser(apiBaseUrl, controller.signal).then(
      (me) => setUser(me),
      () => undefined, // network error → keep the logged-out affordance
    );
    return () => controller.abort();
  }, [apiBaseUrl]);

  if (user === null) {
    return (
      <a href="/login" className="transition-colors hover:text-foreground">
        Entrar
      </a>
    );
  }
  return (
    <a
      href="/account"
      className="max-w-[16ch] truncate font-medium text-foreground transition-colors"
      title={user.email}
    >
      {user.display_name ?? user.email}
    </a>
  );
}
