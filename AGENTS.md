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

## Engineering standards (portfolio-wide)

These apply to every project in the portfolio. Canonical copy lives in
`~/Sites/hq/ESTANDARES.md`; this section is the repo-local copy so an agent
working inside the repo doesn't need it. If they diverge, the canonical one wins.

**TDD — the test comes first.**
- No production code without a test that asked for it first. Red → green →
  refactor. The test and the implementation land in the same commit, but the
  test was written first and was seen to fail.
- A test describes behaviour, not implementation. If a behaviour-preserving
  refactor breaks the test, the test was wrong.
- A reported bug starts with a test that reproduces it. Never "fix now, test
  later".
- Green before committing, always. Red doesn't get committed.

**DDD — domain first and isolated.** Already the shape of this repo: four
bounded contexts (`catalog`, `holdings`, `availability`, `covers`) over
`domain` / `application` / `infrastructure` / `interfaces`. The rules that are
easy to break:
- Dependencies point inward. `*/domain/` imports no FastAPI, no SQLAlchemy, no
  httpx, nothing from `infrastructure`.
- A context doesn't reach into another context's tables — it asks through an
  interface.
- Invariants live in entities and value objects, not in controllers. No anemic
  models.
- Every external API and vendor SDK sits behind an interface this project owns
  (anti-corruption layer), so a vendor change touches one adapter.

**SOLID — all five.**
- **S**ingle responsibility: one reason to change per class.
- **O**pen/closed: extend by adding, not by editing what already works.
- **L**iskov: any implementation of a port substitutes for another.
- **I**nterface segregation: narrow ports. Three one-method interfaces beat one
  of ten.
- **D**ependency inversion: high-level modules depend on abstractions; concrete
  implementations are wired in infrastructure.

**Coverage — a ratchet, not an aspiration.**
- The floor is `fail_under = 82` in `backend/pyproject.toml`, measured with
  **branch** coverage. Real number today is **83.09%** (664 tests, 26-08-2026);
  the floor sits one point below on purpose, so a refactor that adds a
  defensive branch doesn't go red for the wrong reason. It only goes up.
  Lowering it is an explicit decision with its own commit and a written reason.
- **New code: 100%.** The global floor is the ratchet for old debt; there's no
  excuse for what gets written today.
- Exclusions are listed **by name with a written reason** in
  `[tool.coverage.run] omit`. No wildcards.
- Coverage is not a substitute for assertions. A test that executes a line
  without asserting anything raises the number and buys false confidence.
- **`pytest` can fail with every test green** if coverage drops below the
  floor. That's a red, not a pass.

## Deploy traps — read before touching `docker-compose.prod.yml`

- **No hardcoded IPs, ever.** Postgres and MinIO bind to the NAS LAN IP so the
  off-NAS worker/embedder can reach them without exposing anything to the
  internet. That IP comes from `NAS_BIND_IP` in the NAS's `.env` — never
  written into the compose file.

  This cost an outage on 2026-08-26. The IP had been pinned to
  `192.168.1.130`; DHCP moved the NAS to `.131` at some point after the last
  deploy (2026-07-16), and the next deploy died starting Postgres with
  `bind: cannot assign requested address`. Six weeks of armed bomb that only
  goes off when someone deploys. `bibliohack-minio` survived only because it
  had held the old socket for seven weeks — a restart would have killed it too.

- **`Created` is not `Exited`.** If `docker ps -a` shows containers in
  `Created`, the deploy built and created them and then died *before starting
  them*. Look at the deploy job's log, not at the container logs — a container
  that never started has none.

- **A green CI is not a green deploy.** `deploy` is a separate job. Tests,
  lint, typecheck, docs and the docker build smoke can all pass while the
  deploy fails. Check the deploy job explicitly:
  `gh run view <id> -R jarcos/biblioHack --log-failed`.

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
