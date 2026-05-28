// Astro auto-generates a types declaration in .astro/types.d.ts. We re-export
// it via a regular `import` to keep eslint happy (no triple-slash references).
import type {} from "../.astro/types.d.ts";

interface ImportMetaEnv {
  readonly PUBLIC_API_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
