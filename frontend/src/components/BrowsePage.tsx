import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactElement } from "react";

import { AvailabilityBadge } from "@/components/AvailabilityBadge";
import { Cover } from "@/components/Cover";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  browseSearchParams,
  DEFAULT_BROWSE_FILTERS,
  parseBrowseFilters,
  type BrowseFilters as Filters,
} from "@/lib/browse";
import { audienceLabel, formLabel, genreLabel, inDefaultScope } from "@/lib/literary";
import {
  RADIUS_OPTIONS,
  useAvailabilityContext,
  type AvailabilityContext,
} from "@/lib/useAvailability";
import { fetchMyBranches } from "@infrastructure/api/branches";
import {
  browseCatalog,
  CatalogApiError,
  fetchAuthors,
  type Audience,
  type BrowseParams,
  type CatalogRecordSummary,
  type FacetCount,
  type Genre,
  type LiteraryForm,
} from "@infrastructure/api/catalog";

/**
 * BrowsePage — the catalogue navigator island (/browse).
 *
 * Facet sidebar + paginated card grid over `GET /catalog/browse`. State is
 * plain React (filters change rarely); every change resets to page 0. The
 * author facet is a small search box backed by `GET /catalog/authors`.
 */

interface Props {
  apiBaseUrl: string;
}

const PAGE_SIZE = 24;

export function BrowsePage({ apiBaseUrl }: Props): ReactElement {
  // Per-mount client (not module-level): the island mounts once in prod, and
  // tests get a fresh cache per render instead of bleeding 30s-stale pages.
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 30_000, retry: false, refetchOnWindowFocus: false },
        },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <BrowseInner apiBaseUrl={apiBaseUrl} />
    </QueryClientProvider>
  );
}

// `Filters` (and its `| undefined` clearable members, for
// `exactOptionalPropertyTypes`) now lives in `@/lib/browse`, shared with the
// cross-link builders so `/browse?author=…` deep links round-trip exactly.

const FACET_LABELS: Record<string, (value: string) => string> = {
  genre: genreLabel,
  language: (v) => v,
  audience: audienceLabel,
  literary_form: formLabel,
};

const FACET_TITLES: Record<string, string> = {
  genre: "Género",
  language: "Idioma",
  audience: "Público",
  literary_form: "Forma",
};

function BrowseInner({ apiBaseUrl }: Props): ReactElement {
  // Seed from the URL so `/browse?author=…&genre=…` deep links (from a search
  // result or record page) land pre-filtered; defaults when there's no query.
  const [filters, setFilters] = useState<Filters>(() =>
    typeof window === "undefined"
      ? DEFAULT_BROWSE_FILTERS
      : parseBrowseFilters(window.location.search),
  );
  const [page, setPage] = useState(0);

  // Library-aware availability: resolves the reader's anchor (primary library
  // coords, or device GPS), the branch directory, and the radius. Auto-prompts
  // GPS on first visit for anchor-less readers (D-C).
  const availability = useAvailabilityContext(apiBaseUrl, { autoLocate: true });

  // Mirror the active filters back into the URL (replace, not push — filter
  // tweaks shouldn't pile up in history) so the page is shareable and the
  // browser back button restores a sensible state.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const qs = browseSearchParams(filters).toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [filters]);
  // Whether to offer the library-scope control: only for signed-in users who
  // follow ≥1 branch. The backend resolves scope to the full catalogue for
  // everyone else, so sending the param is harmless when this is false.
  const [followsBranches, setFollowsBranches] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchMyBranches(apiBaseUrl, controller.signal).then(
      (codes) => setFollowsBranches(codes !== null && codes.length > 0),
      () => setFollowsBranches(false),
    );
    return () => controller.abort();
  }, [apiBaseUrl]);

  const params: BrowseParams = {
    ...(filters.author !== undefined ? { author: filters.author } : {}),
    ...(filters.language !== undefined ? { language: filters.language } : {}),
    ...(filters.genre !== undefined ? { genre: filters.genre } : {}),
    ...(filters.audience !== undefined ? { audience: filters.audience } : {}),
    ...(filters.literaryForm !== undefined ? { literaryForm: filters.literaryForm } : {}),
    ...(filters.yearFrom !== undefined ? { yearFrom: filters.yearFrom } : {}),
    ...(filters.yearTo !== undefined ? { yearTo: filters.yearTo } : {}),
    ...(filters.available ? { available: true } : {}),
    sort: filters.sort,
    ...(followsBranches ? { libraryScope: filters.libraryScope } : {}),
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  };

  const { data, error, isFetching, isSuccess } = useQuery({
    queryKey: ["catalog-browse", params],
    queryFn: ({ signal }) => browseCatalog(apiBaseUrl, params, signal),
  });

  function update(partial: Partial<Filters>): void {
    setFilters((current) => ({ ...current, ...partial }));
    setPage(0);
  }

  /** Toggle a facet value: clicking the active value clears it. */
  function toggle<K extends keyof Filters>(key: K, value: Filters[K]): void {
    update({ [key]: filters[key] === value ? undefined : value } as Partial<Filters>);
  }

  const totalPages = isSuccess ? Math.ceil(data.total / PAGE_SIZE) : 0;

  return (
    <div className="grid items-start gap-10 lg:grid-cols-[262px_1fr]">
      <aside className="space-y-6 self-start lg:sticky lg:top-24">
        <CatalogSearchBox />

        <AuthorFacet
          apiBaseUrl={apiBaseUrl}
          selected={filters.author}
          onSelect={(author) => toggle("author", author)}
        />

        {isSuccess &&
          Object.entries(data.facets).map(([dim, counts]) => (
            <FacetGroup
              key={dim}
              title={FACET_TITLES[dim] ?? dim}
              counts={counts}
              labelFor={FACET_LABELS[dim] ?? ((v: string) => v)}
              selected={facetSelection(filters, dim)}
              onToggle={(value) => toggleFacet(dim, value, filters, toggle)}
            />
          ))}

        <section className="space-y-2.5">
          <h3 className="eyebrow m-0 font-normal">Año de publicación</h3>
          <div className="flex items-center gap-2">
            <Input
              type="number"
              inputMode="numeric"
              placeholder="Desde"
              aria-label="Año desde"
              value={filters.yearFrom ?? ""}
              onChange={(e) =>
                update({ yearFrom: e.target.value ? Number(e.target.value) : undefined })
              }
            />
            <Input
              type="number"
              inputMode="numeric"
              placeholder="Hasta"
              aria-label="Año hasta"
              value={filters.yearTo ?? ""}
              onChange={(e) =>
                update({ yearTo: e.target.value ? Number(e.target.value) : undefined })
              }
            />
          </div>
        </section>

        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={filters.available}
            onChange={(e) => update({ available: e.target.checked })}
            className="h-4 w-4 rounded border-border accent-primary"
          />
          Solo disponibles ahora
        </label>

        <section className="space-y-2.5">
          <h3 className="eyebrow m-0 font-normal">Ordenar por</h3>
          <select
            value={filters.sort}
            onChange={(e) => update({ sort: e.target.value as Filters["sort"] })}
            aria-label="Ordenar por"
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          >
            <option value="relevance">Destacados</option>
            <option value="newest">Más recientes</option>
            <option value="title">Título (A–Z)</option>
          </select>
        </section>

        {followsBranches && (
          <section className="space-y-2.5">
            <h3 className="eyebrow m-0 font-normal">Bibliotecas</h3>
            <select
              value={filters.libraryScope}
              onChange={(e) => update({ libraryScope: e.target.value as Filters["libraryScope"] })}
              aria-label="Ámbito de bibliotecas"
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            >
              <option value="mine">Mis bibliotecas</option>
              <option value="province">Mi provincia</option>
              <option value="full">Todo el catálogo</option>
            </select>
            <p className="text-xs text-muted-foreground">
              Filtra por lo que hay en las bibliotecas que sigues.{" "}
              <a href="/account" className="underline underline-offset-4">
                Edítalas
              </a>
              .
            </p>
          </section>
        )}

        {availability.anchor !== null && (
          <section className="space-y-2.5">
            <h3 className="eyebrow m-0 font-normal">Distancia</h3>
            <select
              value={availability.radiusKm}
              onChange={(e) => availability.setRadiusKm(Number(e.target.value))}
              aria-label="Radio de cercanía"
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            >
              {RADIUS_OPTIONS.map((km) => (
                <option key={km} value={km}>
                  {km} km
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              {availability.anchor.kind === "primary"
                ? "Cuenta como «cercana» una biblioteca a esta distancia de la tuya."
                : "Cuenta como «cercana» una biblioteca a esta distancia de tu ubicación."}
            </p>
          </section>
        )}
      </aside>

      <section className="space-y-6">
        {isFetching && <p className="text-sm text-muted-foreground">Cargando el catálogo…</p>}
        {error != null && (
          <p className="text-sm text-destructive">
            ✗ No se pudo cargar el catálogo:{" "}
            {error instanceof CatalogApiError
              ? `${error.status} · ${error.detail}`
              : error instanceof Error
                ? error.message
                : "error desconocido"}
          </p>
        )}
        {isSuccess && (
          <>
            <div className="flex flex-wrap items-center gap-3 border-b border-border pb-4">
              <span role="status" className="font-mono text-sm text-foreground">
                <strong>{data.total.toLocaleString("es-ES")}</strong>{" "}
                <span className="text-faint">obras en el espejo</span>
              </span>
              <ActiveFilterChips filters={filters} onClear={update} />
            </div>
            {data.items.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nada por aquí todavía — el catálogo crece cada hora; prueba a quitar algún filtro.
              </p>
            ) : (
              <ul className="grid grid-cols-2 gap-x-5 gap-y-7 sm:grid-cols-3 xl:grid-cols-4">
                {data.items.map((item) => (
                  <li key={item.titn}>
                    <BrowseCard item={item} apiBaseUrl={apiBaseUrl} availability={availability} />
                  </li>
                ))}
              </ul>
            )}
            {totalPages > 1 && (
              <nav className="flex items-center justify-center gap-4 pt-4" aria-label="Paginación">
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-lg"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  ←
                </Button>
                <span className="font-mono text-sm text-muted-foreground">
                  Página {page + 1} de {totalPages.toLocaleString("es-ES")}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-lg"
                  disabled={!data.has_more}
                  onClick={() => setPage((p) => p + 1)}
                >
                  →
                </Button>
              </nav>
            )}
          </>
        )}
      </section>
    </div>
  );
}

/** Free-text search box on /browse — hands the query off to the full-text
 *  search on the home page (`/?q=…`), the browse → search half of the
 *  cross-link loop. */
function CatalogSearchBox(): ReactElement {
  const [draft, setDraft] = useState("");

  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const q = draft.trim();
    if (q.length === 0) return;
    window.location.assign(`/?q=${encodeURIComponent(q)}`);
  };

  return (
    <section>
      <form
        onSubmit={onSubmit}
        className="flex items-center gap-2 rounded-lg border-[1.5px] border-input bg-muted px-3"
      >
        <span aria-hidden="true" className="text-faint">
          ⌕
        </span>
        <input
          type="search"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Buscar en el catálogo…"
          aria-label="Buscar en el catálogo"
          className="w-full border-none bg-transparent py-2.5 text-sm text-foreground outline-none placeholder:text-faint"
        />
      </form>
    </section>
  );
}

/**
 * ActiveFilterChips — the "Género: Narrativa ✕" pills next to the result
 * count (design: verde-suave pills; clicking one clears that filter).
 */
function ActiveFilterChips({
  filters,
  onClear,
}: {
  filters: Filters;
  onClear: (partial: Partial<Filters>) => void;
}): ReactElement | null {
  const chips: { key: string; label: string; clear: Partial<Filters> }[] = [];
  if (filters.author !== undefined)
    chips.push({ key: "author", label: `Autor: ${filters.author}`, clear: { author: undefined } });
  if (filters.genre !== undefined)
    chips.push({
      key: "genre",
      label: `Género: ${genreLabel(filters.genre)}`,
      clear: { genre: undefined },
    });
  if (filters.language !== undefined)
    chips.push({
      key: "language",
      label: `Idioma: ${filters.language}`,
      clear: { language: undefined },
    });
  if (filters.audience !== undefined)
    chips.push({
      key: "audience",
      label: `Público: ${audienceLabel(filters.audience)}`,
      clear: { audience: undefined },
    });
  if (filters.literaryForm !== undefined)
    chips.push({
      key: "literaryForm",
      label: `Forma: ${formLabel(filters.literaryForm)}`,
      clear: { literaryForm: undefined },
    });
  if (filters.yearFrom !== undefined || filters.yearTo !== undefined)
    chips.push({
      key: "years",
      label: `Años: ${filters.yearFrom ?? "…"}–${filters.yearTo ?? "…"}`,
      clear: { yearFrom: undefined, yearTo: undefined },
    });
  if (filters.available)
    chips.push({ key: "available", label: "Disponible ahora", clear: { available: false } });

  if (chips.length === 0) return null;
  return (
    <>
      {chips.map(({ key, label, clear }) => (
        <button
          key={key}
          type="button"
          onClick={() => onClear(clear)}
          title="Quitar filtro"
          className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft py-1 pl-3 pr-2.5 text-[0.82rem] font-medium text-brand-soft-foreground transition-opacity hover:opacity-80"
        >
          <span className="max-w-[24ch] truncate">{label}</span>
          <span aria-hidden="true" className="opacity-70">
            ✕
          </span>
        </button>
      ))}
    </>
  );
}

function facetSelection(filters: Filters, dim: string): string | undefined {
  if (dim === "genre") return filters.genre;
  if (dim === "language") return filters.language;
  if (dim === "audience") return filters.audience;
  if (dim === "literary_form") return filters.literaryForm;
  return undefined;
}

function toggleFacet(
  dim: string,
  value: string,
  filters: Filters,
  toggle: <K extends keyof Filters>(key: K, value: Filters[K]) => void,
): void {
  if (dim === "genre") toggle("genre", value as Genre);
  else if (dim === "language") toggle("language", value);
  else if (dim === "audience") toggle("audience", value as Audience);
  else if (dim === "literary_form") toggle("literaryForm", value as LiteraryForm);
}

function FacetGroup({
  title,
  counts,
  labelFor,
  selected,
  onToggle,
}: {
  title: string;
  counts: FacetCount[];
  labelFor: (value: string) => string;
  selected: string | undefined;
  onToggle: (value: string) => void;
}): ReactElement | null {
  if (counts.length === 0) return null;
  return (
    <section className="space-y-2.5 border-t border-border pt-6">
      <h3 className="eyebrow m-0 font-normal">{title}</h3>
      <ul className="space-y-0.5">
        {counts.map(({ value, count }) => (
          <li key={value}>
            <button
              type="button"
              aria-pressed={selected === value}
              onClick={() => onToggle(value)}
              className={`flex w-full items-center justify-between gap-2 rounded-[7px] px-2.5 py-1.5 text-left text-sm transition-colors ${
                selected === value
                  ? "bg-brand-soft font-semibold text-brand-soft-foreground"
                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
              }`}
            >
              <span className="truncate">{labelFor(value)}</span>
              <span className="shrink-0 font-mono text-xs tabular-nums opacity-80">
                {count.toLocaleString("es-ES")}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AuthorFacet({
  apiBaseUrl,
  selected,
  onSelect,
}: {
  apiBaseUrl: string;
  selected: string | undefined;
  onSelect: (author: string) => void;
}): ReactElement {
  const [draft, setDraft] = useState("");
  const [submitted, setSubmitted] = useState("");

  const { data } = useQuery({
    queryKey: ["catalog-authors", submitted],
    queryFn: ({ signal }) => fetchAuthors(apiBaseUrl, submitted || undefined, signal),
  });

  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    setSubmitted(draft.trim());
  };

  return (
    <section className="space-y-2.5 border-t border-border pt-6">
      <h3 className="eyebrow m-0 font-normal">Autor</h3>
      {selected !== undefined && (
        <button
          type="button"
          onClick={() => onSelect(selected)}
          className="flex w-full items-center justify-between gap-2 rounded-[7px] bg-brand-soft px-2.5 py-1.5 text-left text-sm font-semibold text-brand-soft-foreground"
        >
          <span className="truncate">{selected}</span>
          <span aria-hidden="true" className="opacity-70">
            ✕
          </span>
        </button>
      )}
      <form onSubmit={onSubmit} className="flex gap-1.5">
        <Input
          type="search"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Buscar autor…"
          aria-label="Buscar autor"
          className="h-9 rounded-lg bg-muted"
        />
        <Button type="submit" variant="outline" size="sm" className="rounded-lg">
          Ir
        </Button>
      </form>
      {data !== undefined && data.items.length > 0 && (
        <ul className="max-h-56 space-y-0.5 overflow-y-auto">
          {data.items.map(({ name, records }) => (
            <li key={name}>
              <button
                type="button"
                onClick={() => onSelect(name)}
                className={`flex w-full items-center justify-between gap-2 rounded-[7px] px-2.5 py-1.5 text-left text-sm transition-colors ${
                  selected === name
                    ? "bg-brand-soft font-semibold text-brand-soft-foreground"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                }`}
              >
                <span className="truncate">{name}</span>
                <span className="shrink-0 font-mono text-xs tabular-nums opacity-80">
                  {records}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function BrowseCard({
  item,
  apiBaseUrl,
  availability,
}: {
  item: CatalogRecordSummary;
  apiBaseUrl: string;
  availability: AvailabilityContext;
}): ReactElement {
  const coverSrc = item.cover?.url ? `${apiBaseUrl}${item.cover.url}` : null;
  return (
    <a
      href={`/record?titn=${item.titn}`}
      className="group flex h-full flex-col gap-3 no-underline transition-transform hover:-translate-y-0.5"
    >
      <div className="overflow-hidden rounded-md shadow-cover">
        {coverSrc !== null ? (
          <img src={coverSrc} alt="" loading="lazy" className="aspect-[0.66] w-full object-cover" />
        ) : (
          <Cover title={item.title} author={item.authors[0]} />
        )}
      </div>
      <div className="min-w-0">
        <h3 className="line-clamp-2 font-serif text-[1.02rem] font-semibold leading-tight tracking-tight text-foreground">
          {item.title}
        </h3>
        {item.authors.length > 0 && (
          <p className="mt-1 line-clamp-1 text-[0.85rem] text-muted-foreground">
            {item.authors.join(" · ")}
          </p>
        )}
        {item.pub_year != null && (
          <p className="mt-0.5 font-mono text-xs text-faint">
            {item.pub_year}
            {item.genre !== "unknown" ? ` · ${genreLabel(item.genre)}` : ""}
          </p>
        )}
      </div>
      <div className="mt-auto flex flex-wrap items-center gap-1.5">
        {/* Flag out-of-default-scope rows (infantil / juvenil / no ficción) so
            they're distinguishable at a glance — /browse covers the whole
            mirror, not just the adult-literary default that search assumes. */}
        {!inDefaultScope(item.audience, item.literary_form) && (
          <>
            <Badge variant="secondary">{audienceLabel(item.audience)}</Badge>
            <Badge variant="secondary">{formLabel(item.literary_form)}</Badge>
          </>
        )}
        <AvailabilityBadge
          item={item}
          anchor={availability.anchor}
          branches={availability.branches}
          radiusKm={availability.radiusKm}
          onLocate={availability.locate}
          canLocate={availability.canLocate}
          locating={availability.locating}
        />
      </div>
    </a>
  );
}

export default BrowsePage;
