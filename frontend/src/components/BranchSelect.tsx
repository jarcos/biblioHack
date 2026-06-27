import { useMemo, useState, type ReactElement } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
        <ul className="flex flex-wrap gap-2">
          {selected.map((code) => {
            const b = byCode.get(code);
            return (
              <li key={code}>
                <button
                  type="button"
                  onClick={() => onToggle(code)}
                  className="inline-flex items-center gap-1 rounded-full border border-border bg-secondary px-3 py-1 text-sm hover:bg-secondary/70"
                  aria-label={`Dejar de seguir ${b?.name ?? code}`}
                >
                  {b?.name ?? code}
                  <span aria-hidden="true">×</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Input
          type="search"
          placeholder="Buscar biblioteca o municipio…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Buscar biblioteca"
          className="max-w-xs"
        />
        <Button type="button" variant="outline" onClick={useMyLocation}>
          {geoState === "locating" ? "Localizando…" : "Ordenar por cercanía"}
        </Button>
      </div>

      {geoState === "denied" && (
        <p className="text-sm text-muted-foreground">
          No pudimos acceder a tu ubicación. Usa el buscador para encontrar tus bibliotecas.
        </p>
      )}

      {/* Candidate list. */}
      <ul className="max-h-80 divide-y divide-border overflow-y-auto rounded-md border border-border">
        {visible.length === 0 ? (
          <li className="p-4 text-sm text-muted-foreground">Sin resultados.</li>
        ) : (
          visible.map((b) => (
            <li key={b.code} className="flex items-center justify-between gap-3 px-4 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{b.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {b.province ?? "—"}
                  {coords && b.lat !== null && b.lng !== null
                    ? ` · ${Math.round(haversineKm(coords, { lat: b.lat, lng: b.lng }))} km`
                    : ""}
                </p>
              </div>
              <Button type="button" variant="ghost" onClick={() => onToggle(b.code)}>
                Seguir
              </Button>
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
