import { useEffect, useState, type ReactElement } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AuthApiError,
  deleteAccount,
  exportAccountData,
  fetchCurrentUser,
  logout,
  type User,
} from "@infrastructure/api/auth";

/**
 * AccountPanel — the /account island: profile summary, logout, and the
 * GDPR self-service actions (data export download + account deletion with
 * password re-authentication). Redirects to /login when there is no
 * session (static site → guard is client-side).
 */

interface Props {
  apiBaseUrl: string;
}

export function AccountPanel({ apiBaseUrl }: Props): ReactElement {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchCurrentUser(apiBaseUrl, controller.signal).then(
      (me) => {
        if (me === null) {
          window.location.assign("/login?next=/account");
          return;
        }
        setUser(me);
        setLoading(false);
      },
      () => setLoading(false),
    );
    return () => controller.abort();
  }, [apiBaseUrl]);

  async function onLogout(): Promise<void> {
    await logout(apiBaseUrl);
    window.location.assign("/");
  }

  async function onExport(): Promise<void> {
    setBusy(true);
    try {
      const blob = await exportAccountData(apiBaseUrl);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "bibliohack-export.json";
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setDeleteError("No se pudo generar la exportación. Inténtalo de nuevo.");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(): Promise<void> {
    setDeleteError(null);
    setBusy(true);
    try {
      await deleteAccount(apiBaseUrl, deletePassword);
      window.location.assign("/");
    } catch (err) {
      setBusy(false);
      setDeleteError(
        err instanceof AuthApiError && err.detail === "invalid_password"
          ? "Contraseña incorrecta."
          : "No se pudo eliminar la cuenta. Inténtalo de nuevo.",
      );
    }
  }

  if (loading || user === null) {
    return <p className="text-sm text-muted-foreground">Cargando tu cuenta…</p>;
  }

  return (
    <div className="space-y-8">
      <dl className="space-y-4 rounded-md border border-border p-6 text-sm">
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Correo</dt>
          <dd className="font-medium">{user.email}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Nombre</dt>
          <dd className="font-medium">{user.display_name ?? "—"}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Correo verificado</dt>
          <dd className="font-medium">{user.email_verified ? "Sí ✓" : "No"}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Miembro desde</dt>
          <dd className="font-medium">
            {new Date(user.created_at).toLocaleDateString("es-ES", { dateStyle: "long" })}
          </dd>
        </div>
      </dl>

      <div className="space-y-3">
        <h2 className="font-serif text-lg font-semibold">Seguridad</h2>
        <p className="text-sm text-muted-foreground">
          Para cambiar la contraseña usa{" "}
          <a href="/forgot-password" className="text-foreground underline underline-offset-4">
            recuperar contraseña
          </a>{" "}
          — el enlace que recibirás cierra todas las sesiones abiertas.
        </p>
        <Button variant="outline" onClick={() => void onLogout()}>
          Cerrar sesión
        </Button>
      </div>

      <div className="space-y-3">
        <h2 className="font-serif text-lg font-semibold">Tus datos</h2>
        <p className="text-sm text-muted-foreground">
          Descarga todo lo que guardamos sobre ti (cuenta, estantería, importaciones y
          recomendaciones) en un archivo JSON. Más detalles en la{" "}
          <a href="/privacy" className="text-foreground underline underline-offset-4">
            política de privacidad
          </a>
          .
        </p>
        <Button variant="outline" disabled={busy} onClick={() => void onExport()}>
          Exportar mis datos
        </Button>
      </div>

      <div className="space-y-3 rounded-md border border-destructive/40 p-4">
        <h2 className="font-serif text-lg font-semibold text-destructive">Eliminar la cuenta</h2>
        <p className="text-sm text-muted-foreground">
          Borra tu cuenta, tu estantería y tus recomendaciones de forma{" "}
          <strong>irreversible</strong> (las copias de seguridad rotan en un máximo de 30 días).
        </p>
        {!deleteArmed ? (
          <Button variant="destructive" onClick={() => setDeleteArmed(true)}>
            Quiero eliminar mi cuenta
          </Button>
        ) : (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              void onDelete();
            }}
          >
            <label htmlFor="delete-password" className="block text-sm font-medium">
              Confirma tu contraseña para continuar
            </label>
            <Input
              id="delete-password"
              type="password"
              required
              autoComplete="current-password"
              value={deletePassword}
              onChange={(e) => setDeletePassword(e.target.value)}
            />
            {deleteError && <p className="text-sm text-destructive">✗ {deleteError}</p>}
            <div className="flex gap-2">
              <Button type="submit" variant="destructive" disabled={busy}>
                {busy ? "Eliminando…" : "Eliminar definitivamente"}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setDeleteArmed(false)}>
                Cancelar
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
