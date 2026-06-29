import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactElement } from "react";

import { AvailabilityBadge } from "@/components/AvailabilityBadge";
import { Badge } from "@/components/ui/badge";
import { useAvailabilityContext, type AvailabilityContext } from "@/lib/useAvailability";
import { fetchMyBranches } from "@infrastructure/api/branches";
import { fetchRecommendations, type RecommendationItem } from "@infrastructure/api/recommendations";

/**
 * Recommendations — the per-user "qué leer ahora" grid. The first request
 * after a shelf change generates the batch server-side (pgvector + LLM), so
 * it can take a few seconds; afterwards it's cached until the shelf moves.
 *
 * Library-aware (L4): titles borrowable in followed branches are boosted
 * server-side; users who follow branches also get a "solo en mis bibliotecas"
 * toggle that hard-filters to nearby availability.
 */

interface Props {
  apiBaseUrl: string;
}

// Own QueryClient so the availability hook (react-query) works inside this
// island, which otherwise manages its own fetch state.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: false, refetchOnWindowFocus: false },
  },
});

export function Recommendations({ apiBaseUrl }: Props): ReactElement {
  return (
    <QueryClientProvider client={queryClient}>
      <RecommendationsInner apiBaseUrl={apiBaseUrl} />
    </QueryClientProvider>
  );
}

function RecommendationsInner({ apiBaseUrl }: Props): ReactElement {
  const availability = useAvailabilityContext(apiBaseUrl);
  const [items, setItems] = useState<RecommendationItem[] | null>(null);
  const [reason, setReason] = useState<"ok" | "empty_profile">("ok");
  const [coldStart, setColdStart] = useState(false);
  const [tastes, setTastes] = useState<string[]>([]);
  const [error, setError] = useState(false);
  const [nearby, setNearby] = useState(false);
  const [followsBranches, setFollowsBranches] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchMyBranches(apiBaseUrl, controller.signal).then(
      (codes) => setFollowsBranches(codes !== null && codes.length > 0),
      () => setFollowsBranches(false),
    );
    return () => controller.abort();
  }, [apiBaseUrl]);

  useEffect(() => {
    const controller = new AbortController();
    setItems(null);
    setError(false);
    fetchRecommendations(apiBaseUrl, { nearby, signal: controller.signal }).then(
      (response) => {
        setItems(response.items);
        setReason(response.reason);
        setColdStart(response.cold_start);
        setTastes(response.inferred_tastes);
      },
      () => setError(true),
    );
    return () => controller.abort();
  }, [apiBaseUrl, nearby]);

  const toggle =
    followsBranches && reason === "ok" ? (
      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <input
          type="checkbox"
          checked={nearby}
          onChange={(e) => setNearby(e.target.checked)}
          className="h-4 w-4 rounded border-border accent-primary"
        />
        Solo en mis bibliotecas
      </label>
    ) : null;

  if (error) {
    return (
      <p className="text-sm text-destructive">
        ✗ No se pudieron cargar las recomendaciones. Inténtalo de nuevo en un momento.
      </p>
    );
  }
  if (items === null) {
    return (
      <p className="text-sm text-muted-foreground" role="status">
        Preparando recomendaciones… la primera vez puede tardar unos segundos.
      </p>
    );
  }
  if (reason === "empty_profile") {
    return (
      <p className="text-sm text-muted-foreground">
        Aún no hay base para recomendar: importa tu biblioteca en{" "}
        <a href="/shelf" className="text-foreground underline underline-offset-4">
          tu estantería
        </a>{" "}
        y, cuando algún libro cruce con el catálogo, aquí aparecerán sugerencias.
      </p>
    );
  }
  if (items.length === 0) {
    return (
      <div className="space-y-3">
        {coldStart && <ColdStartBanner tastes={tastes} />}
        {toggle}
        <p className="text-sm text-muted-foreground">
          {nearby
            ? "Ninguna sugerencia disponible ahora mismo en tus bibliotecas. Prueba a quitar el filtro o a seguir más bibliotecas."
            : "Todavía nada que sugerir — el catálogo sigue indexándose. Vuelve a pasarte pronto."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {coldStart && <ColdStartBanner tastes={tastes} />}
      {toggle}
      <ul className="grid gap-4 sm:grid-cols-2">
        {items.map((item) => (
          <li key={item.record.titn}>
            <RecommendationCard item={item} apiBaseUrl={apiBaseUrl} availability={availability} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Cold-start banner (§8.3.3): when there are no catalogue-matched books yet,
 * the batch is inferred from the raw imported titles — weaker than taste-based
 * recs, so we say so plainly and show the inferred tastes as chips, with a
 * note that recs sharpen as the shelf matches the catalogue.
 */
function ColdStartBanner({ tastes }: { tastes: readonly string[] }): ReactElement {
  return (
    <div className="space-y-2 rounded-md border border-border bg-muted/40 p-4">
      <p className="text-sm font-medium text-foreground">Para empezar, según tu estantería</p>
      {tastes.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-sm text-muted-foreground">Detectamos que te gusta:</span>
          {tastes.map((taste) => (
            <Badge key={taste} variant="secondary">
              {taste}
            </Badge>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Estas sugerencias se afinarán a medida que emparejemos tus libros con el catálogo.
      </p>
    </div>
  );
}

function RecommendationCard({
  item,
  apiBaseUrl,
  availability,
}: {
  item: RecommendationItem;
  apiBaseUrl: string;
  availability: AvailabilityContext;
}): ReactElement {
  const { record } = item;
  const coverSrc = record.cover?.url ? `${apiBaseUrl}${record.cover.url}` : null;

  return (
    <a
      href={`/record?titn=${record.titn}`}
      className="flex h-full gap-4 rounded-md border border-border bg-card p-4 transition-colors hover:border-foreground/30 hover:bg-muted/40"
    >
      {coverSrc !== null ? (
        <img
          src={coverSrc}
          alt=""
          loading="lazy"
          className="h-28 w-auto shrink-0 self-start rounded border border-border object-cover"
        />
      ) : (
        <div
          aria-hidden="true"
          className="flex h-28 w-20 shrink-0 items-center justify-center rounded border border-dashed border-border bg-muted/50 text-2xl"
        >
          📚
        </div>
      )}
      <div className="min-w-0 space-y-1.5">
        <h3 className="line-clamp-2 font-serif text-base font-semibold leading-snug">
          {record.title}
        </h3>
        {record.authors.length > 0 && (
          <p className="truncate text-xs text-muted-foreground">{record.authors.join(" · ")}</p>
        )}
        {item.rationale != null && (
          <p className="line-clamp-3 text-sm italic text-muted-foreground">«{item.rationale}»</p>
        )}
        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          {record.available_count > 0 ? (
            <AvailabilityBadge
              item={record}
              anchor={availability.anchor}
              branches={availability.branches}
              radiusKm={availability.radiusKm}
            />
          ) : (
            <Badge variant="outline">en catálogo</Badge>
          )}
          <Badge variant="secondary">{Math.round(item.score * 100)}% afín</Badge>
        </div>
      </div>
    </a>
  );
}
