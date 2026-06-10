import { type ReactElement } from "react";

import { AuthGate } from "@/components/auth/AuthGate";
import { Recommendations } from "@/components/Recommendations";

/**
 * RecommendationsPage — the single island for /recommendations. See
 * ShelfPage for why the gate must compose inside React rather than via
 * Astro island children (static-slot pitfall).
 */

interface Props {
  apiBaseUrl: string;
}

export function RecommendationsPage({ apiBaseUrl }: Props): ReactElement {
  return (
    <AuthGate apiBaseUrl={apiBaseUrl}>
      <Recommendations apiBaseUrl={apiBaseUrl} />
    </AuthGate>
  );
}
