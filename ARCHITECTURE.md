# biblioHack — Architecture & Research

A reverse catalog and AI-driven book recommender for the Andalusian public-library network, bootstrapped from the **Biblioteca Provincial de Huelva**.

> Status: research and design draft, May 2026. No code written yet — this document is the contract we agree on before scaffolding the repo. Items marked **OPEN** require a decision or further verification.

---

## 1. Project goals and constraints

- **Mirror** the bibliographic catalog of the Red de Bibliotecas Públicas de Andalucía (RBPA), starting with Huelva, into a database we own.
- Track **historical availability** per copy (loaned vs. on shelf) so we can analyse loan patterns over time.
- Allow the user to **import their reading history** from Goodreads (and later StoryGraph, Hardcover, BookWyrm) to feed an AI recommender.
- Provide a **semantic-first search** experience and an **AI-driven recommender** that considers what the user has read and what is currently available at their preferred branch.
- All open-source, self-hosted on a homelab, side project, no monetization for now.
- Backend in FastAPI; frontend in Astro + React islands.
- DDD + hexagonal architecture, TDD, SOLID — front and back.

Non-goals for v1: account integration with the library (loaning books from the app), mobile app (later), supporting Andalusian university libraries (CBUA) or specialised documentation centres.

---

## 2. The catalog landscape

### 2.1 What software does Andalucía use?

The Red de Bibliotecas Públicas de Andalucía runs on **AbsysNET** (by Baratz). All eight Provincial State Public Libraries — including Huelva — plus municipal, supramunicipal, neighbourhood libraries and bookmobiles are integrated into a single collective catalog. The Madrid open-data community migrated to AbsysNet 2.2 alongside Andalucía. ([Comunidad Baratz](https://www.comunidadbaratz.com/blog/la-red-idea-y-la-red-de-bibliotecas-publicas-de-andalucia-ya-estan-en-absysnet-2-2/), [Junta de Andalucía — RBPA](https://www.juntadeandalucia.es/organismos/culturaydeporte/areas/cultura/bibliotecas-documentacion/red-publicas.html))

Relevant entry points:

| Catalog | URL | Notes |
| --- | --- | --- |
| RBPA collective OPAC | <https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi?ACC=101> | Federated; we filter to Huelva via `SUBC` |
| Catálogo Colectivo del Patrimonio Bibliográfico Andaluz | <https://www.juntadeandalucia.es/cultura/absys/ccpba/abnetcl.cgi?FORM=2> | Heritage subset |
| National Collective Catalog (CCBIP) | <https://catalogos.cultura.gob.es/CCBIP/ccbipopac/> | Wraps all autonomous regions, also AbsysNet |
| Biblioteca Provincial de Huelva landing page | <https://www.bibliotecasdeandalucia.es/web/biblioteca-del-estado-publica-provincial-de-huelva/catalogos/catalogo-de-la-biblioteca> | UI for end-users |

### 2.2 Is there a public API?

**No usable bibliographic API for Andalucía.** The good news: AbsysNet *ships* an "API module", MOPAC, digital-library extensions and the rest — but Comunidad Baratz confirms that several of those are **not currently in operation** for the Andalucía install. ([Comunidad Baratz](https://www.comunidadbaratz.com/blog/la-red-idea-y-la-red-de-bibliotecas-publicas-de-andalucia-ya-estan-en-absysnet-2-2/))

What does exist:

- **Library directory** (just metadata about the libraries themselves, not their holdings): `https://datos.juntadeandalucia.es/api/v0/libraries/all?format=json` — OpenAPI spec at `/openapi.json`. ([datos.gob.es dataset](https://datos.gob.es/en/catalogo/a01002820-bibliotecas-y-centros-de-documentacion-de-andalucia))
- **Andalusian government publications** (only what the Junta itself edits): XML/Atom feed.
- **Andalucía does NOT publish a MARC-XML dump** of the public-library catalog. The Comunidad de Madrid does ([193 + 192 MB MARC-XML on datos.gob.es](https://datos.gob.es/en/catalogo/a13002908-catalogo-bibliografico)) — that is the precedent we should lobby Junta to follow, but for now we have to scrape. **OPEN:** worth a formal email to the RBPA coordinator asking whether a periodic MARC dump can be released.

### 2.3 What we can actually rely on: stable OPAC URLs

AbsysNet exposes a documented CGI parameter scheme that gives us deterministic URLs. ([Comunidad Baratz — URLs estables](https://www.comunidadbaratz.com/blog/como-crear-urls-estables-al-opac-de-absysnet-y-no-morir-en-el-intento/), [Comunidad Baratz — Consultas por URL](https://www.comunidadbaratz.com/blog/como-lanzar-consultas-bibliograficas-a-absysnet-traves-de-la-url-del-opac/))

Search variables:

| Variable | Field |
| --- | --- |
| `xsqf01` | Any field |
| `xsqf02` | Title |
| `xsqf03` | Author |
| `xsqf04` | Publisher |
| `xsqf05` | Subject |
| `xsqf06` | Collection |
| `xsqf07` / `xsqf08` | Date from / to |
| `xsqf99` | Expert query (supports operators `y`, `o`, `adj`, `mismo`, and field-coded queries like `(comic.t650.)`) |
| `TITN` | Stable per-record permalink |
| `SUBC` | Branch / sublibrary filter |

A few load-bearing examples:

```
# Free-text search:
https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi?ACC=DOSEARCH&xsqf02=cazadores+sombras

# Stable permalink to a record:
https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi?TITN=12345

# Expert query (everything in Huelva published after 2015):
https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi?ACC=DOSEARCH&xsqf99=(@fepu>=2015)&SUBC=...
```

`TITN` is the keystone: every record has a stable integer ID that gives us a deterministic permalink. The crawl strategy becomes: enumerate the TITN space (or seed it via paged result sets), fetch detail pages, parse.

### 2.4 Existing open-source initiatives

- **opacapp / opacclient** (Java, GitHub, MIT) — an Android app and the underlying `libopac` library claim to support 1000+ libraries including some AbsysNet instances. **Archived as of 2024-12-25, end-of-life from 2024-06-30**, so it is a *reference* for HTML parsing patterns, not a dependency. ([opacapp/opacclient](https://github.com/opacapp/opacclient))
- **VideLibri** (Pascal/Free Pascal, GitHub, GPL) — cross-platform OPAC automation client. Supports ~200 libraries, mostly DE/CH/AT, but the engine can be pointed at AbsysNet with custom XPath. ([benibela/videlibri](https://github.com/benibela/videlibri))
- **Nothing public-facing for Andalucía specifically.** A targeted GitHub search for `absysnet` + Spanish public libraries returned no maintained Python projects. We are in clear water.
- **Madrid bibliographic dump** ([datos.comunidad.madrid](https://datos.comunidad.madrid/dataset/catalogo_bibliografico_completo)) — full MARC-XML, redistributed via datos.gob.es. License is open per the Spanish PSI rules; the exact CC variant on the resource page should be re-read before redistribution. Useful as a *known-good MARC corpus* to bootstrap parsers and embeddings while we wait on Huelva data.

### 2.5 Legal and ethical notes

- The catalog data itself is public information published by a public administration; the rules of *reutilización de información del sector público* (Spanish Law 37/2007 / EU PSI Directive) lean toward "reuse is allowed unless explicitly restricted". A formal review of the OPAC's *aviso legal* is **OPEN**.
- Be polite. The OPAC runs on modest hardware. The crawl plan in §6 assumes 1 request/second at most, exponential backoff on errors, off-hours scheduling, and a contact email in the `User-Agent`. No headless-browser fingerprint evasion — we identify ourselves.
- We must respect `robots.txt`. **OPEN:** verify the current `robots.txt` for `juntadeandalucia.es/cultura/absys/...` before the first crawl.

---

## 3. Top-level architecture

The high-level shape you sketched maps cleanly onto a hexagonal backend with a static-first frontend:

```
┌───────────────────────┐   polite, throttled HTTP   ┌─────────────────────┐
│  AbsysNet OPAC        │ ◄────────────────────────► │  Fetch worker       │
│  (Junta de Andalucía) │                            │  (Scrapling + Camoufox)
└───────────────────────┘                            └──────────┬──────────┘
                                                                │ raw HTML snapshots + parsed records
                                                                ▼
                                                     ┌─────────────────────┐
                                                     │ PostgreSQL 16        │
                                                     │   + pgvector         │
                                                     │   + (TimescaleDB?)   │
                                                     └──────────┬──────────┘
                                                                │
                                          ┌─────────────────────┼─────────────────────┐
                                          ▼                     ▼                     ▼
                                   ┌─────────────┐      ┌──────────────┐      ┌─────────────┐
                                   │ Embeddings  │      │  FastAPI     │      │ Recommender │
                                   │ pipeline    │      │  domain API  │      │  service    │
                                   │ (BGE-M3)    │      │              │      │ (OpenRouter)│
                                   └─────────────┘      └──────┬───────┘      └──────┬──────┘
                                                               │                     │
                                                               ▼                     ▼
                                                       ┌──────────────────────────────┐
                                                       │ Astro + React islands         │
                                                       │ (TanStack Query, Tailwind)    │
                                                       └──────────────────────────────┘
                                                                ▲
                                                                │
                                                       ┌──────────────────────────────┐
                                                       │ Web / Mobile clients          │
                                                       └──────────────────────────────┘
```

This adds two boxes to your original sketch — an embeddings pipeline and a recommender service — but keeps the same backbone.

---

## 4. Bounded contexts (DDD)

Six contexts. Each one is a **module** in the backend repo (`packages/<context>/`) with its own `domain/`, `application/`, `infrastructure/` and `interfaces/` folders. The hexagon is per context, not per repo — a common rookie mistake is to draw one giant hexagon for the whole app; what you actually want is one per context, with explicit contracts (DTOs or events) between them.

| Context | Aggregates | Ports (interfaces) | Adapters |
| --- | --- | --- | --- |
| **Catalog** | `BibliographicRecord` (root), `Edition`, `Contributor`, `Subject` | `BibliographicRepository`, `OpacGateway`, `EmbeddingService` | Postgres repo, AbsysNet HTML adapter, sentence-transformers adapter |
| **Holdings** | `Copy` (root), `Branch`, `Signature`, `Loan` | `HoldingsRepository`, `OpacGateway` | Postgres repo, AbsysNet adapter |
| **Availability** | `AvailabilitySnapshot` (root, immutable) | `AvailabilityRepository`, `AvailabilityProbe` | Postgres / Timescale repo, AbsysNet adapter |
| **ReadingHistory** | `Bookshelf` (root), `ReadEntry`, `Rating`, `ImportJob` | `BookshelfRepository`, `Importer` | Postgres repo, Goodreads CSV adapter, StoryGraph CSV adapter |
| **Recommendations** | `Recommendation` (root), `RecommendationRequest` | `RecommendationRepository`, `RecommenderEngine`, `LlmClient` | Postgres repo, hybrid retriever (FTS + pgvector), OpenRouter adapter |
| **Identity** | `User` (root), `Preference` | `UserRepository`, `AuthProvider` | Postgres repo, local password auth (Argon2id) |
| **Covers** | `Cover` (root) | `CoverRepository`, `CoverProvider`, `CoverStore`, `ImageProcessor` | Postgres repo, OpenLibrary/GoogleBooks/Absys providers, MinIO store, Pillow processor (see §7.5) |

**Cross-context communication.** Catalog and Holdings are tightly coupled (you can't have a holding without a record), but the relationship is *navigational by ID*, not foreign-key chasing across module boundaries. ReadingHistory references catalog records by an opaque `BibliographicRecordId` — it does not load `BibliographicRecord` directly. Recommendations integrate via published domain events (`BookRead`, `BookRated`, `CatalogRecordIndexed`) consumed through an in-process event bus (start with `blinker` or a tiny custom dispatcher; only move to Redis Streams / NATS when we actually need it).

**SOLID applied:**

- *S* — each context handles one reason to change. Catalog ingestion changes do not ripple into the recommender.
- *O* — adding a second OPAC vendor (e.g. Koha for a future migration) means a new adapter implementing `OpacGateway`, not editing the domain.
- *L* — the `OpacGateway` port doesn't leak HTML-specific quirks. Stub adapters used in tests are full substitutes.
- *I* — `RecommenderEngine` doesn't drag in `OpacGateway`. Each port is small.
- *D* — domain depends on abstractions; concrete `httpx`, `asyncpg`, `sentence-transformers` calls live only in infrastructure.

---

## 5. Backend architecture details

### 5.1 Tech stack

- Python **3.12+** (3.13 once SQLAlchemy 2.0+ is fully clean on it).
- **FastAPI** + Pydantic v2 for the HTTP layer.
- **SQLAlchemy 2.0** (Core + ORM hybrid; ORM for write models, Core for analytical reads) + **Alembic** migrations.
- **asyncpg** as the DB driver; everything in the I/O path is `async`.
- **Scrapling** ([D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling)) as the primary scraper — its `StealthyFetcher` (Camoufox-based) gives us anti-bot resilience and its adaptive selectors survive minor HTML drift. Falls back to plain `httpx` when no JS rendering is needed (AbsysNet is mostly server-rendered HTML, so the heavy fetcher is only needed when we hit JS-driven gates). ([Scrapling docs](https://scrapling.readthedocs.io/en/latest/index.html))
- **Dramatiq** + Redis (or **APScheduler** in-process for v0) for background scraping/embedding jobs.
- **sentence-transformers** with **BGE-M3** (multilingual, 1024-dim, strong Spanish performance) for embeddings, run locally on the homelab. The catalog is ~1.5M records; ~6GB of vectors at float32, ~1.5GB at int8 quantised. ([BGE-M3 / multilingual embeddings overview](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models))
- **OpenRouter** for LLM reasoning (recommendation explanations, query rewriting, cold-start classification). Free-model rate limits are tiered: ~20 RPM and 50 requests/day for free accounts, lifted to 1,000 requests/day once the account holds ≥$10 in credits. Either way it is **enough for user-facing inference but not enough for batch jobs** — so we *never* batch-embed via OpenRouter. ([OpenRouter free models](https://openrouter.ai/collections/free-models))
- **Testing**: `pytest`, `hypothesis` (property-based), **testcontainers** for real-Postgres integration tests, **schemathesis** for FastAPI contract tests, **respx** to record AbsysNet HTML fixtures, **pytest-cov` ≥90% on domain code.
- **Code quality**: `ruff` (lint + format), `mypy --strict` on domain and application layers (relax to `--strict-optional` only on infrastructure), `pre-commit`.

### 5.2 Database choice — semantic-first, time-series capable

You asked about MongoDB. For *this* shape — semantic-first search, relational holdings, time-series availability — **Postgres 16 + pgvector** is the right answer. Reasons:

1. **One store** for relational data, vectors, and (with the TimescaleDB extension) the availability time series. Fewer moving parts to maintain in a homelab. ([2026 vector-DB benchmarks](https://callsphere.ai/blog/vector-database-benchmarks-2026-pgvector-qdrant-weaviate-milvus-lancedb))
2. **Scale is small for vectors.** 1.5M records × 1024-dim is well within pgvector's comfortable range (HNSW indexes hold up cleanly to ~10M). Qdrant is faster, but the operational simplicity of staying on Postgres is worth more than the marginal latency, and we can always swap in Qdrant behind the existing `EmbeddingService` port if we hit a wall — that's exactly what hexagonal architecture is for.
3. **ACID for holdings.** Concurrent scraping workers touching holdings and availability benefit from real transactions.
4. **Full-text search out of the box** (`tsvector`) for the hybrid retriever, avoiding a separate Meilisearch/Elasticsearch service.

Schema sketch (just the headline tables — full DDL in Alembic later):

```
bibliographic_records (
  id              uuid PK,
  titn            int UNIQUE NOT NULL,           -- AbsysNet permalink id
  title           text NOT NULL,
  subtitle        text,
  authors         text[],                        -- denormalised for fast read; canonical in contributors
  isbn_10/isbn_13 text,
  language        text,
  pub_year        int,
  publisher       text,
  subjects        text[],
  summary         text,
  marc_raw        jsonb,                         -- whatever MARC-ish blob we recovered
  fts             tsvector GENERATED ALWAYS AS (...) STORED,
  embedding       vector(1024),                  -- BGE-M3
  first_seen_at   timestamptz NOT NULL,
  last_seen_at    timestamptz NOT NULL,
  source_hash     bytea                          -- hash of raw HTML, drives re-parse decisions
)
copies (
  id              uuid PK,
  record_id       uuid FK -> bibliographic_records,
  branch_code     text NOT NULL,                 -- SUBC value
  signature       text,                          -- e.g. "N MUR cor"
  barcode         text,
  active          boolean NOT NULL DEFAULT true
)
availability_snapshots (   -- time-series, append-only
  copy_id         uuid FK -> copies,
  observed_at     timestamptz NOT NULL,
  status          text NOT NULL,                 -- 'available' | 'loaned' | 'reserved' | 'unavailable' | 'unknown'
  due_back_at     date,
  PRIMARY KEY (copy_id, observed_at)
)  -- candidate for hypertable via Timescale
bookshelves (id, user_id, name, ...)
read_entries (id, bookshelf_id, record_id NULLABLE, isbn_13 NULLABLE, title, author, rating, read_at, raw_source jsonb)
recommendations (id, user_id, record_id, score, rationale_text, generated_at, model_id)
```

Note `read_entries.record_id` is **nullable**: Goodreads will give us books that don't exist in Huelva, and the recommender still benefits from knowing about them as taste signal. They get matched against the catalog lazily.

### 5.3 Hexagonal repository layout (Python)

```
backend/
├── pyproject.toml
├── docker-compose.yml
├── alembic/
└── src/
    └── bibliohack/
        ├── shared/
        │   ├── domain/          # base Entity, ValueObject, DomainEvent
        │   ├── application/     # base UseCase, Result types
        │   └── infrastructure/  # event bus, settings, logging, telemetry
        ├── catalog/
        │   ├── domain/
        │   │   ├── model.py
        │   │   ├── events.py
        │   │   └── services.py
        │   ├── application/
        │   │   ├── ports.py           # OpacGateway, BibliographicRepository, EmbeddingService
        │   │   ├── use_cases/
        │   │   │   ├── ingest_record.py
        │   │   │   ├── reindex_record.py
        │   │   │   └── search_catalog.py
        │   │   └── dto.py
        │   ├── infrastructure/
        │   │   ├── absysnet/         # HTML parser, URL builder, throttler
        │   │   ├── postgres/         # SQLAlchemy mappers, repository impl
        │   │   └── embeddings/       # sentence-transformers adapter
        │   └── interfaces/
        │       ├── http/             # FastAPI router
        │       └── jobs/             # Dramatiq actors / APScheduler jobs
        ├── holdings/        # same layout
        ├── availability/    # same layout
        ├── reading_history/ # same layout
        ├── recommendations/ # same layout
        └── identity/        # same layout
```

The `application/ports.py` files are the heart of the hexagonal discipline. Every concrete dependency (HTTP client, DB session, model) is constructed in `infrastructure/` and injected via FastAPI's `Depends` (or a small DI container — `lagom` is a good lightweight choice). The domain layer **never** imports from `infrastructure/`.

### 5.4 TDD strategy

Test pyramid, top-to-bottom:

1. **Unit tests** — domain (`shared/domain/`, `<context>/domain/`) and use cases. Fast, no I/O. Property-based via `hypothesis` for invariants (e.g. "a `Loan` interval never has negative duration", "a `BibliographicRecord` with the same `titn` is always equal regardless of construction order").
2. **Adapter integration tests** — each adapter implementation is tested against its real dependency via `testcontainers` (Postgres, Redis). The AbsysNet parser is tested against a folder of saved HTML fixtures (snapshotted real responses). This is the *single most important* test suite: HTML drift will break us, and snapshot tests catch it the day it happens.
3. **Contract tests** — `schemathesis` generates random valid inputs against the FastAPI OpenAPI schema, catching serialisation drift between the API and the frontend.
4. **End-to-end** — Playwright drives the Astro UI against the full Docker Compose stack, asserting on a small smoke-test catalog.

Coverage targets: domain & application ≥95%, infrastructure ≥75%, interfaces ≥60%. We *don't* chase 100% — coverage measures the wrong thing on adapter code.

---

## 6. Scraping plan

### 6.1 Tool choice

**Primary: [Scrapling](https://github.com/D4Vinci/Scrapling).** It gives us three things we want:

- `StealthyFetcher` (Camoufox-backed) for any page where Cloudflare-style protection appears.
- Adaptive selectors that re-locate elements when class names drift — relevant because AbsysNet OPAC themes vary across deployments.
- Native async fetcher with a session/spider abstraction supporting pause/resume.

**Fallback: plain `httpx` + `selectolax`** for the 90% of pages that don't need a browser. AbsysNet detail pages are server-rendered HTML; we don't pay the browser cost for those. The decision happens in the `OpacGateway` adapter — domain code never sees either tool.

Why not Crawl4AI or Firecrawl: both optimise for "give me clean Markdown for an LLM". We need *structured* extraction from a well-known HTML shape, and we want to keep operating costs at zero (Crawl4AI requires Playwright + LLM credits for its structured-extraction mode; Firecrawl is a paid SaaS). ([Crawl4AI vs Firecrawl 2026](https://brightdata.com/blog/ai/crawl4ai-vs-firecrawl), [Best Python scraping libraries 2026](https://oxylabs.io/blog/python-web-scraping-libraries))

### 6.2 Crawl strategy

Three phases, in order:

1. **Discovery** — enumerate `TITN` IDs we don't yet know about. Two strategies in tandem:
   - *Letter walk*: for each combination of `xsqf02=a*`, `xsqf02=b*`, …, page through the result set. Tedious but exhaustive.
   - *Expert query slicing*: `xsqf99=(@fepu>=2024) y (@fepu<2025)` to slice the publication-year axis. Hits the "novedades" cohort first, which is the most user-relevant.
2. **Ingest** — for each `TITN`, fetch the permalink (`?TITN=N`), parse, persist `BibliographicRecord` + `Copy` rows, snapshot raw HTML to S3-compatible storage (or `~/biblioHack-data/` on the homelab) with content-addressed naming.
3. **Refresh** — re-fetch records on a tiered schedule:
   - New / never-seen: ingest immediately.
   - High-availability churn (loaned out often): re-probe daily.
   - Stable backlist: re-probe monthly.
   - Use the source-hash to skip parsing when nothing has changed.

### 6.3 Politeness budget

| Setting | Value |
| --- | --- |
| Max concurrent requests | 1 (yes, single-threaded — the OPAC is shared infrastructure) |
| Request interval | ≥1 s, jittered to 1.0–1.8 s |
| Time window | 02:00–07:00 Europe/Madrid (low library-staff usage) |
| Daily request cap | 30,000 |
| Backoff on 5xx | Exponential, base 30 s, cap 30 min, abort run after 3 consecutive caps |
| `User-Agent` | `bibliohack/0.x (+contact-email)` — clearly identified |
| `robots.txt` | Honoured strictly; verify before each run |

A full first-pass crawl of ~1.5M records at 1 req/s with 5-hour nightly windows ≈ 18,000 requests/night, so ~12 weeks for the initial corpus. That's fine — it's a side project and the OPAC will thank us. After bootstrap, the incremental rate is well under 1k requests/night.

### 6.4 The MARC question — resolved (no, parse HTML)

Verified against the live OPAC (May 2026, TITN=1): **there is no public MARC export.** The "Enviar a" dialog offers Dublin Core, Google Scholar, RIS and RefWorks. RIS and Dublin Core are usable as supplementary structured sources but neither carries holdings/availability — the data we want most. So we commit to parsing the **rendered HTML**.

Two consequences flow from this:

1. **The OPAC is a JavaScript-rendered SPA.** Plain `httpx` returns a near-empty boilerplate document. The fetcher must execute JS — **Scrapling's `StealthyFetcher`** (Camoufox-backed) is the primary, with Playwright as fallback. There is no "lightweight" path.
2. **Sessions are required.** Hitting `?TITN=N` 302-redirects to `/abnetcl.cgi/{SESSION_TOKEN}?ACC=161`. The session token is per-browser; our fetcher must either (a) keep one long-lived session per worker run, or (b) accept the redirect and let each request bootstrap its own. We start with (b) for simplicity; switch to (a) only if rate-limiting penalises new sessions.

The rendered record page exposes everything M1 needs: title, author (linked under "Otras obras de"), publisher, document type, per-branch copy list with availability flags, and lifetime loan count. The "Más información" tab additionally provides "Otras ediciones" (related editions) which will help us cluster works in M3.

The "Formato → Visualización Etiquetas" dropdown on Más información hints at an ISBD/MARC-tag view; left as an optimisation for later (M2+) if HTML drift bites us.

### 6.5 Vocabulary — discovery vs. scraping vs. importing

These three words refer to three different operations and we keep them strictly separate in code (module names, function names, log fields). Mixing them is the most common way for crawler codebases to turn into mud:

- **Discovery** — figure out *what exists*. The output is a set of `TITN` identifiers we hadn't seen before. No bibliographic data is extracted yet; we just learn that record #842,193 exists.
- **Scraping** (= *fetching* + *parsing*) — for a known `TITN`, retrieve the HTML/MARC, parse it into typed fields, persist a `BibliographicRecord` + its `Copy` rows. This is the heavy work and the only step that touches the OPAC's `?TITN=N` permalinks.
- **Refreshing** — re-fetch a `TITN` we already know about, on a tiered cadence, to detect drift (title corrections, new copies, withdrawn items). Refreshes share the scraper but use the `source_hash` to short-circuit the parse step when nothing has changed.
- **Importing** — consume a *structured external feed* (Goodreads CSV, BNE RDF dump, our own backup file). Importing **never** touches the OPAC. Reading-history imports land in M4; an optional BNE authority-record import in M5.

Authors are not a thing we discover — they fall out as a side-effect of scraping records. We don't need a Spanish-writers seed list to start. Authority data from datos.bne.es (Linked Open Data, ~1.4M entities) becomes useful later for author deduplication and a cold-start recommender, but it's not on the M1 critical path.

### 6.6 Discovery strategy — TITN enumeration first, letter walks for freshness

Two complementary discovery strategies:

1. **TITN enumeration (primary).** `TITN` is a sequential integer permalink. We don't yet know its range. First task: a *probe* — binary-search by hitting a handful of well-chosen IDs (`?TITN=10000`, `?TITN=100000`, `?TITN=1000000`, ...) and observing where "no se ha encontrado" responses begin. Once the upper bound is known (likely 1–2M), we enumerate. Gaps from deletions become `not_found` rows in the state table — that's information, not a failure.

2. **Letter walks (secondary, for refresh).** Use `xsqf02=a*`, `xsqf02=b*` … paged result sets to find newly-cataloged records on the recurring schedule. Sliced by `xsqf07` (publication-date-from) to keep the cost bounded.

Bootstrap uses (1) once. The daily refresh job uses (2) plus a small re-scrape of the hot subset.

### 6.7 State model — the `scrape_tasks` table

Idempotency, crash safety, and refresh scheduling all depend on a dedicated state table separate from `bibliographic_records` (the lifecycles are different):

```sql
scrape_tasks (
  titn               int PRIMARY KEY,
  status             text NOT NULL,         -- discovered | fetched | parsed | failed | not_found | tombstoned
  source_hash        bytea,                 -- sha256 of the raw HTML/MARC payload
  source_seen_at     timestamptz,           -- last time we observed the record (any status)
  attempt_count      int NOT NULL DEFAULT 0,
  last_attempted_at  timestamptz,
  next_retry_at      timestamptz,           -- exponential-backoff target
  last_error         text,
  priority           int NOT NULL DEFAULT 100,  -- lower = sooner; refresh tiers manipulate this
  refresh_due_at     timestamptz            -- when this record is eligible for re-fetch
)
```

**State machine:**

```
                ┌──────────────┐
   discover  →  │  discovered  │  ← bulk seeded by discovery sweep
                └──────┬───────┘
                       │ worker locks via SELECT ... FOR UPDATE SKIP LOCKED
                       ▼
                ┌──────────────┐         404
                │   fetched    │  ───────────────→  not_found  (no retry, no body)
                └──────┬───────┘
                       │ parse + persist BibliographicRecord
                       ▼
                ┌──────────────┐  same hash on next refresh → status stays parsed, source_seen_at bumped
                │    parsed    │  different hash             → re-parse + upsert
                └──────────────┘
                       │ retried on schedule (refresh tiers)
                       ▼

  on transient error (5xx, timeout):
    attempt_count++, exponential backoff into next_retry_at, status='failed' once attempts > 5
```

**Properties this gives us:**

- **Idempotent reruns** — re-running the worker is safe; `parsed` rows are skipped unless their refresh schedule (driven by `refresh_due_at` + `priority`) says they're due.
- **Crash safety** — `SELECT ... FOR UPDATE SKIP LOCKED` means multiple workers can run concurrently and a killed worker doesn't block its row forever (Postgres releases the lock with the transaction).
- **Drift detection** — `source_hash` (sha256 of the raw payload) lets us skip the parser when the upstream HTML/MARC hasn't changed; cheap full-record-equivalence check.
- **Politeness accounting** — a separate `scrape_log(observed_at, titn, status_code, latency_ms)` table feeds the daily-cap and rate-limit enforcement across worker restarts.
- **Tombstoning** — records the OPAC has actively removed go to `tombstoned`, distinct from `not_found` (gap) so we can audit.

### 6.8 Scheduling — three cadences, not one

| Job | Cadence | What it does |
|---|---|---|
| **Initial bootstrap** | once | Range probe + full TITN sweep. Runs for weeks (1 req/s, 5-hour night window ≈ 12 weeks for ~1.5M records). |
| **New-records sweep** | daily, 02:00 Europe/Madrid | Letter walk for records added since yesterday (via `@copi` and `@fepu` slices). |
| **Refresh tiers** | continuous, prioritised | Re-fetch by hotness: novedades daily, mid-list weekly, backlist monthly. Driven by `refresh_due_at`. |
| **Availability probe** (M2) | hourly, hot subset only | Just the loan-status field of currently-loaned items, populates the availability time-series. |

We drive these with **APScheduler** for cron-style triggers and **Dramatiq** for the per-record work queue (APScheduler enqueues into Dramatiq).

---

## 7. Frontend architecture

### 7.1 Why Astro + React islands

The catalog is 95% read-mostly content (book detail pages, search results, branch pages) and 5% interactive (search-as-you-type, recommender UI, reading-history dashboard). That's the textbook case for Astro:

- Most routes ship **zero JS** — book detail pages are pre-rendered HTML, fast on a Pi.
- The handful of interactive widgets (`<SearchBox client:idle />`, `<RecommendationDeck client:visible />`, `<BookshelfImporter client:load />`) are React islands.
- SEO is good for free — important if you ever decide to publish this for the wider Huelva community.

### 7.2 Stack

- **Astro 5+** with the `@astrojs/react` integration.
- **TanStack Query** in the React islands for data fetching/caching.
- **Tailwind CSS** + **shadcn/ui** components ported to Astro/React.
- **Zod** for runtime API-response validation (the same schemas FastAPI exports via Pydantic — generate the TypeScript types from the OpenAPI doc, no hand-written types).

### 7.3 DDD/hexagonal on the frontend

A frontend doesn't have a "domain" in the same way the backend does, but the *spirit* — separating business rules from frameworks — still applies. Concretely:

```
frontend/src/
├── domain/         # framework-free TS: types, predicates, scoring helpers
│   ├── catalog/    # BibliographicRecord type, search-result rankers
│   ├── reading-history/
│   └── recommendations/
├── application/    # use-case orchestrators, framework-agnostic
│   └── ports/      # API client interfaces
├── infrastructure/
│   ├── api/        # generated OpenAPI client + zod schemas
│   └── storage/    # localStorage wrapper, etc.
├── components/     # React components (islands) and Astro components
├── pages/          # Astro routes
└── styles/
```

Use cases live in `application/`, return plain data, and are called from React islands. React components stay dumb — render and dispatch — so they can be replaced wholesale (e.g. by a React Native client later) without re-doing business logic. This is the same dependency-inversion discipline as the backend, just sized to a frontend.

**TDD on the frontend**: Vitest for `domain/` and `application/` (unit + property-based via `fast-check`), React Testing Library for components, Playwright for end-to-end.

---

## 7.5 Book covers (cover-image enrichment)

Covers transform the UI from a text list into a browsable shelf, so they're worth doing well — but they are an *enrichment* concern, deliberately decoupled from catalog ingest. Two rules drive the whole design: **never resolve covers on the crawl/ingest path** (it must not compete with the OPAC politeness budget) and **never hotlink at request time** (page loads must not depend on third-party uptime). Covers are their own bounded context, resolved asynchronously and served from our own storage.

### 7.5.1 What the OPAC gives us, and why it isn't enough

The rendered record page carries a cover slot — `<img src="https://covers.absys.cloud/{isbn}">` — that falls back to `https://covers.absys.cloud/nofound` when Baratz has no image (confirmed against TITN=1, May 2026). So the upstream covers are: (a) partial, (b) on third-party infrastructure with no reuse guarantee, and (c) keyed by ISBN. We treat `covers.absys.cloud` as one *opportunistic* source among several, never a dependency. The ISBN we already parse into the `isbns` table is the join key for everything below.

### 7.5.2 Source fallback chain

No single source covers Spanish-language and regional editions well, so we resolve through an ordered chain and stop at the first hit:

1. **Open Library Covers** — `https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg`. Free, no key, permissive enough to **store and redistribute**, returns blank/404 when missing. This is the primary *storable* source. Politeness: ≤100 cover requests / IP / 5 min, which an async cached pipeline respects trivially.
2. **Open Library / `covers.absys.cloud`** by ISBN — opportunistic, used when present.
3. **Google Books** — `volumes?q=isbn:{isbn}` → `imageLinks.thumbnail`. Broad, but the ToS expect thumbnails to be *displayed linking back*, not warehoused — so this tier is a **display-time hotlink fallback**, not stored. (See open question added to §12.)
4. **BNE / Wikidata (P18)** — long-tail Spanish titles; lower priority, added later.
5. **Deterministic placeholder** — generated from title+author (hashed colour) so the grid never has holes.

Realistic coverage: 60–85% for mainstream titles, far less on the regional long tail — hence the placeholder matters as a first-class state, not an afterthought.

### 7.5.3 Bounded context, ports and adapters

A new `covers/` context with the same hexagonal layout as the rest:

| Aggregate | Ports (interfaces) | Adapters |
| --- | --- | --- |
| `Cover` (root: image identity + provenance + status) | `CoverRepository`, `CoverProvider` (resolve by ISBN), `CoverStore` (blob put/get), `ImageProcessor` (derivatives) | Postgres repo; OpenLibrary / GoogleBooks / Absys provider adapters; MinIO/S3 `CoverStore`; Pillow `ImageProcessor` |

The `CoverProvider` chain is just a composite of provider adapters tried in order — adding BNE later is one new adapter, no domain change. `CoverStore` is the same port-discipline as `EmbeddingService` (§5.2): MinIO today, swap to Backblaze B2 / S3 later without touching the domain.

### 7.5.4 Resolution (write path)

On `CatalogRecordIndexed` (or when a record gains an ISBN), emit a `CoverWanted` event consumed by a **Dramatiq** worker — entirely off the OPAC path. The worker walks the provider chain, downloads the first hit, hands it to the `ImageProcessor` which re-encodes to **WebP** and generates `thumb` / `medium` / `large` derivatives, then stores them via `CoverStore`. Resolve **lazily and popular-first**: do *not* pre-fetch covers for all ~2.66M records — resolve on first record view and for the novedades cohort, letting the long tail fill on demand. This keeps egress and storage proportional to what users actually look at.

### 7.5.5 Storage — object store, content-addressed

Images go in **object storage, never Postgres blobs**. On the homelab that's **MinIO** (S3-compatible) behind the `CoverStore` port. Store **content-addressed by image sha256**, which automatically deduplicates the many editions that share one cover. A small `covers` table holds only metadata:

```
covers (
  id            uuid PK,
  isbn_13       text,                 -- resolution key
  record_id     uuid,                 -- nullable; an ISBN may precede its record
  status        text NOT NULL,        -- pending | resolved | nofound | failed
  source        text,                 -- openlibrary | googlebooks | absys | placeholder
  license       text,                 -- provenance, for attribution / takedown
  sha256        bytea,                 -- content address into the object store
  width         int,
  height        int,
  fetched_at    timestamptz,
  next_retry_at timestamptz           -- nofound is re-tried on a slow cadence
)
```

Tracking `source` + `license` per cover lets us honour attribution, and purge a single source cleanly if its terms ever change.

### 7.5.6 Serving (read path) and performance

Because URLs are content-addressed they're **immutable**, so serve them with `Cache-Control: public, max-age=31536000, immutable`. Front the object store with **Caddy** (already in the stack) at a stable path like `/covers/{sha256}/{size}.webp`, and let **Cloudflare** (you already plan the Tunnel, §10) edge-cache globally — the homelab then serves each image essentially once. In the UI: responsive `srcset` across the three derivative sizes, native lazy-loading, and a blurhash/placeholder while the image arrives. The API returns a `cover` object per record (`{url, status, source}`) so the frontend renders the right state (image / placeholder / pending) without a second round-trip.

### 7.5.7 Why this scales

Storage and serving live on an object store + CDN, not on the Pi or in Postgres; immutability means the cache never invalidates; WebP + derivatives keep bytes small; lazy popular-first resolution keeps the working set tiny relative to 2.66M records; and content-addressing dedupes shared covers. Expanding to other provinces (§11 M7) adds no covers work — the pipeline is keyed by ISBN, not by branch.

---

## 8. AI / recommender architecture

### 8.1 Embeddings

- **Local** sentence-transformers with **BGE-M3** (1024-dim, multilingual; very strong on Spanish in the MTEB leaderboard).
- Computed *once* per record on ingest; recomputed when the title/subjects/summary change (driven by source-hash).
- Stored in `bibliographic_records.embedding` and indexed via pgvector HNSW.
- Same model also embeds the user's read-shelf entries (we embed `title + author + subjects + user_rating_bucket`) so we can score "books like things you liked".

### 8.2 Retrieval

Hybrid: BM25 via Postgres FTS *plus* cosine over pgvector embeddings, combined via Reciprocal Rank Fusion. The combined ranker is implemented in the `recommendations/infrastructure/` adapter behind a `RecommenderEngine` port — switching to a learned reranker later is one file.

### 8.3 LLM layer (OpenRouter)

The LLM is **not** the retriever. It does three small jobs:

1. **Query rewriting** — user types "lo último de Sapiens" → LLM rewrites to a structured search (`author:"Yuval Noah Harari" sort:pub_year desc`).
2. **Rationales** — generate one-paragraph "why we recommend this for you" text. Cached per (user, record) pair.
3. **Cold-start classification** — for a brand-new user, ask the LLM to extract preferred genres/topics from their imported Goodreads shelf.

Constraints from the OpenRouter free-model tier (20 RPM, 50–1,000 requests/day depending on account credit): batch jobs **must not** go through OpenRouter. Everything that would consume the daily budget (re-embedding, mass classification) runs on local models instead. ([OpenRouter free models](https://openrouter.ai/collections/free-models))

Model selection happens behind a `LlmClient` port; the adapter implements OpenRouter, but a local Ollama adapter is the obvious fallback.

---

## 9. Reading-history imports

Goodreads still supports CSV export from the desktop site (Tools → Import and export). The CSV is well-known: title, author, ISBN, ISBN-13, rating, date-read, shelves, review. ([Goodreads help](https://help.goodreads.com/s/article/How-do-I-import-or-export-my-books-1553870934590))

Plan:

- **Day-one importer**: Goodreads CSV. Robust parser, idempotent (re-import is a no-op).
- **Tier-two importers** (each one is a new adapter implementing `Importer`): StoryGraph CSV (very similar shape), Hardcover (API, requires user OAuth), BookWyrm (ActivityPub, more complex). Each is a separate ticket. ([Goodreads alternatives](https://booktrack.app/blog/the-best-alternative-to-goodreads-for-ios/))
- **Matching** to catalog: try ISBN-13 first, fall back to fuzzy title+author match against the embedded catalog (using the same embedding model — same vector space = clean similarity scores).

---

## 10. Deployment (Synology NAS + Cloudflare Tunnel)

> **Status: LIVE since 2026-05-30** at <https://biblio.josearcos.me>. The four-container read+serve plane runs on the NAS; the catalog mirror is empty until the off-NAS crawler is run against it. Hard-won Synology deploy specifics (SSH pubkey, BuildKit DNS, rsync-gated, `astro preview` host block) are recorded in `homelab-josearcos-me-infra-reference.md` §12.

Concrete target: the **Synology "Home-NAS"** (`192.168.1.130`, Container Manager), published at **`biblio.josearcos.me`** through the **existing `synology-nas` Cloudflare Tunnel** — the same tunnel that already serves `josearcos.me → wordpress`. No new tunnel, no open inbound ports, no DDNS; TLS terminates at Cloudflare's edge. (Full home-lab inventory lives in the gitignored `homelab-josearcos-me-infra-reference.md`.)

**Two planes, deliberately split.** The crawl worker (Scrapling/Camoufox → Chromium) and the BGE-M3 embedder are CPU/RAM-heavy and won't run on an ARM Synology at all, so they do **not** live on the NAS:

- **Read + serve plane — on the NAS** (`docker-compose.prod.yml`): `postgres` (timescaledb-ha:pg16, x86-64 — verify NAS arch), `api` (FastAPI/uvicorn), `frontend` (Astro), `minio` (content-addressed cover store, §7.5). State on `/volume1/docker/bibliohack/{pgdata,minio}`.
- **Compute plane — off the NAS** (`docker-compose.worker.yml`, on a mini-PC or the Mac): `redis` (Dramatiq broker), `worker`, `embedder`. Reaches the NAS Postgres over **Tailscale/LAN** — Postgres binds to the NAS LAN IP only, never the tunnel. The hexagonal design makes this purely a deployment choice, no code change.

**Public exposure.** `frontend` and `api` attach to the pre-existing external Docker network **`tunnel`** so `cloudflared` resolves `bibliohack-frontend:4321` / `bibliohack-api:8000` by name (same mechanism as `wordpress`). Ingress uses **same-origin path routing** so there's no CORS: the frontend calls `/catalog/*` and `/healthz` at the root, so the tunnel routes **`biblio.josearcos.me ^/(catalog|healthz)` → api** and **`* ` → frontend** (Astro build bakes `PUBLIC_API_BASE_URL=https://biblio.josearcos.me`). The frontend output is fully static and served by `serve` (not `astro preview`, which enforces a Host allowlist that's awkward behind the tunnel). See `infra/cloudflared-config.example.yml`.

**Security posture** (mirrors the existing public-web-vs-Tailscale split): the tunnel exposes a **read-only surface only** — frontend + read API. Write/admin endpoints, the MinIO console, Postgres, and worker controls stay on LAN/Tailscale and are never added to tunnel ingress. Read endpoints sit behind a soft rate limit (`slowapi`); Cloudflare WAF + rate-limiting sit in front. The public app only ever reads our mirror — it never triggers a live OPAC call per request.

**Covers + CDN synergy.** Cover URLs are immutable/content-addressed (§7.5.6), so a Cloudflare Cache Rule on `biblio.josearcos.me/covers/*` (cache-everything, long TTL) lets the edge serve each cover globally and the NAS serve it once — important because home **upload** bandwidth (DIGI fibre) is the real bottleneck, not NAS CPU. Covers are served via a `/covers/*` path proxied to a read-only MinIO bucket, never by exposing the S3 endpoint.

**Backups & observability.** Nightly `pg_dump` of the NAS Postgres + Synology Hyper Backup of `/volume1/docker/bibliohack` (covers Postgres data and the MinIO bucket); optional `restic` to Backblaze B2. Observability (`prometheus` + `grafana` + `loki`) is optional for v0 — track scrape success rate, parse-error rate, embedding queue depth, DB size.

### 10.1 CI/CD and automated deploy (planned — milestone M6.5)

**Goal:** every green push to `main` deploys itself to the NAS; a red pipeline never deploys (so a broken build/test can't reach production).

**What exists today** (`.github/workflows/ci.yml`): three jobs on GitHub-hosted runners — `backend` (ruff + mypy + pytest against service Postgres/Redis), `frontend` (prettier + eslint + astro check + vitest), and `docker-build` (builds both images with `push: false`, BuildKit cache via `type=gha`). Triggers on push to `main` and on PRs. The deploy step is still manual (driven from the Mac over SSH).

**The gate (deploy only on success).** Add a `deploy` job that depends on all three:

```yaml
deploy:
  needs: [backend, frontend, docker-build]            # runs only if ALL pass
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  runs-on: ubuntu-latest
  environment: production                             # scoped secrets + history
  concurrency: { group: deploy-prod, cancel-in-progress: false }
```

`needs:` means a single failing job aborts the run before deploy is ever scheduled; `if:` restricts to direct pushes to `main` (never PRs/forks). A GitHub **Environment** (`production`) scopes the deploy secrets and records a deployment history (and can add a manual-approval gate later if desired).

**Reaching the NAS — the crux.** GitHub-hosted runners live in the public cloud; the NAS has **no public inbound** (SSH 2222 is LAN-only, the site is behind the tunnel). Three patterns, in recommended order:

1. **Tailscale GitHub Action (recommended).** The NAS already runs Tailscale. [`tailscale/github-action`](https://github.com/tailscale/github-action) joins the runner to the tailnet as an **ephemeral, tagged** node (OAuth client with the `auth_keys` scope + a `tag:ci`), giving it a Tailscale IP for the job only; the job then SSHes to the NAS over WireGuard and runs the deploy. No public ports, no port-forwarding; the ephemeral node auto-deregisters after the run. Needs a Tailscale ACL rule allowing `tag:ci → Home-NAS:2222`.
2. **Self-hosted runner on the NAS.** A GitHub Actions runner in Container Manager polls GitHub **outbound** (no inbound needed) and deploys locally (can reuse its own checkout). Simplest networking, but it executes workflow code on the NAS — acceptable only because `jarcos/biblioHack` is **private**; harden it and treat it as ephemeral. Costs NAS CPU.
3. **Cloudflare Tunnel for SSH** (`cloudflared access ssh` + a service token). Works, but adds moving parts to the token-managed tunnel; lower priority since Tailscale is already in place.

**Build-and-ship strategy** (evolving):

- **A — NAS-side build (quick path).** Deploy job SSHes in, syncs code (**tar-over-ssh**; rsync is gated on Synology — infra §12.1), then `docker compose -f docker-compose.prod.yml up -d --build` + Alembic migrations. Zero new infra, but builds on the NAS (slow).
- **B — registry pull (recommended target).** Promote `docker-build` to **build-and-push** tagged images to **GHCR** (`ghcr.io/jarcos/bibliohack-{api,frontend}:<sha>` + `:latest`); the deploy job then only runs `docker compose pull && up -d` (no NAS build → faster, near-atomic). Needs the prod compose to reference image tags and the NAS to authenticate to GHCR (a read-only token, or public packages).

**"Don't break the app" guardrails:**

- Unreachable unless lint + types + tests + image-build all pass (`needs:`).
- Run **DB migrations before** swapping app containers, and keep them **backward-compatible** (expand→migrate→contract) so brief version skew is safe.
- **Post-deploy health gate:** after `up -d`, poll `https://biblio.josearcos.me/healthz` (+ a `/catalog/search` smoke) with retries; if it doesn't go green the job **fails loudly** — and, in strategy B, **rolls back** to the previous `<sha>` image (still in GHCR). One-line revert.
- `concurrency: deploy-prod` so two deploys never overlap.

**Secrets (GitHub Environment `production`):** `TS_OAUTH_CLIENT_ID` / `TS_OAUTH_SECRET`, `NAS_SSH_HOST` (Tailscale name/IP), `NAS_SSH_USER`, and a **dedicated CI deploy key** `NAS_SSH_KEY` — *not* the `bibliohack_deploy` key used for manual/interactive deploys; CI gets its own, separately revocable. Strategy B also needs a GHCR pull credential on the NAS.

---

## 11. Roadmap (proposed milestones)

| Milestone | Outcome | Duration estimate |
| --- | --- | --- |
| **M0 — Foundations** | Repo scaffold, Docker Compose dev env, CI (GitHub Actions: ruff + mypy + pytest + Playwright), `make` targets, ARCHITECTURE.md kept in sync. Empty FastAPI hello + empty Astro hello. | 1 weekend |
| **M1 — Catalog ingest, Huelva** | AbsysNet adapter, parser, persistence. First polite crawl of the Huelva subset. Read-only catalog API + bare-bones search UI (FTS only). | 3–4 weekends |
| **M2 — Availability history** | Availability snapshot worker, time-series schema, simple "is it on the shelf?" badge in the UI. | 1–2 weekends |
| **M2.5 — Book covers** | `covers` context + async resolution worker (OpenLibrary → Google Books → placeholder), MinIO content-addressed store, immutable serving, `srcset` + lazy-load in the UI. Enriches search/detail UI dramatically. (Design: §7.5.) | 1–2 weekends |
| **M3 — Semantic search** | Local BGE-M3 embedding pipeline, pgvector index, hybrid retriever, "more like this" links on detail pages. | 2 weekends |
| **M4 — Goodreads import** | CSV importer, matching to catalog, bookshelf UI. | 1–2 weekends |
| **M5 — Recommender v1** | Cold-start + content-based recommendations, OpenRouter rationales, "recommended right now in your branch" view. | 2 weekends |
| **M6 — Polish + public deploy** | Caddy/Cloudflare Tunnel, rate limiting, error pages, backups. **(Deploy done 2026-05-30 — see §10.)** | 1 weekend |
| **M6.5 — CI/CD auto-deploy** | Green push to `main` → auto-deploy to the NAS (Tailscale GitHub Action → SSH; build-and-push to GHCR → `compose pull`), gated on all CI passing, with a post-deploy health gate + rollback. Never deploys on a red pipeline. (Design: §10.1.) | 1 weekend |
| **M7 — Expand to other provinces** | Generalise the SUBC handling so each Andalusian province can be enabled by config; first add Sevilla + Cádiz; same crawl, no new code. | 1 weekend |
| **M8 — Mobile app** | React Native or Expo client reusing the API. Out of scope for the doc. | — |

Total to M6: ~12–15 weekends if everything is fun. Realistic with life-in-the-loop: 4–6 months.

---

## 12. Open questions and risks

These are the things I am **not** confident about. Address before committing too far.

> **First live crawl — findings (2026-05-29).** The legal gate cleared (see item 1), and the full M1 stack ran end-to-end against the live OPAC for the first time: range probe + a 30-task smoke crawl of TITN 1–30. What we learned:
>
> - **TITN high-water mark is `2,662,739`** (lowest missing `2,662,740`), found in 42 polite fetches. That's ~1.8× the ~1.5M estimate in §5.1 — re-baseline the bootstrap duration (§6.8) and the embedding storage math (§5.1) against ~2.66M, not 1.5M.
> - **The `?TITN=N` → `…/{SESSION}?ACC=161` session-token redirect (§6.4) works transparently** through Scrapling's stealth fetcher. No per-worker session pinning was needed — strategy (b) holds.
> - **🐞 Encoding bug (must-fix before any real ingest).** Persisted titles are double-UTF-8-encoded mojibake: "Juan Jesús García" stored as "Juan JesÃºs GarcÃ­a". Byte dump confirms `ú` (UTF-8 `C3 BA`) stored as `C3 83 C2 BA` — i.e. the UTF-8 page bytes were decoded as Latin-1/cp1252 and re-encoded. The fix is in the fetch→parse path (force the correct source charset before parsing); existing rows are recoverable via `convert_from(convert_to(col,'LATIN1'),'UTF8')` but a re-crawl is cleaner. This corrupts *all* accented text and will wreck FTS/embeddings, so it blocks a wider crawl.
> - **`subjects` table is empty** after 16 records (`contributors` populated, 13 rows). Either these low-TITN records genuinely lack materia headings or the subject parser isn't wired — verify against a record known to have subjects before trusting M3 semantic input.
> - **Copies are network-wide, not Huelva-only.** 16 records yielded 120 copies across **73 branches** — the full RBPA, because no `SUBC` Huelva filter is applied at ingest. Expected at this stage; decide whether to filter at ingest or keep all-province copies and filter at query time (the latter is cheaper to expand for M7).
> - **Records with zero copies exist** (e.g. TITN=10 persisted with `copies=0`). Confirms the §12.5 "ejemplares virtuales" / no-holdings case is real and the schema tolerates it; double-check we aren't silently dropping virtual copies.
> - **Run mechanics (dev runbook).** Scrapling's `StealthyFetcher` (v0.4.8) drives a **Patchright Chromium**, not the Camoufox binary — install browsers with `scrapling install`, *not* `camoufox fetch`. Host-run CLI/Alembic need `DATABASE_URL`/`DATABASE_URL_SYNC` overridden from host `postgres` to `localhost:5432`.


1. ~~**Does the OPAC's *aviso legal* / `robots.txt` allow systematic crawling?**~~ **RESOLVED 2026-05-29 — yes, with conditions.** `robots.txt` for `www.juntadeandalucia.es` does **not** disallow the `/cultura/absys/...` OPAC path for the generic `user-agent: *` (only `PetalBot` is fully banned; we are not it), and sets no `Crawl-delay`. The portal *aviso legal* (`/informacion/legal.html`) grants reuse under **Creative Commons Reconocimiento 3.0 ES (CC-BY)** — copying, redistribution, commercial use and derivatives are all allowed, provided we (a) attribute the source with the exact phrase **"Información obtenida del Portal de la Junta de Andalucía"** in a visible place, (b) propagate that same attribution obligation in any derivative, (c) do not distort the data, and (d) do not reproduce the Junta's logos/escudos/marcas. The *términos de uso* also forbid any access that **damages, degrades or overloads ("sobrecarga")** the service — which makes the §6.3 politeness budget (1 req/s, single-threaded, nightly window) a hard compliance requirement, not just good manners. **Action carried forward:** surface the attribution string in the frontend footer and in any data export before M6 public deploy.
2. **Does AbsysNet expose a per-record MARC export URL on the public OPAC?** If yes, the parser collapses from "fragile HTML scraping" to "pymarc". This is the single biggest unknown that could simplify the project.
3. **Is there a published `OAI-PMH` endpoint** for the RBPA we missed? Unlikely (AbsysNet's OAI module is optional and Comunidad Baratz suggests it's not active here), but worth one more probe — try the conventional path `/cgi-bin/abnetcl?ACC=OAI` and similar.
4. **eBiblio Andalucía** (the eBook lending platform) is a separate system, not AbsysNet. Decision: out of scope for v1, revisit at M7.
5. **Holdings semantics** — AbsysNet has "ejemplares" (copies) and "ejemplares virtuales" (virtual copies, used for digital loans). The data model needs to handle both cleanly. Will be confirmed when we inspect real Huelva HTML.
6. **Goodreads ToS for re-importing** — they have intermittently restricted scraping. CSV export is allowed for the user themselves; we just consume what they bring us. No Goodreads-side scraping.
7. **Vector index migration path** — if pgvector hits a wall, the `EmbeddingService` port lets us swap to Qdrant. **Acceptance criterion**: when query p95 latency exceeds 250 ms on the production homelab, migrate. Not before.
8. **Spanish-specific tokenisation** for FTS — Postgres ships a `spanish` config; verify accent handling and stopwords against real queries.
9. **Google Books cover ToS** — their terms expect thumbnails to be *displayed linking back*, not stored/redistributed. Decision (§7.5.2): use Google Books only as a **display-time hotlink fallback**, and treat **Open Library** (permissive) as the only *storable* source. Re-read both terms before M-covers ships, and keep per-cover `license`/`source` so a source can be purged cleanly if its terms change.
10. **Auto-deploy connectivity + safety (M6.5, §10.1)** — confirm the Tailscale ACL allows a `tag:ci` ephemeral node to reach `Home-NAS:2222`; decide GHCR package visibility (private + pull token vs. public); and settle the migration-rollback story (strategy B makes image rollback trivial, but a bad *migration* still needs an expand→contract discipline or a tested down-path). A dedicated CI deploy key (separate from `bibliohack_deploy`) must be issued.

---

## 13. Decisions already made (so we don't relitigate them)

- Data scope: **full historical availability tracking**, not just bibliographic snapshots.
- Reading-history input: **importers from Goodreads/StoryGraph/etc.**, no manual log first.
- Frontend: **Astro + React islands**.
- Deployment: **homelab, self-hosted, Docker Compose**.
- Search: **semantic-first**, hybrid retrieval.
- Scraping cadence: **polite + slow**, 1 req/s nightly window.
- Database: **PostgreSQL 16 + pgvector** (single store, with `EmbeddingService` port to allow swapping to Qdrant later).
- Scraper: **Scrapling** primary, plain `httpx` for non-JS pages.
- Embeddings: **local BGE-M3**.
- LLM: **OpenRouter free tier** for user-facing inference only; **no batch jobs** through it.
- Covers: a **separate `covers` bounded context**, resolved **asynchronously off the OPAC path**, **never hotlinked at request time**. **Open Library** is the storable primary source; **Google Books** is a display-time fallback only; a deterministic **placeholder** is a first-class state. Stored in **MinIO, content-addressed by sha256**, served immutable through Caddy + Cloudflare. Resolution is **lazy / popular-first**, never a full 2.66M pre-fetch. (Full design: §7.5.)

---

## 14. Sources

- [Catálogo OPAC Biblioteca Provincial de Huelva](https://www.bibliotecasdeandalucia.es/web/biblioteca-del-estado-publica-provincial-de-huelva/catalogos/catalogo-de-la-biblioteca)
- [AbsysNet OPAC — Red de Bibliotecas Públicas de Andalucía](https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi?ACC=101)
- [Catálogo Colectivo del Patrimonio Bibliográfico Andaluz](https://www.juntadeandalucia.es/cultura/absys/ccpba/abnetcl.cgi?FORM=2)
- [Catálogo Colectivo de Bibliotecas Públicas (CCBIP, nacional)](https://catalogos.cultura.gob.es/CCBIP/ccbipopac/)
- [Junta de Andalucía — Red de Bibliotecas Públicas de Andalucía](https://www.juntadeandalucia.es/organismos/culturaydeporte/areas/cultura/bibliotecas-documentacion/red-publicas.html)
- [Comunidad Baratz — La Red IDEA y la RBPA ya están en AbsysNet 2.2](https://www.comunidadbaratz.com/blog/la-red-idea-y-la-red-de-bibliotecas-publicas-de-andalucia-ya-estan-en-absysnet-2-2/)
- [Comunidad Baratz — Cómo crear URLs estables al OPAC de AbsysNet](https://www.comunidadbaratz.com/blog/como-crear-urls-estables-al-opac-de-absysnet-y-no-morir-en-el-intento/)
- [Comunidad Baratz — Cómo lanzar consultas bibliográficas a AbsysNet por URL](https://www.comunidadbaratz.com/blog/como-lanzar-consultas-bibliograficas-a-absysnet-traves-de-la-url-del-opac/)
- [datos.gob.es — Bibliotecas y Centros de Documentación de Andalucía](https://datos.gob.es/en/catalogo/a01002820-bibliotecas-y-centros-de-documentacion-de-andalucia)
- [datos.gob.es — Catálogo bibliográfico (Comunidad de Madrid, MARC-XML)](https://datos.gob.es/en/catalogo/a13002908-catalogo-bibliografico)
- [Scrapling — D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling)
- [Scrapling documentation](https://scrapling.readthedocs.io/en/latest/index.html)
- [Crawl4AI vs Firecrawl 2026 — BrightData](https://brightdata.com/blog/ai/crawl4ai-vs-firecrawl)
- [Best Python web-scraping libraries 2026 — Oxylabs](https://oxylabs.io/blog/python-web-scraping-libraries)
- [opacapp/opacclient (archived)](https://github.com/opacapp/opacclient)
- [VideLibri — benibela/videlibri](https://github.com/benibela/videlibri)
- [BentoML — Open-source embedding models guide](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models)
- [OpenRouter free models](https://openrouter.ai/collections/free-models)
- [OpenRouter — Text Embedding Models](https://openrouter.ai/collections/embedding-models)
- [Vector-DB benchmarks 2026 — CallSphere](https://callsphere.ai/blog/vector-database-benchmarks-2026-pgvector-qdrant-weaviate-milvus-lancedb)
- [Goodreads — How do I import or export my books?](https://help.goodreads.com/s/article/How-do-I-import-or-export-my-books-1553870934590)
- [Privacy-first Goodreads alternatives — BookTrack](https://booktrack.app/blog/the-best-alternative-to-goodreads-for-ios/)
