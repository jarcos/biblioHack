import { z } from "zod";

/**
 * Catalog API client — typed mirrors of the FastAPI Pydantic schemas in
 * `backend/src/bibliohack/catalog/interfaces/http/schemas.py`. Zod is
 * our runtime contract: if the backend ever drifts, the parse fails
 * loudly here instead of corrupting state downstream.
 *
 * Endpoints currently mirrored:
 *   GET /catalog/records/{titn}   → CatalogRecord | 404
 *   GET /catalog/search?q=…       → SearchResponse
 */

// ── Schemas (kept in sync with backend manually until OpenAPI codegen) ──

/**
 * Literary profile (see backend `catalog/domain/literary_profile.py`).
 * `.catch("unknown")` makes both axes resilient: a missing field (older
 * backend) or an unexpected value degrades to `unknown` rather than failing
 * the whole parse — `unknown` is a first-class, in-scope value anyway.
 */
export const AUDIENCES = ["adult", "youth", "children", "unknown"] as const;
export type Audience = (typeof AUDIENCES)[number];
export const AudienceSchema = z.enum(AUDIENCES).catch("unknown");

export const LITERARY_FORMS = ["literary", "nonfiction", "unknown"] as const;
export type LiteraryForm = (typeof LITERARY_FORMS)[number];
export const LiteraryFormSchema = z.enum(LITERARY_FORMS).catch("unknown");

/** Search scope — mirrors the backend `SearchScope` query param. */
export type SearchScope = "literary" | "all";

/** Search ranking mode — mirrors the backend `SearchMode` query param.
 * `keyword` is FTS; `semantic` ranks by BGE-M3 vector similarity; `hybrid`
 * fuses both rankings with Reciprocal Rank Fusion. */
export type SearchMode = "keyword" | "semantic" | "hybrid";

/** Latest availability of a copy (mirrors backend `AvailabilityStatus`). */
export const AVAILABILITY_STATUSES = [
  "available",
  "loaned",
  "reserved",
  "unavailable",
  "unknown",
] as const;
export type AvailabilityStatus = (typeof AVAILABILITY_STATUSES)[number];
export const AvailabilityStatusSchema = z.enum(AVAILABILITY_STATUSES).catch("unknown");

/** Cover state (mirrors backend `CoverSchema`). `url` is set only when
 * resolved; the UI renders the image when present, a placeholder otherwise.
 * `.catch(null)` keeps a malformed cover from failing the whole record parse. */
export const COVER_STATUSES = ["resolved", "nofound", "pending", "failed", "unknown"] as const;
export type CoverStatus = (typeof COVER_STATUSES)[number];
export const CoverStatusSchema = z.enum(COVER_STATUSES).catch("unknown");

export const CoverSchema = z.object({
  status: CoverStatusSchema,
  source: z.string().catch("unknown"),
  url: z.string().nullable().optional(),
});
export type Cover = z.infer<typeof CoverSchema>;

export const CopySchema = z.object({
  branch_code: z.string(),
  branch_name: z.string(),
  signature: z.string().nullable().optional(),
  status: AvailabilityStatusSchema,
  due_back_at: z.string().nullable().optional(),
});

export const CatalogRecordSchema = z.object({
  titn: z.number().int(),
  title: z.string(),
  subtitle: z.string().nullable().optional(),
  document_type: z.string().nullable().optional(),
  language: z.string().nullable().optional(),
  pub_year: z.number().int().nullable().optional(),
  publisher: z.string().nullable().optional(),
  classification: z.string().nullable().optional(),
  audience: AudienceSchema,
  literary_form: LiteraryFormSchema,
  authors: z.array(z.string()),
  subjects: z.array(z.string()),
  isbns: z.array(z.string()),
  copies: z.array(CopySchema),
  source_url: z.string(),
  cover: CoverSchema.nullable().optional().catch(null),
});
export type CatalogRecord = z.infer<typeof CatalogRecordSchema>;

export const CatalogRecordSummarySchema = z.object({
  titn: z.number().int(),
  title: z.string(),
  authors: z.array(z.string()),
  publisher: z.string().nullable().optional(),
  pub_year: z.number().int().nullable().optional(),
  copies_count: z.number().int().nonnegative(),
  audience: AudienceSchema,
  literary_form: LiteraryFormSchema,
  available_count: z.number().int().nonnegative().catch(0),
  cover: CoverSchema.nullable().optional().catch(null),
});
export type CatalogRecordSummary = z.infer<typeof CatalogRecordSummarySchema>;

export const SearchResponseSchema = z.object({
  query: z.string(),
  /** Effective ranking used. May differ from the requested mode when semantic
   * search is unavailable (no embedder configured) → backend falls back to
   * keyword and reports it here. `.catch("keyword")` tolerates an older backend
   * that doesn't yet send the field. */
  mode: z.enum(["keyword", "semantic", "hybrid"]).catch("keyword"),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
  has_more: z.boolean(),
  items: z.array(CatalogRecordSummarySchema),
});
export type SearchResponse = z.infer<typeof SearchResponseSchema>;

/** Mirrors backend `SimilarResponseSchema` ("más como este"). */
export const SimilarResponseSchema = z.object({
  titn: z.number().int(),
  items: z.array(CatalogRecordSummarySchema),
});
export type SimilarResponse = z.infer<typeof SimilarResponseSchema>;

// ── Bookshelf (reading history) ──────────────────────────────────────

/** One logged book; `match` is the catalogue projection when resolved. */
export const ShelfEntrySchema = z.object({
  source_book_id: z.string(),
  title: z.string(),
  author: z.string().nullable().optional(),
  isbn_13: z.string().nullable().optional(),
  rating: z.number().int().min(1).max(5).nullable().optional(),
  date_read: z.string().nullable().optional(),
  matched_via: z.string().catch("none"),
  match: CatalogRecordSummarySchema.nullable().optional().catch(null),
});
export type ShelfEntry = z.infer<typeof ShelfEntrySchema>;

export const ShelfCountsSchema = z.object({
  total: z.number().int().nonnegative(),
  matched: z.number().int().nonnegative(),
  read: z.number().int().nonnegative(),
  currently_reading: z.number().int().nonnegative(),
  to_read: z.number().int().nonnegative(),
});

/** Mirrors backend `ShelfResponseSchema` — the whole shelf grouped. */
export const ShelfResponseSchema = z.object({
  counts: ShelfCountsSchema,
  read: z.array(ShelfEntrySchema),
  currently_reading: z.array(ShelfEntrySchema),
  to_read: z.array(ShelfEntrySchema),
});
export type ShelfResponse = z.infer<typeof ShelfResponseSchema>;

// ── Errors ───────────────────────────────────────────────────────────

/**
 * Thrown when the backend returns a recognised non-2xx status. The caller
 * gets the HTTP status + the FastAPI `detail` string when present, so the
 * UI can distinguish a 404 (record missing) from a 422 (bad input) from a
 * 5xx (server unhealthy) without parsing strings.
 */
export class CatalogApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`Catalog API ${status}: ${detail}`);
    this.name = "CatalogApiError";
  }
}

// ── Endpoints ────────────────────────────────────────────────────────

export interface SearchParams {
  query: string;
  limit?: number;
  offset?: number;
  /**
   * `literary` (backend default: adult literature, all genres) or `all`
   * (whole mirror). Omitted from the request when undefined so the default
   * stays server-side and the URL stays clean.
   */
  scope?: SearchScope;
  /**
   * `keyword` (backend default: FTS), `semantic` (BGE-M3 vector KNN) or
   * `hybrid` (RRF fusion of both). Omitted when undefined so the
   * server-side default holds.
   */
  mode?: SearchMode;
}

/**
 * `GET /catalog/search?q=…`. Empty / whitespace-only `query` is rejected
 * by the backend (HTTP 422); the caller is expected to gate the call,
 * but we don't pre-validate here.
 */
export async function searchCatalog(
  apiBaseUrl: string,
  { query, limit, offset, scope, mode }: SearchParams,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const url = new URL("/catalog/search", apiBaseUrl);
  url.searchParams.set("q", query);
  if (limit !== undefined) url.searchParams.set("limit", String(limit));
  if (offset !== undefined) url.searchParams.set("offset", String(offset));
  if (scope !== undefined) url.searchParams.set("scope", scope);
  if (mode !== undefined) url.searchParams.set("mode", mode);

  const response = await fetch(url.toString(), {
    headers: { Accept: "application/json" },
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) {
    throw new CatalogApiError(response.status, await readDetail(response));
  }
  const json: unknown = await response.json();
  return SearchResponseSchema.parse(json);
}

/**
 * `GET /catalog/records/{titn}/similar`. Returns the nearest records by
 * embedding ("más como este"); `items` is empty when the record isn't
 * embedded yet, in which case the UI hides the strip.
 */
export async function fetchSimilar(
  apiBaseUrl: string,
  titn: number,
  limit?: number,
  signal?: AbortSignal,
): Promise<SimilarResponse> {
  const url = new URL(`/catalog/records/${titn}/similar`, apiBaseUrl);
  if (limit !== undefined) url.searchParams.set("limit", String(limit));

  const response = await fetch(url.toString(), {
    headers: { Accept: "application/json" },
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) {
    throw new CatalogApiError(response.status, await readDetail(response));
  }
  const json: unknown = await response.json();
  return SimilarResponseSchema.parse(json);
}

/**
 * `GET /catalog/records/{titn}`. Returns the full bibliographic record
 * + copies, or throws CatalogApiError(404) when the TITN isn't in the
 * mirror yet.
 */
export async function fetchRecord(
  apiBaseUrl: string,
  titn: number,
  signal?: AbortSignal,
): Promise<CatalogRecord> {
  const url = new URL(`/catalog/records/${titn}`, apiBaseUrl);
  const response = await fetch(url.toString(), {
    headers: { Accept: "application/json" },
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) {
    throw new CatalogApiError(response.status, await readDetail(response));
  }
  const json: unknown = await response.json();
  return CatalogRecordSchema.parse(json);
}

/**
 * `GET /shelf`. Returns the reader's bookshelf grouped by shelf, each book
 * enriched with its catalogue match (cover + availability) when resolved.
 */
export async function fetchShelf(apiBaseUrl: string, signal?: AbortSignal): Promise<ShelfResponse> {
  // Served at /api/shelf (the tunnel routes /api/* to the backend); a bare
  // /shelf is the frontend page route, not the API. Auth-gated since the
  // identity milestone: the session cookie must travel (`include` matters
  // in dev, where the dev server and API are different origins).
  const url = new URL("/api/shelf", apiBaseUrl);
  const response = await fetch(url.toString(), {
    headers: { Accept: "application/json" },
    credentials: "include",
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) {
    throw new CatalogApiError(response.status, await readDetail(response));
  }
  const json: unknown = await response.json();
  return ShelfResponseSchema.parse(json);
}

// ── Shelf imports (background jobs) ──────────────────────────────────

/** Mirrors backend `ImportJobSchema` — polled while the worker matches. */
export const ImportJobSchema = z.object({
  id: z.string(),
  status: z.enum(["queued", "running", "done", "failed"]).catch("queued"),
  filename: z.string().nullable().optional(),
  total: z.number().int().nullable().optional(),
  inserted: z.number().int().nullable().optional(),
  updated: z.number().int().nullable().optional(),
  matched_isbn: z.number().int().nullable().optional(),
  matched_title_author: z.number().int().nullable().optional(),
  unmatched: z.number().int().nullable().optional(),
  error: z.string().nullable().optional(),
});
export type ImportJob = z.infer<typeof ImportJobSchema>;

/** `POST /api/shelf/import` — upload a Goodreads CSV; returns the queued job. */
export async function uploadShelfCsv(apiBaseUrl: string, file: File): Promise<ImportJob> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(new URL("/api/shelf/import", apiBaseUrl).toString(), {
    method: "POST",
    body: form,
    credentials: "include",
  });
  if (!response.ok) {
    throw new CatalogApiError(response.status, await readDetail(response));
  }
  const json: unknown = await response.json();
  return ImportJobSchema.parse(json);
}

/** `GET /api/shelf/import/{id}` — job status (404 for other users' jobs). */
export async function fetchImportJob(
  apiBaseUrl: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<ImportJob> {
  const response = await fetch(new URL(`/api/shelf/import/${jobId}`, apiBaseUrl).toString(), {
    headers: { Accept: "application/json" },
    credentials: "include",
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) {
    throw new CatalogApiError(response.status, await readDetail(response));
  }
  const json: unknown = await response.json();
  return ImportJobSchema.parse(json);
}

// ── helpers ──────────────────────────────────────────────────────────

async function readDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof (body as { detail: unknown }).detail === "string"
    ) {
      return (body as { detail: string }).detail;
    }
  } catch {
    /* response wasn't JSON — fall through to the status text */
  }
  return response.statusText || `HTTP ${response.status}`;
}
