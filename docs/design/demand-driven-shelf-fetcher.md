---
title: "biblioHack — Demand-driven fetcher (unmatched shelf books)"
h1: "Demand-driven fetcher — unmatched shelf books"
tagline: "Draft plan 2026-06-22 · Kanban To-do #2. The user-shelf variant of the canon C3 resolve: resolve unmatched Goodreads/StoryGraph shelf entries against the live OPAC and ingest the ones the RBPA actually holds."
---

> **Status: S0–S3 implemented (2026-06-22), pending the gate + NAS rebuild; S4
> (optional Grafana) still to build.** Kanban card "2 · Demand-driven fetcher
> (unmatched shelf books)" (MEDIUM, top build). This is the user-shelf sibling of
> the shipped canon **C3** resolve (`docs/design/canon-import.md`). It reuses the
> same OPAC resolve machinery, aimed at unmatched `shelf_entries` instead of
> `canon_seed`.
>
> **Done so far:**
> - **S0** — Alembic `20260622_0020` + the three `shelf_entries` columns
>   (`resolve_status`, `resolve_attempts`, `last_resolved_at`) + partial index.
> - **S1** — `RematchShelf` use case, `iter_unmatched` / `link_match` repo
>   methods, `bibliohack shelf rematch` CLI, unit + integration tests. DB-only,
>   CD-deployable.
> - **S2** — `ResolveUnmatchedShelf` use case (on-OPAC; dedup across users +
>   cooldown), `ShelfResolveStatus` enum, `iter_resolvable_books` /
>   `mark_resolve_result` repo methods, `bibliohack shelf resolve` CLI, unit +
>   integration tests.
> - **S3** — crawl-plane `shelf_resolve` job (`run-job.sh` rematch→resolve under
>   the shared OPAC lock, `40 */6` crontab tick, `SHELF_RESOLVE_MAX` compose
>   knob). Ships on the next **manual NAS crawler rebuild** (crawler ≠ CD).
>
> - **S4** — Grafana "shelf coverage" panels on the crawl dashboard (unmatched
>   count, matched %, resolve-status breakdown, held/seeded, OPAC attempts),
>   mirroring the canon coverage row.
>
> Lint/format/`py_compile` clean in-sandbox; `mypy` + `pytest` (incl. testcontainers
> integration) **still to run on the Mac** (no Python 3.12 in the sandbox). Once
> green: NAS crawler rebuild (S3 job) + Grafana reload (S4), then move the kanban
> card to Done.

## Decisions locked (2026-06-22)

- **Scope:** all users, **bounded per run** (a `--max` cap, like `CANON_RESOLVE_MAX`),
  with **dedup across users** so a book on N shelves is queried once.
- **Trigger:** a **crawl-plane cron** job, mirroring `canon_resolve` — bounded,
  shares the 1 req/s budget and the crawl flock, deployed via the manual NAS
  crawler rebuild (crawler ≠ CD).
- **Miss policy:** **track attempt + timestamp**, re-try after a cooldown. A book
  the RBPA doesn't hold today may be held later as the mirror grows.

## The one thing that's different from canon (don't miss it)

Canon resolve's only job is to *seed TITNs* into `scrape_tasks`; the `canon match`
step (run before/after) does the linking. **Shelf entries have no equivalent
standalone re-match step** — today matching only happens inside `import_shelf`
while iterating CSV rows. So seeding + ingesting a held book will **not** link the
unmatched shelf entry on its own.

This plan therefore has **two** new use cases, not one:

1. **Resolve** — find unmatched entries, ask the OPAC, seed held TITNs, record the
   attempt.
2. **Re-match** — after the worker ingests, link now-present records to the
   unmatched entries (and flip `matched_via`). Cheap: the `ShelfRepository` port
   already exposes `match_isbn13` / `match_title_author`.

The crawl-plane job runs `re-match → resolve → (worker ingests) → re-match` so a
book held and ingested in one tick is linked on the next, exactly like
`canon match` brackets `canon resolve`.

## What we reuse unchanged

| Reuse | Where | For |
|---|---|---|
| `ResolveCanonSeed` shape | `catalog/.../use_cases/resolve_canon_seed.py` | The ISBN-first → title+author-fallback → seed-TITN → mark-status loop, batching, break-on-first-hit, per-run bound. Copy the structure. |
| `isbn_expert_expression`, `title_author_expert_expression` | `catalog/.../use_cases/discover_via_search.py` | OPAC expert queries (MARC 020 / title+author). |
| `OpacSearchGateway` (`discover_slice`) + `ScraplingOpacGateway` | `catalog` ports + infra | The live, throttled OPAC search. |
| `ScrapeTaskRepository.seed_one(Titn)` | `catalog` port + `PostgresScrapeTaskRepository` | Seed held TITNs for the existing worker. |
| `match_isbn13` / `match_title_author` | `reading_history` `ShelfRepository` | The re-match step's matching logic — already conservative, already tested. |
| The scrape worker | `bibliohack catalog worker` | Turns seeded TITNs into real records with copies + availability. |
| Crawl-plane plumbing | `infra/crawler/run-job.sh`, `crontab`, `docker-compose.crawler.yml` | Add one job case + one cron line + one env knob. |

## Schema change (one Alembic revision)

Add resolve-attempt bookkeeping to `shelf_entries` so we can (a) pick eligible
rows, (b) honour the cooldown, (c) avoid re-querying the same miss every tick:

```
ALTER TABLE shelf_entries ADD COLUMN resolve_status   text NOT NULL DEFAULT 'unchecked';
        -- 'unchecked' | 'held' | 'not_held'   (held → TITN seeded; not_held → miss)
ALTER TABLE shelf_entries ADD COLUMN resolve_attempts smallint NOT NULL DEFAULT 0;
ALTER TABLE shelf_entries ADD COLUMN last_resolved_at timestamptz NULL;
-- partial index for the eligibility scan (unmatched + due):
CREATE INDEX ix_shelf_entries_resolvable
  ON shelf_entries (last_resolved_at)
  WHERE matched_record_id IS NULL;
```

Per CLAUDE.md / AGENTS: **one Alembic revision** for this, and the SQLAlchemy
model in `reading_history/infrastructure/postgres/models.py` updated to match.
A successful re-match (entry gets a `matched_record_id`) naturally drops it out of
the eligibility query; optionally set `resolve_status` for analytics symmetry with
canon's `acquire_status`.

> Note on `matched_via`: canon uses a 4-state `acquire_status` enum on its own
> table. For shelf we keep `matched_via` as-is (it describes *how* a match was
> made) and add the separate `resolve_status` (whether we've *asked the OPAC*),
> because the two are orthogonal.

## Eligibility query (the dedup'd "what to resolve")

A new read method on the reading-history side — call it
`iter_resolvable_unmatched(limit, cooldown)` — selecting:

- `matched_record_id IS NULL` (still unmatched), and
- `resolve_status = 'unchecked'` **OR** (`resolve_status = 'not_held'` AND
  `last_resolved_at < now() - cooldown`), and
- **dedup across users**: collapse rows sharing the same `isbn_13`, else the same
  normalised `(title, author)`, to a single OPAC query per distinct book. One
  resolve outcome then updates every entry in that group (so two users with the
  same book both get linked from one query).

Cooldown as an env knob (suggest 30 days). Order by `last_resolved_at NULLS FIRST`
so never-tried entries go first.

## New code (all small)

```
reading_history/
  application/
    use_cases/
      resolve_unmatched_shelf.py   # NEW — mirror of ResolveCanonSeed
      rematch_shelf.py             # NEW — link now-present records, flip matched_via
    ports.py                       # +iter_resolvable_unmatched, +set_resolve_status
  infrastructure/postgres/
    models.py                      # +3 columns (above)
    shelf_resolve_repository.py    # NEW — eligibility scan + status writes (or extend shelf_repository)
  interfaces/
    cli.py                         # +`bibliohack shelf resolve` and `bibliohack shelf rematch`
backend/alembic/versions/
  XXXX_shelf_resolve_columns.py    # NEW — the migration
```

`ResolveUnmatchedShelf` depends on abstract ports only: the new
`UnmatchedShelfRepository` (reading_history) plus the existing catalog
`OpacSearchGateway` and `ScrapeTaskRepository`. Cross-context dependency on
catalog ports is fine and already precedented (the shelf read repo imports the
catalog read repo). Keep the use case pure; wiring lives in the CLI.

### CLI (mirrors `catalog canon resolve`)

```
bibliohack shelf rematch                       # DB-only: link ingested records, flip matched_via
bibliohack shelf resolve --max 100 --rate 1.0  # on-OPAC, bounded, polite
```

`shelf_app` already exists in `reading_history/interfaces/cli.py` (currently just
`import`). Add the two commands there, copying the gateway/session wiring from
`_run_canon_resolve`.

## Ops — crawl plane (crawler ≠ CD)

Mirror the canon wiring exactly:

- **`infra/crawler/run-job.sh`** — add a `shelf_resolve)` case: `bibliohack shelf
  rematch` → `bibliohack shelf resolve --max "${SHELF_RESOLVE_MAX:-100}" --rate
  "${CRAWL_RATE:-1.0}"`. Use the **shared crawl lock** (it hits the OPAC), same as
  `canon_resolve`.
- **`infra/crawler/crontab`** — one line on a tick that doesn't collide with
  discover/refresh/`canon_resolve` (canon is `50 */4`; pick e.g. `20 */6 * * *`).
- **`docker-compose.crawler.yml`** — add `SHELF_RESOLVE_MAX: "100"` (and reuse
  `CRAWL_RATE`).
- **Deploy:** manual **NAS crawler rebuild**, not CD. Won't auto-deploy from a
  push to main.
- **Grafana (optional, follow canon):** a "shelf coverage" row on the crawl
  dashboard — unmatched count, % resolved held, attempts, last-tick linked.
  Defer if status rows are enough.

## Politeness / safety (non-negotiable, from canon-import §risks)

- Bounded per run (`--max`) and rate-capped at `CRAWL_RATE`; shares the crawl
  flock so it can never starve novedades growth or raise the OPAC rate.
- ISBN first (precise, MARC 020), title+author only with an author present and via
  the existing sanitised builder — never a bare-title query.
- **Never invent a phantom record:** a miss only writes `resolve_status =
  'not_held'`; we only ever seed TITNs the OPAC actually returns.
- Re-match keeps the conservative Goodreads thresholds (prefer ISBN) to keep false
  positives low.

## Tests (the backend gate must stay green)

- `resolve_unmatched_shelf` unit tests mirroring
  `tests/catalog/.../test_resolve_canon_seed.py`: held-by-ISBN, fallback-to-title,
  miss → `not_held`, dedup across users (one query, two entries updated), `--max`
  bound, cooldown skip.
- `rematch_shelf` unit tests: ingested record now links, `matched_via` flips,
  already-matched untouched.
- Repository integration test for `iter_resolvable_unmatched` (eligibility +
  cooldown + dedup) against a test DB, like the existing
  `tests/reading_history/test_import_*`.
- Gate before push: `ruff format --check .`, `ruff check .`, `mypy src`, `pytest`.

## Docs

Move the kanban card to Done and update the backlog, then regenerate — **never
hand-edit `docs/site/*.html`**:

- `docs/site/_src/kanban.md` — move card #2 to Done.
- `docs/site/_src/pending-and-ops.md` — drop/append the row.
- Promote this draft into the doc set (it already carries the frontmatter), and
  cross-link from `docs/design/canon-import.md` ("user-shelf variant").
- Run `make docs`.

## Suggested build order

| Step | Deliverable | Plane | Notes |
|---|---|---|---|
| S0 | Alembic migration + model columns + eligibility query | DB-only | Land + test first; no behaviour change yet. |
| S1 | `RematchShelf` use case + `bibliohack shelf rematch` | DB-only | Useful immediately — links the backlog of unmatched entries the novedades crawl has *already* brought in. Ships value with zero OPAC load. |
| S2 | `ResolveUnmatchedShelf` use case + `bibliohack shelf resolve` | on-OPAC | The fetcher proper. Bounded + polite. |
| S3 | Crawl-plane job (run-job.sh + crontab + compose knob) + NAS rebuild | crawl plane | Self-maintaining. |
| S4 | (optional) Grafana shelf-coverage row | crawl plane | Defer until status rows fall short. |

S1 alone is a quick, deploy-via-CD win (no OPAC, no crawler rebuild) that closes
the "re-match for free as the catalogue grows" promise that's currently only
honoured on re-import. S2–S3 add the active acquisition.

## Open questions for José

1. **Cooldown length** for re-trying `not_held` — 30 days a good default?
2. **Which shelves count?** All three (read / currently-reading / to-read), or
   prioritise `to-read` + `read` (likeliest to be wanted) and skip nothing — just
   ordering? Suggest: resolve all, order `read`/`to-read` first.
3. **Re-match cadence:** should `shelf rematch` also run on the **app/CD plane**
   (e.g. a light periodic task) so users who never trigger the crawl path still
   get linked as novedades grows — or is the crawl-plane bracket enough?
4. **StoryGraph:** card #5 adds a second importer. Nothing here is Goodreads-
   specific (we resolve from stored `title`/`author`/`isbn_13`), so this fetcher
   covers StoryGraph entries for free once they exist — confirm that's the intent.
