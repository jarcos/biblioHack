import { useEffect, useState, type FormEvent, type ReactElement } from "react";

import { BranchSelect } from "@/components/BranchSelect";
import { TurnstileWidget } from "@/components/auth/TurnstileWidget";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AuthApiError, register } from "@infrastructure/api/auth";
import { fetchBranches, type Branch } from "@infrastructure/api/branches";

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

  // L5: optional «Mis bibliotecas» picker, collapsed by default (skippable).
  const [showLibraries, setShowLibraries] = useState(false);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [selectedBranches, setSelectedBranches] = useState<string[]>([]);
  const [branchesError, setBranchesError] = useState<string | null>(null);

  // Load the branch list lazily — only when the user opens the section, so
  // anyone who skips never pays the request.
  useEffect(() => {
    if (!showLibraries || branches.length > 0) return;
    const controller = new AbortController();
    fetchBranches(apiBaseUrl, controller.signal).then(
      (all) => setBranches(all),
      () => setBranchesError("No se pudieron cargar las bibliotecas."),
    );
    return () => controller.abort();
  }, [showLibraries, branches.length, apiBaseUrl]);

  function toggleBranch(code: string): void {
    setSelectedBranches((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code],
    );
  }

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
        branchCodes: selectedBranches.length > 0 ? selectedBranches : undefined,
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

      <div className="space-y-3 rounded-md border border-border p-3">
        <button
          type="button"
          onClick={() => setShowLibraries((v) => !v)}
          aria-expanded={showLibraries}
          className="flex w-full items-center justify-between text-left text-sm font-medium"
        >
          <span>
            Elige tus bibliotecas <span className="text-muted-foreground">(opcional)</span>
            {selectedBranches.length > 0 && (
              <span className="text-muted-foreground"> · {selectedBranches.length} elegida(s)</span>
            )}
          </span>
          <span aria-hidden="true">{showLibraries ? "−" : "+"}</span>
        </button>
        {showLibraries && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Sigue las bibliotecas donde sueles coger libros para priorizar lo que tienes
              disponible cerca. Puedes omitirlo y configurarlo más tarde en tu cuenta.
            </p>
            {branchesError ? (
              <p className="text-sm text-destructive">✗ {branchesError}</p>
            ) : branches.length === 0 ? (
              <p className="text-sm text-muted-foreground">Cargando bibliotecas…</p>
            ) : (
              <BranchSelect
                branches={branches}
                selected={selectedBranches}
                onToggle={toggleBranch}
              />
            )}
          </div>
        )}
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
