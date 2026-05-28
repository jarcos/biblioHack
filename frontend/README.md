# biblioHack — frontend

[Astro 5](https://astro.build) + React islands, with Tailwind, TanStack Query, and Zod-validated API responses.

## Setup

```bash
pnpm install
```

## Common tasks

All targets are also wrapped in the **repo-root** `Makefile` (`make frontend-*`):

```bash
pnpm dev          # Astro dev server on http://localhost:4321
pnpm build        # production build (runs `astro check` first)
pnpm typecheck    # astro check + tsc --noEmit
pnpm lint         # eslint
pnpm format       # prettier write
pnpm test         # vitest (unit tests)
```

## Layout

```
src/
├── domain/             # framework-free TS (types, predicates, scoring)
├── application/        # use cases + port interfaces
├── infrastructure/
│   └── api/            # generated OpenAPI client, zod schemas, fetch wrappers
├── components/         # React + Astro components
├── layouts/            # Astro layouts
├── pages/              # Astro routes
└── styles/
    └── global.css      # Tailwind directives
```

Pages stay dumb (compose components, fetch data). Business rules live in `domain/` and orchestration in `application/` so they can be reused by a future React Native client without bringing Astro or React along.

## Tests

Vitest for unit tests (`tests/**/*.test.ts(x)`), `fast-check` for property-based tests in `domain/`, React Testing Library for components. Playwright e2e lives at the repo root when M6 adds it.
