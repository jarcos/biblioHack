import { useEffect, useMemo, useState, type ReactElement } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  fetchBranches,
  fetchMyBranches,
  haversineKm,
  setMyBranches,
  type Branch,
} from "@infrastructure/api/branches";

/**
 * LibraryPicker — the /account "Mis bibliotecas" island (Libraries L2).
 *
 * Lets a signed-in user follow one or more RBPA branches. The browser may sort
 * the list by proximity using the device geolocation (which never leaves the
 * browser — design D11); if the prompt is denied or unavailable, a type-ahead
 * over branch name/municipality is the fallback (D12). Follows are saved with a
 * single PUT that replaces the set (order = preference). Redirects to /login
 * when there is no session (static site → client-side guard).
 */

interface Props {
  apiBaseUrl: string;
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

export function LibraryPicker({ apiBaseUrl }: Props): ReactElement {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [saved, setSaved] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [coords, setCoords] = useState<Coords | null>(null);
  const [geoState, setGeoState] = useState<"idle" | "locating" | "denied">("idle");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [justSaved, setJustSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchBranches(apiBaseUrl, controller.signal),
      fetchMyBranches(apiBaseUrl, controller.signal),
    ]).then(
      ([all, mine]) => {
        if (mine === null) {
          window.location.assign("/login?next=/account");
          return;
        }
        setBranches(all);
        setSelected(mine);
        setSaved(mine);
        setLoading(false);
      },
      () => {
        setError("No se pudieron cargar las bibliotecas. Inténtalo de nuevo.");
        setLoading(false);
      },
    );
    return () => controller.abort();
  }, [apiBaseUrl]);

  const byCode = useMemo(() => new Map(branches.map((b) => [b.code, b])), [branches]);

  const dirty = useMemo(() => selected.join(",") !== saved.join(","), [selected, saved]);

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

  function toggle(code: string): void {
    setJustSaved(false);
    setSelected((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]));
  }

  async function save(): Promise<void> {
    setSaving(true);
    setError(null);
    try {
      const codes = await setMyBranches(apiBaseUrl, selected);
      setSaved(codes);
      setSelected(codes);
      setJustSaved(true);
    } catch {
      setError("No se pudo guardar. Inténtalo de nuevo.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">Cargando bibliotecas…</p>;
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Sigue las bibliotecas donde sueles coger libros. Las usaremos para priorizar lo que tienes
        disponible cerca en el catálogo, la búsqueda y las recomendaciones. Tu ubicación se usa solo
        en tu navegador para ordenar por cercanía: nunca se envía ni se guarda.
      </p>

      {/* Selected libraries as removable chips. */}
      {selected.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {selected.map((code) => {
            const b = byCode.get(code);
            return (
              <li key={code}>
                <button
                  type="button"
                  onClick={() => toggle(code)}
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
              <Button type="button" variant="ghost" onClick={() => toggle(b.code)}>
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

      <div className="flex items-center gap-3">
        <Button type="button" disabled={!dirty || saving} onClick={() => void save()}>
          {saving ? "Guardando…" : "Guardar"}
        </Button>
        {justSaved && !dirty && <span className="text-sm text-muted-foreground">Guardado ✓</span>}
        {error && <span className="text-sm text-destructive">✗ {error}</span>}
      </div>
    </div>
  );
}

function distance(b: Branch, coords: Coords): number {
  if (b.lat === null || b.lng === null) return Number.POSITIVE_INFINITY;
  return haversineKm(coords, { lat: b.lat, lng: b.lng });
}
