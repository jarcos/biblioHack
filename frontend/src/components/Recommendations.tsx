import { useEffect, useState, type ReactElement } from "react";

import { Badge } from "@/components/ui/badge";
import { fetchRecommendations, type RecommendationItem } from "@infrastructure/api/recommendations";

/**
 * Recommendations — the per-user "qué leer ahora" grid. The first request
 * after a shelf change generates the batch server-side (pgvector + LLM), so
 * it can take a few seconds; afterwards it's cached until the shelf moves.
 */

interface Props {
  apiBaseUrl: string;
}

export function Recommendations({ apiBaseUrl }: Props): ReactElement {
  const [items, setItems] = useState<RecommendationItem[] | null>(null);
  const [reason, setReason] = useState<"ok" | "empty_profile">("ok");
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchRecommendations(apiBaseUrl, controller.signal).then(
      (response) => {
        setItems(response.items);
        setReason(response.reason);
      },
      () => setError(true),
    );
    return () => controller.abort();
  }, [apiBaseUrl]);

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
      <p className="text-sm text-muted-foreground">
        Todavía nada que sugerir — el catálogo sigue indexándose. Vuelve a pasarte pronto.
      </p>
    );
  }

  return (
    <ul className="grid gap-4 sm:grid-cols-2">
      {items.map((item) => (
        <li key={item.record.titn}>
          <RecommendationCard item={item} apiBaseUrl={apiBaseUrl} />
        </li>
      ))}
    </ul>
  );
}

function RecommendationCard({
  item,
  apiBaseUrl,
}: {
  item: RecommendationItem;
  apiBaseUrl: string;
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
        <div className="flex flex-wrap gap-1.5 pt-1">
          {record.available_count > 0 ? (
            <Badge variant="available">{record.available_count} disp.</Badge>
          ) : (
            <Badge variant="outline">en catálogo</Badge>
          )}
          <Badge variant="secondary">{Math.round(item.score * 100)}% afín</Badge>
        </div>
      </div>
    </a>
  );
}
