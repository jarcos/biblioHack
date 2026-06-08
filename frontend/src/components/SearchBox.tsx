import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactElement } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { audienceLabel, formLabel, inDefaultScope } from "@/lib/literary";
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
  // Default scope is the literary catalogue (adult, all genres). The toggle
  // flips to `all` so children's / youth / non-fiction become searchable.
  const [includeAll, setIncludeAll] = useState(false);
  // Keyword (FTS) by default; semantic ranks by meaning via BGE-M3 vectors.
  const [semantic, setSemantic] = useState(false);

  const { data, error, isFetching, isSuccess } = useQuery({
    queryKey: [
      "catalog-search",
      query,
      includeAll ? "all" : "literary",
      semantic ? "semantic" : "keyword",
    ],
    queryFn: ({ signal }) =>
      searchCatalog(
        apiBaseUrl,
        {
          query,
          ...(includeAll ? { scope: "all" as const } : {}),
          ...(semantic ? { mode: "semantic" as const } : {}),
        },
        signal,
      ),
    enabled: query.length > 0,
  });

  // The backend may downgrade a semantic request to keyword when no embedder
  // is configured; `data.mode` reports what actually ran.
  const requestedSemantic = semantic;
  const fellBackToKeyword = requestedSemantic && isSuccess && data.mode === "keyword";

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

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div
            role="group"
            aria-label="Modo de búsqueda"
            className="inline-flex rounded-md border border-border p-0.5"
          >
            <button
              type="button"
              aria-pressed={!semantic}
              onClick={() => setSemantic(false)}
              className={`rounded px-3 py-1 text-sm transition-colors ${
                !semantic
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Palabra clave
            </button>
            <button
              type="button"
              aria-pressed={semantic}
              onClick={() => setSemantic(true)}
              className={`rounded px-3 py-1 text-sm transition-colors ${
                semantic
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Semántica
            </button>
          </div>

          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={includeAll}
              onChange={(event) => setIncludeAll(event.target.checked)}
              className="h-4 w-4 rounded border-border accent-primary"
            />
            Incluir infantil, juvenil y no ficción
          </label>
        </div>

        {semantic && (
          <p className="text-xs text-muted-foreground">
            La búsqueda semántica encuentra libros por significado (vectores BGE-M3), no solo por
            coincidencia de palabras.
          </p>
        )}
        {fellBackToKeyword && (
          <p className="text-xs text-amber-600 dark:text-amber-500">
            La búsqueda semántica no está disponible ahora mismo; mostrando resultados por palabra
            clave.
          </p>
        )}

        <SearchState
          isLoading={isFetching}
          error={error}
          submittedQuery={query}
          results={isSuccess ? data.items : null}
          total={isSuccess ? data.total : 0}
          apiBaseUrl={apiBaseUrl}
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
  apiBaseUrl,
}: {
  isLoading: boolean;
  error: unknown;
  submittedQuery: string;
  results: readonly CatalogRecordSummary[] | null;
  total: number;
  apiBaseUrl: string;
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
              <ResultRow record={record} apiBaseUrl={apiBaseUrl} />
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return null;
}

function ResultRow({
  record,
  apiBaseUrl,
}: {
  record: CatalogRecordSummary;
  apiBaseUrl: string;
}): ReactElement {
  const subtitleParts = [
    record.authors.join(", ") || null,
    record.publisher ?? null,
    record.pub_year != null ? String(record.pub_year) : null,
  ].filter((part): part is string => part !== null);

  // In `scope=all` mode the list surfaces children's/youth/non-fiction rows;
  // badge those so it's clear why they appear outside the literary default.
  const flagged = !inDefaultScope(record.audience, record.literary_form);
  const coverSrc = record.cover?.url ? `${apiBaseUrl}${record.cover.url}` : null;

  return (
    <a
      href={`/record?titn=${record.titn}`}
      className="flex items-start justify-between gap-4 rounded-md border border-border bg-card p-4 transition-colors hover:border-foreground/30 hover:bg-muted/40"
    >
      <div className="flex min-w-0 items-start gap-4">
        {coverSrc !== null ? (
          <img
            src={coverSrc}
            alt=""
            loading="lazy"
            className="h-16 w-11 shrink-0 rounded border border-border object-cover"
          />
        ) : (
          <div
            aria-hidden="true"
            className="flex h-16 w-11 shrink-0 items-center justify-center rounded border border-dashed border-border bg-muted/50 text-muted-foreground"
          >
            <span className="text-xs">📚</span>
          </div>
        )}
        <div className="min-w-0 space-y-1">
          <h3 className="font-serif text-lg font-semibold leading-tight tracking-tight">
            {record.title}
          </h3>
          {subtitleParts.length > 0 && (
            <p className="text-sm text-muted-foreground">{subtitleParts.join(" · ")}</p>
          )}
          {flagged && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Badge variant="secondary">{audienceLabel(record.audience)}</Badge>
              <Badge variant="secondary">{formLabel(record.literary_form)}</Badge>
            </div>
          )}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        {record.available_count > 0 && (
          <Badge variant="available">{record.available_count} disp. ahora</Badge>
        )}
        <Badge variant="outline">
          {record.copies_count} ejemplar{record.copies_count === 1 ? "" : "es"}
        </Badge>
      </div>
    </a>
  );
}

export default SearchBox;
