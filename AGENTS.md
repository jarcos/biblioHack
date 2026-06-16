# AGENTS.md

Guidance for AI assistants and contributors working in this repo.
`docs/design/architecture.md` is the full design; this file captures conventions
that are easy to break. (Claude Code reads `CLAUDE.md`, which points here.)

## Project

biblioHack is a reverse catalogue + availability tracker + recommender that
mirrors the Andalusian public-library OPAC (AbsysNET). Python/FastAPI backend
(hexagonal/DDD — `catalog`, `holdings`, `availability`, `covers` bounded
contexts under `backend/src/bibliohack/`, with `domain` / `application` /
`infrastructure` / `interfaces` layers), Astro frontend, Postgres
(TimescaleDB + pgvector + `spanish_unaccent` FTS). Deployed on a Synology NAS
behind a Cloudflare Tunnel. The crawl/worker plane runs off the public API in
an on-NAS `bibliohack-crawler` container (supercronic-scheduled: hourly
cursor-advancing `discover`+`worker`, 6-hourly `refresh`). Green pushes to
`main` auto-deploy to the NAS via CI.

## Docs layout — read this before editing docs

- **Markdown is the single source of truth; the HTML site is generated.**
- `docs/design/*.md` — canonical design & milestone docs (architecture,
  identity-milestone, relevance-and-libraries). Machine-readable.
- `docs/ops/*.md` — operational references (infra). `docs/outreach/` — drafts.
- `docs/site/_src/*.md` — sources for the human-only pages (index, kanban,
  pending-and-ops), authored as Markdown (raw HTML allowed for layout bits).
- `docs/site/*.html` — **generated build artifacts; never edit by hand.**
- `README.md` (root) is the GitHub front door; `AGENTS.md` (this file) is the
  agent/contributor doc.

**Workflow:** edit the `.md`, then run `make docs` to regenerate the site
(`tools/build_docs.py`). CI regenerates and fails on any diff, so a stale
`docs/site/` cannot be committed.

## APM / tracing — keep this in mind

The production `api` is instrumented with **OpenTelemetry** (live since
2026-06-04). `infra/backend.Dockerfile`'s runtime CMD runs uvicorn under
`opentelemetry-instrument`, which auto-instruments **FastAPI + asyncpg**. It is
a **no-op unless the `OTEL_*` env vars are set** (only `docker-compose.prod.yml`
sets them), so local/dev/test runs are unaffected. When changing things:

- Do **not** unwrap or replace the `opentelemetry-instrument …` CMD in
  `infra/backend.Dockerfile` without preserving the instrumentation.
- Keep the OTel deps in `backend/pyproject.toml`: `opentelemetry-distro[otlp]`,
  `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-asyncpg`.
- New outbound integrations (HTTP clients, other drivers) are **not** traced
  automatically — add the matching `opentelemetry-instrumentation-*` package if
  you want spans for them.
- Traces export via OTLP to a shared collector on the NAS (→ Grafana Tempo +
  SigNoz), reached over the external `tunnel` Docker network. Details in
  `docs/design/architecture.md` §10.
- The crawl/worker plane is **not** OTel-instrumented yet; crawl health comes
  from the `scrape_tasks` status histogram + `last_error`.

## Conventions

- **Ship workflow:** commit + push to `main`; CI gates everything and then
  auto-deploys to the NAS. Never deploy on a red pipeline.
- **Backend gate before pushing** (all also enforced in CI): `ruff format
  --check .`, `ruff check .`, `mypy src`, `pytest`.
- **Docs gate:** after editing any `.md`, run `make docs`; CI fails if
  `docs/site/` is out of date.
- **Migrations** ship in the api image and run (`alembic upgrade head`) on
  deploy; add an Alembic revision for every schema change.
- **Be a good OPAC citizen:** the crawler is polite by design (per-second
  throttle + per-run caps). Don't raise request rates casually — it hits a
  public library system.
