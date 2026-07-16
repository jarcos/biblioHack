import { z } from "zod";

import { CatalogApiError, CatalogRecordSummarySchema } from "@infrastructure/api/catalog";

/**
 * Recommendations API client — mirrors
 * `backend/src/bibliohack/recommendations/interfaces/http/schemas.py`.
 * Auth-required: the session cookie must travel (`credentials: "include"`).
 */

export const RecommendationItemSchema = z.object({
  /** The catalogue record's id — echo it back to `sendFeedback` (§D4). */
  record_id: z.string(),
  record: CatalogRecordSummarySchema,
  score: z.number(),
  rationale: z.string().nullable().optional(),
});
export type RecommendationItem = z.infer<typeof RecommendationItemSchema>;

export const RecommendationsResponseSchema = z.object({
  reason: z.enum(["ok", "empty_profile"]).catch("ok"),
  /** True when the batch was inferred from the raw imported shelf (no
   * catalogue-matched books yet, §8.3.3) — weaker than taste-based recs, so
   * the UI labels it. `.catch(false)` tolerates an older backend. */
  cold_start: z.boolean().catch(false),
  /** Genre/topic chips inferred on a fresh cold-start batch ("detectamos que
   * te gusta…"); empty on a cache hit (not persisted) or for taste-based recs. */
  inferred_tastes: z.array(z.string()).catch([]),
  items: z.array(RecommendationItemSchema),
});
export type RecommendationsResponse = z.infer<typeof RecommendationsResponseSchema>;

/** The four feedback signals P1 exposes (chat-recs §D4). `read_rating` is P2. */
export const FEEDBACK_SIGNALS = ["like", "dislike", "more_like_this", "not_interested"] as const;
export type FeedbackSignal = (typeof FEEDBACK_SIGNALS)[number];

/** `POST /api/recommendations/feedback` — record one like/dislike/«más como
 * esto»/«no me interesa» on a recommended record. Writing the signal busts the
 * server-side cache (§D4), so the next `fetchRecommendations` regenerates. */
export async function sendFeedback(
  apiBaseUrl: string,
  input: { recordId: string; signal: FeedbackSignal; signal_?: AbortSignal },
): Promise<void> {
  const response = await fetch(new URL("/api/recommendations/feedback", apiBaseUrl).toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    credentials: "include",
    body: JSON.stringify({ record_id: input.recordId, signal: input.signal }),
    ...(input.signal_ ? { signal: input.signal_ } : {}),
  });
  if (!response.ok) {
    throw new CatalogApiError(response.status, response.statusText || `HTTP ${response.status}`);
  }
}

/** `GET /api/recommendations` — the user's current batch (cached server-side).
 *
 * `nearby` (L4) hard-filters to titles borrowable in the user's followed
 * branches; omitted/false leaves the library-aware boost in place. */
export async function fetchRecommendations(
  apiBaseUrl: string,
  opts: { nearby?: boolean; signal?: AbortSignal } = {},
): Promise<RecommendationsResponse> {
  const url = new URL("/api/recommendations", apiBaseUrl);
  if (opts.nearby) url.searchParams.set("nearby", "true");
  const response = await fetch(url.toString(), {
    headers: { Accept: "application/json" },
    credentials: "include",
    ...(opts.signal ? { signal: opts.signal } : {}),
  });
  if (!response.ok) {
    throw new CatalogApiError(response.status, response.statusText || `HTTP ${response.status}`);
  }
  const json: unknown = await response.json();
  return RecommendationsResponseSchema.parse(json);
}
