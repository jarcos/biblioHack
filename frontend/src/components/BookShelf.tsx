import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { type ReactElement } from "react";

import { Badge } from "@/components/ui/badge";
import { CatalogApiError, fetchShelf, type ShelfEntry } from "@infrastructure/api/catalog";

/**
 * BookShelf — the imported Goodreads library, grouped by shelf. Mounted as a
 * `client:only` island. Matched books link to their catalogue record and show
 * cover + live availability; unmatched books still appear (they re-match for
 * free as the catalogue grows).
 */

interface Props {
  apiBaseUrl: string;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: false, refetchOnWindowFocus: false },
  },
});

export function BookShelf({ apiBaseUrl }: Props): ReactElement {
  return (
    <QueryClientProvider client={queryClient}>
      <BookShelfInner apiBaseUrl={apiBaseUrl} />
    </QueryClientProvider>
  );
}

const SHELVES: { key: "read" | "currently_reading" | "to_read"; label: string }[] = [
  { key: "currently_reading", label: "Leyendo ahora" },
  { key: "read", label: "Leídos" },
  { key: "to_read", label: "Pendientes" },
];

function BookShelfInner({ apiBaseUrl }: Props): ReactElement {
  const { data, error, isFetching, isSuccess } = useQuery({
    queryKey: ["shelf"],
    queryFn: ({ signal }) => fetchShelf(apiBaseUrl, signal),
  });

  if (isFetching) {
    return <p className="text-sm text-muted-foreground">Cargando tu estantería…</p>;
  }
  if (error) {
    const message =
      error instanceof CatalogApiError
        ? `${error.status} · ${error.detail}`
        : error instanceof Error
          ? error.message
          : "Error desconocido";
    return <p className="text-sm text-destructive">✗ No se pudo cargar la estantería: {message}</p>;
  }
  if (!isSuccess) return <></>;

  if (data.counts.total === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Tu estantería está vacía. Importa tu biblioteca de Goodreads con{" "}
        <code>bibliohack shelf import</code>.
      </p>
    );
  }

  return (
    <div className="space-y-10">
      <p className="text-sm text-muted-foreground">
        {data.counts.total.toLocaleString("es-ES")} libros ·{" "}
        <strong className="text-foreground">{data.counts.matched}</strong> encontrados en el
        catálogo
      </p>
      {SHELVES.map(({ key, label }) => {
        const books = data[key];
        if (books.length === 0) return null;
        return (
          <section key={key} className="space-y-4">
            <h2 className="font-serif text-xl font-semibold tracking-tight">
              {label}{" "}
              <span className="text-sm font-normal text-muted-foreground">({books.length})</span>
            </h2>
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {books.map((book) => (
                <li key={book.source_book_id}>
                  <BookCard book={book} apiBaseUrl={apiBaseUrl} />
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function BookCard({ book, apiBaseUrl }: { book: ShelfEntry; apiBaseUrl: string }): ReactElement {
  const titn = book.match?.titn ?? null;
  const coverSrc = book.match?.cover?.url ? `${apiBaseUrl}${book.match.cover.url}` : null;
  const available = book.match?.available_count ?? 0;

  const inner = (
    <div className="flex h-full flex-col gap-2 rounded-md border border-border bg-card p-3 transition-colors hover:border-foreground/30 hover:bg-muted/40">
      {coverSrc !== null ? (
        <img
          src={coverSrc}
          alt=""
          loading="lazy"
          className="h-36 w-auto self-center rounded border border-border object-cover"
        />
      ) : (
        <div
          aria-hidden="true"
          className="flex h-36 items-center justify-center rounded border border-dashed border-border bg-muted/50 text-muted-foreground"
        >
          <span className="text-2xl">📚</span>
        </div>
      )}
      <div className="min-w-0 space-y-1">
        <h3 className="line-clamp-2 font-serif text-sm font-semibold leading-snug">{book.title}</h3>
        {book.author != null && book.author.length > 0 && (
          <p className="truncate text-xs text-muted-foreground">{book.author}</p>
        )}
        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          {book.rating != null && (
            <span className="text-xs text-amber-500" aria-label={`${book.rating} de 5`}>
              {"★".repeat(book.rating)}
              <span className="text-muted-foreground">{"★".repeat(5 - book.rating)}</span>
            </span>
          )}
          {titn !== null ? (
            available > 0 ? (
              <Badge variant="available">{available} disp.</Badge>
            ) : (
              <Badge variant="outline">en catálogo</Badge>
            )
          ) : (
            <Badge variant="secondary">no en catálogo</Badge>
          )}
        </div>
      </div>
    </div>
  );

  // Matched books link to their record page; unmatched are inert cards.
  return titn !== null ? (
    <a href={`/record?titn=${titn}`} className="block h-full">
      {inner}
    </a>
  ) : (
    inner
  );
}

export default BookShelf;
