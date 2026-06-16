---
title: "biblioHack — Identity Milestone"
h1: "Identity milestone — implementation plan"
tagline: "Single-reader homelab → public multi-user app."
---
Turning biblioHack from a single-reader homelab into a multi-user app with
**public registration**, where each user owns their bookshelf and gets
**recommendations scoped to their own `user_id`**.

This plan is faithful to the existing hexagonal/DDD layout (`domain` /
`application` / `infrastructure` / `interfaces` per bounded context) and to
`docs/design/architecture.md §4`, which already specs the **Identity** context: `User`
(root) + `Preference`, ports `UserRepository` / `AuthProvider`, adapter "local
password auth (**Argon2id**)".

## Current state (verified in code)

- **No auth anywhere.** The only request dependency is `get_session`
  (`interfaces/http/dependencies.py`). `GET /api/shelf` is explicitly
  single-user ("there is one reader, so no auth or user scoping").
- **`shelf_entries` is globally keyed**, not per-user. Identity is
  `UniqueConstraint(source, source_book_id)`; there is no `user_id` column.
- **Imports are CLI-only.** `bibliohack shelf import <csv>` →
  `ImportShelf` → `PostgresShelfRepository`. There is no HTTP import endpoint,
  so public users currently have no way to load their shelf.
- **`recommendations` context is empty scaffolding** — just `__init__.py` files
  under `domain/application/infrastructure/interfaces`. Nothing is built, so we
  design it user-scoped from day one (no retrofit needed there).
- **Stack already in place that we'll lean on:** Redis
  (`settings.redis_url`), CORS with `allow_credentials=True`, Alembic
  (`backend/alembic/`), Astro + React-islands frontend (`frontend/src`),
  OpenTelemetry auto-instrumenting FastAPI + asyncpg in prod.

## Decisions to lock before coding (with recommended defaults)

These materially change the work. Defaults are what I'd pick for a public,
EU-facing homelab app.

1. **Session mechanism — *server-side Redis sessions + opaque httpOnly
   cookie* (recommended)** over stateless JWT. Redis is already in the stack;
   opaque sessions are trivially revocable (logout, "log out everywhere",
   ban), no JWT secret-rotation pain, and same-origin behind the tunnel means
   we don't need bearer tokens. `allow_credentials=True` is already set.
2. **Email verification at launch — *yes*. DECIDED.** Sent via the **mailer
   already connected on the NAS** (SMTP). No new provider needed — the
   `Mailer` adapter (Phase 1) points at the NAS SMTP host.
3. **Bot protection — *Cloudflare Turnstile* on register/login (recommended).**
   You're already fronted by Cloudflare; Turnstile is free and keeps signup
   spam down without a CAPTCHA UX hit.
4. **GDPR posture — *DECIDED: we act as data controller*.** Public EU users
   storing personal reading history (ratings, reviews, dates) is personal data
   under GDPR. We will ship **Privacy Policy** and **Terms & Conditions** pages
   (Phase 3), consent at signup, account deletion (cascade), and data export.

## Phase 0 — schema & settings groundwork

### `users` table (new) — Identity context

`identity/infrastructure/postgres/models.py`:

- `id UUID PK`
- `email CITEXT UNIQUE NOT NULL` (case-insensitive; enable the `citext`
  extension in the migration, consistent with how `spanish_unaccent`/`pg_trgm`
  are managed)
- `password_hash TEXT NOT NULL` (Argon2id encoded string)
- `email_verified BOOL NOT NULL DEFAULT false`
- `display_name TEXT NULL`
- `created_at`, `updated_at` (timezone-aware, `server_default=func.now()`)

Optional companion tables: `email_verification_tokens` and
`password_reset_tokens` (`user_id` FK, `token_hash`, `expires_at`,
`consumed_at`) — store **hashes** of tokens, never the raw token.

### `shelf_entries` retrofit — simplified (DECIDED: discard existing data)

Existing rows are throwaway CSV imports that the owner will simply re-import,
so **no backfill and no owner-bootstrap is needed**. The migration is trivial
and low-risk:

1. `TRUNCATE shelf_entries` (discard current single-user data).
2. `ADD COLUMN user_id UUID NOT NULL` directly (safe — table is empty).
3. `ADD CONSTRAINT fk_shelf_entries_user FOREIGN KEY (user_id) REFERENCES
   users(id) ON DELETE CASCADE`.
4. Swap the uniqueness rule: drop `uq_shelf_entries_source_book`, add
   `uq_shelf_entries_user_source_book (user_id, source, source_book_id)`.
5. `CREATE INDEX ix_shelf_entries_user_id ON shelf_entries (user_id)`.

The owner just registers like any other user and re-imports their CSV through
the new flow. Per `CLAUDE.md`, this ships as an Alembic revision and runs
`alembic upgrade head` on deploy.

### Settings additions (`shared/infrastructure/settings.py`)

- `session_secret: str` (signing key for the cookie), `session_ttl_seconds`,
  cookie name/domain (`biblio.josearcos.me`), `SameSite=Lax`, `Secure=True`.
- `argon2_time_cost` / `memory_cost` / `parallelism`.
- `registration_enabled: bool = True` (kill-switch for abuse).
- **NAS SMTP** config (host/port/credentials, STARTTLS/SSL) + `from` address —
  reuses the mailer already connected on the NAS.
- `turnstile_secret` / `turnstile_site_key`.

## Phase 1 — Identity context (auth, no scoping yet)

Hexagon, mirroring the other contexts:

**domain/** — `User` aggregate (registration invariants, e.g. valid email,
verified-state transitions); value objects `Email`, `PasswordHash`;
`Preference` VO (reserve for later, e.g. preferred branch/locale). Domain
imports nothing from infrastructure.

**application/ports.py** — `UserRepository` (get_by_email, get_by_id, add,
mark_verified), `PasswordHasher` (the `AuthProvider`: `hash`, `verify`,
`needs_rehash`), `SessionStore` (create, get, delete), `TokenService` (issue +
verify email/reset tokens), `Clock`. IDs cross as plain strings, matching the
existing port discipline.

**application/use_cases/** — `RegisterUser`, `AuthenticateUser`, `VerifyEmail`,
`RequestPasswordReset`, `ResetPassword`, `GetCurrentUser`. Pure logic over the
ports; in-memory fakes in tests.

**infrastructure/** — `postgres/user_repository.py`;
`security/argon2_hasher.py` (argon2-cffi); `sessions/redis_session_store.py`
(opaque session id → `{user_id, created_at}`); `email/smtp_mailer.py` behind a
`Mailer` port, **pointed at the NAS SMTP service** (verification + reset
mails).

**interfaces/http/router.py** (prefix `/api/auth` — must stay under `/api/*`
per the tunnel-routing rule):

- `POST /api/auth/register` → create user (unverified), send verification mail,
  Turnstile-gated.
- `POST /api/auth/verify` → consume token, set `email_verified`.
- `POST /api/auth/login` → verify password, create session, set httpOnly
  cookie. Turnstile-gated; rate-limited.
- `POST /api/auth/logout` → delete session, clear cookie.
- `GET  /api/auth/me` → current user (or 401).
- `POST /api/auth/password/reset-request` + `/password/reset`.

Register `auth_router` in `interfaces/http/app.py`.

**The cross-cutting dependency** — add to
`interfaces/http/dependencies.py`:

- `get_current_user` → reads the session cookie → `SessionStore` →
  `UserRepository`; raises 401 if absent/expired. Used by all per-user
  endpoints.
- `get_optional_user` → same but returns `None` instead of 401, for endpoints
  that work logged-out (catalog search stays public).

## Phase 2 — scope ReadingHistory by user

- **`ShelfEntryData`** (`reading_history/application/ports.py`): add
  `user_id: str`.
- **`ShelfRepository`**: `upsert_entry` keyed by `(user_id, source,
  source_book_id)`; add `user_id` to read methods.
- **`PostgresShelfReadRepository.list_entries(user_id)`** — filter by user.
- **`ImportShelf.execute(rows, *, user_id)`** — stamp every entry with the
  importing user. Matching against the catalogue is unchanged (catalogue is
  shared, global).
- **`GET /api/shelf`** → `Depends(get_current_user)`, pass `user_id` through.
- **New `POST /api/shelf/import`** (multipart CSV upload, `get_current_user`):
  the public path to load a Goodreads export, since the CLI isn't available to
  web users. **DECIDED: runs as a Dramatiq background job** (see "Background
  imports" below), returning `202` + an import id. **Guardrails:** max upload
  size and row cap (a malicious/huge CSV otherwise floods the per-row trigram
  matching).
- **`ImportJob` aggregate + `import_jobs` table** — already in `docs/design/architecture.md
  §4`. Tracks `id`, `user_id`, `status` (queued/running/done/failed),
  per-shelf stats, `error`, timestamps. The worker updates it; the frontend
  polls it.
- **`GET /api/shelf/import/{id}`** — job status for the polling UI.
- **CLI** stays for the owner; add a `--user-email` option so it resolves a
  `user_id` rather than assuming the sole reader.

### Background imports — sync vs Dramatiq (DECIDED: Dramatiq)

Per-row matching fires two trigram queries against the ~1.5M-record catalogue.
Doing that **inline in the request** is simplest but blocks the user's browser
for the whole import, risks tunnel/HTTP timeouts on large libraries, holds an
asyncpg connection for the duration, and lets concurrent public uploads
saturate the pool and slow catalogue search for everyone.

Offloading to a **Dramatiq worker** (broker = Redis, already in the stack;
worker runs as an on-NAS container alongside `bibliohack-crawler`) keeps the
endpoint fast (`202` + import id), bounds DB load by worker count/prefetch
rather than by upload concurrency, retries transient failures, and survives
client disconnects. Cost: a worker process to deploy and the `import_jobs`
status-tracking + "processing…" UX. This matches the architecture (Dramatiq +
Redis named in §5.1; `ImportJob` aggregate in §4), so it's the intended design
rather than an add-on. **Note:** the Dramatiq worker, like the crawler plane,
is not OTel-instrumented — crawl/job health comes from the `import_jobs` status
rows.

## Phase 3 — frontend auth (Astro + React islands)

- Pages: `/register`, `/login`, `/account`, `/verify`, password-reset pages.
- React-island forms calling `/api/auth/*` with `credentials: "include"`.
- **Astro middleware** to read the session cookie server-side and guard SSR
  pages; redirect `/shelf` and `/recommendations` to `/login` when
  unauthenticated.
- Account page: change password, **export my data**, **delete my account**
  (GDPR).
- **`/privacy` (Privacy Policy) and `/terms` (Terms & Conditions) pages**
  (DECIDED). Link both from the footer and from the registration form, with a
  consent checkbox at signup ("I agree to the Terms and Privacy Policy") that
  registration enforces.
- Add Turnstile widget to register/login.

## Phase 4 — Recommendations, user-scoped from the start (greenfield)

Build the empty context per `docs/design/architecture.md §4` (root `Recommendation`,
`RecommendationRequest`; ports `RecommendationRepository`, `RecommenderEngine`,
`LlmClient`), with `user_id` threaded through everywhere:

- **`recommendations` table**: `id`, `user_id` FK (`ON DELETE CASCADE`),
  `matched_record_id`, `score`, `rationale`, `generated_at`, plus a per-user
  cache key. Index on `user_id`.
- **Engine**: builds a *per-user* profile from **that user's** `shelf_entries`
  (ratings + read books → pgvector centroid / liked-item retrieval), runs the
  hybrid retriever (FTS + pgvector) over the shared catalogue, **excludes books
  already on the user's shelf**, and asks OpenRouter for rationales.
- **Events** (per the architecture's in-process bus): `BookRead` / `BookRated`
  carry `user_id`; the recommender invalidates that user's cache on those
  events.
- **`GET /api/recommendations`** → `Depends(get_current_user)` →
  `engine.recommend(user_id)`. Never returns another user's data.

## Phase 5 — hardening for public exposure

- **Rate limiting** on `/api/auth/*` and `/api/shelf/import` (slowapi, or at the
  Caddy/Cloudflare edge) — brute force, signup spam, import abuse.
- **Per-user isolation tests**: integration test (testcontainers) proving user
  A cannot read/import into user B's shelf or see B's recommendations.
  schemathesis contract tests on the new endpoints.
- **Account deletion** cascades through `shelf_entries` and `recommendations`
  (FKs already `ON DELETE CASCADE`); confirm session invalidation.
- **Privacy**: signup consent + privacy notice, data export endpoint.
- **OTel note** (`CLAUDE.md`): FastAPI + asyncpg are auto-instrumented, so new
  endpoints/queries get spans for free. The **Redis session store is not** —
  add `opentelemetry-instrumentation-redis` if you want session-store spans.

## Suggested build/PR order

Each step is independently shippable and green-gated
(`ruff format --check`, `ruff check`, `mypy src`, `pytest`), then auto-deploys:

1. Phase 0 migration + settings (owner backfilled; app still works single-user).
2. Phase 1 Identity context + auth endpoints + session store.
3. Phase 2 shelf scoping + HTTP import endpoint.
4. Phase 3 frontend auth + guards.
5. Phase 4 recommendations (user-scoped).
6. Phase 5 hardening.

## Open dependencies / risks

- **Email deliverability** — verification + reset depend on the NAS SMTP
  service; confirm it can send to external addresses (not just LAN) and isn't
  flagged as spam (SPF/DKIM on `biblio.josearcos.me`).
- **Migration safety** — resolved: existing `shelf_entries` are discarded and
  re-imported, so the migration runs on an empty table. No backfill risk.
- **Import cost under load** — resolved: imports run on a Dramatiq worker
  (`import_jobs` tracking), so concurrent uploads don't block the API or
  saturate the connection pool.
- **GDPR** — confirmed: we act as data controller. Privacy Policy + T&C pages,
  signup consent, deletion, and export are in scope (Phases 3 & 5).
