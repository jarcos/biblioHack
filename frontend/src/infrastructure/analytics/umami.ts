/**
 * Usage analytics — Umami on the NAS (06-11-2026, asked by José).
 *
 * The same self-hosted instance FrienDraft and the Huelva Developers sites
 * report to (panel at umami.josearcos.me). No cookies; events are purged after
 * 90 days on the Umami side.
 *
 * The tracker is loaded straight from umami.josearcos.me rather than through
 * the app's own origin: the frontend is a static `serve` with no proxy, and
 * the tunnel can route a path to a container but cannot rewrite it.
 *
 * Rules worth keeping:
 *   - No website id baked into the build → no tag at all. Only the production
 *     compose passes PUBLIC_UMAMI_WEBSITE_ID, so dev, CI and smoke builds never
 *     report.
 *   - `data-domains` keeps a stray build from reporting anywhere else.
 *   - Never send query strings or hashes: /verify and /reset-password carry
 *     one-time tokens in the URL, and search terms are nobody's business.
 */

export const UMAMI_SCRIPT_URL = "https://umami.josearcos.me/script.js";
export const PUBLIC_HOSTNAME = "biblio.josearcos.me";

export interface UmamiScriptAttributes {
  src: string;
  "data-website-id": string;
  "data-domains": string;
  "data-exclude-search": "true";
  "data-exclude-hash": "true";
}

export function umamiScript(websiteId: string | null | undefined): UmamiScriptAttributes | null {
  const id = websiteId?.trim();
  if (!id) return null;
  return {
    src: UMAMI_SCRIPT_URL,
    "data-website-id": id,
    "data-domains": PUBLIC_HOSTNAME,
    "data-exclude-search": "true",
    "data-exclude-hash": "true",
  };
}
