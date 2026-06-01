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
});
export type CatalogRecordSummary = z.infer<typeof CatalogRecordSummarySchema>;

export const SearchResponseSchema = z.object({
  query: z.string(),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
  has_more: z.boolean(),
  items: z.array(CatalogRecordSummarySchema),
});
export type SearchResponse = z.infer<typeof SearchResponseSchema>;

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
}

/**
 * `GET /catalog/search?q=…`. Empty / whitespace-only `query` is rejected
 * by the backend (HTTP 422); the caller is expected to gate the call,
 * but we don't pre-validate here.
 */
export async function searchCatalog(
  apiBaseUrl: string,
  { query, limit, offset, scope }: SearchParams,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const url = new URL("/catalog/search", apiBaseUrl);
  url.searchParams.set("q", query);
  if (limit !== undefined) url.searchParams.set("limit", String(limit));
  if (offset !== undefined) url.searchParams.set("offset", String(offset));
  if (scope !== undefined) url.searchParams.set("scope", scope);

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
