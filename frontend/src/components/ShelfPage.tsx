import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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

// One QueryClient for the whole island: ShelfImport and BookShelf both read
// the ["shelf"] query, and sharing the cache means one /api/shelf request
// serves both (the import widget only needs to know "is there a shelf yet?").
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: false, refetchOnWindowFocus: false },
  },
});

export function ShelfPage({ apiBaseUrl }: Props): ReactElement {
  return (
    <AuthGate apiBaseUrl={apiBaseUrl}>
      <QueryClientProvider client={queryClient}>
        <div className="space-y-8">
          <ShelfImport apiBaseUrl={apiBaseUrl} />
          <BookShelf apiBaseUrl={apiBaseUrl} />
        </div>
      </QueryClientProvider>
    </AuthGate>
  );
}
