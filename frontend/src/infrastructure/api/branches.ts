import { z } from "zod";

/**
 * Branches API client — typed mirror of the FastAPI schemas in
 * `backend/src/bibliohack/holdings/interfaces/http/branches_router.py`
 * (Libraries milestone L1).
 *
 * The public list is unauthenticated; the per-user follow get/put ride the
 * session cookie, so they use `credentials: "include"` (required cross-port in
 * dev). The browser distance-sorts the list client-side — the user's location
 * never leaves the device (design D11).
 *
 * Endpoints:
 *   GET /api/branches      → { branches: Branch[] }   (public)
 *   GET /api/me/branches   → { codes: string[] }      (auth; 401 → null)
 *   PUT /api/me/branches   → { codes: string[] }      (auth)
 */

export const BranchSchema = z.object({
  code: z.string(),
  name: z.string(),
  municipality: z.string().nullable(),
  province: z.string().nullable(),
  lat: z.number().nullable(),
  lng: z.number().nullable(),
});
export type Branch = z.infer<typeof BranchSchema>;

const BranchListSchema = z.object({ branches: z.array(BranchSchema) });
const FollowedSchema = z.object({ codes: z.array(z.string()) });

export class BranchApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`Branches API ${status}: ${detail}`);
    this.name = "BranchApiError";
  }
}

/** `GET /api/branches` — every active branch (public, cacheable). */
export async function fetchBranches(apiBaseUrl: string, signal?: AbortSignal): Promise<Branch[]> {
  const response = await fetch(new URL("/api/branches", apiBaseUrl).toString(), {
    headers: { Accept: "application/json" },
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) throw new BranchApiError(response.status, await readDetail(response));
  const json: unknown = await response.json();
  return BranchListSchema.parse(json).branches;
}

/** `GET /api/me/branches` — the caller's followed codes, or null when not signed in. */
export async function fetchMyBranches(
  apiBaseUrl: string,
  signal?: AbortSignal,
): Promise<string[] | null> {
  const response = await fetch(new URL("/api/me/branches", apiBaseUrl).toString(), {
    headers: { Accept: "application/json" },
    credentials: "include",
    ...(signal ? { signal } : {}),
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new BranchApiError(response.status, await readDetail(response));
  const json: unknown = await response.json();
  return FollowedSchema.parse(json).codes;
}

/** `PUT /api/me/branches` — replace the follow set (order = preference). */
export async function setMyBranches(apiBaseUrl: string, codes: string[]): Promise<string[]> {
  const response = await fetch(new URL("/api/me/branches", apiBaseUrl).toString(), {
    method: "PUT",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    credentials: "include",
    body: JSON.stringify({ codes }),
  });
  if (!response.ok) throw new BranchApiError(response.status, await readDetail(response));
  const json: unknown = await response.json();
  return FollowedSchema.parse(json).codes;
}

/**
 * Great-circle distance in km (haversine) — for the client-side proximity sort.
 * Pure + exported so it's unit-testable without a browser.
 */
export function haversineKm(
  a: { lat: number; lng: number },
  b: { lat: number; lng: number },
): number {
  const R = 6371;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h = Math.sin(dLat / 2) ** 2 + Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

function toRad(deg: number): number {
  return (deg * Math.PI) / 180;
}

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
    /* not JSON — fall through */
  }
  return response.statusText || `HTTP ${response.status}`;
}
