import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useMemo, type ReactElement } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { availabilityLabel, availabilityVariant } from "@/lib/availability";
import { browseHref } from "@/lib/browse";
import { audienceLabel, formLabel, genreLabel, inDefaultScope } from "@/lib/literary";
import { useAvailabilityContext, type AvailabilityContext } from "@/lib/useAvailability";
import { haversineKm } from "@infrastructure/api/branches";
import {
  CatalogApiError,
  fetchRecord,
  fetchSimilar,
  type CatalogRecord,
  type CatalogRecordSummary,
} from "@infrastructure/api/catalog";

/**
 * RecordDetail — the per-record page. Mounted by `record.astro` as a
 * `client:only` island, so it reads the `?titn=` query param straight off
 * `window.location` at runtime (the static build ships one HTML shell; the
 * data is fetched in the browser). This keeps a 2.66M-record catalogue off
 * the static-build critical path — no `getStaticPaths` over millions of IDs.
 */

interface Props {
  apiBaseUrl: string;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: false, refetchOnWindowFocus: false },
  },
});

export function RecordDetail({ apiBaseUrl }: Props): ReactElement {
  return (
    <QueryClientProvider client={queryClient}>
      <RecordDetailInner apiBaseUrl={apiBaseUrl} />
    </QueryClientProvider>
  );
}

function RecordDetailInner({ apiBaseUrl }: Props): ReactElement {
  const titn = useMemo(() => parseTitn(), []);

  const { data, error, isFetching, isSuccess } = useQuery({
    queryKey: ["catalog-record", titn],
    queryFn: ({ signal }) => {
      if (titn === null) throw new Error("missing titn");
      return fetchRecord(apiBaseUrl, titn, signal);
    },
    enabled: titn !== null,
  });

  return (
    <article className="space-y-8">
      <a href="/" className="text-sm text-muted-foreground transition-colors hover:text-foreground">
        ← Volver a la búsqueda
      </a>
      {titn === null ? (
        <Message
          title="Falta el identificador del registro"
          body="La URL debe incluir un TITN, p. ej. /record?titn=1."
        />
      ) : isFetching ? (
        <p className="text-sm text-muted-foreground">Cargando registro…</p>
      ) : error ? (
        <ErrorState error={error} titn={titn} />
      ) : isSuccess ? (
        <RecordBody record={data} apiBaseUrl={apiBaseUrl} />
      ) : null}
    </article>
  );
}

function RecordBody({
  record,
  apiBaseUrl,
}: {
  record: CatalogRecord;
  apiBaseUrl: string;
}): ReactElement {
  // cover.url is a relative /catalog/covers/… path; make it absolute against
  // the API origin (same-origin in prod, cross-origin in dev).
  const coverSrc = record.cover?.url ? `${apiBaseUrl}${record.cover.url}` : null;
  const meta = [
    record.authors.join(", ") || null,
    record.pub_year != null ? String(record.pub_year) : null,
    record.publisher ?? null,
    record.document_type ?? null,
  ].filter((part): part is string => part !== null);

  // Anchor (primary library coords, or GPS) to highlight the reader's branch
  // and order the rest by proximity. No auto-prompt here.
  const availability = useAvailabilityContext(apiBaseUrl);
  const primaryCode = availability.anchor?.kind === "primary" ? availability.anchor.code : null;
  const branches = sortByProximity(groupByBranch(record), availability, primaryCode);
  const totalAvailable = branches.reduce((sum, b) => sum + b.available, 0);
  const branchesWithAvailable = branches.filter((b) => b.available > 0).length;
  const hasAvailabilityData = record.copies.some((c) => c.status !== "unknown");

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-5 sm:flex-row sm:items-start">
        {coverSrc !== null && (
          <img
            src={coverSrc}
            alt=""
            loading="lazy"
            className="h-48 w-auto shrink-0 rounded-md border border-border object-cover shadow-sm"
          />
        )}
        <div className="min-w-0 space-y-3">
          <h1 className="font-serif text-3xl font-semibold leading-tight tracking-tight">
            {record.title}
          </h1>
          {record.subtitle != null && record.subtitle.length > 0 && (
            <p className="text-lg text-muted-foreground">{record.subtitle}</p>
          )}
          {meta.length > 0 && <p className="text-sm text-muted-foreground">{meta.join(" · ")}</p>}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {/* Público + forma double as filters: each jumps to /browse scoped
                to that audience / literary form. */}
            <a href={browseHref({ audience: record.audience })} className="inline-flex">
              <Badge variant="secondary">{audienceLabel(record.audience)}</Badge>
            </a>
            <a href={browseHref({ literaryForm: record.literary_form })} className="inline-flex">
              <Badge variant="secondary">{formLabel(record.literary_form)}</Badge>
            </a>
            {record.classification != null && record.classification.length > 0 && (
              <Badge variant="outline" title="Clasificación CDU (MARC T080)">
                CDU {record.classification}
              </Badge>
            )}
            {!inDefaultScope(record.audience, record.literary_form) && (
              <span className="text-xs text-muted-foreground">
                · fuera del catálogo literario por defecto
              </span>
            )}
          </div>
          {(record.authors.length > 0 || record.genre !== "unknown") && (
            <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs">
              <span className="text-muted-foreground">Explorar:</span>
              {record.authors.map((author) => (
                <BrowseChip key={author} href={browseHref({ author })}>
                  {author}
                </BrowseChip>
              ))}
              {record.genre !== "unknown" && (
                <BrowseChip href={browseHref({ genre: record.genre })}>
                  {genreLabel(record.genre)}
                </BrowseChip>
              )}
            </div>
          )}
        </div>
      </header>

      {record.subjects.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-foreground">Materias</h2>
          <ul className="flex flex-wrap gap-2">
            {record.subjects.map((subject) => (
              <li key={subject}>
                <Badge variant="outline">{subject}</Badge>
              </li>
            ))}
          </ul>
        </section>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="font-sans text-base font-medium">
            Ejemplares · {record.copies.length} en {branches.length} sucursal
            {branches.length === 1 ? "" : "es"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {branches.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Sin ejemplares registrados (posible recurso virtual).
            </p>
          ) : (
            <>
              <div className="mb-3 flex items-center gap-2 text-sm">
                {!hasAvailabilityData ? (
                  <span className="text-muted-foreground">Disponibilidad aún sin rastrear.</span>
                ) : totalAvailable > 0 ? (
                  <>
                    <Badge variant="available">Disponible ahora</Badge>
                    <span className="text-muted-foreground">
                      {totalAvailable} ejemplar{totalAvailable === 1 ? "" : "es"} en{" "}
                      {branchesWithAvailable} sucursal{branchesWithAvailable === 1 ? "" : "es"}
                    </span>
                  </>
                ) : (
                  <span className="text-muted-foreground">
                    Ningún ejemplar disponible ahora mismo.
                  </span>
                )}
              </div>
              <ul className="divide-y divide-border">
                {branches.map((branch) => (
                  <li
                    key={branch.code}
                    className="flex items-center justify-between gap-3 py-2 text-sm"
                  >
                    <span className="text-foreground">
                      {branch.name}
                      {branch.code === primaryCode && (
                        <Badge variant="secondary" className="ml-2 align-middle">
                          tu biblioteca
                        </Badge>
                      )}
                      <span className="text-muted-foreground">
                        {" · "}
                        {branch.count} ejemplar{branch.count === 1 ? "" : "es"}
                      </span>
                    </span>
                    {branch.available > 0 ? (
                      <Badge variant="available" className="shrink-0">
                        {branch.available} disponible{branch.available === 1 ? "" : "s"}
                      </Badge>
                    ) : (
                      <Badge variant={availabilityVariant(branch.status)} className="shrink-0">
                        {availabilityLabel(branch.status)}
                      </Badge>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="pt-4 text-xs text-muted-foreground">
            Disponibilidad según el último rastreo del espejo, no en vivo contra el OPAC.
          </p>
        </CardContent>
      </Card>

      <SimilarStrip titn={record.titn} apiBaseUrl={apiBaseUrl} />

      <footer className="space-y-1 border-t border-border pt-4 text-xs text-muted-foreground">
        {record.isbns.length > 0 && <p>ISBN: {record.isbns.join(", ")}</p>}
        <p>
          <a
            href={record.source_url}
            className="text-foreground underline-offset-4 hover:underline"
            target="_blank"
            rel="noreferrer"
          >
            Ver en el OPAC original ↗
          </a>
        </p>
      </footer>
    </div>
  );
}

function SimilarStrip({
  titn,
  apiBaseUrl,
}: {
  titn: number;
  apiBaseUrl: string;
}): ReactElement | null {
  // "Más como este" — pure pgvector KNN over the record's stored embedding.
  // Returns an empty list when the record isn't embedded yet; we then render
  // nothing rather than an empty heading. Failures are swallowed (it's an
  // enhancement, not core content).
  const { data, isSuccess } = useQuery({
    queryKey: ["catalog-similar", titn],
    queryFn: ({ signal }) => fetchSimilar(apiBaseUrl, titn, 8, signal),
    enabled: titn > 0,
  });

  if (!isSuccess || data.items.length === 0) return null;

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium text-foreground">Más como este</h2>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {data.items.map((item) => (
          <li key={item.titn}>
            <SimilarCard record={item} apiBaseUrl={apiBaseUrl} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function SimilarCard({
  record,
  apiBaseUrl,
}: {
  record: CatalogRecordSummary;
  apiBaseUrl: string;
}): ReactElement {
  const coverSrc = record.cover?.url ? `${apiBaseUrl}${record.cover.url}` : null;
  const author = record.authors[0] ?? null;

  return (
    <a
      href={`/record?titn=${record.titn}`}
      className="flex h-full flex-col gap-2 rounded-md border border-border bg-card p-3 transition-colors hover:border-foreground/30 hover:bg-muted/40"
    >
      {coverSrc !== null ? (
        <img
          src={coverSrc}
          alt=""
          loading="lazy"
          className="h-32 w-auto self-center rounded border border-border object-cover"
        />
      ) : (
        <div
          aria-hidden="true"
          className="flex h-32 items-center justify-center rounded border border-dashed border-border bg-muted/50 text-muted-foreground"
        >
          <span className="text-xl">📚</span>
        </div>
      )}
      <div className="min-w-0 space-y-0.5">
        <h3 className="line-clamp-2 font-serif text-sm font-semibold leading-snug">
          {record.title}
        </h3>
        {author !== null && <p className="truncate text-xs text-muted-foreground">{author}</p>}
      </div>
    </a>
  );
}

/** A small chip-link into a pre-filtered /browse (author or genre). */
function BrowseChip({ href, children }: { href: string; children: string }): ReactElement {
  return (
    <a
      href={href}
      className="rounded-full border border-border px-2 py-0.5 text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
    >
      {children}
    </a>
  );
}

function ErrorState({ error, titn }: { error: unknown; titn: number }): ReactElement {
  if (error instanceof CatalogApiError && error.status === 404) {
    return (
      <Message
        title={`El registro TITN ${titn} aún no está en el espejo`}
        body="El worker puebla el catálogo de forma educada (1 req/s); es posible que este registro todavía no se haya rastreado. Vuelve a intentarlo más adelante."
      />
    );
  }
  const message =
    error instanceof CatalogApiError
      ? `${error.status} · ${error.detail}`
      : error instanceof Error
        ? error.message
        : "Error desconocido";
  return <p className="text-sm text-destructive">✗ No se pudo cargar el registro: {message}</p>;
}

function Message({ title, body }: { title: string; body: string }): ReactElement {
  return (
    <div className="space-y-2">
      <h1 className="font-serif text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="text-sm text-muted-foreground">{body}</p>
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────

function parseTitn(): number | null {
  if (typeof window === "undefined") return null;
  const raw = new URLSearchParams(window.location.search).get("titn");
  if (raw === null) return null;
  const value = Number(raw);
  return Number.isInteger(value) && value > 0 ? value : null;
}

interface BranchGroup {
  code: string;
  name: string;
  count: number;
  available: number;
  // Representative status for the branch badge when nothing is available.
  status: string;
}

// When a branch has no available copy, summarise it with the status
// "closest to borrowable" so the badge stays the most useful signal.
const STATUS_PRIORITY = ["available", "loaned", "reserved", "unavailable", "unknown"];

function rank(status: string): number {
  const i = STATUS_PRIORITY.indexOf(status);
  return i === -1 ? STATUS_PRIORITY.length : i;
}

function betterStatus(a: string, b: string): string {
  return rank(b) < rank(a) ? b : a;
}

/**
 * Order branches for the copies list: the reader's primary library first, then
 * the rest by distance from the anchor (primary coords or GPS), falling back to
 * alphabetical when there's no anchor or a branch isn't geocoded.
 */
function sortByProximity(
  groups: BranchGroup[],
  availability: AvailabilityContext,
  primaryCode: string | null,
): BranchGroup[] {
  const { anchor, branches } = availability;
  const distanceKm = (code: string): number => {
    if (anchor === null) return Number.POSITIVE_INFINITY;
    const coord = branches.get(code);
    if (!coord || coord.lat === null || coord.lng === null) return Number.POSITIVE_INFINITY;
    return haversineKm({ lat: anchor.lat, lng: anchor.lng }, { lat: coord.lat, lng: coord.lng });
  };
  return [...groups].sort((a, b) => {
    if (a.code === primaryCode) return -1;
    if (b.code === primaryCode) return 1;
    const da = distanceKm(a.code);
    const db = distanceKm(b.code);
    if (da !== db) return da - db;
    return a.name.localeCompare(b.name, "es");
  });
}

function groupByBranch(record: CatalogRecord): BranchGroup[] {
  const byCode = new Map<string, BranchGroup>();
  for (const copy of record.copies) {
    const existing = byCode.get(copy.branch_code);
    if (existing) {
      existing.count += 1;
      if (copy.status === "available") existing.available += 1;
      existing.status = betterStatus(existing.status, copy.status);
    } else {
      byCode.set(copy.branch_code, {
        code: copy.branch_code,
        name: copy.branch_name,
        count: 1,
        available: copy.status === "available" ? 1 : 0,
        status: copy.status,
      });
    }
  }
  return [...byCode.values()].sort((a, b) => a.name.localeCompare(b.name, "es"));
}

export default RecordDetail;
