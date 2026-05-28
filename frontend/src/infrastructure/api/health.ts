import { z } from "zod";

/**
 * Health/version endpoint contract.
 *
 * Mirrors `HealthResponse` in the FastAPI app. Until we generate types from the
 * OpenAPI doc in M1, we hand-write the Zod schema and let it be the source of
 * truth at runtime.
 */
export const HealthSchema = z.object({
  status: z.literal("ok"),
  version: z.string(),
});

export type Health = z.infer<typeof HealthSchema>;

export async function fetchHealth(apiBaseUrl: string): Promise<Health> {
  const url = new URL("/healthz", apiBaseUrl).toString();
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`/healthz returned ${response.status}`);
  }
  const json: unknown = await response.json();
  return HealthSchema.parse(json);
}
