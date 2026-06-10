import { useState, type FormEvent, type ReactElement } from "react";

import { TurnstileWidget } from "@/components/auth/TurnstileWidget";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AuthApiError, login } from "@infrastructure/api/auth";

/**
 * LoginForm — opens the session (httpOnly cookie) and redirects to `?next=`
 * (sanitised to local paths) or the shelf.
 */

interface Props {
  apiBaseUrl: string;
  turnstileSiteKey?: string;
}

const ERROR_MESSAGES: Record<string, string> = {
  invalid_credentials: "Correo o contraseña incorrectos.",
  email_not_verified:
    "Tu correo aún no está verificado. Busca el enlace de activación en tu bandeja de entrada.",
};

function nextPath(): string {
  const raw = new URLSearchParams(window.location.search).get("next") ?? "/shelf";
  // Local paths only — never an absolute URL someone mailed around.
  return raw.startsWith("/") && !raw.startsWith("//") ? raw : "/shelf";
}

export function LoginForm({ apiBaseUrl, turnstileSiteKey = "" }: Props): ReactElement {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [turnstileToken, setTurnstileToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(apiBaseUrl, { email, password, turnstileToken: turnstileToken || undefined });
      window.location.assign(nextPath());
    } catch (err) {
      setBusy(false);
      setError(
        err instanceof AuthApiError
          ? (ERROR_MESSAGES[err.detail] ?? `Error ${err.status}: ${err.detail}`)
          : "No se pudo contactar con el servidor. Inténtalo de nuevo.",
      );
    }
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
      <div className="space-y-1.5">
        <label htmlFor="password" className="text-sm font-medium">
          Contraseña
        </label>
        <Input
          id="password"
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>

      <TurnstileWidget siteKey={turnstileSiteKey} onToken={setTurnstileToken} />

      {error && <p className="text-sm text-destructive">✗ {error}</p>}

      <Button type="submit" disabled={busy} className="w-full">
        {busy ? "Entrando…" : "Entrar"}
      </Button>
      <div className="flex justify-between text-sm text-muted-foreground">
        <a href="/forgot-password" className="underline-offset-4 hover:underline">
          He olvidado mi contraseña
        </a>
        <a href="/register" className="text-foreground underline underline-offset-4">
          Crear cuenta
        </a>
      </div>
    </form>
  );
}
