import { useQuery } from "@tanstack/react-query";
import { type ReactElement } from "react";

import { Cover } from "@/components/Cover";
import { Badge } from "@/components/ui/badge";
import { CatalogApiError, fetchShelf, type ShelfEntry } from "@infrastructure/api/catalog";

/**
 * BookShelf — the imported Goodreads library, grouped by shelf. Matched books
 * link to their catalogue record and show cover + live availability;
 * unmatched books still appear (they re-match for free as the catalogue
 * grows). Expects an ambient QueryClientProvider — ShelfPage owns the client
 * so the ["shelf"] query is shared with ShelfImport.
 */

interface Props {
  apiBaseUrl: string;
}

const SHELVES: { key: "read" | "currently_reading" | "to_read"; label: string }[] = [
  { key: "currently_reading", label: "Leyendo ahora" },
  { key: "read", label: "Leídos" },
  { key: "to_read", label: "Pendientes" },
];

export function BookShelf({ apiBaseUrl }: Props): ReactElement {
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
        Tu estantería está vacía. Exporta tu biblioteca de Goodreads (Export Library, CSV) y usa el
        botón «Importar CSV de Goodreads» de arriba.
      </p>
    );
  }

  return (
    <div className="space-y-12">
      <p className="m-0 -mt-4 font-mono text-[0.82rem] text-faint" role="status">
        <strong className="text-foreground">{data.counts.total.toLocaleString("es-ES")}</strong>{" "}
        libros · <strong className="text-foreground">{data.counts.matched}</strong> encontrados en
        el catálogo
      </p>
      {SHELVES.map(({ key, label }) => {
        const books = data[key];
        if (books.length === 0) return null;
        return (
          <section key={key} className="space-y-5">
            <div className="flex items-baseline gap-2.5">
              <h2 className="m-0 font-serif text-2xl font-semibold tracking-tight">{label}</h2>
              <span className="font-mono text-[0.9rem] text-faint">{books.length}</span>
            </div>
            <ul className="m-0 grid list-none grid-cols-2 gap-x-5 gap-y-7 p-0 sm:grid-cols-3 lg:grid-cols-4">
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
    <div className="flex h-full flex-col gap-3">
      <div className="overflow-hidden rounded-md shadow-cover">
        {coverSrc !== null ? (
          <img src={coverSrc} alt="" loading="lazy" className="aspect-[0.66] w-full object-cover" />
        ) : (
          <Cover title={book.title} author={book.author ?? undefined} />
        )}
      </div>
      <div className="min-w-0">
        <h3 className="line-clamp-2 font-serif text-[1.02rem] font-semibold leading-tight tracking-tight text-foreground">
          {book.title}
        </h3>
        {book.author != null && book.author.length > 0 && (
          <p className="mt-1 line-clamp-1 text-[0.85rem] text-muted-foreground">{book.author}</p>
        )}
      </div>
      <div className="mt-auto flex flex-wrap items-center gap-2.5">
        {book.rating != null && (
          <span
            className="text-[0.95rem] tracking-wider text-ocre"
            aria-label={`${book.rating} de 5`}
          >
            {"★".repeat(book.rating)}
            <span className="text-faint">{"☆".repeat(5 - book.rating)}</span>
          </span>
        )}
        {titn !== null ? (
          available > 0 ? (
            <Badge variant="available">{available} disp.</Badge>
          ) : (
            <Badge variant="secondary">en catálogo</Badge>
          )
        ) : (
          <Badge variant="unknown">no en catálogo</Badge>
        )}
      </div>
    </div>
  );

  // Matched books link to their record page; unmatched are inert cards.
  return titn !== null ? (
    <a
      href={`/record?titn=${titn}`}
      className="block h-full no-underline transition-transform hover:-translate-y-0.5"
    >
      {inner}
    </a>
  ) : (
    inner
  );
}

export default BookShelf;
