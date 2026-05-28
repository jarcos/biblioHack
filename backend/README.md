# biblioHack — backend

FastAPI + SQLAlchemy 2.0 + pgvector. Hexagonal architecture with six bounded contexts plus a `shared` module.

## Setup

```bash
# From this directory
uv sync --all-extras    # install runtime + scraper + ai + worker + dev
```

If you only need the lean dev shell:

```bash
uv sync                 # runtime + dev only
```

## Common tasks

All targets are also wrapped in the **repo-root** `Makefile` (`make backend-*`):

```bash
uv run ruff check .         # lint
uv run ruff format .        # format
uv run mypy src             # typecheck
uv run pytest               # unit + integration tests
uv run uvicorn bibliohack.interfaces.http.app:app --reload
```

## Layout

```
src/bibliohack/
├── shared/                 # framework-free primitives shared across contexts
│   ├── domain/             # Entity, ValueObject, DomainEvent, identifiers
│   ├── application/        # Result, UseCase, ports.EventBus
│   └── infrastructure/     # settings, logging, event bus impl
├── catalog/                # bibliographic records
├── holdings/               # physical copies, branches, signatures
├── availability/           # time-series of loan status
├── reading_history/        # imported bookshelves
├── recommendations/        # AI-driven recommender
├── identity/               # users, preferences
└── interfaces/             # composition root
    └── http/               # FastAPI app
```

Each bounded context follows the same internal pattern:

```
<context>/
├── domain/                 # entities, value objects, domain services
├── application/            # use cases, ports (interfaces)
├── infrastructure/         # adapters (db, http, external services)
└── interfaces/             # FastAPI routers, dramatiq actors, CLI commands
```

**Rule of thumb**: `domain/` must not import from `application/` or `infrastructure/`. `application/` may import from `domain/` only. `infrastructure/` may import from both. `interfaces/` is the composition root and may import from all three.

The CI typechecker enforces this via `mypy` + a small import-linter rule (added in M1 when there is actual domain code to protect).
