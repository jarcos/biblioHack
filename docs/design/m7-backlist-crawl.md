---
title: "biblioHack — M7: network-wide backlist crawl"
h1: "M7 — Network-wide backlist crawl"
tagline: "Spec for the observable, resumable backlist discovery job + crawl dashboards."
---

> **Status: design spec, 2026-06-26.** Drafted after correcting the M7 framing
> — see [Architecture](architecture.html) §11 M7 and §2.3. Backend slice
> (use case + `seed_range` priority + index migration + CLI) in progress.

## 1. What M7 actually is

M7 is a **coverage** job, not a scoping one. Discovery already runs
network-wide: the OPAC expert queries (`@fepu` publication-year slices, TITN
enumeration) return records from all eight provinces, `SUBC` only scopes
*display* not search, and ingest already stores copies for every branch. So
there is no Huelva/`SUBC` filter to generalise.

What's missing is the **pre-2024 backlist**. Today's mirror is roughly:

- the one-time bootstrap TITN sweep range (`catalog seed` + `worker`, run once), plus
- the ongoing novedades discovery — the only `discover_worker` cron, running
  `@fepu>=2024` (`DISCOVER_YEAR_FROM=2024`).

Records published before 2024 that the bootstrap sweep never reached — in any
province — aren't mirrored. Closing the gap means **enumerating the whole TITN
space and letting the worker ingest it**, within the 1 req/s politeness budget
(§6.3). At an effective drain of ~1–1.5k records/hour that's weeks of polite
crawl over the ~2.66M-record space (high-water mark `2,662,739`, §12).

The goal of this spec is to make that crawl **resumable, observable, and
freshness-safe** — it must never starve the hourly novedades + refresh paths
that keep "on shelf now" current.

## 2. Design in one paragraph

TITN enumeration is the exhaustive discovery path. We already have the
primitives: `ProbeTitnRange` (high-water mark), `SeedDiscoveredTasks`
(idempotent `seed_range(low, high)`), and the worker that drains `discovered`
tasks. The worker claims by `priority ASC, titn ASC`
(`scrape_task_repository.claim_next_batch`), so the whole milestone reduces to:
**seed the backlist at a lower priority than novedades, in resumable chunks,
and let the existing worker fill its idle capacity with it.** Freshness wins
automatically because novedades/refresh sit at higher precedence in the same
queue.

## 3. Components

### 3.1 `SeedBacklistChunk` (new use case)

`catalog/application/use_cases/seed_backlist_chunk.py`

Each run advances a persisted cursor through the TITN space and seeds the next
chunk as `discovered` at backlist priority:

1. Read the backlist cursor. If absent (first run), call `ProbeTitnRange` once
   to establish `total` (high-water mark) and start `next_offset = 1`.
2. Compute the chunk `[next_offset, min(next_offset + chunk_size, total)]`.
3. **Top-up mode (recommended):** before seeding, count outstanding backlist
   rows (`status='discovered' AND priority = BACKLIST_PRIORITY`). Seed only
   enough to refill the queue to a target depth (e.g. 100k), so the discovered
   backlog stays bounded and `count_by_state` / the claim index stay cheap.
   (Simpler alternative: always seed a fixed chunk — relies on `seed_range`
   idempotency, but lets the discovered backlog balloon to millions of rows.)
4. `seed_range(low, high, priority=BACKLIST_PRIORITY)` — idempotent; only
   unknown TITNs insert, so re-runs and overlap with the bootstrap range are
   free.
5. Advance and persist the cursor (`next_offset = high + 1`). Stop when
   `next_offset > total`.

Returns a typed `BacklistResult(seeded, range_low, range_high, next_offset,
total, queue_depth)` for CLI/observability, mirroring `DiscoverResult` /
`SeedResult`.

### 3.2 Cursor — reuse `discovery_cursors`

The `discovery_cursors` table (`expression PK, next_offset, total`,
migration `0005`) already models exactly "how far through a sequence we've
gone." Reuse it with a reserved sentinel expression, e.g.
`__backlist_titn__`, where `next_offset` = the next TITN to seed and `total` =
the probed high-water mark. No new table, no new migration for state. (The
only semantic stretch: `next_offset` here is a TITN, not a DOC search offset —
documented at the call site.) `DiscoveryCursorRepository.get/save` are reused
as-is.

### 3.3 Priority — the freshness guard

Novedades and refresh seed at the default `priority = 100`. Backlist seeds at
`BACKLIST_PRIORITY = 500` (lower precedence; claim orders `priority ASC`). The
worker therefore always drains fresh + refresh work first and fills only its
*remaining* hourly capacity with backlist. No worker logic changes.

`seed_range` / `seed_one` currently hardcode the default priority; add an
optional `priority: int = 100` parameter to `ScrapeTaskRepository.seed_range`
and its Postgres implementation (one `INSERT ... VALUES` column).

### 3.4 Worker — no functional change, one index

The worker already drains by priority. But a backlog of up to 2.66M
`discovered` rows makes the claim query
(`WHERE status='discovered' ORDER BY priority, titn ... FOR UPDATE SKIP LOCKED`)
expensive against the single-column `ix_scrape_tasks_status`. Add a composite
index:

```
ix_scrape_tasks_status_priority_titn ON scrape_tasks (status, priority, titn)
```

This is the one real schema change → **Alembic revision required** (per
`CLAUDE.md`). Operational note: building an index on a multi-million-row table
inside the deploy migration transaction will lock writes; prefer
`op.create_index(..., postgresql_concurrently=True)` in a non-transactional
revision, **or** create it on the NAS before the big seed and add the Alembic
revision as a no-op/IF NOT EXISTS guard so CI and prod agree.

### 3.5 CLI — `bibliohack catalog backlist`

`catalog/interfaces/cli.py`, alongside `discover` / `worker`:

```
bibliohack catalog backlist --chunk 50000            # seed next chunk (resumable)
bibliohack catalog backlist --target-depth 100000    # top-up mode
bibliohack catalog backlist --reset                  # re-probe + restart cursor
bibliohack catalog backlist --status                 # print cursor + queue depth, seed nothing
```

Prints: probed `total`, cursor `next_offset` (→ "% swept"), rows seeded this
run, current backlist queue depth. Pure DB + at most one tiny probe, so it
needs no special politeness handling itself — the OPAC budget is spent by the
**worker** draining the queue.

## 4. Crawler-plane wiring (manual NAS rebuild — crawler ≠ CD)

A new job in `infra/crawler/run-job.sh` and a cron line in
`infra/crawler/crontab`. The backlist *seeder* is cheap/DB-only, so it doesn't
need the shared crawl lock for politeness — but give it the shared lock anyway
so a giant seed can't run while a probe is mid-flight. The existing hourly
`discover_worker` already drains the queue; the backlist job only keeps it
topped up.

```sh
# run-job.sh
  backlist)
    bibliohack catalog backlist \
      --target-depth "${BACKLIST_TARGET_DEPTH:-100000}" \
      --chunk "${BACKLIST_CHUNK:-50000}"
    ;;
```

```cron
# Top up the backlist queue twice a day; the hourly worker drains it.
0 1,13 * * * /app/run-job.sh backlist
```

New env knobs in `docker-compose.crawler.yml` (`environment:`):
`BACKLIST_TARGET_DEPTH`, `BACKLIST_CHUNK`, and optionally
`BACKLIST_PRIORITY`. `CRAWL_RATE` stays at 1.0 — untouched.

Tuning lever for "how fast does the backlist fill": raise `WORKER_MAX` (the
hourly drain cap) and/or `DISCOVER_MAX` headroom — never `CRAWL_RATE`. With
novedades producing ~400/hr and `WORKER_MAX=1000`, ~600/hr of worker capacity
already spills onto the backlist; that alone clears ~2.66M in ~6 months. To go
faster, raise `WORKER_MAX` toward the 1 req/s ceiling (≈3600/hr) and watch the
failure-rate panel.

## 5. Dashboards — extend `infra/grafana/bibliohack-crawl-dashboard.json`

Postgres datasource `bibliohack-pg`, `rawSql`, matching existing panels.

| Panel | Type | SQL (sketch) |
|---|---|---|
| Backlist swept % | stat | `SELECT round(100.0*next_offset/nullif(total,0),2) FROM discovery_cursors WHERE expression='__backlist_titn__'` |
| Backlist queue depth | stat | `SELECT count(*) FROM scrape_tasks WHERE status='discovered' AND priority=500` |
| Backlist drained / day | timeseries | parsed rows at backlist priority bucketed by `source_seen_at::date` |
| Backlist ETA (days) | stat | remaining (`total - parsed-at-backlist`) ÷ recent daily drain rate (derived) |

Also revisit the existing **"TITN space covered"** stat: its denominator
`2662739` is hardcoded and the monthly re-probe will grow it — template it off
`discovery_cursors.total` or update on each re-probe. Dashboard JSON syncs into
the Grafana stack on the NAS (same path as the shelf-coverage row), not via CD.

## 6. Testing (TDD, per AGENTS.md)

- **Unit** `test_seed_backlist_chunk.py`: cursor seeded from probe on first run;
  chunk math; advances and persists; stops at `total`; idempotent re-run;
  top-up respects target depth; seeds at `BACKLIST_PRIORITY`.
- **Repo** `test_scrape_task_repository.py`: `seed_range(priority=…)` persists
  the priority; `claim_next_batch` returns priority-100 rows before priority-500
  rows even when the 500s have lower TITNs (the freshness guarantee).
- **CLI** smoke: `backlist --status` prints cursor + depth and seeds nothing;
  `--reset` re-probes.
- **Migration**: `alembic upgrade head` + `downgrade` round-trips the index;
  index present in `\d scrape_tasks`.
- Backend gate stays green: `ruff format --check . && ruff check . && mypy src && pytest`.

## 7. Shipping order

1. Backend (use case, `seed_range` priority param, CLI, Alembic index) →
   commit + push → **rides CD** on green.
2. Pre-create the composite index on the NAS (concurrently) if not done via the
   migration, **before** the first big seed.
3. Crawler job (`run-job.sh`, `crontab`, compose env) → push → **manual NAS
   rebuild** (`docker compose -p bibliohack-crawler -f docker-compose.crawler.yml up -d --build`).
4. Dashboard panels → sync JSON into Grafana.
5. Kick the first chunk (`backlist --status` to confirm cursor, then let the
   cron run), watch "Backlist swept %" + failure-rate panels.

> Build/git/Docker run on the Mac, not in the Cowork sandbox — each of the
> push/rebuild steps is executed there (iTerm), per the established workflow.

## 8. Out of scope / follow-ups

- **`scrape_log` / req-rate panel.** A true politeness panel (requests/sec over
  time) needs `scrape_log` wired, still pending (kanban #4, OTel on the crawl
  plane). Not required for M7 — the 1 req/s throttle is enforced in-process.
- **Publication-year slicing** as an alternative backlist axis (`@fepu<2024`
  walked backward). Rejected as primary: not exhaustive (depends on every
  record carrying a parseable pub date) and more OPAC-expensive than TITN
  enumeration. TITN enumeration is the exhaustive path (§6.6).
- **MARC dump from the Junta** would obsolete the whole crawl and close the gap
  instantly — orthogonal, still parked (`docs/outreach/marc-dump-request.md`).
