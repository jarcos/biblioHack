---
title: "biblioHack — Kanban"
h1: "Kanban — project status"
raw_html: true
---
  <p class="intro">Status as of <strong>2026-07-16</strong>. <strong>Direction:</strong> going region-wide / library-agnostic — the app targets all eight RBPA provinces (Huelva was just the bootstrap), with the user picking their own library of reference. "In progress" includes the autonomous work the system does for itself — the crawler never stops. Cards link the commit that shipped them where it helps. The continuous tasks have a live <a href="https://grafana.josearcos.me/d/bibliohack-crawl">Grafana dashboard</a> (LAN/Tailscale). <strong>Since 2026-07-03</strong> the product surface has been stable while the crawl scaled hard — the mirror more than doubled (123k → <strong>300k records</strong>) — and three back-to-back reliability fixes tamed the failure modes that surfaced at that scale (a browser-fetch hang on 07-09, hourly runs pegging the NAS CPU on 07-13, and a 4-hourly canon-resolve timeout on 07-14). The design reskin is now fully shipped (phase 2 landed the shelf/recs/account pages) and the stalled shelf-resolve job is finally resolving on-OPAC.</p>

  <div class="board">

    <!-- ── DONE ──────────────────────────────────────────── -->
    <section class="col done">
      <h2>Done <span class="n">38</span></h2>

      <div class="card">
        <h3>Chat &amp; Recommendations — P1 feedback loop</h3>
        <p>The recommender's return channel, shipped. Like / dislike / «más como esto» / «no me interesa» buttons on every recommendation card POST to <code>/api/recommendations/feedback</code>, appending to a new <code>recommendation_feedback</code> table (migration <code>0023</code>, <code>varchar</code> signal per the enum-ish-column convention — <code>read_rating</code> stays P2). The latest signal per record now re-weights the taste centroid — a <strong>weighted mean</strong> (shelf +1.0 · like +0.7 · dislike −0.5) with disliked / not-interested records hard-excluded — and its state hash joins the recommendations cache key, so a button press regenerates the batch on the next visit (no scheduler, same event-free pattern as the shelf fingerprint). Negative signals drop the card optimistically; the reskin phase-2 recommendations page hosts the UI. Gate green on the Mac (ruff · mypy clean, 664 passed, 83% cov; +use-case cache-bust + HTTP + DB integration tests for exclusion/re-ranking/state-hash, +frontend <code>sendFeedback</code>). <strong>Deploy:</strong> commit/push auto-deploys backend + frontend + migration <code>0023</code>; no NAS crawler rebuild. Foundation for P2–P4 (read-loop → chatbot → taste profile). Plan: <a href="chat-recommendations.html">Chat &amp; Recommendations</a>.</p>
        <div class="meta"><span class="tag t-done">2026-07-16</span><span class="tag t-done">MIGRATION 0023</span></div>
      </div>

      <div class="card">
        <h3>Canon-resolve timeout fix — index-eligible trigram match</h3>
        <p>New 95% CPU plateaus every 4h (from 2026-07-13) were <code>canon_resolve</code> dying at its 1800s watchdog inside <code>canon match</code>: <code>similarity(title,q) &gt;= 0.5</code> is <strong>not index-eligible</strong> — only the <code>%</code>/<code>&lt;-&gt;</code> operators use the trigram GIN indexes — so each of ~989 unmatched seeds seq-scanned the (now 236k, doubled in 10 days) mirror at ~2.5s each and crossed the budget; the load landed in the uncapped Postgres container, pegging the host despite the crawler's cpuset. Fix: a shared <code>trgm_match.py</code> used by both the canon and shelf matchers — <code>SET LOCAL pg_trgm.similarity_threshold=0.5</code> + <code>title % q</code> (index-driven, EXPLAIN-validated on prod: 2.5s → 0.2–0.5s/row; author <code>EXISTS</code> stays function-form). Verified live: a full <code>canon match</code> sweep <strong>3m59s</strong> (was a 30-min kill), canon coverage unstalled and ticking (18.0% → now 20.2%).</p>
        <div class="meta"><span class="tag t-done">2026-07-14</span><span class="tag t-done">8a77e31</span></div>
      </div>

      <div class="card">
        <h3>NAS CPU spikes — lazy browser launch + CPU cap</h3>
        <p>The hourly <code>discover_worker</code> pegged the NAS CPU ~100% for 40–60 min/run behind a 7+-process idle Chromium stack. Two real bugs (the 40–60 min duration itself is by design — <code>WORKER_MAX=2000</code>): (1) <code>async with gateway</code> eagerly launched the pooled Camoufox session even though HTTP-first makes it fallback-only — now <strong>lazy</strong> (the browser launches on the first browser fetch, outside the hard timeout; a healthy run never starts one); (2) no container CPU cap. Deploy gotcha: <code>cpus:</code> fails on the NAS 4.4 kernel («NanoCPUs can not be set» — no CFS quota), so the cap is <code>cpuset: "0,1"</code> (pin 2 of 4 cores). Verified post-deploy: host CPU 69.5% idle mid-run (was pegged), crawler container 16.5% CPU, a 09:00 run finished browserless.</p>
        <div class="meta"><span class="tag t-done">2026-07-13</span><span class="tag t-done">e087383 · f4a0fc0</span></div>
      </div>

      <div class="card">
        <h3>Crawler hang — bounded browser fetches + job timeouts</h3>
        <p>Twice in six days (2026-07-03, 2026-07-09) the hourly <code>discover_worker</code> wedged after an OPAC timeout window — a browser <code>Page.goto</code> retry never returned, the process sat at 0% CPU, and (because of the crawl-lock <em>wait</em>) everything behind the lock, including the availability heartbeat, was starved for 16–85h until a manual <code>docker restart</code>. Two layers of fix: (1) <code>gateway.py</code> — a <code>fetch_hard_timeout_seconds</code> (120s) <code>asyncio.wait_for</code> bound on every rendered fetch + session recycle (bounded close, reopen-or-degrade-to-one-shot) on any fetch failure; (2) <code>run-job.sh</code> — a per-command <code>timeout --kill-after</code> budget wrapper (discover 900s, worker 6000s, …) that pkills leftover chromium. Regression tests for the wedged/failing-once sessions (649 passed). <strong>Still open (the detection layer):</strong> Loki/Grafana staleness alerts — see To&nbsp;do.</p>
        <div class="meta"><span class="tag t-done">2026-07-09</span><span class="tag t-done">c25a14b</span></div>
      </div>

      <div class="card">
        <h3>Shelf-resolve stall — fixed, now resolving on-OPAC</h3>
        <p>The long-standing anomaly (4+ consecutive health checks showed <code>shelf_opac_attempts_total = 0</code> with every unmatched entry <code>unchecked</code>) is <strong>closed</strong>: the demand-driven fetcher is now working end-to-end — <strong>75 OPAC attempts</strong>, 11 held / 46 not_held, 0 unchecked as of 2026-07-16. The 6-hourly <code>shelf_resolve</code> job resolves unmatched user-shelf books against the live OPAC as intended.</p>
        <div class="meta"><span class="tag t-done">2026-07-13</span><span class="tag t-ops">CRAWLER PLANE</span></div>
      </div>

      <div class="card">
        <h3>Design reskin — phases 1 &amp; 2 (complete)</h3>
        <p>From the Claude-Design handoff (Biblio design system): warm-paper palette (papel cálido + verde bosque + ocre) mapped onto the existing token names with new <code>faint</code>/<code>brand-soft</code>/<code>ocre*</code>/shadow tokens; Spectral / IBM Plex Sans / IBM Plex Mono self-hosted via @fontsource; <strong><code>Cover.tsx</code> procedural typographic jackets</strong> (hash → 10 palettes × 3 layouts) as the no-cover fallback everywhere. <strong>Phase 1</strong> (<code>ad78f4e</code>): nav/footer, home (hero + search card), browse (facets, filter chips, cover grid) and record detail (sticky cover + availability card). <strong>Phase 2</strong> (<code>d6a672a</code>): the remaining <strong>shelf, recommendations and account</strong> pages — so the whole app now carries the design system, and the recommendations page is styled ready to host the Chat &amp; Recommendations UI.</p>
        <div class="meta"><span class="tag t-done">2026-07-03</span><span class="tag t-done">ad78f4e · d6a672a</span></div>
      </div>

      <div class="card">
        <h3>Chat &amp; Recommendations — designed</h3>
        <p>Full design for closing the recommender's feedback loop: like/dislike buttons → <code>recommendation_feedback</code> + a <strong>weighted taste centroid</strong>; append-only impressions → a read-after-recommended rating; a <strong>catalogue-grounded chatbot</strong> (tool-calling over OpenRouter, retrieve-then-pick — the model can only recommend ids returned by <code>search_catalog</code>); and a distilled per-user taste profile blended into retrieval. Decisions locked: no fine-tuning, no local model on the NAS, chat history never fed raw. Phased P1–P4. Plan: <a href="chat-recommendations.html">Chat &amp; Recommendations</a>.</p>
        <div class="meta"><span class="tag t-done">2026-07-03</span><span class="tag t-done">P1 SHIPPED 2026-07-16 · P2 NEXT</span></div>
      </div>

      <div class="card">
        <h3>M7 pace fixes — HTTP-first fetch + crawl-hour recovery</h3>
        <p>Three fixes that took the backlist sweep from ~10k to ~30k tasks/day <strong>without touching <code>CRAWL_RATE</code></strong>: (1) <strong>HTTP-first record fetch</strong> with browser fallback — record pages aren't JS-rendered (verified live), so steady state is one plain GET per record (~1.1s vs 2.5–4.5s Camoufox renders); kill switch <code>SCRAPER_HTTP_FIRST=false</code>; also dissolved the «No TITN field» parse-failure cluster (TITN 68221–69024), which was a browser-rendering artifact. (2) <code>run-job.sh</code> lock-<em>wait</em> (bounded <code>flock -w</code>) instead of skip — overruns no longer forfeit whole crawl hours (~half of scheduled capacity was being lost). (3) <code>WORKER_MAX</code> 1000→2000. Plus a whole-catalog coverage panel (records vs TITN high-water mark) on the Grafana dashboard (2026-07-01). Crawler plane ≠ CD: landed via the manual NAS rebuild.</p>
        <div class="meta"><span class="tag t-done">2026-07-02</span><span class="tag t-ops">NAS REBUILD</span></div>
      </div>

      <div class="card">
        <h3>Library-aware availability badge</h3>
        <p>The «212 disp.» network-wide count replaced by <strong>«Disponible en tu biblioteca · +N cercanas»</strong> — optimistic, distance-anchored, resolved against the reader's followed branches with <strong>all distance math client-side</strong> (D11: location never leaves the device). Shared <code>AvailabilityBadge</code> + <code>useAvailability</code> hook wired into browse, search, recommendations and the record page. No schema migration. Full plan: <a href="library-aware-availability.html">Library-aware Availability</a>.</p>
        <div class="meta"><span class="tag t-done">2026-06-29</span></div>
      </div>

      <div class="card">
        <h3>L5 — Library picker at registration (optional)</h3>
        <p>Signup can pre-follow RBPA branches («Mis bibliotecas» at registration), <strong>optional / skippable</strong> — pick up front or set later on <code>/account</code>. <strong>No schema change</strong> (reuses <code>user_followed_branches</code>): optional <code>branch_codes</code> on <code>/api/auth/register</code>, validated up front (unknown → 422 before any account or verification mail) and written in the new user's transaction via an injectable <code>RegisterBranchFollows</code> port. Frontend: extracted a shared <code>BranchSelect</code> core (the <code>/account</code> picker now reuses it) plus a collapsible «Elige tus bibliotecas (opcional)» section at signup. Gate green (ruff·mypy, pytest 638, frontend lint/typecheck/vitest 78); deployed via CD.</p>
        <div class="meta"><span class="tag t-done">2026-06-26</span><span class="tag t-done">5bdb6d6</span></div>
      </div>

      <div class="card">
        <h3>Cold-start taste chips persisted</h3>
        <p>The §8.3.3 «detectamos que te gusta…» chips were returned only on a fresh recommendation and lost on a cache hit (kept migration-free at the time), so they flickered away on reload. Now persisted with the cached batch: migration <code>0021</code> adds a nullable <code>inferred_tastes text[]</code> on <code>recommendations</code>, denormalised onto each row of a batch (NULL for taste-centroid batches); a <code>CachedBatch(recommendations, inferred_tastes)</code> carries them through the repo, and a cold-start cache hit re-surfaces the stored chips with no second LLM call. Gate green on the Mac (ruff·mypy clean, 626 passed, 82.2% cov; +use-case cache-hit test + integration round-trip). <strong>Deploy:</strong> commit/push auto-deploys backend + migration <code>0021</code>; no NAS crawler rebuild.</p>
        <div class="meta"><span class="tag t-done">2026-06-25</span><span class="tag t-done">2315c95</span></div>
      </div>

      <div class="card">
        <h3>Audience / form surfaced end-to-end</h3>
        <p>The §5.5 scope data (público + literary-form) was filterable (browse facets + the search «incluir infantil…» toggle) but barely visible at the row level. Now: <strong>browse cards</strong> flag out-of-default-scope rows (infantil / juvenil / no ficción) with público+forma badges so they're distinguishable in the whole-mirror navigator; the <strong>record page</strong> público/forma badges deep-link into the matching <code>/browse</code> facet; and <strong>flagged search hits</strong> expose público/forma as cross-link chips in the «Explorar» footer (building on the cross-link helper). Frontend-only, gate green (74/74 vitest, +1 regression test on the record-page facet links). <strong>Deploy:</strong> commit/push auto-deploys; no Alembic, no crawler rebuild.</p>
        <div class="meta"><span class="tag t-done">2026-06-25</span><span class="tag t-done">4eccaea</span></div>
      </div>

      <div class="card">
        <h3>Search ⇄ browse cross-links</h3>
        <p>The navigator's missing connective tissue. A shared <code>@/lib/browse</code> is now the single source of truth for <code>/browse</code> filter state ↔ URL (<code>parseBrowseFilters</code> · <code>browseSearchParams</code> · <code>browseHref</code>). <strong>Deep links:</strong> <code>/browse</code> seeds its filters from the query string and mirrors them back via <code>history.replaceState</code>, so a filtered view is shareable and back/forward-friendly. <strong>Cross-links:</strong> author/genre chips on search results (<code>ResultRow</code> restructured from one big anchor into a card so the chip links don't nest) and on the record page deep-link into a pre-filtered <code>/browse</code>. <strong>Loop closed both ways:</strong> a search box on <code>/browse</code> hands off to full-text search via <code>/?q=</code>, and <code>SearchBox</code> reads <code>?q=</code> on mount (in an effect, to avoid a hydration mismatch on the <code>client:load</code> island). Frontend-only; gate green (format · lint · typecheck · 74/74 vitest incl. 8 new). <strong>Deploy:</strong> commit/push auto-deploys; no Alembic, no crawler rebuild.</p>
        <div class="meta"><span class="tag t-done">2026-06-25</span><span class="tag t-done">79eac77</span></div>
      </div>

      <div class="card">
        <h3>LLM query rewriting + cold-start classification</h3>
        <p>The two remaining OpenRouter jobs from §8.3, each behind a port with an OpenRouter adapter + Null fallback (selected on <code>OPENROUTER_API_KEY</code>), strictly best-effort. <strong>Query rewriting:</strong> <code>rewrite=true</code> (default) on <code>GET /catalog/search</code> turns natural language into structured intent — a cheap <code>should_rewrite</code> heuristic gates the LLM call (short keyword queries never pay), structured intent (author / year / orden) runs as a faceted <code>/browse</code>, a zero-result rewrite falls back to the literal search, and the response echoes the applied intent so the UI shows a revertible «buscar literalmente» chip (the Google pattern — no opt-in toggle). <strong>Cold-start:</strong> when a new user has no catalogue-matched books yet, the LLM reads the raw imported titles into a taste descriptor, embedded (BGE-M3) + KNN-retrieved; the response is flagged <code>cold_start</code> with «detectamos que te gusta…» chips and a note it sharpens as the shelf matches — empty shelf / LLM-down degrades to the prior <code>empty_profile</code>. No schema change (cold-start reuses the recommendation cache under a raw-shelf key). Tests: rewriter + classifier adapters, the rewrite-aware use case, cold-start branching, and HTTP. <strong>Deploy:</strong> commit/push auto-deploys backend + frontend; no Alembic, no NAS crawler rebuild.</p>
        <div class="meta"><span class="tag t-done">2026-06-23</span></div>
      </div>

      <div class="card">
        <h3>Demand-driven fetcher — unmatched shelf books</h3>
        <p>The user-shelf sibling of canon C3: resolve still-unmatched Goodreads/StoryGraph shelf entries against the live OPAC and ingest the ones the RBPA actually holds. <strong>S0</strong> — resolve bookkeeping on <code>shelf_entries</code> (<code>resolve_status</code> · <code>resolve_attempts</code> · <code>last_resolved_at</code> + partial index, migration <code>0020</code>). <strong>S1</strong> — <code>RematchShelf</code> + <code>bibliohack shelf rematch</code> (DB-only): links unmatched entries the worker has since ingested, closing the «re-matches for free as the catalogue grows» gap that previously only fired on re-import. <strong>S2</strong> — <code>ResolveUnmatchedShelf</code> + <code>shelf resolve</code> (on-OPAC): deduped across users by ISBN→title+author, 30-day re-try cooldown, seeds held TITNs into the existing worker; never invents a phantom record. <strong>S3</strong> — crawl-plane <code>shelf_resolve</code> job (rematch→resolve under the shared OPAC lock, <code>40 */6</code>, bounded by <code>SHELF_RESOLVE_MAX</code>). <strong>S4</strong> — Grafana «shelf coverage» row. Gate green: 595 passed · mypy clean · 81.9% coverage. <strong>Fully deployed 2026-06-24</strong> (<code>140f3d6</code>): backend + migration <code>0020</code> via CD, manual NAS crawler rebuild landed the <code>shelf_resolve</code> job (<code>40 */6</code>, <code>SHELF_RESOLVE_MAX=100</code>) with supercronic reloading the new schedule cleanly, and the Grafana shelf-coverage row was synced into the monitoring-stack provisioning dir (separate from CD). Full plan: <a href="demand-driven-shelf-fetcher.html">Demand-driven fetcher</a>.</p>
        <div class="meta"><span class="tag t-done">2026-06-24</span><span class="tag t-done">140f3d6</span></div>
      </div>

      <div class="card">
        <h3>OPENROUTER_API_KEY set on the NAS</h3>
        <p>Key added to the prod <code>.env</code> at <code>/volume1/docker/bibliohack/.env</code> and the <code>api</code> container force-recreated to pick it up — recommendation rationales now populate (empty key shipped them blank by design). Unblocks the LLM query-rewriting + cold-start work. Manual NAS step (CD never touches <code>.env</code>).</p>
        <div class="meta"><span class="tag t-done">2026-06-22</span><span class="tag t-ops">OPS</span></div>
      </div>

      <div class="card">
        <h3>Libraries milestone (L0–L4)</h3>
        <p>Follow real RBPA branches by proximity, then scope browse/search/recs to «mis bibliotecas → mi provincia → todo». <strong>L0:</strong> branch geo/contact schema + backfill, then a Nominatim geocode CLI (<code>holdings enrich-branches</code>, resumable per-batch commits + dedication-name cleaning) — <strong>571/573 branches geocoded</strong>. <strong>L1:</strong> <code>user_followed_branches</code> table + <code>/api/branches</code> (public) and <code>/api/me/branches</code> (get/put). <strong>L2:</strong> the «Mis bibliotecas» picker on <code>/account</code> — geolocation proximity sort (client-side only, never sent), type-ahead fallback. <strong>L3:</strong> a <code>library_scope</code> filter on <code>/catalog/browse</code> + search, a hard pre-filter on records held in followed branches ordered by relevance, wired through keyword/semantic/hybrid. <strong>L4:</strong> library-aware recommendations — borrowable-nearby titles get a capped boost in the taste-centroid ranking, plus a «solo en mis bibliotecas» toggle. Full plan: <a href="relevance-and-libraries.html">Relevance &amp; Libraries</a>.</p>
        <div class="meta"><span class="tag t-done">2026-06-22</span><span class="tag t-done">f40f884…</span></div>
      </div>

      <div class="card">
        <h3>Browse default → relevance sort («Destacados»)</h3>
        <p><code>/browse</code> was hardcoded to «Más recientes» (pub_year desc) in the frontend, so the relevance score — and the canon boost on top of it — never showed: freshly-added 2026 novedades with score 0 floated to the top. Added a «Destacados» (relevance) sort, made it the default, aligned the type unions. Now the boosted classics lead the page; «Más recientes» / «Título» stay as options. The 2026-at-top puzzle was this sort, <em>not</em> a pub_year import bug — canon titles carry their real years (Pilares 1994, Doctor Zhivago 1984).</p>
        <div class="meta"><span class="tag t-done">2026-06-22</span><span class="tag t-done">7c0d5c0</span></div>
      </div>

      <div class="card">
        <h3>Canon import — classics from open sources (C0–C4 + scheduling)</h3>
        <p>A back-catalogue path that doesn't wait on the MARC dump: Wikidata/award seed (<code>canon_seed</code>, CC0) → ISBN-13/title+author matcher → positive-only <code>canon</code> relevance boost (folded into the nightly recompute) → polite OPAC <code>resolve</code> that seeds held classics into the existing worker → Open Library ratings + curated award fallback. As of 2026-06-21 the pipeline is <strong>scheduled and live on the crawl plane</strong> (<code>canon_seed</code> monthly, <code>canon_resolve</code> 4-hourly) and bootstrapped in prod: ~1,210 seed works, 28 matched to holdings (~5.7%, all title+author). Follow-ups also closed 2026-06-21 (<code>56a77b7</code>): <strong>WDQS keyset pagination</strong> (seek by last work IRI, no more deep-<code>OFFSET</code> 504s capping the seed at ~500), the <strong>OL rating count wired into the canon boost</strong>, and a <strong>canon coverage row on the Grafana dashboard</strong> (seed size · % matched · % held · acquire-status · ratings). <strong>Live on <code>/browse</code>:</strong> after enrich-ratings + a full recompute, 82 matched classics now lead the catalogue at the top percentile (Los pilares de la tierra, Ensayo sobre la ceguera, Doctor Zhivago, Por quién doblan las campanas…) instead of just recent novedades. Full plan: <a href="canon-import.html">Canon Import</a>.</p>
        <div class="meta"><span class="tag t-done">2026-06-21</span><span class="tag t-done">255e491…56a77b7</span></div>
      </div>

      <div class="card">
        <h3>Future-year pub_year fix</h3>
        <p>Browse was floating 2033/2029/2028 rows to the top (sorts by <code>pub_year DESC</code>). Capped the parser's plausibility band at the current year + 1 (was 2100), unified the ceiling into one shared helper, cleaned the existing bad rows in prod, and shipped end-to-end. New records can no longer store implausible future years.</p>
        <div class="meta"><span class="tag t-done">2026-06-21</span><span class="tag t-done">057bc70…1caf751</span></div>
      </div>

      <div class="card">
        <h3>Relevance milestone — Phase R (R0–R3)</h3>
        <p>Stored <code>relevance_score</code> ∈ [0,1] = demand (from the availability time-series) + holdings breadth + recency + display completeness, corpus-normalised (p95) with cold-start neutral demand and thin-history trend shrinkage. Recomputed nightly on the crawl plane (<code>catalog relevance recompute</code>, 04:00); now the default <code>/browse</code> sort and a filter-and-tiebreak in keyword/semantic/hybrid search. Live in prod: 43,412 records scored. External canon boost deferred to the back-catalogue.</p>
        <div class="meta"><span class="tag t-done">2026-06-16</span><span class="tag t-done">3aff42d…7f6e693</span></div>
      </div>

      <div class="card">
        <h3>Crawl throughput — pooled browser session</h3>
        <p>One <code>AsyncStealthySession</code> (<code>max_pages=1</code>) now spans each discover/worker/refresh run instead of launching a browser per record — the launch, not the request, was the real cap under the 1 req/s budget. Politeness unchanged (single page, serial, throttle still gates every fetch). Crawler container rebuilt on the NAS to pick it up.</p>
        <div class="meta"><span class="tag t-done">2026-06-13</span><span class="tag t-done">dbe7486</span></div>
      </div>

      <div class="card">
        <h3>Catalog navigator — Tier A+B</h3>
        <p><code>/browse</code> faceted explorer (author · genre · idioma · año · disponibilidad) + <code>GET /catalog/browse</code> with self-excluding facet counts + <code>/catalog/authors</code>; CDU-derived <code>genre</code> column, backfilled (migration 0013).</p>
        <div class="meta"><span class="tag t-done">2026-06-12</span><span class="tag t-done">24d2b7e</span></div>
      </div>

      <div class="card">
        <h3>Shelf re-import UX</h3>
        <p>Uploader collapses to a discreet «Re-importar» link once a shelf exists; re-imports upsert in place (pendiente → leyendo → leído), never duplicate — now pinned by an integration test.</p>
        <div class="meta"><span class="tag t-done">2026-06-11</span><span class="tag t-done">d51248b</span></div>
      </div>

      <div class="card">
        <h3>Hybrid search (RRF)</h3>
        <p><code>?mode=hybrid</code> fuses FTS + BGE-M3 KNN (k=60, 50-candidate pools); degrades to keyword on embedder failure; three-way toggle in the UI.</p>
        <div class="meta"><span class="tag t-done">2026-06-11</span><span class="tag t-done">95122e4</span></div>
      </div>

      <div class="card">
        <h3>Post-identity follow-ups batch</h3>
        <p>Junta CC-BY attribution (footer/README/export) · schemathesis contract suite · otel-redis · rate limits on verify/reset · README refresh.</p>
        <div class="meta"><span class="tag t-done">2026-06-11</span><span class="tag t-done">1fc2c11</span></div>
      </div>

      <div class="card">
        <h3>Identity milestone — Phases 0–5</h3>
        <p>Public registration (Argon2id, Redis sessions, Turnstile, Mailgun EU), per-user shelves, Dramatiq background imports, frontend auth + legal pages, user-scoped recommender, GDPR export/deletion + isolation suite.</p>
        <div class="meta"><span class="tag t-done">2026-06-10</span><span class="tag t-done">7992892…5ce696c</span></div>
      </div>

      <div class="card">
        <h3>Project summary docs (this site)</h3>
        <p>Overview + architecture + identity + pending/ops pages; navigator requirement recorded; this board.</p>
        <div class="meta"><span class="tag t-done">2026-06-10</span><span class="tag t-done">057af23</span></div>
      </div>

      <div class="card">
        <h3>José's shelf re-imported</h3>
        <p>The post-truncation re-import is done; shelf lives under his account.</p>
        <div class="meta"><span class="tag t-ops">OPS</span><span class="tag t-done">2026-06-11</span></div>
      </div>

      <div class="card">
        <h3>privacy@josearcos.me delivers</h3>
        <p>Verified end-to-end 2026-06-13: it had <em>no</em> Cloudflare Email Routing rule (mail hard-bounced <code>550</code>). Added <code>privacy@ → josearcoscampos@gmail.com</code>, cleared the Mailgun bounce-suppression the failed test had created, and confirmed delivery (<code>250 OK</code>). The legal-page privacy contact now reaches a mailbox.</p>
        <div class="meta"><span class="tag t-ops">OPS</span><span class="tag t-done">2026-06-13</span></div>
      </div>

      <details class="archive">
        <summary>Earlier milestones (M0 → M6.5) — all shipped</summary>
        <div class="card"><h3>M6.5 CI/CD auto-deploy</h3><p>Green push to <code>main</code> → NAS; red never deploys.</p></div>
        <div class="card"><h3>M5 Recommender v1</h3><p>Shipped as identity Phase 4 — per-user taste centroid + pgvector KNN, OpenRouter rationales.</p><div class="meta"><span class="tag t-done">2026-06-10</span></div></div>
        <div class="card"><h3>M4 Goodreads import</h3><p>CSV importer, ISBN-13 + trigram matching, shelf UI.</p><div class="meta"><span class="tag t-done">2026-06-08</span></div></div>
        <div class="card"><h3>M3 Semantic search</h3><p>BGE-M3 via HF Inference API, pgvector HNSW, similar-records.</p><div class="meta"><span class="tag t-done">2026-06-08</span></div></div>
        <div class="card"><h3>APM / OpenTelemetry</h3><p>FastAPI + asyncpg (+ Redis since 2026-06-11) → Tempo + SigNoz.</p><div class="meta"><span class="tag t-done">2026-06-04</span></div></div>
        <div class="card"><h3>Autonomous crawler</h3><p>On-NAS supercronic container; cursor-resumable discover/worker/refresh.</p><div class="meta"><span class="tag t-done">2026-06-03</span></div></div>
        <div class="card"><h3>M6 Public deploy</h3><p>NAS + Cloudflare Tunnel, same-origin routing, backups.</p><div class="meta"><span class="tag t-done">2026-05-30</span></div></div>
        <div class="card"><h3>M0–M2.5 Foundations → covers</h3><p>Scaffold + CI · catalogue ingest + FTS + literary scoping · availability time-series · covers pipeline.</p></div>
      </details>
    </section>

    <!-- ── IN PROGRESS ───────────────────────────────────── -->
    <section class="col wip">
      <h2>In progress <span class="n">4</span></h2>

      <div class="card">
        <h3>M7 — Network-wide backlist crawl (operating)</h3>
        <p>Region-wide coverage of the <strong>pre-2024 backlist</strong> across all eight provinces — a <em>coverage</em> job, not a scoping one (discovery was already network-wide; <code>SUBC</code> only scopes display, and copies are stored for every branch). Live since 2026-06-26; the 2026-07-02 pace fixes tripled the drain and it has held there since — a steady <strong>~32k tasks/day</strong> (07-15: 32,098). As of <strong>2026-07-16</strong>: <strong>300,035 records mirrored</strong> (17.9% of the TITN space), backlist <strong>15.7% swept</strong>, queue ~37.6k, ETA upper bound <strong>~75 days</strong> and shrinking (was ~167d on 07-03). Failures are background noise (424 total, 0 clustered in the last 2h — the recent 336314–336320 run was a single-attempt OPAC-timeout wobble on 07-14, self-recovered). Watch swept % + failure-rate on the <a href="https://grafana.josearcos.me/d/bibliohack-crawl">crawl dashboard</a>; next lever <code>WORKER_MAX</code>→3000 (never <code>CRAWL_RATE</code>). Build plan: <a href="m7-backlist-crawl.html">M7 Backlist Crawl</a>.</p>
        <div class="meta"><span class="tag t-wip">CONTINUOUS · OPERATING</span></div>
      </div>

      <div class="card">
        <h3>Catalogue crawl (autonomous)</h3>
        <p><strong>Novedades 2024+ is caught up</strong> (the hourly cursor trickle is by design); nearly all crawl budget now feeds the M7 backlist sweep, which more than doubled the mirror in under two weeks — <strong>300,035 records</strong> as of 2026-07-16, adding ~20k/day. The full TITN space stays the long game (the MARC dump closes it, not crawling). The OPAC budget is shared under the single crawl lock by the hourly discover+worker, <code>canon_resolve</code> (4-hourly, now index-fast) and <code>shelf_resolve</code> (6-hourly, <strong>now resolving on-OPAC</strong>). The 07-09/07-13/07-14 reliability fixes (browser-fetch timeout, CPU cap, trigram index) hardened this plane at the new scale. Live progress: <a href="https://grafana.josearcos.me/d/bibliohack-crawl">Grafana → biblioHack crawl &amp; enrichment</a>.</p>
        <div class="meta"><span class="tag t-wip">CONTINUOUS</span></div>
      </div>

      <div class="card">
        <h3>Genre coverage (self-healing)</h3>
        <p><strong>37.1% genre-known</strong> as of 2026-07-16 — new records arrive classified, and coverage climbs as the sweep re-scrapes (roughly flat in % because the denominator is growing ~20k/day). <strong>Gotcha (2026-06-12):</strong> the crawler container doesn't ride CD — it needs a manual <code>--build</code> for code changes. Watch «% known by ingest day» on the dashboard.</p>
        <div class="meta"><span class="tag t-wip">CONTINUOUS</span></div>
      </div>

      <div class="card">
        <h3>Embedding backfill</h3>
        <p>BGE-M3 vectors via the HF Inference API, every 3h on the crawler plane — semantic/hybrid quality grows with the mirror. <strong>19.6% backfilled</strong> as of 2026-07-16, and <strong>still falling in % terms</strong> (was 32.1% on 07-03) because ingestion is outrunning the embed job: the mirror has ~2.4×'d while the embedder held its cadence. Coverage of the <em>whole</em> mirror will keep dipping until the embed batch size is raised — <code>EMBED_MAX</code> is the lever, worth pulling now that the crawl pace is stable.</p>
        <div class="meta"><span class="tag t-wip">CONTINUOUS · WATCH</span></div>
      </div>
    </section>

    <!-- ── TO DO ─────────────────────────────────────────── -->
    <section class="col todo">
      <h2>To do <span class="n">11</span></h2>
      <!-- count = all cards in this column (4 active next-up + 3 demand-gated + won't-do/roadmap/parked) -->


      <div class="divider">Next up — re-prioritised 2026-07-16. The reskin (both phases), the shelf-resolve stall and <strong>Chat &amp; Recommendations P1</strong> are now shipped; the build queue is the operational gaps the 07-07 → 07-14 incident run exposed, then Chat &amp; Recommendations P2 (read-loop).</div>

      <div class="card">
        <h3>1 · Crawl-plane detection layer (alerting)</h3>
        <p>The 07-03 → 07-09 hangs were only caught because José happened to spot a flatline on Grafana — the crawl plane can go silent for days without paging anyone. The 07-09 code fix bounds the hang, but the <strong>detection layer is still unbuilt</strong>: a Loki alert on supercronic «not starting: job is still running», plus Grafana staleness alerts (availability heartbeat &gt; ~9h, 0 records ingested in 3h). Cheap insurance now that the mirror is 300k and growing.</p>
        <div class="meta"><span class="tag t-todo">OBSERVABILITY · NEXT</span></div>
      </div>

      <div class="card">
        <h3>2 · Raise <code>EMBED_MAX</code> (embeddings falling behind)</h3>
        <p>Whole-mirror embedding coverage is down to <strong>19.6%</strong> and still dropping in % terms — the 3-hourly embed job can't keep pace with ~20k new records/day. Bump the embed batch size (<code>EMBED_MAX</code>) on the crawler plane so semantic/hybrid coverage stops eroding; a crawler-plane env change, so it needs the manual NAS recreate (no <code>--build</code>).</p>
        <div class="meta"><span class="tag t-todo">SMALL · CRAWLER PLANE</span></div>
      </div>

      <div class="card">
        <h3>3 · Failed-task requeue</h3>
        <p>424 <code>failed</code> scrape tasks sit permanently (parse errors + intermittent OPAC-timeout bursts like 336314–336320 on 07-14); there's no retry path, so each transient wobble accretes. Add a bounded requeue (attempt cap + backoff) so transient failures self-heal instead of accumulating — a <code>catalog requeue-failed</code> CLI so it never needs raw prod SQL again.</p>
        <div class="meta"><span class="tag t-todo">SMALL · CRAWLER PLANE</span></div>
      </div>

      <div class="card">
        <h3>4 · Canon OL-ratings collection</h3>
        <p>Only <strong>3</strong> Open Library ratings stored in prod (unchanged across every recent check) — the enrich-ratings step is barely producing signal, so the rating term of the canon boost is effectively idle. Investigate the collector before touching boost weights.</p>
        <div class="meta"><span class="tag t-todo">SMALL · ENRICHMENT</span></div>
      </div>

      <div class="divider">Demand-gated — let real usage pull these forward</div>

      <div class="card">
        <h3>StoryGraph CSV importer</h3>
        <p>Second <code>Importer</code> adapter; CSV shape close to Goodreads. Wait for a real user asking, or do it as the second-source proof — small but demand-gated. <em>Note: the demand-driven fetcher already covers StoryGraph entries for free once they exist (it resolves from stored title/author/ISBN, nothing Goodreads-specific).</em></p>
        <div class="meta"><span class="tag t-todo">SMALL · DEMAND-GATED</span></div>
      </div>

      <div class="card">
        <h3>OTel on the crawl/worker plane</h3>
        <p>When <code>scrape_tasks</code>/<code>import_jobs</code> status rows stop being enough; <code>scrape_log</code> remains unwired. Internal observability — defer until the status rows actually fall short. <em>(Complements the detection-layer alerting above: alerts tell you the plane went silent; per-job traces tell you why.)</em></p>
        <div class="meta"><span class="tag t-todo">MEDIUM</span></div>
      </div>

      <div class="card">
        <h3>Edge rate limiting (Cloudflare WAF)</h3>
        <p>App-level limits shipped in Phase 5; add edge rules if abuse actually appears. Reactive — only worth doing once abuse shows up.</p>
        <div class="meta"><span class="tag t-todo">IF NEEDED</span></div>
      </div>

      <div class="divider">Won't do (reviewed 2026-06-22)</div>

      <div class="card">
        <h3>LibraryThing / OCLC ubiquity (optional)</h3>
        <p>A "held by N libraries" worldcat-style signal to deepen canon notability. <strong>Won't do for now (reviewed 2026-06-22):</strong> it's a third ubiquity proxy redundant with signals already in the blend — the canon term already carries Wikipedia-sitelink notability (sub-weight 0.30) and OL rating popularity (0.20), all inside a capped <code>CANON_MAX_BOOST = 0.15</code>. It fires only on <code>is_canon</code> matches (~28 of ~37k records, ≈0.08%) and the corpus is <code>pub_year ≥ 2023</code>, so the boost barely has a population to act on until the back-catalogue import lands (2–4 mo effort). Cost is lopsided: Wikidata + OL are CC0/free, whereas OCLC WorldCat Search API v1 shut off in 2025 and v2 needs an institutional Cataloging + FirstSearch/Discovery subscription biblioHack doesn't have. <strong>Revisit</strong> only after back-catalogue grows matched classics into the thousands <em>and</em> telemetry shows notability + OL can't separate them — and even then prefer LibraryThing (accessible) over OCLC (paywalled).</p>
        <div class="meta"><span class="tag t-todo">WON'T DO · revisit post-back-catalogue</span></div>
      </div>

      <div class="divider">Roadmap (bigger bets)</div>

      <div class="card">
        <h3>Navigator Tier C — author country</h3>
        <p>True nationality facet needs BNE/Wikidata authority enrichment; deferred until the mirror justifies it.</p>
        <div class="meta"><span class="tag t-todo">DEFERRED</span></div>
      </div>

      <div class="card">
        <h3>M8 — Mobile app</h3>
        <p>React Native/Expo over the same API. Parked behind M7.</p>
        <div class="meta"><span class="tag t-todo">PARKED</span></div>
      </div>

      <div class="divider">Parked — needs a human / external party</div>

      <div class="card">
        <h3>MARC-dump request to the Junta (RBPA) — parked</h3>
        <p>Email the RBPA coordinator for a periodic MARC-XML dump (Madrid precedent, CC-BY). One «sí» obsoletes ~90% of the crawl — bibliographic data arrives in bulk; only holdings/availability still need probing. Highest long-term leverage (it attacks the binding constraint behind canon/relevance: the corpus being a thin <code>pub_year ≥ 2023</code> slice) but it's <strong>not something we can ship ourselves</strong> — it depends on an external party and José sending the email. <strong>Parked at the bottom 2026-06-25</strong> to focus on what's in our control; draft stays ready at <code>docs/outreach/marc-dump-request.md</code> — pick it up when there's appetite to send.</p>
        <div class="meta"><span class="tag t-ops">OPS</span><span class="tag t-todo">PARKED · EXTERNAL DEP</span></div>
      </div>
    </section>
  </div>
