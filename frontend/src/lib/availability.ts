import { haversineKm } from "@infrastructure/api/branches";
import type { AvailabilityStatus } from "@infrastructure/api/catalog";

/**
 * Presentation helpers for a copy's availability status. Values mirror the
 * backend `AvailabilityStatus`; the `Badge` variants line up with the
 * `--status-*` colours in global.css. Both helpers are tolerant — an
 * unrecognised value reads as "Sin datos" / the neutral variant.
 */

export type StatusVariant = "available" | "loaned" | "reserved" | "unavailable" | "unknown";

const LABELS: Record<AvailabilityStatus, string> = {
  available: "Disponible",
  loaned: "Prestado",
  reserved: "Reservado",
  unavailable: "No disponible",
  unknown: "Sin datos",
};

const VARIANTS: Record<AvailabilityStatus, StatusVariant> = {
  available: "available",
  loaned: "loaned",
  reserved: "reserved",
  unavailable: "unavailable",
  unknown: "unknown",
};

export function availabilityLabel(status: string): string {
  return LABELS[status as AvailabilityStatus] ?? LABELS.unknown;
}

export function availabilityVariant(status: string): StatusVariant {
  return VARIANTS[status as AvailabilityStatus] ?? "unknown";
}

// ── Library-aware availability (the catalogue badge) ──────────────────
//
// All distance math is client-side (design D11: the reader's location never
// leaves the device). The backend returns each record's optimistically-
// available branch codes; here we intersect them with the within-radius branch
// set, anchored on either the reader's primary library (its public coords) or a
// device GPS fix, and turn that into a badge.

/** Where "nearby" is measured from. `null` = no anchor (anonymous, GPS not granted). */
export type AvailabilityAnchor =
  | { readonly kind: "primary"; readonly code: string; readonly lat: number; readonly lng: number }
  | { readonly kind: "gps"; readonly lat: number; readonly lng: number }
  | null;

/** Branch coordinates as served by `/api/branches` (may be ungeocoded → null). */
export interface BranchCoord {
  readonly lat: number | null;
  readonly lng: number | null;
}

/** The availability-bearing slice of a catalogue summary the badge needs. */
export interface AvailabilityItem {
  readonly available_count: number;
  readonly available_branch_codes: readonly string[];
  readonly available_at_primary?: boolean | null;
}

/** What the badge should render. `label === null` ⇒ render no pill. */
export interface AvailabilityView {
  readonly label: string | null;
  readonly variant: StatusVariant;
  /** Secondary "+N cercanas" pill, when the primary library has it AND there's more nearby. */
  readonly nearby: string | null;
  /** True only for anchor-less callers — the UI then offers a "ver cerca de mí" action. */
  readonly offerLocate: boolean;
}

function plural(n: number, singular: string, pluralForm: string): string {
  return `${n} ${n === 1 ? singular : pluralForm}`;
}

/**
 * How many distinct nearby branches hold an available copy: the available
 * branches within `radiusKm` of the anchor, excluding the anchor's own branch.
 * Branches we can't place (no coordinates) are skipped, never counted.
 */
export function countNearbyAvailable(
  availableBranchCodes: readonly string[],
  branches: ReadonlyMap<string, BranchCoord>,
  anchor: { readonly lat: number; readonly lng: number },
  radiusKm: number,
  excludeCode?: string | null,
): number {
  const within = new Set<string>();
  for (const code of availableBranchCodes) {
    if (code === excludeCode) continue;
    const branch = branches.get(code);
    if (!branch || branch.lat === null || branch.lng === null) continue;
    if (haversineKm(anchor, { lat: branch.lat, lng: branch.lng }) <= radiusKm) {
      within.add(code);
    }
  }
  return within.size;
}

/**
 * Turn a record's availability + the reader's anchor into a badge (D-F/D-G).
 *
 * States:
 *  - no anchor      → "N disp." (+ offer to locate), or nothing when N = 0.
 *  - at my library  → "Disponible en tu biblioteca" (+ "+N cercanas").
 *  - not at library, but nearby → "No en tu biblioteca · N cercanas"
 *                                 (GPS callers: "N bibliotecas cerca").
 *  - only elsewhere → "Disponible en la red".
 *  - nowhere        → no pill.
 */
export function describeAvailability(
  item: AvailabilityItem,
  anchor: AvailabilityAnchor,
  branches: ReadonlyMap<string, BranchCoord>,
  radiusKm: number,
): AvailabilityView {
  const codes = item.available_branch_codes ?? [];
  const networkCount = item.available_count ?? 0;

  if (anchor === null) {
    return {
      label: networkCount > 0 ? `${networkCount} disp.` : null,
      variant: "available",
      nearby: null,
      offerLocate: true,
    };
  }

  const primaryCode = anchor.kind === "primary" ? anchor.code : null;
  // Derive "at my library" from the codes + the known primary (uniform across
  // surfaces); fall back to the backend flag when the primary isn't known here.
  const atPrimary =
    primaryCode !== null ? codes.includes(primaryCode) : (item.available_at_primary ?? false);
  const nearby = countNearbyAvailable(codes, branches, anchor, radiusKm, primaryCode);

  if (atPrimary) {
    return {
      label: "Disponible en tu biblioteca",
      variant: "available",
      nearby: nearby > 0 ? `+${plural(nearby, "cercana", "cercanas")}` : null,
      offerLocate: false,
    };
  }
  if (nearby > 0) {
    const label =
      primaryCode !== null
        ? `No en tu biblioteca · ${plural(nearby, "cercana", "cercanas")}`
        : plural(nearby, "biblioteca cerca", "bibliotecas cerca");
    return { label, variant: "available", nearby: null, offerLocate: false };
  }
  if (networkCount > 0) {
    return { label: "Disponible en la red", variant: "unknown", nearby: null, offerLocate: false };
  }
  return { label: null, variant: "unknown", nearby: null, offerLocate: false };
}
