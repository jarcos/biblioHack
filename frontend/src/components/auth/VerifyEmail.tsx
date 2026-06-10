import { useEffect, useRef, useState, type ReactElement } from "react";

import { Button } from "@/components/ui/button";
import { verifyEmail } from "@infrastructure/api/auth";

/**
 * VerifyEmail — landing island for the emailed verification link
 * (`/verify?token=…`). Consumes the token on mount; tokens are single-use,
 * so a re-run (React strict-mode, reload after success) is guarded.
 */

interface Props {
  apiBaseUrl: string;
}

type State = "working" | "done" | "failed" | "missing";

export function VerifyEmail({ apiBaseUrl }: Props): ReactElement {
  const [state, setState] = useState<State>("working");
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) {
      setState("missing");
      return;
    }
    verifyEmail(apiBaseUrl, token).then(
      () => setState("done"),
      () => setState("failed"),
    );
  }, [apiBaseUrl]);

  if (state === "working") {
    return <p className="text-sm text-muted-foreground">Verificando tu correo…</p>;
  }
  if (state === "done") {
    return (
      <div className="space-y-4">
        <p className="text-sm">
          ✓ <strong>Correo verificado.</strong> Tu cuenta ya está activa.
        </p>
        <Button asChild>
          <a href="/login">Iniciar sesión</a>
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-destructive">
        ✗{" "}
        {state === "missing"
          ? "Falta el código de verificación en el enlace."
          : "El enlace no es válido o ha caducado (duran 24 horas)."}
      </p>
      <p className="text-sm text-muted-foreground">
        Puedes pedir un correo nuevo registrándote otra vez con la misma dirección si la cuenta no
        llegó a activarse, o escribir a{" "}
        <a href="mailto:no-reply@mail.josearcos.me" className="underline underline-offset-4">
          soporte
        </a>
        .
      </p>
    </div>
  );
}
