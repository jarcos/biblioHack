import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useMemo, type ReactElement } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { availabilityLabel, availabilityVariant } from "@/lib/availability";
import { audienceLabel, formLabel, inDefaultScope } from "@/lib/literary";
import { CatalogApiError, fetchRecord, type CatalogRecord } from "@infrastructure/api/catalog";

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
        <RecordBody record={data} />
      ) : null}
    </article>
  );
}

function RecordBody({ record }: { record: CatalogRecord }): ReactElement {
  const meta = [
    record.authors.join(", ") || null,
    record.pub_year != null ? String(record.pub_year) : null,
    record.publisher ?? null,
    record.document_type ?? null,
  ].filter((part): part is string => part !== null);

  const branches = groupByBranch(record);
  const totalAvailable = branches.reduce((sum, b) => sum + b.available, 0);
  const branchesWithAvailable = branches.filter((b) => b.available > 0).length;
  const hasAvailabilityData = record.copies.some((c) => c.status !== "unknown");

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <h1 className="font-serif text-3xl font-semibold leading-tight tracking-tight">
          {record.title}
        </h1>
        {record.subtitle != null && record.subtitle.length > 0 && (
          <p className="text-lg text-muted-foreground">{record.subtitle}</p>
        )}
        {meta.length > 0 && <p className="text-sm text-muted-foreground">{meta.join(" · ")}</p>}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Badge variant="secondary">{audienceLabel(record.audience)}</Badge>
          <Badge variant="secondary">{formLabel(record.literary_form)}</Badge>
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
