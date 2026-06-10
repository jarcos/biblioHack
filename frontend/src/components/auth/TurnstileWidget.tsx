import { useEffect, useRef, type ReactElement } from "react";

/**
 * Cloudflare Turnstile widget. Renders nothing when no site key is
 * configured (`PUBLIC_TURNSTILE_SITE_KEY` unset) — the backend check is
 * disabled in lockstep, so register/login work without it until the keys
 * land in both environments.
 */

declare global {
  interface Window {
    turnstile?: {
      render: (
        container: HTMLElement,
        options: { sitekey: string; callback: (token: string) => void },
      ) => string;
    };
  }
}

const SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

interface Props {
  siteKey: string;
  onToken: (token: string) => void;
}

export function TurnstileWidget({ siteKey, onToken }: Props): ReactElement | null {
  const containerRef = useRef<HTMLDivElement>(null);
  const renderedRef = useRef(false);

  useEffect(() => {
    if (!siteKey || renderedRef.current) return;
    const render = () => {
      if (containerRef.current && window.turnstile && !renderedRef.current) {
        renderedRef.current = true;
        window.turnstile.render(containerRef.current, { sitekey: siteKey, callback: onToken });
      }
    };
    if (window.turnstile) {
      render();
      return;
    }
    const script = document.createElement("script");
    script.src = SCRIPT_SRC;
    script.async = true;
    script.onload = render;
    document.head.appendChild(script);
  }, [siteKey, onToken]);

  if (!siteKey) return null;
  return <div ref={containerRef} className="min-h-[65px]" />;
}
