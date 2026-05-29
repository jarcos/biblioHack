import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactElement } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  CatalogApiError,
  searchCatalog,
  type CatalogRecordSummary,
} from "@infrastructure/api/catalog";

/**
 * SearchBox — the first end-to-end UI flow. Astro hydrates this as an
 * island; it owns its own QueryClient instance because each Astro island
 * is its own React tree.
 *
 * Submit-on-enter (or button click). We deliberately do NOT do
 * search-as-you-type yet — it's gentler on the OPAC mirror and the user
 * experience while results are empty.
 *
 * State machine:
 *   - idle:    no query submitted yet
 *   - loading: request in flight
 *   - error:   network failed or backend returned non-2xx
 *   - empty:   request OK but `items.length === 0`
 *   - results: at least one result
 */

interface Props {
  apiBaseUrl: string;
}

// Cached at module scope — created once per island mount, shared across
// any re-renders during the island's lifetime.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // We want a cold lookup the first time, but quick re-renders
      // shouldn't re-fetch. 30s feels right for a side-project catalog.
      staleTime: 30_000,
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

export function SearchBox({ apiBaseUrl }: Props): ReactElement {
  return (
    <QueryClientProvider client={queryClient}>
      <SearchBoxInner apiBaseUrl={apiBaseUrl} />
    </QueryClientProvider>
  );
}

function SearchBoxInner({ apiBaseUrl }: Props): ReactElement {
  // `draft` is what's typed; `query` is what was submitted. Splitting the
  // two means typing doesn't trigger fresh requests on every keystroke.
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");

  const { data, error, isFetching, isSuccess } = useQuery({
    queryKey: ["catalog-search", query],
    queryFn: ({ signal }) => searchCatalog(apiBaseUrl, { query }, signal),
    enabled: query.length > 0,
  });

  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    setQuery(draft.trim());
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Buscar en el catálogo</CardTitle>
        <CardDescription>
          Búsqueda de texto completo en castellano, sensible al acento gracias a la configuración{" "}
          <code>spanish_unaccent</code> de Postgres.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <form className="flex gap-2" onSubmit={onSubmit} autoComplete="off">
          <Input
            type="search"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Cien años de soledad, García Márquez, Planeta…"
            aria-label="Buscar en el catálogo"
          />
          <Button type="submit" disabled={draft.trim().length === 0}>
            Buscar
          </Button>
        </form>

        <SearchState
          isLoading={isFetching}
          error={error}
          submittedQuery={query}
          results={isSuccess ? data.items : null}
          total={isSuccess ? data.total : 0}
        />
      </CardContent>
    </Card>
  );
}

function SearchState({
  isLoading,
  error,
  submittedQuery,
  results,
  total,
}: {
  isLoading: boolean;
  error: unknown;
  submittedQuery: string;
  results: readonly CatalogRecordSummary[] | null;
  total: number;
}): ReactElement | null {
  if (submittedQuery.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Escribe una consulta y pulsa{" "}
        <kbd className="rounded border bg-muted px-1.5 py-0.5 text-xs">Enter</kbd>.
      </p>
    );
  }
  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Buscando…</p>;
  }
  if (error) {
    const message =
      error instanceof CatalogApiError
        ? `${error.status} · ${error.detail}`
        : error instanceof Error
          ? error.message
          : "Error desconocido";
    return (
      <p className="text-sm text-destructive">✗ No se pudo completar la búsqueda: {message}</p>
    );
  }
  if (results && results.length === 0) {
    return (
      <div className="space-y-2 text-sm text-muted-foreground">
        <p>
          Sin resultados para <strong className="text-foreground">«{submittedQuery}»</strong>.
        </p>
        <p>
          El espejo del catálogo aún está prácticamente vacío — el worker se ejecuta de forma
          educada (1 req/s) y poblar la red completa lleva varias semanas. Vuelve a intentarlo más
          adelante.
        </p>
      </div>
    );
  }
  if (results && results.length > 0) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          {total.toLocaleString("es-ES")} resultado{total === 1 ? "" : "s"} para{" "}
          <strong className="text-foreground">«{submittedQuery}»</strong>
          {total > results.length ? ` · mostrando ${results.length}` : ""}
        </p>
        <ul className="space-y-3">
          {results.map((record) => (
            <li key={record.titn}>
              <ResultRow record={record} />
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return null;
}

function ResultRow({ record }: { record: CatalogRecordSummary }): ReactElement {
  const subtitleParts = [
    record.authors.join(", ") || null,
    record.publisher ?? null,
    record.pub_year != null ? String(record.pub_year) : null,
  ].filter((part): part is string => part !== null);

  return (
    <article className="flex items-start justify-between gap-4 rounded-md border border-border bg-card p-4">
      <div className="space-y-1">
        <h3 className="font-serif text-lg font-semibold leading-tight tracking-tight">
          {record.title}
        </h3>
        {subtitleParts.length > 0 && (
          <p className="text-sm text-muted-foreground">{subtitleParts.join(" · ")}</p>
        )}
      </div>
      <Badge variant="outline" className="shrink-0">
        {record.copies_count} ejemplar{record.copies_count === 1 ? "" : "es"}
      </Badge>
    </article>
  );
}

export default SearchBox;
