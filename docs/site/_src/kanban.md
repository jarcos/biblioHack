---
title: "biblioHack — Kanban"
h1: "Kanban — project status"
raw_html: true
---
  <p class="intro">Status as of <strong>2026-06-25</strong>. "In progress" includes the autonomous work the system does for itself — the crawler never stops. Cards link the commit that shipped them where it helps. The continuous tasks have a live <a href="https://grafana.josearcos.me/d/bibliohack-crawl">Grafana dashboard</a> (LAN/Tailscale).</p>

  <div class="board">

    <!-- ── DONE ──────────────────────────────────────────── -->
    <section class="col done">
      <h2>Done <span class="n">24</span></h2>

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
      <h2>In progress <span class="n">3</span></h2>

      <div class="card">
        <h3>Catalogue crawl (autonomous)</h3>
        <p><strong>Novedades 2024+ window is caught up:</strong> ~54,030 records mirrored (2026-06-21) against a ~55–56k result set, so the resumable <code>(@fepu&gt;=2024)</code> cursor has reached the end and the hourly bars are now a near-zero trickle of newly-catalogued arrivals — expected, not a break (a 2026-06-18 "imports stopped" scare turned out to be exactly this). The full ~2.66M TITN space stays the long game (the MARC dump closes it, not crawling). With novedades caught up there's spare OPAC budget, now shared by the <code>canon_resolve</code> (4-hourly) and <code>shelf_resolve</code> (6-hourly) jobs under the single crawl lock. Live progress: <a href="https://grafana.josearcos.me/d/bibliohack-crawl">Grafana → biblioHack crawl &amp; enrichment</a>.</p>
        <div class="meta"><span class="tag t-wip">CONTINUOUS</span></div>
      </div>

      <div class="card">
        <h3>Genre coverage (self-healing)</h3>
        <p>~5k records carry a real genre; the rest re-derive on re-scrape. <strong>Gotcha found 2026-06-12:</strong> the crawler container doesn't ride CD — it needed a manual <code>--build</code> to pick up genre derivation (done). Watch «% known by ingest day» on the dashboard to confirm new records arrive classified.</p>
        <div class="meta"><span class="tag t-wip">CONTINUOUS</span></div>
      </div>

      <div class="card">
        <h3>Embedding backfill</h3>
        <p>BGE-M3 vectors via the HF Inference API, every 3h on the crawler plane — semantic/hybrid quality grows with the mirror.</p>
        <div class="meta"><span class="tag t-wip">CONTINUOUS</span></div>
      </div>
    </section>

    <!-- ── TO DO ─────────────────────────────────────────── -->
    <section class="col todo">
      <h2>To do <span class="n">9</span></h2>

      <div class="divider">Next up — prioritised 2026-06-22 (leverage ÷ effort); LLM query rewriting + cold-start shipped 2026-06-23, demand-driven fetcher fully deployed 2026-06-24</div>

      <div class="card">
        <h3>1 · MARC-dump request to the Junta (RBPA) — postponed</h3>
        <p>Email the RBPA coordinator for a periodic MARC-XML dump (Madrid precedent, CC-BY). One «sí» obsoletes ~90% of the crawl — bibliographic data arrives in bulk; only holdings/availability still need probing. Deploy-free, highest long-term leverage and it attacks the binding constraint behind every canon/relevance feature (the corpus being a thin <code>pub_year ≥ 2023</code> slice). <strong>Postponed by José 2026-06-22</strong> — still #1 on merit; pick it back up when ready to send.</p>
        <div class="meta"><span class="tag t-ops">OPS</span><span class="tag t-todo">QUICK · POSTPONED</span></div>
      </div>

      <div class="card">
        <h3>2 · Search ⇄ browse cross-links</h3>
        <p>Natural follow-on to the navigator: clicking an author/genre badge on a search result or record page jumps into <code>/browse</code> pre-filtered; search box on /browse. <strong>#2:</strong> small, cheap, self-contained UX polish.</p>
        <div class="meta"><span class="tag t-todo">SMALL</span></div>
      </div>

      <div class="card">
        <h3>3 · StoryGraph CSV importer</h3>
        <p>Second <code>Importer</code> adapter; CSV shape close to Goodreads. Wait for a real user asking, or do it as the second-source proof. <strong>#3:</strong> small but demand-gated — let a real request pull it forward. <em>Note: the demand-driven fetcher already covers StoryGraph entries for free once they exist (it resolves from stored title/author/ISBN, nothing Goodreads-specific).</em></p>
        <div class="meta"><span class="tag t-todo">SMALL</span></div>
      </div>

      <div class="card">
        <h3>4 · OTel on the crawl/worker plane</h3>
        <p>When <code>scrape_tasks</code>/<code>import_jobs</code> status rows stop being enough; <code>scrape_log</code> remains unwired. <strong>#4:</strong> internal observability — defer until the status rows actually fall short.</p>
        <div class="meta"><span class="tag t-todo">MEDIUM</span></div>
      </div>

      <div class="card">
        <h3>5 · Edge rate limiting (Cloudflare WAF)</h3>
        <p>App-level limits shipped in Phase 5; add edge rules if abuse actually appears. <strong>#5:</strong> reactive — only worth doing once abuse shows up.</p>
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
        <h3>M7 — Other provinces (Sevilla, Cádiz…)</h3>
        <p>Config-driven SUBC scoping + crawl budget; copies are already stored network-wide. The natural next big milestone now that the app is multi-user.</p>
        <div class="meta"><span class="tag t-todo">MILESTONE</span></div>
      </div>

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
    </section>
  </div>
