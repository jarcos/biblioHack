---
title: "biblioHack — Canon Import"
h1: "Canon Import — classics from Wikidata &amp; open sources"
tagline: "Designed 2026-06-17 · C0–C2 built 2026-06-18. A back-catalogue path that doesn't depend on the Junta MARC dump or a full OPAC crawl."
---

How to surface the **classics** in biblioHack without (a) waiting on the RBPA
MARC dump or (b) crawling the whole ~2.66M-TITN historical catalogue. The idea:
let open knowledge bases tell us *which* works are canonical, and let the live
OPAC stay the source of truth for *what the libraries actually hold*.

> Status: **C0, C1 and C2 built** (2026-06-18) — the off-OPAC Wikidata seed
> builder (`canon_seed` table + `bibliohack catalog canon refresh-seed`), the
> DB-only matcher + coverage report (`bibliohack catalog canon match`), and the
> positive-only canon relevance boost (now folded into the nightly
> `catalog relevance recompute`), and **C3 ISBN-resolve** (`catalog canon
> resolve`: query the OPAC by ISBN for unmatched classics, seed held TITNs for
> the worker, mark `held`/`not_held`). C3 title+author resolve and C4 remain
> planned. C0–C2 touch the OPAC zero times; C3 resolve is the one polite
> on-OPAC step.
> Sibling plan: `docs/design/relevance-and-libraries.html` (Phase R / R-later).

---

## The one rule that shapes everything

biblioHack is a **mirror of what the Red de Bibliotecas Públicas de Andalucía
actually holds** — every record has real copies and live availability. So we do
**not** import Wikidata works as catalogue records: that would invent holdings
the libraries don't have, with no copies and no availability, breaking the core
promise of the site.

Instead, the external sources become a **canon seed** — a curated list of
"works worth having" — that drives two separate workstreams:

1. **Canon-seeded acquisition** ("the import"): for each seed work, ask the live
   OPAC whether the RBPA holds it (by ISBN, then title+author). When it does,
   ingest that record through the **existing scrape pipeline** so it arrives
   with real copies + availability. Targeted lookups (tens of thousands), not a
   millions-record crawl.
2. **Canon relevance boost** (this is Phase **R-later** from the relevance plan):
   the same seed becomes a *positive-only* signal on records already in the
   mirror — matched by ISBN-13 then title+author — feeding a new `canon`
   sub-score in `relevance_components`. It can never penalise a non-match.

Workstream 2 pays off immediately on classics the RBPA *already* holds (there
are surely some even in the 2024+ slice — reissues, anniversary editions).
Workstream 1 grows the catalogue's classic coverage over time, politely.

---

## What we already have (reuse, don't rebuild)

- **Expert-query discovery** (`discover_via_search.py`, `build_expert_url`): the
  OPAC's `xsqf99` expert syntax already drives resumable, cursor-paginated
  discovery (`(@fepu>=2024)`). Canon acquisition is the same machinery aimed at
  ISBN/title instead of publication year.
- **A book matcher**: the Goodreads shelf import already matches external books
  to mirror records by **ISBN-13 first, then title+author trigram** — exactly
  the matching canon import needs (reading_history `import_shelf`).
- **Open Library integration**: already used in the **covers** pipeline, so an
  HTTP client + politeness pattern for OL exists to extend to ratings.
- **The relevance blend** (`catalog/domain/relevance.py`): adding a `canon`
  component is a localised change to a tested, pure scorer; the nightly
  recompute job already exists.
- **The crawl plane** (supercronic on the NAS): a natural home for both a
  monthly off-OPAC "refresh the seed" job and a polite on-OPAC "resolve & ingest
  unmatched classics" job.

---

## Sources

| Source | Gives us | License | Access | Notes |
|---|---|---|---|---|
| **Wikidata** (primary) | Canonical works: title, author, year, ISBN-13/10, awards (P166), notability (sitelink/Wikipedia language count) | **CC0** (public domain) | `query.wikidata.org/sparql` — free, no auth | Best signal-to-effort. CC0 means no attribution constraint, though we still cite. |
| **Curated award seed** | Cervantes · Planeta · Premio Nacional · Nobel · Príncipe de Asturias… winners | Facts (not copyrightable); lists compiled by us | Mostly *derived from Wikidata P166*; a small hand-kept YAML as fallback | Guarantees the marquee names even if a Wikidata edge is missing. |
| **Open Library** | Ratings / reading-log counts; covers; work→edition→ISBN | Open (data CC0-ish; check per-endpoint) | REST API + bulk dumps | Already wired for covers. Ratings feed a popularity sub-signal. |
| **LibraryThing / OCLC** (optional, later) | "held by N libraries" (worldcat-style ubiquity) | Restrictive / rate-limited | API key | Earmarked, low priority — only if Wikidata+OL prove insufficient. |

Match key priority everywhere: **ISBN-13 → ISBN-10 (converted) → conservative
title+author**, mirroring the Goodreads matcher to keep false positives low.

---

## The canon seed builder (Wikidata)

A new off-OPAC use case queries WDQS in pages and writes a normalised seed.

**Scope of the query** (tunable): literary works (`wdt:P31`/subclass of literary
work) that are either (a) in Spanish (`wdt:P407 wd:Q1321`), (b) by Spanish or
Latin-American authors, or (c) carry a literary award (`wdt:P166`), ranked by
notability (count of Wikipedia sitelinks). Pull per work: label (`P1476`/rdfs),
author (`P50`), publication year (`P577`), ISBN-13 (`P212`) / ISBN-10 (`P957`),
awards (`P166`), and the QID + sitelink count.

Practicalities: WDQS is free/no-auth but **enforces a ~60s query timeout**, so
the builder paginates (`LIMIT`/`OFFSET` or chunk by award/decade), backs off on
429, sets a descriptive `User-Agent`, and is **idempotent** (upsert by QID).
Target seed size: a few thousand → low tens of thousands of works.

Output → a new **`canon_seed`** table:

```
canon_seed(
  id, source ('wikidata'|'award_list'|'openlibrary'),
  source_ref (QID / OLID), title, author, pub_year,
  isbn13 text[], awards text[], notability int,
  matched_record_id uuid NULL,   -- set by the matcher (C1)
  acquire_status ('unchecked'|'held'|'not_held'|'ingested'),
  created_at, updated_at
)
```

---

## Pipeline

```
Wikidata / award lists / Open Library
        │  (C0) seed builder  — off-OPAC, monthly
        ▼
   canon_seed  ──(C1) matcher: ISBN-13 → title+author trigram──►  existing bibliographic_records?
        │                                                          │ yes → link matched_record_id
        │                                                          ▼
        │                                                   (C2) canon relevance boost
        │                                                        (positive-only sub-score)
        │ no match
        ▼
  (C3) OPAC resolve  — expert query by ISBN / title+author, polite 1 req/s
        │  held?  → seed scrape_tasks → existing worker ingests (real copies + availability)
        │  not held? → mark not_held (don't invent a record)
        ▼
   mirror grows with genuinely-held classics → C2 boost now applies to them too
```

---

## Schema &amp; surfacing changes

- **`canon_seed`** table (above) — one Alembic revision.
- **`relevance_components`** gains a `canon` key; `catalog/domain/relevance.py`
  adds a *positive-only* canon term (a small additive boost, capped, applied
  after the four-component blend so it lifts matched classics without letting a
  single award dominate). Re-tune weights; the nightly recompute picks it up.
- Optional: a `provenance` tag on records ingested via canon acquisition
  (`discovered_via = 'canon'`) for analytics — distinct from the novedades crawl.
- **Frontend**: optional "premiado / clásico" badge when a record has a canon
  match (uses the existing `relevance_components` payload — no new endpoint).

---

## Ops (crawl plane — remember: crawler ≠ CD)

- **Seed refresh** — off-OPAC, monthly: `bibliohack catalog canon refresh-seed`
  (hits WDQS / OL, own flock, no OPAC budget). 
- **Canon acquisition** — on-OPAC, shares the polite 1 req/s budget and the
  crawl flock: `bibliohack catalog canon resolve --max N` resolves a bounded
  batch of unmatched seed works per run (never raise `CRAWL_RATE`).
- Both ship in the **crawler image** → need the manual NAS rebuild, not CD.
- **Grafana**: add a "canon coverage" panel (seed size · % matched in mirror · %
  acquired) to the crawl dashboard, alongside the relevance panels.

---

## Suggested build order

| Phase | Deliverable | Plane | Payoff |
|---|---|---|---|
| **C0** ✅ | Wikidata seed builder + `canon_seed` table + `refresh-seed` CLI | off-OPAC | A clean, idempotent canon list (CC0). |
| **C1** ✅ | Matcher: link seed ↔ existing records (ISBN-13 → trigram) + coverage report | DB-only | Tells us how many classics we *already* hold. |
| **C2** ✅ | Canon relevance boost (R-later): positive-only sub-score, recompute | DB-only | Immediate ranking lift for held classics. Ships value without any OPAC load. |
| **C3** ◑ | OPAC resolve &amp; ingest unmatched seed (demand-driven fetcher) | on-OPAC (polite) | Grows genuine classic coverage in the mirror. *(ISBN resolve shipped; title+author resolve pending.)* |
| **C4** | Open Library ratings + curated award fallback + (optional) LibraryThing | mixed | Deepens the popularity/notability signal. |

C0–C2 are the high-value, low-risk core and touch the OPAC **zero** times. C3 is
where politeness matters; keep it bounded and rate-unchanged.

---

## Open questions &amp; risks (resolve before/within C3)

- **OPAC search fields (was blocking for C3) — RESOLVED 2026-06-18.** Confirmed
  against the live RBPA OPAC: the `xsqf99` expert query supports a MARC-tag
  index of the form `(<term>.tNNN.)`, so **ISBN** is `(<isbn>.t020.)` (MARC tag
  020). A round-trip of a known holding's ISBN (`(8425536001871.t020.)`)
  returned exactly that one record with its 9 copies — precise, no free-text
  fallback needed for ISBN. Title/author use the dedicated direct fields
  `xsqf02` / `xsqf03` (title verified: 181 results for "cien años de soledad").
  Builder lives in `catalog/.../discover_via_search.py::isbn_expert_expression`.
  Note: the OPAC stores per-edition ISBNs (often publisher EANs, not always a
  978/979 ISBN-13), so ISBN resolve catches exact-edition holdings and the
  title+author pass (the conservative C1 thresholds) catches the rest.
- **Works vs editions:** Wikidata mixes the abstract work and its editions; an
  ISBN may sit on an edition item. The seed builder must walk `P747`
  (has edition) / editions to collect ISBNs, or accept work-level matching by
  title+author when no ISBN is present.
- **Match precision:** title+author trigram on classics risks false positives
  (many editions, translations, adaptations). Keep the conservative threshold
  from the Goodreads matcher; prefer ISBN; record match confidence.
- **Don't pollute the mirror:** C3 only ingests what the OPAC actually returns.
  A seed work the RBPA doesn't hold stays `not_held` — never a phantom record.
- **Licensing hygiene:** Wikidata CC0 (clean); Open Library check per-endpoint;
  keep the existing "Información obtenida del Portal de la Junta" provenance for
  anything ingested from the OPAC.
- **Volume / rate budget:** tens of thousands of resolve lookups at 1 req/s is
  days–weeks of *shared* crawl budget; sequence C3 behind the novedades steady
  state and cap per-run so it never starves the hourly growth job.
- **Relationship to the MARC dump:** this is complementary, not a replacement —
  if the Junta later says yes, the dump supersedes C3's acquisition, but C0–C2
  (the canon signal) remain useful regardless.
