import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Sparkles, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { useCallback, useEffect, useState, type ReactElement } from "react";

import { AvailabilityBadge } from "@/components/AvailabilityBadge";
import { Cover } from "@/components/Cover";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAvailabilityContext, type AvailabilityContext } from "@/lib/useAvailability";
import { fetchMyBranches } from "@infrastructure/api/branches";
import {
  fetchRecommendations,
  sendFeedback,
  type FeedbackSignal,
  type RecommendationItem,
} from "@infrastructure/api/recommendations";

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

  // One feedback press (chat-recs §D4). "No me interesa" / "no me gusta" drop
  // the card straight away — the server has busted the cache, so the batch
  // regenerates on the next visit; we don't refetch mid-scroll and yank the
  // grid out from under the reader. Likes stay put (the card acknowledges
  // itself). Fire-and-forget: a failed write just leaves the card in place.
  const handleSignal = useCallback(
    (recordId: string, signal: FeedbackSignal) => {
      void sendFeedback(apiBaseUrl, { recordId, signal }).catch(() => {
        /* best-effort: the next batch will still reflect a successful write */
      });
      if (signal === "dislike" || signal === "not_interested") {
        setItems((current) =>
          current === null ? current : current.filter((i) => i.record_id !== recordId),
        );
      }
    },
    [apiBaseUrl],
  );

  const toggle =
    followsBranches && reason === "ok" ? (
      <label className="flex cursor-pointer items-center gap-2.5 text-sm text-muted-foreground">
        <input
          type="checkbox"
          checked={nearby}
          onChange={(e) => setNearby(e.target.checked)}
          className="h-5 w-5 rounded-md border-input accent-primary"
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
      <ul className="m-0 grid list-none gap-5 p-0 sm:grid-cols-2">
        {items.map((item) => (
          <li key={item.record.titn}>
            <RecommendationCard
              item={item}
              apiBaseUrl={apiBaseUrl}
              availability={availability}
              onSignal={(signal) => handleSignal(item.record_id, signal)}
            />
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
    <div className="space-y-2 rounded-xl border border-border bg-card p-4 shadow-card">
      <p className="m-0 text-sm font-semibold text-foreground">Para empezar, según tu estantería</p>
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
  onSignal,
}: {
  item: RecommendationItem;
  apiBaseUrl: string;
  availability: AvailabilityContext;
  onSignal: (signal: FeedbackSignal) => void;
}): ReactElement {
  const { record } = item;
  const coverSrc = record.cover?.url ? `${apiBaseUrl}${record.cover.url}` : null;
  const affinity = Math.round(item.score * 100);

  // The card chrome (border/bg/shadow) lives on this wrapper so the feedback
  // bar can sit outside the <a> — a button can't legally nest inside an anchor,
  // and its click must never navigate to the record.
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-card transition-transform hover:-translate-y-0.5">
      <a
        href={`/record?titn=${record.titn}`}
        className="grid flex-1 cursor-pointer grid-cols-[88px_1fr] gap-[18px] p-5 no-underline"
      >
        <div className="self-start overflow-hidden rounded shadow-[0_8px_18px_-10px_rgba(0,0,0,.4)]">
          {coverSrc !== null ? (
            <img
              src={coverSrc}
              alt=""
              loading="lazy"
              className="aspect-[0.66] w-full object-cover"
            />
          ) : (
            <Cover title={record.title} author={record.authors[0]} />
          )}
        </div>
        <div className="flex min-w-0 flex-col">
          <h3 className="m-0 line-clamp-2 font-serif text-[1.1rem] font-semibold leading-snug tracking-tight text-foreground">
            {record.title}
          </h3>
          {record.authors.length > 0 && (
            <p className="m-0 mt-1.5 truncate font-mono text-xs text-faint">
              {record.authors.join(" · ")}
            </p>
          )}
          {item.rationale != null && (
            <p className="m-0 my-3 line-clamp-3 font-serif text-[0.95rem] italic leading-normal text-muted-foreground">
              «{item.rationale}»
            </p>
          )}
          <div className="mt-auto flex flex-col gap-2.5">
            <div className="flex items-center gap-3">
              <div
                className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
                role="img"
                aria-label={`Afinidad ${affinity}%`}
              >
                <div
                  className="h-full rounded-full bg-ocre"
                  style={{ width: `${Math.min(100, Math.max(0, affinity))}%` }}
                />
              </div>
              <span className="whitespace-nowrap font-mono text-[0.82rem] font-medium text-ocre">
                {affinity}% afín
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {record.available_count > 0 ? (
                <AvailabilityBadge
                  item={record}
                  anchor={availability.anchor}
                  branches={availability.branches}
                  radiusKm={availability.radiusKm}
                />
              ) : (
                <Badge variant="secondary">En catálogo</Badge>
              )}
            </div>
          </div>
        </div>
      </a>
      <FeedbackBar onSignal={onSignal} />
    </div>
  );
}

/**
 * Feedback bar (chat-recs P1, §D4): the reader's return channel on each card.
 * Positive signals (me gusta / más como esto) acknowledge in place; the
 * negative ones (no me gusta / no me interesa) drop the card, handled by the
 * parent. Icon-only, so every button carries an aria-label + title.
 */
function FeedbackBar({ onSignal }: { onSignal: (signal: FeedbackSignal) => void }): ReactElement {
  const [sent, setSent] = useState<FeedbackSignal | null>(null);
  const press = (signal: FeedbackSignal): void => {
    setSent(signal);
    onSignal(signal);
  };
  const positiveSent = sent === "like" || sent === "more_like_this";
  return (
    <div className="flex items-center gap-0.5 border-t border-border px-2 py-1.5">
      <FeedbackButton
        label="Me gusta"
        active={sent === "like"}
        disabled={positiveSent}
        onClick={() => press("like")}
      >
        <ThumbsUp className="h-4 w-4" aria-hidden="true" />
      </FeedbackButton>
      <FeedbackButton
        label="Más como esto"
        active={sent === "more_like_this"}
        disabled={positiveSent}
        onClick={() => press("more_like_this")}
      >
        <Sparkles className="h-4 w-4" aria-hidden="true" />
      </FeedbackButton>
      <span className="flex-1" />
      <FeedbackButton label="No me gusta" onClick={() => press("dislike")}>
        <ThumbsDown className="h-4 w-4" aria-hidden="true" />
      </FeedbackButton>
      <FeedbackButton label="No me interesa" onClick={() => press("not_interested")}>
        <X className="h-4 w-4" aria-hidden="true" />
      </FeedbackButton>
    </div>
  );
}

function FeedbackButton({
  label,
  active = false,
  disabled = false,
  onClick,
  children,
}: {
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: ReactElement;
}): ReactElement {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label={label}
      aria-pressed={active}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={`h-8 w-8 ${active ? "text-ocre" : "text-muted-foreground"}`}
    >
      {children}
    </Button>
  );
}
