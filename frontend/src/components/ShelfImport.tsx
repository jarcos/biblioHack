import { useEffect, useRef, useState, type ReactElement } from "react";

import { Button } from "@/components/ui/button";
import {
  CatalogApiError,
  fetchImportJob,
  uploadShelfCsv,
  type ImportJob,
} from "@infrastructure/api/catalog";

/**
 * ShelfImport — upload a Goodreads "Export Library" CSV and watch the
 * background job until it resolves. Matching runs on the NAS worker, so
 * this polls `GET /api/shelf/import/{id}` every few seconds and reloads
 * the page when the import lands (simplest way to refresh the shelf
 * island's query cache on a static site).
 */

interface Props {
  apiBaseUrl: string;
}

const POLL_INTERVAL_MS = 3_000;

const UPLOAD_ERRORS: Record<number, string> = {
  413: "El archivo es demasiado grande (máximo 5 MB / 10.000 libros).",
  422: "Eso no parece un export de Goodreads. Usa «Export Library» en formato CSV.",
};

export function ShelfImport({ apiBaseUrl }: Props): ReactElement {
  const [job, setJob] = useState<ImportJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Poll while a job is queued/running.
  useEffect(() => {
    if (job === null || job.status === "done" || job.status === "failed") return;
    const timer = window.setInterval(() => {
      fetchImportJob(apiBaseUrl, job.id).then(
        (fresh) => {
          setJob(fresh);
          if (fresh.status === "done") {
            window.setTimeout(() => window.location.reload(), 1_500);
          }
        },
        () => undefined, // transient poll failure — try again next tick
      );
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [apiBaseUrl, job]);

  async function onFileChosen(file: File | undefined): Promise<void> {
    if (!file) return;
    setError(null);
    setBusy(true);
    try {
      setJob(await uploadShelfCsv(apiBaseUrl, file));
    } catch (err) {
      setError(
        err instanceof CatalogApiError
          ? (UPLOAD_ERRORS[err.status] ?? `Error ${err.status}: ${err.detail}`)
          : "No se pudo subir el archivo. Inténtalo de nuevo.",
      );
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  if (job !== null && (job.status === "queued" || job.status === "running")) {
    return (
      <p className="text-sm text-muted-foreground" role="status">
        ⏳ Importando {job.filename ?? "tu biblioteca"}… cruzando cada libro con el catálogo. Esto
        puede tardar unos minutos; puedes dejar la página abierta.
      </p>
    );
  }
  if (job !== null && job.status === "done") {
    return (
      <p className="text-sm" role="status">
        ✓ Importados <strong>{job.total ?? 0}</strong> libros ({job.matched_isbn ?? 0} por ISBN,{" "}
        {job.matched_title_author ?? 0} por título, {job.unmatched ?? 0} sin cruce). Recargando…
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={(e) => void onFileChosen(e.target.files?.[0])}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "Subiendo…" : "Importar CSV de Goodreads"}
        </Button>
        {job?.status === "failed" && (
          <span className="text-sm text-destructive">
            ✗ La importación falló{job.error ? `: ${job.error}` : ""}. Inténtalo de nuevo.
          </span>
        )}
      </div>
      {error && <p className="text-sm text-destructive">✗ {error}</p>}
    </div>
  );
}
