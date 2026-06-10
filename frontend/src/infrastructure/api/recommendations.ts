import { z } from "zod";

import { CatalogApiError, CatalogRecordSummarySchema } from "@infrastructure/api/catalog";

/**
 * Recommendations API client — mirrors
 * `backend/src/bibliohack/recommendations/interfaces/http/schemas.py`.
 * Auth-required: the session cookie must travel (`credentials: "include"`).
 */

export const RecommendationItemSchema = z.object({
  record: CatalogRecordSummarySchema,
  score: z.number(),
  rationale: z.string().nullable().optional(),
});
export type RecommendationItem = z.infer<typeof RecommendationItemSchema>;

export const RecommendationsResponseSchema = z.object({
  reason: z.enum(["ok", "empty_profile"]).catch("ok"),
  items: z.array(RecommendationItemSchema),
});
export type RecommendationsResponse = z.infer<typeof RecommendationsResponseSchema>;

/** `GET /api/recommendations` — the user's current batch (cached server-side). */
export async function fetchRecommendations(
  apiBaseUrl: string,
  signal?: AbortSignal,
): Promise<RecommendationsResponse> {
  const response = await fetch(new URL("/api/recommendations", apiBaseUrl).toString(), {
    headers: { Accept: "application/json" },
    credentials: "include",
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) {
    throw new CatalogApiError(response.status, response.statusText || `HTTP ${response.status}`);
  }
  const json: unknown = await response.json();
  return RecommendationsResponseSchema.parse(json);
}
