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

  const rows: { k: string; v: string }[] = [
    { k: "Correo", v: user.email },
    { k: "Nombre", v: user.display_name ?? "—" },
    { k: "Correo verificado", v: user.email_verified ? "Sí ✓" : "No" },
    {
      k: "Miembro desde",
      v: new Date(user.created_at).toLocaleDateString("es-ES", { dateStyle: "long" }),
    },
  ];

  return (
    <div className="space-y-10">
      <dl className="m-0 rounded-2xl border border-border bg-card px-6 py-2 shadow-card">
        {rows.map(({ k, v }, i) => (
          <div
            key={k}
            className={`flex items-center justify-between gap-4 py-4 ${
              i > 0 ? "border-t border-border" : ""
            }`}
          >
            <dt className="text-[0.95rem] text-muted-foreground">{k}</dt>
            <dd className="m-0 text-[0.95rem] font-semibold text-foreground">{v}</dd>
          </div>
        ))}
      </dl>

      <div className="space-y-3">
        <h2 className="m-0 font-serif text-[1.4rem] font-semibold tracking-tight">Seguridad</h2>
        <p className="m-0 text-[0.98rem] leading-relaxed text-muted-foreground">
          Para cambiar la contraseña usa{" "}
          <a
            href="/forgot-password"
            className="text-primary underline underline-offset-[3px] transition-opacity hover:opacity-80"
          >
            recuperar contraseña
          </a>{" "}
          — el enlace que recibirás cierra todas las sesiones abiertas.
        </p>
        <Button variant="outline" className="rounded-lg bg-card" onClick={() => void onLogout()}>
          Cerrar sesión
        </Button>
      </div>

      <div className="space-y-3">
        <h2 className="m-0 font-serif text-[1.4rem] font-semibold tracking-tight">Tus datos</h2>
        <p className="m-0 text-[0.98rem] leading-relaxed text-muted-foreground">
          Descarga todo lo que guardamos sobre ti (cuenta, estantería, importaciones y
          recomendaciones) en un archivo JSON. Más detalles en la{" "}
          <a
            href="/privacy"
            className="text-primary underline underline-offset-[3px] transition-opacity hover:opacity-80"
          >
            política de privacidad
          </a>
          .
        </p>
        <Button
          variant="outline"
          className="rounded-lg bg-card"
          disabled={busy}
          onClick={() => void onExport()}
        >
          ↓ Exportar mis datos
        </Button>
      </div>

      <div className="space-y-3 rounded-2xl border border-destructive bg-destructive-soft p-6">
        <h2 className="m-0 font-serif text-[1.3rem] font-semibold tracking-tight text-destructive-soft-foreground">
          Eliminar la cuenta
        </h2>
        <p className="m-0 text-sm leading-relaxed text-muted-foreground">
          Borra tu cuenta, tu estantería y tus recomendaciones de forma{" "}
          <strong className="text-foreground">irreversible</strong> (las copias de seguridad rotan
          en un máximo de 30 días).
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
