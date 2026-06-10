import { type ReactElement } from "react";

import { AuthGate } from "@/components/auth/AuthGate";
import { BookShelf } from "@/components/BookShelf";
import { ShelfImport } from "@/components/ShelfImport";

/**
 * ShelfPage — the single island for /shelf.
 *
 * The gate and its protected content must compose INSIDE React: Astro
 * passes an island's children as a statically-rendered HTML slot, so
 * `<AuthGate client:only><BookShelf/></AuthGate>` in a .astro file produces
 * a dead snapshot of the children (no handlers, no queries) — the bug that
 * froze the shelf on "Cargando…" and made the import button inert.
 */

interface Props {
  apiBaseUrl: string;
}

export function ShelfPage({ apiBaseUrl }: Props): ReactElement {
  return (
    <AuthGate apiBaseUrl={apiBaseUrl}>
      <div className="space-y-8">
        <ShelfImport apiBaseUrl={apiBaseUrl} />
        <BookShelf apiBaseUrl={apiBaseUrl} />
      </div>
    </AuthGate>
  );
}
