import { useState, type FormEvent, type ReactElement } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { requestPasswordReset } from "@infrastructure/api/auth";

/**
 * ForgotPasswordForm — requests a reset link. The backend answers 202 no
 * matter what (no account enumeration), so the UI always shows the same
 * "sent" state.
 */

interface Props {
  apiBaseUrl: string;
}

export function ForgotPasswordForm({ apiBaseUrl }: Props): ReactElement {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await requestPasswordReset(apiBaseUrl, email);
      setDone(true);
    } catch {
      setError("No se pudo contactar con el servidor. Inténtalo de nuevo.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <p className="rounded-md border border-border bg-secondary/40 p-6 text-sm text-muted-foreground">
        Si existe una cuenta con <strong>{email}</strong>, recibirá un enlace para restablecer la
        contraseña en unos minutos. El enlace caduca en 2 horas.
      </p>
    );
  }

  return (
    <form onSubmit={(e) => void onSubmit(e)} className="space-y-4">
      <div className="space-y-1.5">
        <label htmlFor="email" className="text-sm font-medium">
          Correo electrónico
        </label>
        <Input
          id="email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      {error && <p className="text-sm text-destructive">✗ {error}</p>}
      <Button type="submit" disabled={busy} className="w-full">
        {busy ? "Enviando…" : "Enviar enlace de recuperación"}
      </Button>
    </form>
  );
}
