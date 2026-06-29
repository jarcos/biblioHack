import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { AvailabilityAnchor, BranchCoord } from "@/lib/availability";
import { fetchBranches, fetchMyBranches } from "@infrastructure/api/branches";

/**
 * Client-side anchor + branch directory for the library-aware availability
 * badge. Resolves the reader's anchor (their primary library's public coords,
 * or a device GPS fix) and the code→coordinates map the badge needs — all in
 * the browser, so the reader's location never leaves the device (design D11).
 *
 * Persistence (localStorage, this device only):
 *  - radius selector (10/25/50 km, default 25);
 *  - the last GPS fix (so other pages reuse it without re-prompting);
 *  - whether the auto-prompt was dismissed/denied (so we don't nag).
 */

const RADIUS_KEY = "bh.availability.radiusKm";
const GEO_KEY = "bh.availability.geo";
const GEO_DISMISSED_KEY = "bh.availability.geoDismissed";

export const DEFAULT_RADIUS_KM = 25;
export const RADIUS_OPTIONS = [10, 25, 50] as const;

// A GPS fix older than this is re-requested rather than trusted.
const GEO_MAX_AGE_MS = 12 * 60 * 60 * 1000;

interface PersistedGeo {
  lat: number;
  lng: number;
  ts: number;
}

export interface AvailabilityContext {
  /** code → coordinates, from `/api/branches` (cached). Empty until loaded. */
  branches: ReadonlyMap<string, BranchCoord>;
  /** Where "nearby" is measured from, or null when there's no anchor yet. */
  anchor: AvailabilityAnchor;
  radiusKm: number;
  setRadiusKm: (km: number) => void;
  /** True when a "ver cerca de mí" action makes sense (no primary, geolocation available). */
  canLocate: boolean;
  locating: boolean;
  /** Manually trigger the GPS prompt (the "ver cerca de mí" affordance). */
  locate: () => void;
}

function readRadius(): number {
  if (typeof window === "undefined") return DEFAULT_RADIUS_KM;
  const raw = Number(window.localStorage.getItem(RADIUS_KEY));
  return (RADIUS_OPTIONS as readonly number[]).includes(raw) ? raw : DEFAULT_RADIUS_KM;
}

function readGeo(): PersistedGeo | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(GEO_KEY);
    if (raw === null) return null;
    const parsed = JSON.parse(raw) as PersistedGeo;
    if (typeof parsed.lat !== "number" || typeof parsed.lng !== "number") return null;
    if (Date.now() - parsed.ts > GEO_MAX_AGE_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function useAvailabilityContext(
  apiBaseUrl: string,
  options: { autoLocate?: boolean } = {},
): AvailabilityContext {
  const autoLocate = options.autoLocate ?? false;

  const { data: branchList } = useQuery({
    queryKey: ["branches-directory"],
    queryFn: ({ signal }) => fetchBranches(apiBaseUrl, signal),
    staleTime: 60 * 60_000, // branch coordinates are effectively static
  });

  // null = signed out / no follows; resolves to the primary (first follow).
  const { data: myCodes, isFetched: myCodesFetched } = useQuery({
    queryKey: ["my-branches"],
    queryFn: ({ signal }) => fetchMyBranches(apiBaseUrl, signal),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const [radiusKm, setRadiusState] = useState<number>(readRadius);
  const [geo, setGeo] = useState<PersistedGeo | null>(readGeo);
  const [locating, setLocating] = useState(false);

  const branches = useMemo<ReadonlyMap<string, BranchCoord>>(() => {
    const map = new Map<string, BranchCoord>();
    for (const b of branchList ?? []) map.set(b.code, { lat: b.lat, lng: b.lng });
    return map;
  }, [branchList]);

  const primaryCode = myCodes && myCodes.length > 0 ? myCodes[0] : null;

  const anchor = useMemo<AvailabilityAnchor>(() => {
    if (primaryCode != null) {
      const coords = branches.get(primaryCode);
      if (coords && coords.lat !== null && coords.lng !== null) {
        return { kind: "primary", code: primaryCode, lat: coords.lat, lng: coords.lng };
      }
    }
    if (geo !== null) return { kind: "gps", lat: geo.lat, lng: geo.lng };
    return null;
  }, [primaryCode, branches, geo]);

  const setRadiusKm = useCallback((km: number) => {
    setRadiusState(km);
    if (typeof window !== "undefined") window.localStorage.setItem(RADIUS_KEY, String(km));
  }, []);

  const requestGeo = useCallback((onDone?: () => void) => {
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      onDone?.();
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const fix: PersistedGeo = {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          ts: Date.now(),
        };
        setGeo(fix);
        setLocating(false);
        if (typeof window !== "undefined") {
          window.localStorage.setItem(GEO_KEY, JSON.stringify(fix));
          window.localStorage.removeItem(GEO_DISMISSED_KEY);
        }
        onDone?.();
      },
      () => {
        // Denied or failed: remember it so we don't auto-prompt again.
        setLocating(false);
        if (typeof window !== "undefined") {
          window.localStorage.setItem(GEO_DISMISSED_KEY, "1");
        }
        onDone?.();
      },
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: GEO_MAX_AGE_MS },
    );
  }, []);

  const locate = useCallback(() => requestGeo(), [requestGeo]);

  // Auto-prompt once on first visit for anchor-less readers (D-C): no primary,
  // no fresh fix, not previously dismissed. Waits until the follow lookup has
  // settled so we never prompt a signed-in follower.
  useEffect(() => {
    if (!autoLocate || !myCodesFetched) return;
    if (primaryCode != null || geo !== null) return;
    if (typeof window === "undefined") return;
    if (window.localStorage.getItem(GEO_DISMISSED_KEY) === "1") return;
    requestGeo();
  }, [autoLocate, myCodesFetched, primaryCode, geo, requestGeo]);

  const canLocate =
    primaryCode == null && typeof navigator !== "undefined" && "geolocation" in navigator;

  return { branches, anchor, radiusKm, setRadiusKm, canLocate, locating, locate };
}
