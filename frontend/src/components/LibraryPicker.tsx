import { useEffect, useMemo, useState, type ReactElement } from "react";

import { BranchSelect } from "@/components/BranchSelect";
import { Button } from "@/components/ui/button";
import {
  fetchBranches,
  fetchMyBranches,
  setMyBranches,
  type Branch,
} from "@infrastructure/api/branches";

/**
 * LibraryPicker — the /account "Mis bibliotecas" island (Libraries L2).
 *
 * Lets a signed-in user follow one or more RBPA branches. The selection UI is
 * the shared {@link BranchSelect}; this wrapper owns the data (load all + the
 * caller's current follows) and persistence (a single PUT that replaces the
 * set, order = preference). Redirects to /login when there is no session
 * (static site → client-side guard).
 */

interface Props {
  apiBaseUrl: string;
}

export function LibraryPicker({ apiBaseUrl }: Props): ReactElement {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [saved, setSaved] = useState<string[]>([]);
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

  const dirty = useMemo(() => selected.join(",") !== saved.join(","), [selected, saved]);

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

      <BranchSelect branches={branches} selected={selected} onToggle={toggle} />

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
