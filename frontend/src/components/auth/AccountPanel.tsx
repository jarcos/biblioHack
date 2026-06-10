import { useEffect, useState, type ReactElement } from "react";

import { Button } from "@/components/ui/button";
import { fetchCurrentUser, logout, type User } from "@infrastructure/api/auth";

/**
 * AccountPanel — the /account island: profile summary + logout. Redirects
 * to /login when there is no session (static site → guard is client-side).
 *
 * Data export and account deletion are Phase 5 (GDPR self-service); until
 * then the privacy policy points users at the contact address for those
 * rights.
 */

interface Props {
  apiBaseUrl: string;
}

export function AccountPanel({ apiBaseUrl }: Props): ReactElement {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

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
          La exportación y el borrado de cuenta desde esta página llegarán pronto. Mientras tanto
          puedes ejercer esos derechos según se describe en la{" "}
          <a href="/privacy" className="text-foreground underline underline-offset-4">
            política de privacidad
          </a>
          .
        </p>
      </div>
    </div>
  );
}
