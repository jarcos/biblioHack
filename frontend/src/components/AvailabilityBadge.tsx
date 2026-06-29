import type { ReactElement } from "react";

import { Badge } from "@/components/ui/badge";
import {
  describeAvailability,
  type AvailabilityAnchor,
  type AvailabilityItem,
  type BranchCoord,
} from "@/lib/availability";

/**
 * AvailabilityBadge — library-aware availability pill for a catalogue row.
 *
 * Renders "Disponible en tu biblioteca" / "+N cercanas" / "No en tu biblioteca
 * · N cercanas" / "Disponible en la red" / "N disp." depending on the reader's
 * anchor (see `describeAvailability`). For anchor-less readers it can offer a
 * "ver cerca de mí" action that triggers the GPS prompt. Renders nothing when
 * there's no availability to show.
 */

interface Props {
  item: AvailabilityItem;
  anchor: AvailabilityAnchor;
  branches: ReadonlyMap<string, BranchCoord>;
  radiusKm: number;
  onLocate?: () => void;
  canLocate?: boolean;
  locating?: boolean;
}

export function AvailabilityBadge({
  item,
  anchor,
  branches,
  radiusKm,
  onLocate,
  canLocate = false,
  locating = false,
}: Props): ReactElement | null {
  const view = describeAvailability(item, anchor, branches, radiusKm);
  const showLocate = view.offerLocate && canLocate && onLocate !== undefined;

  if (view.label === null && !showLocate) return null;

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {view.label !== null && <Badge variant={view.variant}>{view.label}</Badge>}
      {view.nearby !== null && <Badge variant="secondary">{view.nearby}</Badge>}
      {showLocate && (
        <button
          type="button"
          // These pills live inside card <a> links — don't navigate on click.
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onLocate?.();
          }}
          disabled={locating}
          className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground disabled:opacity-60"
        >
          {locating ? "Localizando…" : "Ver cerca de mí"}
        </button>
      )}
    </span>
  );
}

export default AvailabilityBadge;
