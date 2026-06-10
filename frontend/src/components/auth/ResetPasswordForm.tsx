import { useState, type FormEvent, type ReactElement } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AuthApiError, resetPassword } from "@infrastructure/api/auth";

/**
 * ResetPasswordForm — landing island for the emailed reset link
 * (`/reset-password?token=…`). A successful reset revokes every session,
 * so the user is sent to /login afterwards.
 */

interface Props {
  apiBaseUrl: string;
}

export function ResetPasswordForm({ apiBaseUrl }: Props): ReactElement {
  const [password, setPassword] = useState("");
  const [passwordRepeat, setPasswordRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    if (password !== passwordRepeat) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) {
      setError("Falta el código de recuperación en el enlace.");
      return;
    }
    setBusy(true);
    try {
      await resetPassword(apiBaseUrl, token, password);
      setDone(true);
    } catch (err) {
      setError(
        err instanceof AuthApiError && err.detail === "invalid_or_expired"
          ? "El enlace no es válido o ha caducado (duran 2 horas). Pide uno nuevo."
          : "No se pudo restablecer la contraseña. Inténtalo de nuevo.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="space-y-4">
        <p className="text-sm">
          ✓ <strong>Contraseña actualizada.</strong> Hemos cerrado todas tus sesiones por seguridad.
        </p>
        <Button asChild>
          <a href="/login">Iniciar sesión</a>
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={(e) => void onSubmit(e)} className="space-y-4">
      <div className="space-y-1.5">
        <label htmlFor="password" className="text-sm font-medium">
          Nueva contraseña <span className="text-muted-foreground">(mínimo 8 caracteres)</span>
        </label>
        <Input
          id="password"
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="password-repeat" className="text-sm font-medium">
          Repite la contraseña
        </label>
        <Input
          id="password-repeat"
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          value={passwordRepeat}
          onChange={(e) => setPasswordRepeat(e.target.value)}
        />
      </div>
      {error && <p className="text-sm text-destructive">✗ {error}</p>}
      <Button type="submit" disabled={busy} className="w-full">
        {busy ? "Guardando…" : "Cambiar contraseña"}
      </Button>
    </form>
  );
}
