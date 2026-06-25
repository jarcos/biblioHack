---
title: "biblioHack — Relevance &amp; Libraries"
h1: "Relevance &amp; Libraries — milestone plan"
tagline: "Designed 2026-06-15 · ✓ both milestones shipped (Relevance 2026-06-16, Libraries L0–L4 2026-06-22)."
---
Two coupled features that make the catalogue feel curated and personal:

1. **Catalogue relevance** — every record gets a `relevance_score` so `/browse`
   and search lead with the best titles instead of "newest TITN first".
2. **Libraries** — users follow one or more real RBPA branches (by proximity);
   the catalogue, search, and recommendations are then scoped/primed to what
   they can actually borrow nearby.

They share a spine: a **global** relevance score (precomputable, intrinsic to a
record) and a **contextual** library scope (per-user, applied at query time).
Sequenced **relevance first** (helps everyone immediately, no geo dependency),
**libraries second**.

> **Status: ✓ SHIPPED.** Relevance (R0–R3) went live 2026-06-16 (43,412 records
> scored, default `/browse` sort + search filter/tiebreak; nightly recompute on
> the crawl plane). Libraries (L0–L4) went live 2026-06-22 — branch geo/contact
> schema + geocode CLI (571/573 branches), follow-branches API, the «Mis
> bibliotecas» picker on `/account`, `library_scope` pre-filter on browse +
> search, and library-aware recommendations. The external canon boost ("R-later")
> also shipped via the separate canon-import pipeline (`docs/design/canon-import.md`).
> This page is kept as the design record; the build order below is historical.
> Companion HTML: `docs/site/relevance-and-libraries.html`.

---

## Current state (verified in code + prod, 2026-06-15)

- **Records** (`bibliographic_records`): ~37k, **all `pub_year` ≥ 2023** (discovery
  is the `@fepu>=2024` slice). No relevance/popularity/score column. **94% have an
  ISBN** (34,758 / 37,068). Anglophone enrichment is sparse here: cover resolution
  is ~11% (958 resolved vs 7,439 not-found), so external ratings will match poorly
  on this new-book corpus.
- **Branches** already exist (`holdings.Branch`, table `branches`): **509 branches**
  network-wide, natural key = AbsysNET `BranchCode` (e.g. `AL00`), `name` (the
  municipality). `municipality`/`province` columns exist but are **NULL**; there is
  **no geo, address, url, phone, or hours**.
- **Availability** is a full time-series: 167k copies, 249k snapshots, essentially
  every record has copies + history. Per-copy status enum: `available` (disponible),
  `loaned` (prestado), `reserved` (reservado), `unavailable` (inventory/damaged/
  excluded), `unknown`. Loaned snapshots carry `due_back_at`.
- **`/browse`** (`GET /catalog/browse`) sorts only `newest`/`title`, with an
  `available_only` flag that checks the latest snapshot across **any** branch.
- **Users** (`identity.UserModel`): no library link. Multi-user, Redis sessions.
- **Search**: keyword (FTS), semantic (pgvector KNN), hybrid (RRF). Recommender:
  per-user taste centroid + pgvector KNN.

---

## Decisions locked (2026-06-15 interview)

| # | Decision | Choice |
|---|---|---|
| D1 | Relevance signal direction | **Internal-first**; external canon as a positive-only boost in a later phase |
| D2 | "Related to import" means | **Enrichment score only** (compute after import; not crawl-priority — for now) |
| D3 | Relevance components (v1) | **Demand + holdings breadth + recency + display completeness** |
| D4 | Weighting | **Balanced, demand the largest weight** |
| D5 | Trending sub-signal | **Included in v1** (recent demand acceleration), designed robust to thin history |
| D6 | Library choice | **Multiple branches** per user |
| D7 | Default `/browse` ranking with a library | **Hard filter** to the user's libraries |
| D8 | Filter scope levels | **My libraries → my province → full catalogue** |
| D9 | Branch picker | **Geolocation proximity** (nearest first) |
| D10 | Branch geo source | **Official directory (Junta/Ministerio, CC-BY) + Nominatim geocode fallback** |
| D11 | User location | **Client-side only, never stored** server-side |
| D12 | Geolocation-denied fallback | **Searchable branch list** (type-ahead) |
| D13 | On-loan titles in ordering | **Relevance-first** + availability badges + existing `available_only` quick filter |
| D14 | Library awareness in recommendations | **Yes, in this effort** (prioritise borrowable-nearby titles) |
| D15 | Scope reach | **Browse + search** both library-scoped + relevance |
| D16 | Search × global relevance | **Filter + tiebreak only** (query drives ranking; relevance breaks near-ties) |
| D17 | Relevance recompute job placement | **Crawl/worker plane** (supercronic), nightly — needs the manual crawler rebuild |
| D18 | Earmarked canon sources (later) | Wikidata · curated award lists · Open Library ratings · LibraryThing/OCLC |

Author's-call defaults I'm assuming unless you say otherwise: library selection is
**optional at registration** (skippable, editable in profile); anonymous / no-follow
users get **full catalogue + relevance**; starting component weights **demand 0.45 /
holdings 0.25 / recency 0.20 / completeness 0.10** (tune empirically).

---

## Phase R — Catalogue relevance (ships first)

### R0 — Schema

`bibliographic_records` (Alembic revision):

- `relevance_score double precision NOT NULL DEFAULT 0` — indexed (`ix_records_relevance` desc).
- `relevance_components jsonb` — per-component sub-scores, for debugging + a future
  "why this" UI badge set.
- `relevance_updated_at timestamptz` — staleness tracking.

### R1 — The score (`catalog` domain + a recompute use case)

`relevance_score ∈ [0,1]`, a weighted blend of four **corpus-normalised** components
(percentile or min-max with log compression where noted):

1. **Demand** (largest weight) — derived purely from the availability time-series:
   - *scarcity* = share of observed time the record's copies are `loaned`/`reserved`
     vs `available`, over a trailing window (adaptive while history is short).
   - *velocity* = `available → loaned` transitions per copy per week (checkout events).
   - *trending* = recent velocity vs its own baseline (acceleration). Shrunk toward 0
     while history is thin, so it can't dominate on two weeks of data.
   - `unavailable`/`unknown` snapshots are excluded as noise.
2. **Holdings breadth** — `log(copies)` and `log(distinct branches)`: the library
   system's own buying signal (it stocks many copies of titles in demand).
3. **Recency** — `pub_year` + `first_seen_at`, gentle decay, to keep the first look fresh.
4. **Display completeness** — has cover (`resolved`) / summary / ISBN / subjects, so
   sparse or broken records don't lead the page.

**Cold-start:** a record with no availability history has its demand component set
**neutral** (not zero) and ranks on recency + completeness + holdings, so brand-new
acquisitions are never buried.

### R2 — Recompute job (crawl/worker plane)

- New CLI: `bibliohack catalog relevance recompute [--since ...]`.
- Scheduled **nightly** via the crawler container's supercronic crontab, alongside
  the embeddings/genre enrichment. Pure DB compute (reads availability + holdings).
- **Ops note (crawler ≠ CD):** this lives in `docker-compose.crawler.yml`, so shipping
  it / changing the crontab needs the manual NAS rebuild
  (`docker compose -p bibliohack-crawler … up -d --build`), not a normal `git push`.
- Not OTel-instrumented (crawl plane); add a Grafana panel for relevance coverage +
  freshness on the existing crawl dashboard.

### R3 — Surfacing it

- `BrowseSort` gains `RELEVANCE` and becomes the **default** for `/browse`.
- `/browse` and search results render availability badges; the existing `available_only`
  stays as an optional "available now" quick filter (D13).
- **Search × relevance (D16):** the query drives ranking (FTS rank / vector distance /
  RRF); `relevance_score` only breaks near-ties — it never out-ranks a strong textual/
  semantic match. Keeps exact matches safe.

### R-later — External canon/popularity boost (Phase 2, with the back-catalogue)

A **positive-only** boost applied where a record matches, never a penalty for no match.
Dormant today (corpus is 2023+; classics arrive with back-catalogue import). Earmarked
sources, in priority order: **Wikidata** (literary awards P166, notability via Wikipedia
language-count) → **curated award-winner seed list** (Cervantes, Planeta, Nacional,
Nobel…) → **Open Library** ratings/reading-log → **LibraryThing/OCLC** "held by N
libraries". Match by ISBN-13 first, then conservative title+author (reuse the Goodreads
matcher).

---

## Phase L — Libraries (ships second; depends on Phase R)

### L0 — Branch enrichment

`branches` (Alembic revision) — add nullable: `address`, `lat`, `lng`, `url`, `phone`,
`opening_hours`; **backfill `municipality` (from `name`) and `province` (from the
`BranchCode` prefix) now**, independent of geo.

- **Geo/address sourcing (D10):** primary = an official **library-directory dataset**
  (Junta de Andalucía open data / DERA, or the Ministerio de Cultura library directory)
  — CC-BY, license-compatible with the catalogue. **First implementation step: confirm
  such a dataset exists and its fields/licence.** Fallback that always works: geocode
  each branch's `municipality` via **OpenStreetMap Nominatim** (town-centroid is fine —
  users pick the nearest town's library). One-off CLI: `bibliohack holdings enrich-branches`.

### L1 — Following branches

- New table `user_followed_branches` (`user_id` FK → users, `branch_code` FK → branches,
  `created_at`, optional `position`); PK `(user_id, branch_code)`. Many branches per user (D6).
- API (all under api-routed prefixes — **tunnel rule: new frontend-called paths must be
  `/api/*`**):
  - `GET /api/branches` — full list with `lat/lng/municipality/province`, so the browser
    can distance-sort **client-side** (D9, D11). Cacheable; branches change rarely.
  - `GET /api/me/branches`, `PUT /api/me/branches` (or `POST`/`DELETE`) — manage follows.

### L2 — Selection UX (frontend)

- Registration (optional/skippable) + profile: request **browser geolocation**; sort the
  `/api/branches` list by distance in the browser; user picks one or more. **Location never
  leaves the browser** (D11). If the prompt is denied → **type-ahead search** over all
  branch names/municipalities (D12).

### L3 — Scoping browse + search (D7, D8, D15)

- Add a `scope` parameter to `/catalog/browse` **and** the search endpoints:
  `mine` (default when the user follows ≥1 branch) → `province` → `full`.
- `mine` = records with ≥1 active copy in any followed branch (hard filter via
  `copies → branches`). `province` = copies in any branch sharing a followed branch's
  province. `full` = whole mirror.
- Within scope, order by `relevance_score` (D13). Anonymous / no-follow → `full` + relevance.

### L4 — Library-aware recommendations (D14)

- The `recommendations` context re-ranks candidates to prioritise titles **borrowable in
  the user's followed branches** (a boost on the existing taste-centroid KNN), with an
  optional "nearby only" toggle. Shelf-exclusion and rationale flow unchanged.

---

## Schema & migration summary (one Alembic revision each)

1. `bibliographic_records`: `relevance_score`, `relevance_components`, `relevance_updated_at` (+ index).
2. `branches`: `address`, `lat`, `lng`, `url`, `phone`, `opening_hours`; backfill `municipality`, `province`.
3. `user_followed_branches`: new join table.

## Suggested build/PR order

1. **R0+R1+R2** — schema, score domain + recompute CLI, nightly crontab (crawler rebuild).
2. **R3** — `RELEVANCE` sort + default; availability badges; search tiebreak.
3. **L0** — branch enrichment (confirm directory dataset → import → geocode gaps).
4. **L1** — `user_followed_branches` + `/api/branches` + `/api/me/branches`.
5. **L2** — geolocation picker + searchable fallback (registration + profile).
6. **L3** — `scope` on browse + search.
7. **L4** — library-aware recommendations.
8. **R-later** — external canon boost (with/after back-catalogue import).

## Open dependencies / risks

- **Directory dataset (L0):** if no clean CC-BY directory with coordinates exists,
  Nominatim-geocoded town centroids are the guaranteed fallback (coarser, no per-branch
  address). Confirm before committing.
- **Thin demand history:** demand + trending stabilise as the availability series grows;
  shrinkage keeps early scores sane. Re-tune weights after ~1–2 months of history.
- **Crawler ≠ CD (R2):** the recompute job ships in the crawler image — remember the
  manual NAS rebuild; a normal deploy won't pick it up.
- **Tunnel routing (L1):** every new frontend-called endpoint must sit under `/api/*`
  (or another api-routed prefix) or it falls through to the static frontend and returns
  HTML instead of JSON.
- **Province filter (L3):** depends on `branches.province` being backfilled — gate L3 on L0.
- **Back-catalogue timing:** the canon boost (R-later) only earns its keep once pre-2024
  records exist; the full-catalogue crawl is a ~2–4 month effort.
