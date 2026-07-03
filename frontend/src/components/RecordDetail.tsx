import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useMemo, type ReactElement } from "react";

import { Cover } from "@/components/Cover";
import { Badge } from "@/components/ui/badge";
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
      <a
        href="/browse"
        className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted-foreground no-underline transition-colors hover:text-foreground"
      >
        ← Volver al catálogo
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

  // Anchor (primary library coords, or GPS) to highlight the reader's branch
  // and order the rest by proximity. No auto-prompt here.
  const availability = useAvailabilityContext(apiBaseUrl);
  const primaryCode = availability.anchor?.kind === "primary" ? availability.anchor.code : null;
  const branches = sortByProximity(groupByBranch(record), availability, primaryCode);
  const totalAvailable = branches.reduce((sum, b) => sum + b.available, 0);
  const hasAvailabilityData = record.copies.some((c) => c.status !== "unknown");
  const availableAtPrimary =
    primaryCode !== null && branches.some((b) => b.code === primaryCode && b.available > 0);

  const distanceLabel = (code: string): string | null => {
    const { anchor, branches: coords } = availability;
    if (anchor === null) return null;
    const coord = coords.get(code);
    if (!coord || coord.lat === null || coord.lng === null) return null;
    const km = haversineKm(
      { lat: anchor.lat, lng: anchor.lng },
      { lat: coord.lat, lng: coord.lng },
    );
    return km < 10
      ? `${km.toLocaleString("es-ES", { maximumFractionDigits: 1 })} km`
      : `${Math.round(km).toLocaleString("es-ES")} km`;
  };

  // Ficha bibliográfica — the two-column meta grid (design "detailMeta").
  const meta: { k: string; v: string }[] = [];
  if (record.pub_year != null) meta.push({ k: "Año", v: String(record.pub_year) });
  if (record.language) meta.push({ k: "Idioma", v: record.language });
  if (record.genre !== "unknown") meta.push({ k: "Género", v: genreLabel(record.genre) });
  if (record.publisher) meta.push({ k: "Editorial", v: record.publisher });
  if (record.document_type) meta.push({ k: "Tipo", v: record.document_type });
  // Single string ("CDU 821.111") so the classification reads as one unit.
  if (record.classification) meta.push({ k: "Clasificación", v: `CDU ${record.classification}` });
  if (record.isbns.length > 0) meta.push({ k: "ISBN", v: record.isbns.join(", ") });

  return (
    <div className="grid items-start gap-10 lg:grid-cols-[280px_1fr] lg:gap-12">
      {/* ── Left rail: cover + availability card (sticky) ── */}
      <div className="flex flex-col gap-5 self-start lg:sticky lg:top-24">
        <div className="overflow-hidden rounded-lg shadow-[0_30px_60px_-24px_rgba(28,26,21,.5)]">
          {coverSrc !== null ? (
            <img src={coverSrc} alt="" loading="lazy" className="w-full object-cover" />
          ) : (
            <Cover title={record.title} author={record.authors[0]} />
          )}
        </div>

        <section className="rounded-2xl border border-border bg-card p-5 shadow-card">
          {branches.length === 0 ? (
            <p className="m-0 text-sm text-muted-foreground">
              Sin ejemplares registrados (posible recurso virtual).
            </p>
          ) : (
            <>
              <div className="mb-3.5 flex items-center gap-2 text-[0.98rem] font-semibold">
                {!hasAvailabilityData ? (
                  <span className="text-muted-foreground">Disponibilidad aún sin rastrear</span>
                ) : totalAvailable > 0 ? (
                  <span className="flex items-center gap-2 text-brand-soft-foreground">
                    <span aria-hidden="true" className="h-[9px] w-[9px] rounded-full bg-primary" />
                    {availableAtPrimary ? "Disponible en tu biblioteca" : "Disponible ahora"}
                  </span>
                ) : (
                  <span className="text-muted-foreground">Ningún ejemplar disponible</span>
                )}
              </div>
              <ul className="m-0 list-none divide-y divide-border p-0">
                {branches.map((branch) => {
                  const dist = distanceLabel(branch.code);
                  return (
                    <li
                      key={branch.code}
                      className="flex items-center justify-between gap-2.5 py-2.5"
                    >
                      <div className="min-w-0">
                        <p className="m-0 truncate text-sm text-foreground">
                          {branch.name}
                          {branch.code === primaryCode && (
                            <span className="ml-1.5 font-mono text-xs text-primary">
                              · tu biblioteca
                            </span>
                          )}
                        </p>
                        <p className="m-0 font-mono text-xs text-faint">
                          {[dist, `${branch.count} ejemplar${branch.count === 1 ? "" : "es"}`]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                      </div>
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
                  );
                })}
              </ul>
            </>
          )}
          <a
            href={record.source_url}
            target="_blank"
            rel="noreferrer"
            className="mt-4 block w-full rounded-lg border border-input bg-transparent px-3 py-2.5 text-center text-sm font-semibold text-foreground no-underline transition-colors hover:bg-muted"
          >
            Ver en el catálogo oficial ↗
          </a>
          <p className="m-0 pt-3 text-xs leading-normal text-faint">
            Disponibilidad según el último rastreo del espejo, no en vivo contra el OPAC.
          </p>
        </section>
      </div>

      {/* ── Right: the ficha ── */}
      <div className="min-w-0">
        <p className="eyebrow mb-3.5">Ficha del catálogo · RBPA</p>
        <h1 className="m-0 font-serif text-[2.5rem] font-bold leading-[1.06] tracking-tight [text-wrap:balance]">
          {record.title}
        </h1>
        {record.subtitle != null && record.subtitle.length > 0 && (
          <p className="mb-0 mt-2 font-serif text-xl italic text-muted-foreground">
            {record.subtitle}
          </p>
        )}
        {record.authors.length > 0 && (
          <p className="mb-0 mt-3 text-[1.1rem] text-muted-foreground">
            {record.authors.join(" · ")}
          </p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {/* Público + forma double as filters: each jumps to /browse scoped
              to that audience / literary form. */}
          <a href={browseHref({ audience: record.audience })} className="inline-flex no-underline">
            <Badge variant="secondary">{audienceLabel(record.audience)}</Badge>
          </a>
          <a
            href={browseHref({ literaryForm: record.literary_form })}
            className="inline-flex no-underline"
          >
            <Badge variant="secondary">{formLabel(record.literary_form)}</Badge>
          </a>
          {!inDefaultScope(record.audience, record.literary_form) && (
            <span className="text-xs text-faint">· fuera del catálogo literario por defecto</span>
          )}
        </div>

        {meta.length > 0 && (
          <div className="my-7 grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2">
            {meta.map(({ k, v }) => (
              <div key={k} className="bg-card px-5 py-3.5">
                <p className="m-0 mb-1 font-mono text-[0.68rem] uppercase tracking-[0.14em] text-faint">
                  {k}
                </p>
                <p className="m-0 text-[0.95rem] font-medium text-foreground">{v}</p>
              </div>
            ))}
          </div>
        )}

        {(record.authors.length > 0 || record.genre !== "unknown") && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-faint">Explorar:</span>
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

        {record.subjects.length > 0 && (
          <section className="mt-7">
            <p className="eyebrow mb-3">Materias</p>
            <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
              {record.subjects.map((subject) => (
                <li key={subject}>
                  <span className="inline-flex rounded-full border border-border bg-muted px-3.5 py-1.5 text-[0.84rem] text-muted-foreground">
                    {subject}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <SimilarStrip titn={record.titn} apiBaseUrl={apiBaseUrl} />
      </div>
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
    <section className="mt-9 border-t border-border pt-7">
      <h2 className="m-0 mb-4 font-serif text-xl font-semibold tracking-tight">Más como este</h2>
      <ul className="m-0 grid list-none grid-cols-2 gap-x-4 gap-y-6 p-0 sm:grid-cols-4">
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
      className="group flex h-full flex-col gap-2.5 no-underline transition-transform hover:-translate-y-0.5"
    >
      <div className="overflow-hidden rounded-md shadow-cover">
        {coverSrc !== null ? (
          <img src={coverSrc} alt="" loading="lazy" className="aspect-[0.66] w-full object-cover" />
        ) : (
          <Cover title={record.title} author={author ?? undefined} />
        )}
      </div>
      <div className="min-w-0 space-y-0.5">
        <h3 className="line-clamp-2 font-serif text-sm font-semibold leading-snug text-foreground">
          {record.title}
        </h3>
        {author !== null && <p className="m-0 truncate text-xs text-muted-foreground">{author}</p>}
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
