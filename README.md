<div align="center">

# 📚 biblioHack

**A reverse catalogue, availability tracker, and recommender for the Andalusian public-library network — built to help you find the book you didn't know you were looking for.**

[![CI](https://github.com/jarcos/biblioHack/actions/workflows/ci.yml/badge.svg)](https://github.com/jarcos/biblioHack/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
![Python](https://img.shields.io/badge/python-3.12+-3776ab.svg)
![Node](https://img.shields.io/badge/node-20+-339933.svg)
![Astro](https://img.shields.io/badge/astro-frontend-ff5d01.svg)
![Postgres](https://img.shields.io/badge/postgres-timescale%20%2B%20pgvector-336791.svg)

[Live instance](https://biblio.josearcos.me) · [Architecture](./ARCHITECTURE.md) · [Roadmap](#-status)

</div>

> A personal side project that mirrors public catalogue data. **Not affiliated with the Junta de Andalucía or any of its libraries.**

---

## What is this?

The official public-library OPAC (AbsysNET) is great if you already know the title you want. biblioHack flips it around: it keeps a **local, searchable mirror** of the catalogue so you can explore it the way you'd browse a bookshop — search in natural Spanish (accents optional), filter to the literary catalogue, see **which branch has a copy on the shelf right now**, import your Goodreads shelf, and get **recommendations based on what you've already read**.

It's also a study in doing this **politely and sustainably**: a rate-limited crawler that's a good citizen of a public system, a history-preserving availability time-series, and a clean hexagonal codebase.

### What works today

- 🔎 **Full-text search in Spanish** — accent-insensitive (`café` finds `cafe`) via Postgres `spanish_unaccent` + a generated `tsvector`.
- 📖 **Literary-first catalogue** — records are classified by audience (adult / youth / children) and literary form (literary / non-fiction) from shelf-mark and CDU signals. The default scope shows the **adult literary catalogue**; a toggle includes children's, youth and non-fiction. Nothing is discarded — just scoped.
- 🟢 **Live availability by branch** — a history-preserving time-series of copies per branch, surfaced as "*N disponibles ahora*" badges.
- 🖼️ **Book covers** — resolved asynchronously (Open Library → Google Books → placeholder) and served from a content-addressed store, off the crawl path.
- 🤖 **Autonomous, resumable crawler** — a containerised, scheduled crawler walks the catalogue with a persisted cursor, growing the mirror hour by hour without ever re-scanning from the top.
- 🧠 **Semantic search** — BGE-M3 embeddings in pgvector: `?mode=semantic` queries and "more like this" on every record.
- 👤 **User accounts** — public registration with email verification, Turnstile bot protection, Redis sessions, rate limiting, and GDPR self-service (data export + account deletion).
- 📥 **Reading-history import** — upload a Goodreads CSV; a background worker matches it against the catalogue (ISBN-13 first, fuzzy title+author fallback) and your shelf re-matches for free as the mirror grows.
- ✨ **Per-user recommendations** — a taste profile from your rated shelf drives pgvector retrieval over the catalogue, with optional LLM-written rationales.
- 📊 **Production APM** — OpenTelemetry tracing (FastAPI + asyncpg + Redis) exported to Grafana Tempo / SigNoz.

### On the roadmap

- 🔀 **Hybrid retrieval** — fusing keyword and semantic rankings for better search.
- 🗺️ **Expansion** beyond Huelva to other Andalusian provinces.
- 📱 **Mobile app** reusing the same API.

---

## How it works

biblioHack is a **hexagonal (ports & adapters) modular monolith**. The domain logic never imports a framework or a driver; adapters (the AbsysNET scraper, Postgres repositories, the cover providers) plug in behind Protocol ports, which keeps the core testable and the deployment topology a free choice.

```
                    Cloudflare Tunnel (read-only, TLS at the edge)
                                   │
            ┌──────────────────────┴───────────────────────┐
            ▼                                               ▼
   ┌─────────────────┐                            ┌──────────────────┐
   │  Astro frontend │ ── /catalog, /healthz ──▶  │  FastAPI  (api)  │
   │  (static + React│                            │  + OpenTelemetry │
   │   islands)      │                            └────────┬─────────┘
   └─────────────────┘                                     │
                                                           ▼
                                    ┌──────────────────────────────────────┐
                                    │ Postgres (TimescaleDB + pgvector +    │
                                    │ spanish_unaccent FTS) · MinIO covers  │
                                    └──────────────────────▲───────────────┘
                                                           │ LAN / private network
   ┌───────────────────────────────────────────┐          │
   │ Crawl plane (off the public API)           │ ─────────┘
   │  scheduled discover → worker → refresh,     │
   │  Scrapling/Camoufox→Chromium against the    │
   │  public OPAC, polite by design              │
   └───────────────────────────────────────────┘
```

- **Read + serve plane** is public (read-only) behind the tunnel; **write/admin, the database and the crawler are never exposed** to the internet.
- The **crawler runs separately** from the API so a heavy headless-browser workload can't affect request latency. It paginates the OPAC's expert-query results with a **resumable offset cursor**, so it advances through the whole catalogue across runs and then tracks new arrivals.
- **Availability is a time-series**: copies are upserted (never delete+insert) so each re-scrape appends a snapshot rather than wiping history.

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full design, the scrape state machine, and the data model.

---

## Tech stack

| Layer        | Choice |
|--------------|--------|
| Backend      | Python 3.12, FastAPI, SQLAlchemy 2.0 (async) + asyncpg, Typer CLI, `uv` |
| Database     | PostgreSQL + TimescaleDB (hypertables), pgvector, `spanish_unaccent` FTS |
| Scraping     | Scrapling (Camoufox → Patchright Chromium), polite token-bucket throttle |
| Frontend     | Astro (static) + React islands, Zod, pnpm |
| Covers/store | Pillow (WebP), content-addressed filesystem / MinIO (S3) |
| Observability| OpenTelemetry → OTLP → Grafana Tempo / SigNoz |
| Infra        | Docker Compose, Synology NAS, Cloudflare Tunnel, GitHub Actions CI/CD |

---

## Repository layout

```
biblioHack/
├── ARCHITECTURE.md          # full design + research doc
├── CLAUDE.md                # conventions for AI assistants / contributors
├── docker-compose.yml       # dev environment
├── docker-compose.prod.yml  # production (read + serve plane)
├── docker-compose.crawler.yml  # the autonomous crawl plane
├── backend/                 # FastAPI hexagonal modular monolith (uv)
│   └── src/bibliohack/       # bounded contexts: catalog · holdings · availability ·
│                             #   covers · identity · reading_history · recommendations · shared
├── frontend/                # Astro + React islands (pnpm)
├── infra/                   # Dockerfiles, crawler image + schedule, cloudflared config
└── .github/workflows/       # CI (lint, typecheck, test, build, deploy)
```

---

## Getting started

### Prerequisites

- **Python 3.12+** and [**uv**](https://docs.astral.sh/uv/)
- **Node 20+** and [**pnpm**](https://pnpm.io/)
- **Docker** + **Docker Compose**
- **make** (optional, for the convenience targets)

### Quick start

```bash
git clone https://github.com/jarcos/biblioHack.git
cd biblioHack
cp .env.example .env

# 1. Bring up postgres + redis + api + frontend
make dev-up

# 2. Backend checks (ruff + mypy + pytest)
make backend-check

# 3. Frontend checks (eslint + astro check + vitest)
make frontend-check

# 4. Open the apps
open http://localhost:8800/docs   # FastAPI Swagger
open http://localhost:4321        # Astro frontend
```

Every `make` target is a one-liner — peek inside the [`Makefile`](./Makefile) if you'd rather run things directly. Scraping is opt-in (it's a heavy, browser-backed dependency set): `cd backend && uv sync --extra scraper && uv run camoufox fetch` then `uv run bibliohack catalog --help`.

### Configuration

Copy `.env.example` to `.env` and adjust as needed. Sensible defaults are provided for local development; the OpenTelemetry exporter and other production settings stay dormant unless their env vars are set.

---

## 📈 Status

| Milestone | Scope | State |
|-----------|-------|-------|
| **M0** | Foundations (scaffold, compose, CI) | ✅ Done |
| **M1** | Catalogue ingest + accent-insensitive search + literary scoping | ✅ Done |
| **M2** | Availability history + autonomous resumable crawler | ✅ Done |
| **M2.5** | Book covers (resolution + content-addressed store) | ✅ Done |
| **M3** | Semantic search (BGE-M3 + pgvector) | ✅ Done |
| **M4** | Reading-history import (Goodreads) | ✅ Done |
| **M5** | Recommender v1 (user-scoped) | ✅ Done |
| **Identity** | Public registration, per-user shelves, GDPR self-service, hardening | ✅ Done |
| **M6.5** | CI/CD auto-deploy (green `main` → NAS) | ✅ Done |
| **M7+** | Hybrid retrieval · more provinces · mobile app | ⏳ Planned |

Public deploy is **live** at [biblio.josearcos.me](https://biblio.josearcos.me); see [`ARCHITECTURE.md` §11](./ARCHITECTURE.md#11-roadmap-proposed-milestones) for milestone detail.

---

## Observability

The production `api` is instrumented with **OpenTelemetry** (APM / distributed tracing). The container runtime wraps `uvicorn` with `opentelemetry-instrument`, which auto-instruments **FastAPI** and **asyncpg** — HTTP requests and DB queries become spans with no application-code changes. It is a **no-op locally**: instrumentation only activates when the `OTEL_*` env vars are set (defined only in `docker-compose.prod.yml`), so dev runs and tests are unaffected.

In production, telemetry is exported via **OTLP** to a shared OpenTelemetry collector, which fans traces out to **Grafana Tempo** and **SigNoz** (`service.name=bibliohack-api`). See [`ARCHITECTURE.md` §10](./ARCHITECTURE.md) for the full picture.

---

## Deployment

Green pushes to `main` are gated by CI (lint, typecheck, tests, image build) and then **auto-deploy** to a Synology NAS over Tailscale. The public surface is served through a Cloudflare Tunnel (read-only; no inbound ports). Database migrations ship in the API image and run on deploy. The crawl plane runs as a separate, self-restarting container so it can't affect the public site. Details — including the hard-won Synology specifics — live in [`ARCHITECTURE.md` §10](./ARCHITECTURE.md).

---

## Contributing

This is primarily a personal project, but issues, ideas and PRs are welcome. If you're contributing code:

1. Read [`CLAUDE.md`](./CLAUDE.md) for the conventions (it's written for AI assistants but applies to humans too).
2. Before pushing, the backend must pass `ruff format --check .`, `ruff check .`, `mypy src`, and `pytest`; the frontend must pass its lint/typecheck/test — all enforced in CI.
3. Add an Alembic migration for any schema change.
4. **Be a good OPAC citizen.** The crawler is deliberately rate-limited and capped because it talks to a live public-library system. Please don't change it to be more aggressive.

---

## Responsible use & data

biblioHack mirrors **public-sector bibliographic data** that belongs to the Junta de Andalucía and the Spanish public-library system, reused under the [Spanish public-sector information rules (Ley 37/2007)](https://www.boe.es/buscar/act.php?id=BOE-A-2007-19814). **Información obtenida del Portal de la Junta de Andalucía** (CC-BY 3.0 ES); derivatives of this data must carry the same attribution. The crawler identifies itself, throttles every request, and caps its volume so it never burdens the source system. This project is independent and unaffiliated.

---

## License

[MIT](./LICENSE) © José Arcos.

---

<div align="center">
<sub>Built with care for readers, libraries, and a polite internet.</sub>
</div>
