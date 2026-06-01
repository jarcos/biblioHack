import type { AvailabilityStatus } from "@infrastructure/api/catalog";

/**
 * Presentation helpers for a copy's availability status. Values mirror the
 * backend `AvailabilityStatus`; the `Badge` variants line up with the
 * `--status-*` colours in global.css. Both helpers are tolerant — an
 * unrecognised value reads as "Sin datos" / the neutral variant.
 */

type StatusVariant = "available" | "loaned" | "reserved" | "unavailable" | "unknown";

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
