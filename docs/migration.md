# biblioHack — Project Migration Document

> Purpose of this file: a complete, self-contained handoff so a brand-new project/workspace can restore full context for biblioHack immediately. Generated 2026-06-15.

---

## 1. Project Purpose

**biblioHack** is a reverse catalogue + availability tracker + recommender that mirrors the Andalusian public-library OPAC (AbsysNET, the Red de Bibliotecas Públicas de Andalucía — currently the Huelva provincial library).

The official OPAC works only if you already know the title you want. biblioHack flips it: it keeps a **local, searchable mirror** of the catalogue so you can browse it like a bookshop — search in natural Spanish (accents optional), filter to the literary catalogue, see which branch has a copy on the shelf right now, import your Goodreads shelf, and get recommendations based on what you've already read.

It is also a deliberate study in doing this **politely and sustainably**: a rate-limited, capped crawler that's a good citizen of a public system; a history-preserving availability time-series; and a clean hexagonal codebase.

It is a **personal side project** by José Arcos, deployed to a self-hosted Synology NAS behind a Cloudflare Tunnel, live at **https://biblio.josearcos.me**. It is independent and **not affiliated with the Junta de Andalucía or its libraries**. It reuses public-sector bibliographic data under Spain's Ley 37/2007; derivatives must carry the CC-BY 3.0 ES attribution "Información obtenida del Portal de la Junta de Andalucía".

**Stack at a glance:** Python 3.12 / FastAPI (hexagonal/DDD modular monolith, async SQLAlchemy 2.0 + asyncpg, Typer CLI, `uv`); Astro static + React islands frontend (pnpm); PostgreSQL + TimescaleDB + pgvector + `spanish_unaccent` FTS; Scrapling (Camoufox → Patchright Chromium) crawler; covers via Pillow + content-addressed store / MinIO; OpenTelemetry → OTLP → Grafana Tempo / SigNoz; Docker Compose on a Synology NAS, Cloudflare Tunnel, GitHub Actions CI/CD.

---

## 2. Custom Instructions (CLAUDE.md — reproduced VERBATIM)

The following is the full content of `CLAUDE.md` at the repo root, exactly as written:

```markdown
# CLAUDE.md

Guidance for AI assistants working in this repo. `ARCHITECTURE.md` is the full
design; this file captures conventions that are easy to break.

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
  `ARCHITECTURE.md` §10.
- The crawl/worker plane is **not** OTel-instrumented yet; crawl health comes
  from the `scrape_tasks` status histogram + `last_error`.

## Conventions

- **Ship workflow:** commit + push to `main`; CI gates everything and then
  auto-deploys to the NAS. Never deploy on a red pipeline.
- **Backend gate before pushing** (all also enforced in CI): `ruff format
  --check .`, `ruff check .`, `mypy src`, `pytest`.
- **Migrations** ship in the api image and run (`alembic upgrade head`) on
  deploy; add an Alembic revision for every schema change.
- **Be a good OPAC citizen:** the crawler is polite by design (per-second
  throttle + per-run caps). Don't raise request rates casually — it hits a
  public library system.
```

---

## 3. Knowledge Base (files in the project that carry durable context)

This is a code repository rather than an uploaded-document project, but the following files function as its knowledge base — the durable reference material an assistant should read to understand the project. Listed by name with what each contains and contributes.

**`ARCHITECTURE.md`** (~75 KB, the master design + research doc). The single most important reference. Sections: 1 Project goals & constraints · 2 The catalog landscape (AbsysNET query forms, permalinks, expert queries) · 3 Top-level architecture · 4 Bounded contexts (DDD) · 5 Backend architecture details · 5.5 Catalogue scope — audience & literary-form classification · 6 Scraping plan (+ scrape state machine) · 7 Frontend architecture · 7.5 Book covers · 8 AI / recommender architecture · 9 Reading-history imports · 10 Deployment (Synology NAS + Cloudflare Tunnel) · 11 Roadmap · 12 Open questions & risks · 13 **Decisions already made (so we don't relitigate them)** · 14 Sources. Read §13 before proposing any architectural change.

**`CLAUDE.md`** (repo conventions for AI assistants/contributors; reproduced verbatim in §2 above). Captures the easy-to-break rules: OTel must be preserved, the ship workflow, the backend gate, migrations, and OPAC politeness.

**`README.md`** (public-facing overview). What works today, tech-stack table, repository layout, getting-started (`make dev-up`, `make backend-check`, `make frontend-check`), milestone status table (M0–M6.5 done; M7+ planned), observability, deployment, responsible-use/data notice, MIT license.

**`docs/identity-milestone-plan.md`** — the implementation plan that turned biblioHack from a single-reader homelab into a multi-user app with public registration, per-user shelves, and user-scoped recommendations. Faithful to the hexagonal/DDD layout; documents the pre-identity "current state" (no auth, globally-keyed `shelf_entries`, CLI-only imports, empty recommendations scaffolding) that the milestone replaced.

**`docs/user-accounts-action-plan.html`** — HTML rendering of the user-accounts/identity action plan (companion to the milestone plan above).

**`docs/project-summary/` (HTML mini-site)** — `index.html` (hub) plus `architecture.html`, `identity-milestone.html`, `kanban.html`, and **`pending-and-ops.html`** (the canonical living list of remaining follow-ups and operational to-dos). `favicon.svg` included. This is where the current backlog/kanban lives.

**`docs/outreach/marc-dump-request.md`** — a **draft, not-yet-sent** letter requesting a MARC-XML catalogue dump from the RBPA / Biblioteca de Andalucía (and the Junta open-data office / Registro Electrónico General as alternate channels), citing Madrid's open-data precedent. The "ask politely for the data instead of only crawling it" track.

**`homelab-josearcos-me-infra-reference.md`** (~28 KB) — full verified configuration of José's home network, Synology NAS, self-hosted Docker stack, and how `josearcos.me` is wired (Cloudflare DNS/Tunnel, Tailscale, WireGuard, OpenVPN, WordPress + biblioHack origins). Includes hard-won Synology deploy gotchas (§12) and the CI/CD auto-deploy setup (§13). Essential for any infra/deploy work; broader than biblioHack alone.

**`goodreads_library_export.csv`** — José's actual Goodreads export (95 books). The reference fixture for the reading-history import feature; columns include Title, Author, ISBN/ISBN13, My Rating, Exclusive Shelf, dates, etc. Used to exercise ISBN-13-first / fuzzy title+author matching.

**`infra/grafana/bibliohack-crawl-dashboard.json`** — versioned Grafana dashboard for crawl health (provisioned on the NAS; datasource uid `bibliohack-pg`). Live at https://grafana.josearcos.me/d/bibliohack-crawl.

**`infra/cloudflared-config.example.yml`** — documents tunnel path routing (`/api/*`, `/catalog/*`, `/healthz` → api, else static frontend). NOTE: the live tunnel is dashboard-managed (TUNNEL_TOKEN), so this example file is documentation, not the source of truth — see §4 "Tunnel routing".

**Compose files** — `docker-compose.yml` (dev), `docker-compose.prod.yml` (read+serve plane: api, frontend, postgres, redis, OTEL_* env), `docker-compose.crawler.yml` (the autonomous crawl plane, deliberately separate from CD). **`Makefile`** — convenience targets (`dev-up`, `backend-check`, `frontend-check`).

**Memory files (auto-memory, outside the repo but part of the working context)** — seven `bibliohack-*` notes: ship-workflow, nas-crawler, tunnel-routing, identity-milestone, post-identity-followups, sandbox-limits, email-routing. Their substance is folded into §4 and §5 below.

> Flag: I described `ARCHITECTURE.md`, the HTML summaries, and `homelab-…md` from their structure/headings and excerpts rather than reproducing them in full — they are large. If you need any reproduced verbatim in the new project, say so and point me at the file.

---

## 4. Key Decisions & Recurring Context

**Architecture decisions (from `ARCHITECTURE.md §13`, settled — don't relitigate):**
Full historical availability tracking (not just snapshots). Reading-history via importers (Goodreads/StoryGraph), no manual log. Astro + React islands frontend. Homelab self-hosted Docker Compose deployment. Semantic-first search, with hybrid retrieval. PostgreSQL 16 + pgvector single store (behind an `EmbeddingService`/`Embedder` port so Qdrant is a later option). Scrapling primary scraper, plain `httpx` for non-JS pages. **BGE-M3 (1024-d) embeddings hosted via the HuggingFace Inference API** (originally planned local, but NAS RAM is too tight; local adapter stays available behind the port). **OpenRouter free tier** for user-facing LLM inference only — no batch jobs. Covers are a separate bounded context, resolved asynchronously off the OPAC path, never hotlinked: Open Library is the storable primary, Google Books a display-time fallback, a deterministic placeholder is a first-class state; stored in MinIO content-addressed by sha256; lazy/popular-first. Catalogue scope = **classify, don't discard**: every accepted book is ingested and tagged with a `LiteraryProfile` (audience + literary form); default scope surfaces adult literature all genres, hiding only confidently children's/youth or non-fiction; media type is the only hard ingest-time filter.

**Layout & layering.** Hexagonal (ports & adapters) modular monolith. Bounded contexts under `backend/src/bibliohack/`: `catalog`, `holdings`, `availability`, `covers`, `identity`, `reading_history`, `recommendations`, `shared`. Each has `domain` / `application` / `infrastructure` / `interfaces` layers. Domain logic never imports a framework or driver. Auth provider functions + `get_current_user`/`get_optional_user` live in `identity/interfaces/http/dependencies.py` (NOT shared deps — avoids circular import); write endpoints use `get_tx_session` (commit-on-success) from shared deps.

**Ship workflow (recurring, important).** Commit per accomplishment in **Conventional Commits** style (`feat(catalog):`, `feat(web):`, `docs(architecture):`, `style(...)`); push to `main`; CI gates everything (backend ruff format+lint / mypy / pytest; frontend prettier/eslint/astro check/vitest; docker-build) and only a fully green pipeline auto-deploys to the NAS over Tailscale (SSH → tar-over-ssh → build + `alembic upgrade head`), followed by a post-deploy health gate against `https://biblio.josearcos.me/healthz`. **Never deploy on a red pipeline.** Run the **full-tree** gate before pushing (`ruff format --check .`) — a partial check once missed a file and CI failed. Pushing while a prior `main` run is in flight cancels it (concurrency group) — the newer run deploys both commits; "cancelled" is expected, not an error. CI docker-build can flake on Docker Hub timeouts — rerun.

**Sandbox limitation (critical for any AI working here).** The Cowork Linux sandbox is arm64 Ubuntu 22.04 with only Python 3.10; GitHub and python.org are blocked so `uv` can't fetch a 3.12 interpreter, and biblioHack uses 3.12-only syntax (PEP 695). It also **cannot do git** against the mounted repo (the macOS mount denies `.git` writes and unlink/lock-create; a sandbox `git status` can strand a `.git/index.lock` that blocks the Mac). So: run only `uvx ruff@latest` locally in the sandbox; hand `uv sync`, `mypy src`, `pytest`, and all commit/push/`gh` steps to **José's Mac**. Drive the Mac via `mcp__Control_your_Mac__osascript` → iTerm, finding the session by name containing "biblioHack" (don't rely on the current/front window). `uv sync` on the Mac needs `--extra scraper --extra covers` or it strips `w3lib`/`pillow`. Never use `backend/.venv` from the sandbox (it's macOS-only). For reading command output reliably, have the Mac write to a file in the repo, read it via the mount, then have the Mac `rm` it.

**Tunnel routing trap (recurring).** Prod is one origin (`biblio.josearcos.me`) behind a **dashboard-managed** Cloudflare tunnel (`synology-nas`, TUNNEL_TOKEN — there is NO local `config.yml` to edit; rules live in Zero Trust → Networks → Tunnels → Public Hostnames). The Astro frontend is **static** (no SSR, can't proxy). Routed to the api: `/catalog/*`, `/healthz`, and `/api/*`. Any new frontend-called API endpoint MUST live under `/api/*` (or another api-routed prefix) or it falls through to the static frontend and the browser shows `Unexpected token '<', "<!DOCTYPE "... is not valid JSON`. The tunnel does not strip prefixes — FastAPI routes must match the full public path.

**Crawler ≠ CD (recurring gotcha).** The `bibliohack-crawler` compose project is deliberately kept OUT of `docker-compose.prod.yml` so its heavy (~3.5 GB Chromium) image can never block api/frontend CD. A normal `git push` deploy does NOT rebuild/restart it. Any change to the ingest path (parser, classifier, genre derivation, ingest repo) needs a **manual** rebuild: `ssh nas-deploy 'cd /volume1/docker/bibliohack && /usr/local/bin/docker compose -p bibliohack-crawler -f docker-compose.crawler.yml up -d --build'` (~10 min). Always manage it with its own `-p bibliohack-crawler` project name so it doesn't orphan the prod containers. It runs **supercronic** with a baked crontab: hourly cursor-advancing `discover`+`worker` at :00 (catalogue growth), `refresh` every 6h at :30 (availability — offset to :30 so the shared flock doesn't starve discover). Discovery is resumable via a `discovery_cursors` table (DOC-offset cursor per expert query); `bibliohack catalog discover --reset` restarts from the top. Browser is **Patchright Chromium** (a stale StealthyFetcher docstring still says Camoufox); needs `shm_size: 1gb` + `seccomp:unconfined` on the NAS's old 4.4 kernel.

**OpenTelemetry (don't break it).** Prod api runs uvicorn under `opentelemetry-instrument` (auto-instruments FastAPI + asyncpg + Redis); no-op unless `OTEL_*` env vars are set (only in `docker-compose.prod.yml`). Keep the OTel deps in `pyproject.toml`; new outbound integrations aren't traced unless you add the matching `opentelemetry-instrumentation-*` package. Crawl plane is not OTel-instrumented; its health comes from the `scrape_tasks` status histogram + `last_error`, surfaced in the Grafana crawl dashboard.

**Email / domain.** `josearcos.me` receives via **Cloudflare Email Routing** (no catch-all; `hello@` and `privacy@` forward to José's gmail; unrouted addresses 550-bounce). Sending is **Mailgun EU** (`smtp.eu.mailgun.org:587`, domain `mail.josearcos.me`, user `alerts@mail.josearcos.me`); only SMTP creds are in the NAS `.env` (no Mailgun HTTP API key stored — the SMTP password is rejected by the API with 401). Gotcha: after a 550 hard bounce Mailgun suppresses the address (later sends fail locally with `605`); to re-test, `DELETE` the bounce via the Mailgun EU API then resend. Outbound port 25 from the Mac is blocked, so test delivery only via Mailgun + its events log. No DMARC record (SPF only).

**Infra quick-reference.** NAS SSH alias `nas-deploy` (LAN `192.168.1.130:2222`, Tailscale `100.76.144.26`); docker at `/usr/local/bin/docker`; repo on NAS at `/volume1/docker/bibliohack`. Testcontainers on the Mac need `DOCKER_HOST=unix://$HOME/.orbstack/run/docker.sock` (OrbStack, no `/var/run/docker.sock`). Grafana crawl dashboard provisioned read-only via the postgres_exporter `metrics` user.

**Terminology.** OPAC = the public library catalogue (AbsysNET). TITN = the catalogue's per-record id (TITN-ascending; new acquisitions get high TITNs). DOC = the AbsysNET results-list offset the crawler jumps to. "Literary scope" = the default adult-literature filter. CDU = the Spanish library classification used to derive genre. RBPA = Red de Bibliotecas Públicas de Andalucía.

---

## 5. Work in Progress

**Shipped milestones (all done, deployed, verified live):** M0 foundations · M1 catalogue ingest + accent-insensitive search + literary scoping · M2 availability history + autonomous resumable crawler · M2.5 covers · M3 semantic search (BGE-M3 + pgvector), then **hybrid search** (RRF fusion, `?mode=hybrid`, shipped 2026-06-11) · M4 Goodreads import · M5 recommender v1 (user-scoped, taste-centroid + pgvector KNN, optional OpenRouter rationales) · **Identity milestone phases 0–5** (public registration, email verification, Turnstile, Redis sessions, GDPR export/delete, Redis fixed-window rate limits — all shipped 2026-06-10) · M6.5 CI/CD auto-deploy · plus shelf re-import UX (2026-06-11) and the **catalog navigator Tier A+B** (`/browse` + faceted `GET /catalog/browse` + `GET /catalog/authors`, genre column via CDU, shipped 2026-06-12). José's Goodreads shelf has been imported.

**Latest prod stats (2026-06-12):** ~19,480 records growing ~4–5k/day; scrape_tasks 19,467 parsed / 896 skipped / 198 failed; embeddings ~32%; genre known ~5,024 of the mirror.

**Remaining backlog / ongoing (canonical list: `docs/project-summary/pending-and-ops.html`):**

- **Operational to-dos:** verify `privacy@josearcos.me` delivery end-to-end; ensure `OPENROUTER_API_KEY` is set in the NAS `.env` (required for recommendation rationales). (Shelf re-import is done.)
- **Deferred features:** LLM query rewriting + cold-start handling; StoryGraph importer; audience / literary-form UI badge + toggle; OTel instrumentation on the crawler plane; edge rate limits; catalog navigator **Tier C** (author country via BNE/Wikidata).
- **Roadmap (M7+):** hybrid retrieval refinements, expansion to **other Andalusian provinces** beyond Huelva (M7), **mobile app** reusing the same API (M8).
- **Outreach track:** the MARC-dump request to the RBPA (`docs/outreach/marc-dump-request.md`) is drafted but **not sent** — decide on recipient and send to potentially obtain the catalogue as open data instead of (only) crawling.

**Standing operating reminder:** on each completed accomplishment, commit + push to `main` and verify the NAS auto-deploy (health gate green). Hand all git/gate steps to the Mac per the sandbox limitation above.

---

## 6. Starting Prompt (paste into the new project's first conversation)

```
You are assisting on biblioHack, my personal side project: a reverse catalogue,
availability tracker, and recommender that mirrors the Andalusian public-library
OPAC (AbsysNET / Red de Bibliotecas Públicas de Andalucía, currently Huelva).
Live at https://biblio.josearcos.me. Independent, not affiliated with the Junta;
reuses public data under CC-BY 3.0 ES ("Información obtenida del Portal de la
Junta de Andalucía").

Stack: Python 3.12 / FastAPI hexagonal-DDD modular monolith (async SQLAlchemy 2.0
+ asyncpg, Typer CLI, uv), bounded contexts under backend/src/bibliohack/
(catalog, holdings, availability, covers, identity, reading_history,
recommendations, shared), each layered domain/application/infrastructure/
interfaces; Astro static + React islands frontend (pnpm); PostgreSQL + TimescaleDB
+ pgvector + spanish_unaccent FTS; Scrapling (Patchright Chromium) crawler;
covers via MinIO content-addressed store; OpenTelemetry → OTLP → Grafana Tempo /
SigNoz; Docker Compose on a Synology NAS behind a Cloudflare Tunnel; GitHub
Actions CI/CD.

Read these first: CLAUDE.md (conventions), ARCHITECTURE.md (full design — esp.
§13 "Decisions already made", don't relitigate), README.md, and
docs/project-summary/pending-and-ops.html (the live backlog).

Rules I rely on:
1. Ship workflow: commit per accomplishment (Conventional Commits), push to main;
   CI gates (backend: ruff format --check . / ruff check . / mypy src / pytest;
   frontend: prettier/eslint/astro check/vitest; docker-build) and only a fully
   green pipeline auto-deploys to the NAS, with a /healthz post-deploy gate.
   Never deploy on red. Run the FULL-tree ruff format check before pushing.
2. Sandbox can't run the backend gate or git: it has only Python 3.10 and can't
   reach GitHub/python.org, and can't write the repo's .git. Run only
   `uvx ruff@latest` in the sandbox; hand `uv sync` (needs
   --extra scraper --extra covers), mypy, pytest, and all commit/push/gh steps to
   my Mac (drive iTerm via osascript, find the session named "biblioHack").
3. Add an Alembic migration for every schema change.
4. Be a good OPAC citizen — the crawler is rate-limited and capped; never make it
   more aggressive. It hits a live public-library system.
5. Don't break OpenTelemetry: keep the opentelemetry-instrument CMD in
   infra/backend.Dockerfile and the OTel deps in pyproject.toml.
6. Tunnel routing: any new frontend-called API endpoint must live under /api/*
   (or another api-routed prefix) or it falls through to the static frontend and
   returns page HTML instead of JSON. The tunnel is dashboard-managed (no local
   config.yml).
7. Crawler ≠ CD: the bibliohack-crawler compose project does NOT auto-deploy; any
   ingest-path change needs a manual rebuild on the NAS
   (docker compose -p bibliohack-crawler -f docker-compose.crawler.yml up -d --build).

All M0–M6.5 + Identity + hybrid search + catalog navigator Tier A/B are shipped
and live. Open items: set OPENROUTER_API_KEY on the NAS, verify privacy@ mail
delivery; deferred — StoryGraph importer, LLM query rewriting, audience/form UI
toggle, OTel on the crawler, Tier C author-country, more provinces (M7), mobile
app (M8); the RBPA MARC-dump request is drafted but unsent.

Start by confirming you've read CLAUDE.md and ARCHITECTURE.md §13, then ask me
what we're working on.
```

---

*Flagged uncertainties: this document is built from the repo files, the seven `bibliohack-*` memory notes, and the project instructions. Memory notes are point-in-time (dated 2026-06-01 → 06-13); live prod numbers and the exact backlog may have moved since. Verify `docs/project-summary/pending-and-ops.html` and current code before treating any specific claim as live state.*
