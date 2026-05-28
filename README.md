# biblioHack

A reverse catalog and AI-driven book recommender for the Andalusian public-library network, bootstrapped from the **Biblioteca Provincial de Huelva**.

> Side project. Public data. Not affiliated with the Junta de Andalucía or any of its libraries.

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full design rationale.

---

## Repository layout

```
biblioHack/
├── ARCHITECTURE.md          # design and research doc
├── README.md                # this file
├── LICENSE                  # MIT
├── Makefile                 # common dev targets
├── docker-compose.yml       # dev environment (postgres + pgvector + redis + api + frontend)
├── .env.example             # config defaults
├── backend/                 # FastAPI hexagonal modular monolith
│   ├── pyproject.toml       # uv-managed
│   ├── src/bibliohack/      # six bounded contexts + shared
│   └── tests/
├── frontend/                # Astro + React islands
│   ├── package.json         # pnpm-managed
│   └── src/
├── infra/                   # Dockerfiles, future Kubernetes manifests
└── .github/workflows/       # CI
```

---

## Prerequisites

- **Python 3.12+** and [**uv**](https://docs.astral.sh/uv/) for the backend.
- **Node 20+** and [**pnpm**](https://pnpm.io/) for the frontend.
- **Docker** + **Docker Compose** for the dev environment.
- **make** for the convenience targets (optional but recommended).

---

## Quick start

```bash
# 1. Bring up postgres + redis + everything else
make dev-up

# 2. In another terminal, run backend tests + lint
make backend-check

# 3. In another terminal, run frontend tests + lint
make frontend-check

# 4. Open the hello pages
open http://localhost:8000/docs        # FastAPI Swagger
open http://localhost:4321             # Astro frontend
```

If you don't have `make`, look inside the `Makefile` — each target is a one-liner.

---

## Status

- [x] **M0** — Foundations (scaffold, docker compose, CI)
- [ ] **M1** — Catalog ingest (Huelva)
- [ ] **M2** — Availability history
- [ ] **M3** — Semantic search
- [ ] **M4** — Goodreads import
- [ ] **M5** — Recommender v1
- [ ] **M6** — Public deploy
- [ ] **M7** — Expand to other Andalusian provinces
- [ ] **M8** — Mobile app

See [`ARCHITECTURE.md` §11](./ARCHITECTURE.md#11-roadmap-proposed-milestones) for milestone details.

---

## Contributing

This is a side project, not currently accepting external PRs. Feel free to fork.

## License

[MIT](./LICENSE) © José Arcos. The bibliographic data this project mirrors belongs to the Junta de Andalucía and the Spanish public-library system; it is reused under the [Spanish PSI rules (Ley 37/2007)](https://www.boe.es/buscar/act.php?id=BOE-A-2007-19814).
