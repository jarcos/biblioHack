import { useState, type FormEvent, type ReactElement } from "react";

import { TurnstileWidget } from "@/components/auth/TurnstileWidget";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AuthApiError, register } from "@infrastructure/api/auth";

/**
 * RegisterForm — public sign-up. On success it switches to a
 * "check your inbox" state; the account stays unusable until the emailed
 * verification link is clicked (backend policy).
 */

interface Props {
  apiBaseUrl: string;
  turnstileSiteKey?: string;
}

const ERROR_MESSAGES: Record<string, string> = {
  email_taken: "Ya existe una cuenta con ese correo. ¿Quieres iniciar sesión?",
  invalid_email: "Ese correo no parece válido.",
  weak_password: "La contraseña debe tener al menos 8 caracteres.",
  registration_disabled:
    "El registro está desactivado temporalmente. Vuelve a intentarlo más tarde.",
};

export function RegisterForm({ apiBaseUrl, turnstileSiteKey = "" }: Props): ReactElement {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [passwordRepeat, setPasswordRepeat] = useState("");
  const [consent, setConsent] = useState(false);
  const [turnstileToken, setTurnstileToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    if (password !== passwordRepeat) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    if (!consent) {
      setError("Debes aceptar la política de privacidad y las condiciones de uso.");
      return;
    }
    setBusy(true);
    try {
      await register(apiBaseUrl, {
        email,
        password,
        displayName: displayName.trim() || undefined,
        turnstileToken: turnstileToken || undefined,
      });
      setDone(true);
    } catch (err) {
      setError(
        err instanceof AuthApiError
          ? (ERROR_MESSAGES[err.detail] ?? `Error ${err.status}: ${err.detail}`)
          : "No se pudo contactar con el servidor. Inténtalo de nuevo.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="space-y-3 rounded-md border border-border bg-secondary/40 p-6">
        <h2 className="font-serif text-xl font-semibold">Revisa tu correo 📬</h2>
        <p className="text-sm text-muted-foreground">
          Te hemos enviado un enlace de verificación a <strong>{email}</strong>. La cuenta se activa
          al abrirlo; el enlace caduca en 24 horas.
        </p>
      </div>
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
      <div className="space-y-1.5">
        <label htmlFor="display-name" className="text-sm font-medium">
          Nombre <span className="text-muted-foreground">(opcional)</span>
        </label>
        <Input
          id="display-name"
          type="text"
          maxLength={120}
          autoComplete="name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="password" className="text-sm font-medium">
          Contraseña <span className="text-muted-foreground">(mínimo 8 caracteres)</span>
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

      <label className="flex items-start gap-2 text-sm text-muted-foreground">
        <input
          type="checkbox"
          required
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
          className="mt-0.5 h-4 w-4 rounded border-input"
        />
        <span>
          He leído y acepto la{" "}
          <a href="/privacy" className="text-foreground underline underline-offset-4">
            política de privacidad
          </a>{" "}
          y las{" "}
          <a href="/terms" className="text-foreground underline underline-offset-4">
            condiciones de uso
          </a>
          .
        </span>
      </label>

      <TurnstileWidget siteKey={turnstileSiteKey} onToken={setTurnstileToken} />

      {error && <p className="text-sm text-destructive">✗ {error}</p>}

      <Button type="submit" disabled={busy} className="w-full">
        {busy ? "Creando cuenta…" : "Crear cuenta"}
      </Button>
      <p className="text-center text-sm text-muted-foreground">
        ¿Ya tienes cuenta?{" "}
        <a href="/login" className="text-foreground underline underline-offset-4">
          Inicia sesión
        </a>
      </p>
    </form>
  );
}
