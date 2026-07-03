import { useMemo, useState, type ReactElement } from "react";

import { Button } from "@/components/ui/button";
import { haversineKm, type Branch } from "@infrastructure/api/branches";

/**
 * BranchSelect — the controlled selection UI shared by the /account «Mis
 * bibliotecas» picker (LibraryPicker) and the optional picker at signup
 * (RegisterForm, L5).
 *
 * Presentational only: the parent owns the branch list and the selected set
 * (and any persistence). This component renders the removable chips, the
 * type-ahead over name/municipality, the optional proximity sort (device
 * geolocation never leaves the browser — design D11/D12), and the candidate
 * list, calling `onToggle` when the user adds/removes a branch.
 */

interface Props {
  branches: Branch[];
  selected: string[];
  onToggle: (code: string) => void;
}

const MAX_VISIBLE = 40;

type Coords = { lat: number; lng: number };

function normalize(s: string): string {
  // Strip combining diacritical marks (U+0300–U+036F) for accent-insensitive
  // matching, mirroring the catalogue's Spanish search behaviour.
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "");
}

function distance(b: Branch, coords: Coords): number {
  if (b.lat === null || b.lng === null) return Number.POSITIVE_INFINITY;
  return haversineKm(coords, { lat: b.lat, lng: b.lng });
}

export function BranchSelect({ branches, selected, onToggle }: Props): ReactElement {
  const [query, setQuery] = useState("");
  const [coords, setCoords] = useState<Coords | null>(null);
  const [geoState, setGeoState] = useState<"idle" | "locating" | "denied">("idle");

  const byCode = useMemo(() => new Map(branches.map((b) => [b.code, b])), [branches]);

  function useMyLocation(): void {
    if (!("geolocation" in navigator)) {
      setGeoState("denied");
      return;
    }
    setGeoState("locating");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setGeoState("idle");
      },
      () => setGeoState("denied"),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 },
    );
  }

  // Filtered + sorted candidate list (selected handled separately as chips).
  const visible = useMemo(() => {
    const q = normalize(query.trim());
    let list = branches.filter((b) => !selected.includes(b.code));
    if (q) {
      list = list.filter(
        (b) => normalize(b.name).includes(q) || normalize(b.municipality ?? "").includes(q),
      );
    }
    if (coords) {
      list = [...list].sort((a, b) => distance(a, coords) - distance(b, coords));
    } else {
      list = [...list].sort((a, b) => a.name.localeCompare(b.name, "es"));
    }
    return list.slice(0, MAX_VISIBLE);
  }, [branches, selected, query, coords]);

  return (
    <div className="space-y-4">
      {/* Selected libraries as removable chips. */}
      {selected.length > 0 && (
        <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
          {selected.map((code) => {
            const b = byCode.get(code);
            return (
              <li key={code}>
                <button
                  type="button"
                  onClick={() => onToggle(code)}
                  className="inline-flex items-center gap-2 rounded-full bg-brand-soft px-3 py-1.5 text-[0.86rem] font-semibold text-brand-soft-foreground transition-opacity hover:opacity-80"
                  aria-label={`Dejar de seguir ${b?.name ?? code}`}
                >
                  {b?.name ?? code}
                  <span aria-hidden="true" className="opacity-70">
                    ✕
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex min-w-0 flex-1 basis-60 items-center gap-2 rounded-lg border-[1.5px] border-input bg-muted px-3">
          <span aria-hidden="true" className="text-faint">
            ⌕
          </span>
          <input
            type="search"
            placeholder="Buscar biblioteca o municipio…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Buscar biblioteca"
            className="w-full border-none bg-transparent py-2.5 text-sm text-foreground outline-none placeholder:text-faint"
          />
        </div>
        <Button
          type="button"
          variant="outline"
          className="rounded-lg bg-card"
          onClick={useMyLocation}
        >
          {geoState === "locating" ? "Localizando…" : "⌖ Ordenar por cercanía"}
        </Button>
      </div>

      {geoState === "denied" && (
        <p className="text-sm text-muted-foreground">
          No pudimos acceder a tu ubicación. Usa el buscador para encontrar tus bibliotecas.
        </p>
      )}

      {/* Candidate list. */}
      <ul className="m-0 max-h-80 list-none divide-y divide-border overflow-y-auto rounded-xl border border-border bg-card p-0">
        {visible.length === 0 ? (
          <li className="p-4 text-sm text-muted-foreground">Sin resultados.</li>
        ) : (
          visible.map((b) => (
            <li key={b.code} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <p className="m-0 truncate text-[0.96rem] font-semibold text-foreground">
                  {b.name}
                </p>
                <p className="m-0 truncate text-[0.82rem] text-faint">
                  {b.province ?? "—"}
                  {coords && b.lat !== null && b.lng !== null
                    ? ` · ${Math.round(haversineKm(coords, { lat: b.lat, lng: b.lng }))} km`
                    : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => onToggle(b.code)}
                className="shrink-0 rounded-lg border border-primary bg-transparent px-4 py-2 text-[0.86rem] font-semibold text-primary transition-colors hover:bg-brand-soft"
              >
                Seguir
              </button>
            </li>
          ))
        )}
      </ul>
      {visible.length === MAX_VISIBLE && (
        <p className="text-xs text-muted-foreground">
          Mostrando las primeras {MAX_VISIBLE}. Afina con el buscador o usa tu ubicación.
        </p>
      )}
    </div>
  );
}
