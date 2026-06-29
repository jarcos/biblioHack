---
title: "biblioHack — Library-aware Availability"
h1: "Library-aware Availability — catalogue badge redesign"
tagline: "Designed 2026-06-29 · ✓ implemented 2026-06-29 (backend + frontend; gates green, pending push to main)."
---
The `/browse` cards (and search results) today show a **network-wide** copy
count — `212 disp.` means "212 copies are on a shelf *somewhere* in the eight
RBPA provinces". That number is technically true and practically useless: a
reader in Huelva doesn't care that El Zorro is available in Almería. This
milestone reframes the availability badge around **the reader's own library and
what's borrowable near them**, so a card answers the only question that matters —
*can I get this book, today, close to me?*

> **Status: ✓ implemented 2026-06-29.** Backend (catalog read repo + DTO/schema
> + router primary resolution; recommendations schema) and frontend (the shared
> `AvailabilityBadge`, the `useAvailability` anchor/GPS/radius hook, and wiring
> into browse, search, recommendations, and the record page) are done. Frontend
> gate is green (tsc, eslint, prettier, 89 vitest); backend `ruff format`/`ruff
> check` green; `mypy`/`pytest` (incl. Docker integration tests) run in CI.
> **No schema migration** — it reads existing tables. Deploy is the standard
> push-to-`main` → CI-gates-and-auto-deploys. Builds on the **Libraries**
> milestone — see [`relevance-and-libraries.md`](relevance-and-libraries.html).

---

## 1. Goal and the problem with today's badge

The target wording, by example. For "El Zorro : comienza la leyenda / Isabel
Allende", when the reader's primary library (the **Biblioteca Pública Provincial
de Huelva**) has it *and* nearby branches do too:

> **Disponible en tu biblioteca** · +3 cercanas

Instead of the current `212 disp.`

What this requires, and why it is **not** a label tweak:

- **Today's count is network-wide.** `available_count` in
  `catalog_read_repository._summarize` counts available copies across *all*
  branches. The `library_scope` filter (`mine` / `province` / `full`) only
  decides which **records appear**, never the count. Per-library availability is
  net-new work.
- **The backend doesn't know where the reader is.** Design **D11** is explicit:
  *the user's location never leaves the device.* Branch coordinates are public
  (geocoded via Nominatim); the **browser** already does proximity sorting with
  `haversineKm` (`frontend/src/infrastructure/api/branches.ts`). There is no
  user lat/lng stored server-side.
- **There is no single "selected library".** «Mis bibliotecas» is an *ordered
  set* of followed branches (order = preference). "Your library" has to be
  defined.

---

## 2. Resolved design decisions

The full design tree, as agreed. Each row is load-bearing; later rows depend on
earlier ones.

| # | Decision | Choice |
| --- | --- | --- |
| D-A | **Distance anchor** | Signed-in with ≥1 follow → the **primary** (first follow). Anon / no-follow → **device GPS**. Coords never leave the device for either. |
| D-B | **"Your library"** | The **primary** = the first followed branch (lowest `position`). Other follows are ordinary branches that may fall inside the radius. |
| D-C | **Anchor-less users** | Auto-prompt GPS on first `/browse` visit. Deny/dismiss → remembered in `localStorage`, fall back to `N disp.` + a manual "ver cerca de mí" button. |
| D-D | **Radius** | Client-side, default **25 km**, a 10 / 25 / 50 km selector under «Bibliotecas» in the browse sidebar, persisted in `localStorage`. |
| D-E | **Where distance is computed** | **Hybrid.** Backend returns a cheap `available_at_primary` boolean (it knows the follows) **plus** `available_branch_codes`; the browser does the radius/nearby math. |
| D-F | **What "nearby" counts** | Distinct nearby branches (within radius, **excluding** the primary) that hold an available copy **now**. |
| D-G | **Availability strictness** | **Optimistic**: a copy counts when its latest status is `available` *or* `unknown`/unobserved. Applied everywhere (badge, filter, `N disp.` fallback) for internal consistency; unknown copies are **labelled** on the record page so the higher total is explained, not contradicted. |
| D-H | **Payload bound** | Ship the **full** `available_branch_codes` list, no cap (~19 KB raw / a few KB gzipped worst case). A server-side cap can't rank by true distance, so it would silently drop genuinely-near branches. |
| D-I | **«Solo disponibles ahora» filter** | Redefined to **"available at my primary library"** — server-side, paginates cleanly. Anon falls back to "available anywhere". |
| D-J | **Surfaces** | Browse cards, search results, record detail page, recommendations. |

### 2.1 Why hybrid (D-E), and how D11 survives

The two anchor mechanisms (primary-coords for followers, GPS for everyone else)
collapse into **one** implementation by keeping *all distance math in the
browser*:

- The backend returns, per record, `available_branch_codes` — the branches with
  an (optimistically) available copy. **No coordinates, no distance, no radius**
  cross the wire.
- The frontend fetches and caches `/api/branches` (code → `{lat, lng, name,
  province}`) and intersects the codes with the within-radius set using the
  existing `haversineKm`, anchored on either the primary's public coords or the
  device GPS fix.
- The only thing the backend computes is `available_at_primary` — which it must
  compute anyway to power the redefined «Solo disponibles ahora» filter (D-I).

Net effect: **coordinates never leave the device for any user, signed-in
included** — D11 ends up *better* protected than today, with no duplicated
haversine and no SQL distance function to maintain.

---

## 3. Data contract

Additions to `CatalogRecordSummary` (DTO) and `CatalogRecordSummarySchema`
(wire). **No schema migration** — these read existing `copies`,
`availability_snapshots`, and `branches`; no new columns, so no Alembic
revision.

| Field | Type | Meaning |
| --- | --- | --- |
| `available_at_primary` | `bool \| null` | True when the reader's primary branch holds an optimistically-available copy. `null` when there is no primary (anon / no follow). |
| `available_branch_codes` | `string[]` | Every branch with ≥1 optimistically-available copy right now. Full list, no cap. The browser derives "N nearby" from this. |

`available_count` is **kept** and **redefined to optimistic** so the no-anchor
`N disp.` fallback stays consistent with the rest of the badge.

### 3.1 The optimistic predicate

A copy is counted when its **latest** snapshot status is `available` **or**
`unknown`, *or* it has **no** snapshot yet (unobserved). Reasoning: crawl
coverage is partial (the M7 backlist) so strict `available`-only would show an
empty badge on most records. The honesty cost is paid on the record page (§5),
where unknown copies are explicitly labelled.

> **Accepted risk:** optimistic counting inflates numbers wherever coverage is
> thin. This is a deliberate trade for non-empty cards during the coverage
> ramp; revisit once crawl coverage is high.

---

## 4. Backend changes

All in the **catalog** read path; the **holdings** branch data is already
present.

1. **Resolve primary branch.** A small helper (alongside
   `_resolve_library_codes` in `catalog/interfaces/http/router.py`) returns the
   signed-in user's primary branch code = `followed_codes(user_id)[0]`,
   **independent of `library_scope`** so the badge survives «Todo el catálogo»
   and «Mi provincia». `None` for anon / no-follow.
2. **`_summarize` (read repo).** Compute, per record:
   - `available_branch_codes` — distinct branch codes whose latest snapshot is
     optimistically-available (extends the existing `DISTINCT ON (copy_id)`
     latest-status subquery to also group by `branch_code`, with the relaxed
     predicate).
   - `available_at_primary` — `primary_code in available_branch_codes`
     (cheap; computed from the same set).
3. **Relax the availability predicate** in the count/flag SQL to include
   `unknown` and unobserved copies (a `LEFT JOIN` so never-snapshotted copies
   survive).
4. **`browse` + `search` endpoints** pass the resolved primary through to
   `_summarize` and surface the two new fields in the schema.
5. **«Solo disponibles ahora»** (`available=true` on `/catalog/browse`)
   redefined to "≥1 optimistically-available copy **at the primary branch**"
   when a primary exists; otherwise the existing network-wide "available
   anywhere". Stays a server-side `EXISTS` so pagination/totals remain exact.

> **Per-request cost:** signed-in browse/search now does one extra cheap
> `followed_codes` lookup to find the primary. Acceptable; cache within the
> request if it shows up in traces (the API is OTel-instrumented).

---

## 5. Frontend changes

1. **Branch directory.** `/browse` fetches and caches `/api/branches`
   (code → coords/name/province). One public, cacheable request.
2. **Anchor resolution.**
   - Signed-in with ≥1 follow → primary = first followed code → its coords.
   - Else → device GPS (D-C): auto-prompt on first visit; on deny/dismiss store
     the choice in `localStorage`, fall back to `N disp.`, and show a "ver cerca
     de mí" button to re-trigger.
3. **Nearby computation.** `nearby = available_branch_codes` minus the primary,
   filtered to `haversineKm(anchor, branch) ≤ radius`, counted distinct. Radius
   from the sidebar selector (D-D), default 25 km, persisted.
4. **Badge state machine (Spanish copy):**

   | State | Badge |
   | --- | --- |
   | Available at primary | **Disponible en tu biblioteca** (+ `+N cercanas` chip when N > 0; singular `cercana` at N = 1) |
   | Not at primary, but N nearby | **No en tu biblioteca · N cercanas** |
   | Only elsewhere in the network | **Disponible en la red** |
   | No anchor (anon, GPS denied) | **N disp.** + "ver cerca de mí" button |

5. **Record detail page (`/record`).** Highlight the reader's library among the
   copies («tu biblioteca» first), then sort remaining branches by distance from
   the anchor. **Label unknown-status copies** (e.g. *"sin datos recientes"*) so
   the optimistic totals on the cards are explained rather than contradicted.
6. **Search results & recommendations** render the same badge — they already
   carry `CatalogRecordSummary`, so the fields arrive for free.

---

## 6. Testing

- **Backend:** `_summarize` returns correct `available_branch_codes` /
  `available_at_primary` across available / loaned / unknown / unobserved
  fixtures; primary resolution independent of `library_scope`; redefined
  `available=true` filter scopes to the primary and paginates; optimistic
  predicate includes unknown + unobserved.
- **Frontend:** `haversineKm` nearby filtering (boundary at exactly the radius);
  badge state machine for all five states incl. singular/plural; GPS
  grant/deny/dismiss + `localStorage` persistence; radius selector.
- **Good-OPAC-citizen:** no new crawl load — this is read-only over data already
  mirrored.

---

## 7. Open questions / follow-ons

- **Anon GPS auto-prompt** is the chosen default (D-C); if conversion data later
  shows it annoys users, fall back to opt-in via the button only.
- **Province-border under-count:** with the full-list payload (D-H) there is no
  under-count; if payload ever bites, the fallback is province-trim for
  signed-in users (a coordinate-free superset of within-radius), *not* a blind
  cap.
- **Optimistic → strict transition:** once crawl coverage is high enough that
  strict `available` no longer looks empty, flip D-G to strict and drop the
  record-page "sin datos" caveat.
