---
title: "biblioHack — Pending &amp; Operations"
h1: "Pending Tasks &amp; Operations"
raw_html: true
---
  <p>Everything not done as of 2026-06-10, ordered roughly by how soon it should bite. Items marked <span class="badge b-ops">OPS</span> need a human (José) rather than code.</p>

  <h2>Catalog navigator — project requirement (✓ Tier A+B shipped 2026-06-12)</h2>
  <div class="panel">
    <p>The mirror grows hourly but search-only access hides what's already there. Requirement: a <strong><code>/browse</code> faceted navigator</strong> in the frontend. <strong>Tier A + B are live;</strong> Tier C stays deferred. Scope by tier:</p>
    <p><strong>Tier A (core):</strong> <code>GET /catalog/browse</code> — filters for author (contributors join), language, publication-year range, audience, literary form and "available now"; sort (newest / title / availability); pagination; per-axis facet counts in the response (they double as a crawl-progress dashboard). Frontend <code>/browse</code> page: facet sidebar + paginated card grid reusing the search result cards.</p>
    <p><strong>Tier B (genre + authors):</strong> a <strong>CDU-derived genre tag</strong> (narrativa / poesía / teatro / cómic / otros) persisted on records — same classify-don't-discard pattern as <code>LiteraryProfile</code>, re-derivable without re-crawl (MARC subject headings are too sparse in this catalogue to carry the facet); <code>GET /catalog/authors</code> author search with record counts feeding an author facet/typeahead.</p>
    <p><strong>Tier C (deferred):</strong> author country/nationality — requires BNE/Wikidata authority enrichment (a separate project; revisit when the mirror justifies it).</p>
  </div>

  <h2>Milestones — Relevance &amp; Libraries (designed 2026-06-15)</h2>
  <div class="panel">
    <p>A natural extension of the navigator. Full plan: <a href="relevance-and-libraries.html">Relevance &amp; Libraries</a>.</p>
    <p><strong>Relevance — ✓ SHIPPED 2026-06-16.</strong> A stored <code>relevance_score</code> ∈ [0,1] so <code>/browse</code> + search lead with the best titles: a balanced blend of <em>demand</em> (derived from the availability time-series), <em>holdings breadth</em>, <em>recency</em>, and <em>display completeness</em>, corpus-normalised (p95), recomputed nightly on the crawl plane. It's the default browse sort and a filter + tiebreak in search.</p>
    <p><strong>Canon / external popularity boost — ✓ SHIPPED + scheduled 2026-06-21.</strong> The «positive-only boost added later, with the back-catalogue» from the original plan is now built (Wikidata awards + curated award lists + Open Library ratings) and self-maintaining on the crawl plane. Full plan: <a href="canon-import.html">Canon Import</a>. Follow-ups: WDQS keyset pagination, a Grafana coverage panel, and feeding the OL rating signal into the boost.</p>
    <p><strong>Libraries — PLANNED (ships next).</strong> Promote <code>holdings.Branch</code> to a user-facing entity (geo/address/url; 509 branches already exist), let users <strong>follow multiple branches by geolocation proximity</strong> (location stays client-side), and hard-filter browse + search to «my libraries → my province → full catalogue». Recommendations become library-aware. Branch geo from an official CC-BY directory with Nominatim geocode fallback.</p>
    <p><strong>Carries an OPS dependency:</strong> the nightly relevance recompute and the canon jobs ship in the crawler image, so they need the <span class="badge b-ops">OPS</span> manual NAS rebuild (crawler ≠ CD), and every new frontend-called endpoint must live under <code>/api/*</code> (tunnel routing).</p>
  </div>

  <h2>Near-term follow-ups</h2>
  <table>
    <tr><th>Task</th><th>Detail</th><th>Type</th></tr>
    <tr><td>✓ Re-import José's shelf <em>(done 2026-06-11)</em></td><td>Shelf re-imported; the uploader now collapses to a discreet re-import link, and re-imports upsert in place (no duplicates)</td><td><span class="badge b-ops">OPS</span></td></tr>
    <tr><td><code>privacy@josearcos.me</code> must receive mail</td><td>The legal pages cite it; confirm routing/forwarding actually delivers</td><td><span class="badge b-ops">OPS</span></td></tr>
    <tr><td><code>OPENROUTER_API_KEY</code> in the NAS <code>.env</code></td><td>Without it, recommendation rationales silently stay empty (by design, best-effort)</td><td><span class="badge b-ops">OPS</span></td></tr>
    <tr><td>✓ Junta attribution string <em>(done 2026-06-11)</em></td><td>«Información obtenida del Portal de la Junta de Andalucía» now in the frontend footer, the README and the GDPR export payload</td><td><span class="badge b-pending">CODE</span></td></tr>
    <tr><td>✓ schemathesis contract tests <em>(done 2026-06-11)</em></td><td><code>tests/contract/</code> fuzzes /api/auth|account|shelf from the OpenAPI schema — no generated input may 5xx</td><td><span class="badge b-pending">CODE</span></td></tr>
    <tr><td>✓ <code>opentelemetry-instrumentation-redis</code> <em>(done 2026-06-11)</em></td><td>Session-store + rate-limit Redis calls now traced in Tempo/SigNoz</td><td><span class="badge b-pending">CODE</span></td></tr>
    <tr><td>✓ Rate-limit <code>verify</code> / <code>reset</code> <em>(done 2026-06-11)</em></td><td>Both token-consume endpoints throttled at 10/5 min</td><td><span class="badge b-pending">CODE</span></td></tr>
    <tr><td>✓ README refresh <em>(done 2026-06-11)</em></td><td>Shipped features moved out of "roadmap"; milestone table current</td><td><span class="badge b-pending">CODE</span></td></tr>
  </table>

  <h2>Deferred by design (revisit when there's a reason)</h2>
  <table>
    <tr><th>Item</th><th>Trigger to revisit</th></tr>
    <tr><td>✓ Hybrid FTS + vector fusion <em>(shipped 2026-06-11)</em></td><td><code>?mode=hybrid</code> — RRF (k=60) over both rankings, degrades to keyword on embedder failure; three-way toggle in the UI</td></tr>
    <tr><td>✓ LLM query rewriting &amp; cold-start classification <em>(shipped 2026-06-23)</em></td><td>All three §8.3 jobs now built: <code>rewrite=true</code> on <code>/catalog/search</code> (NL→structured browse, heuristic-gated, revertible chip) and cold-start recs from the raw shelf (LLM taste descriptor → BGE-M3 KNN, <code>cold_start</code> flag + chips). Best-effort; no schema change</td></tr>
    <tr><td>Tier-two importers (StoryGraph, Hardcover, BookWyrm)</td><td>One new <code>Importer</code> adapter each; wait for a real user asking</td></tr>
    <tr><td>OTel on the crawl/worker plane</td><td>If <code>scrape_tasks</code>/<code>import_jobs</code> status rows stop being enough to debug crawl health; <code>scrape_log</code> request log remains unwired</td></tr>
    <tr><td>Frontend audience/literary-form badge + scope toggle</td><td>§5.5 backend is done (<code>?scope=</code>); the UI affordance is still minimal</td></tr>
    <tr><td>Edge rate limiting (Cloudflare WAF rules)</td><td>App-level limits shipped in Phase 5; add edge rules if abuse appears</td></tr>
    <tr><td>Qdrant migration</td><td>Only if pgvector query p95 &gt; 250 ms in production — acceptance criterion fixed in §12.7</td></tr>
    <tr><td><strong>M7</strong> Other provinces (Sevilla, Cádiz…)</td><td>Generalise SUBC handling by config; copies are already stored network-wide, so it's mostly scoping + crawl budget</td></tr>
    <tr><td><strong>M8</strong> Mobile app</td><td>React Native/Expo over the same API; out of scope for now</td></tr>
    <tr><td>Request a MARC dump from the Junta <em>(email drafted 2026-06-13)</em></td><td>A periodic MARC-XML dump (Madrid precedent) would obsolete most of the scraper and close the full ~2.66M gap that crawling never will. Draft ready at <code>docs/outreach/marc-dump-request.md</code> — pending José to pick a channel and send</td></tr>
  </table>

  <p class="muted"><em>Shipped 2026-06-22 (code complete, gate green; deploy pending): the demand-driven fetcher for unmatched shelf books — <code>shelf rematch</code> (DB-only) + <code>shelf resolve</code> (on-OPAC, deduped + cooldown) + the <code>shelf_resolve</code> crawl-plane job. See <a href="demand-driven-shelf-fetcher.html">Demand-driven fetcher</a>.</em></p>

  <h2>Ops runbook (the short version)</h2>
  <div class="panel">
    <p><strong>Ship workflow.</strong> Commit + push to <code>main</code>; CI gates (backend: <code>ruff format --check . &amp;&amp; ruff check . &amp;&amp; mypy src &amp;&amp; pytest</code>; frontend: prettier, eslint, <code>astro check</code>, vitest) and auto-deploys to the NAS. Never deploy on a red pipeline. Migrations ship in the api image and run on deploy.</p>
    <p><strong>Local gate quirks (Mac).</strong> Docker is OrbStack — testcontainers needs <code>DOCKER_HOST=unix://$HOME/.orbstack/run/docker.sock</code>. A local Redis will poison rate-limit windows for any test app that forgets to override <code>get_rate_limiter</code> (all current suites do override it).</p>
    <p><strong>Crawler.</strong> On-NAS container, separate compose project: <code>docker compose -p bibliohack-crawler -f docker-compose.crawler.yml …</code>. Supercronic schedule baked in: hourly discover+worker, 6-hourly refresh, 3-hourly embed, nightly relevance recompute (04:00), and — since 2026-06-21 — the canon jobs <code>canon_seed</code> (monthly, <code>0 5 1 * *</code>: refresh-seed → refresh-awards → match, off-OPAC) and <code>canon_resolve</code> (4-hourly, <code>50 */4 * * *</code>: match → <code>resolve --max $CANON_RESOLVE_MAX</code>, shares the crawl lock + 1 req/s budget). Health = <code>scrape_tasks</code> status histogram + <code>last_error</code>. Throughput knobs live in the compose <code>environment:</code> block — <code>DISCOVER_MAX</code> (the real daily-rate lever; <strong>400</strong>/hr since 2026-06-13), <code>WORKER_MAX</code>, and <code>CANON_RESOLVE_MAX</code> (default 150). A code or env change here does <em>not</em> ride CD: edit, push, then recreate the container on the NAS (<code>… up -d</code>, add <code>--build</code> only for code changes — the canon jobs needed exactly such a rebuild to land in the running container).</p>
    <p><strong>Import worker.</strong> <code>bibliohack-import-worker</code> Dramatiq container, same backend image. Job health = <code>import_jobs</code> rows.</p>
    <p><strong>Mail.</strong> Mailgun EU, <code>smtp.eu.mailgun.org:587</code>, user <code>alerts@mail.josearcos.me</code> (credential shared with Grafana alerting; lives in the NAS <code>.env</code>). The <code>mail.josearcos.me</code> domain is on a separate Mailgun account/region from the sandbox one. Backup of the pre-Mailgun env: <code>.env.bak-mailgun-sandbox</code>.</p>
    <p><strong>Routing.</strong> New frontend-called endpoints must live under <code>/api/*</code> (tunnel routes <code>/api/*</code>, <code>/catalog/*</code>, <code>/healthz</code> → api; everything else → static frontend). The symptom of forgetting: <code>Unexpected token '&lt;'</code>.</p>
    <p><strong>OPAC citizenship.</strong> Politeness budget is a compliance requirement (terms forbid overload): never raise the <strong>request rate</strong> (<code>CRAWL_RATE=1.0</code> req/s, jittered) casually — that is the ceiling. Raising <code>DISCOVER_MAX</code> (daily <em>volume</em>) is fine within that ceiling, but keep it below the worker's drain rate so the backlog shrinks, and watch the failure-rate + pending-task panels after any bump.</p>
  </div>

  <h2>Open questions still worth carrying (from ARCHITECTURE §12)</h2>
  <ul class="tight">
    <li><strong>Virtual copies ("ejemplares virtuales")</strong> — zero-copy records confirmed real; double-check we aren't silently dropping digital-loan copies.</li>
    <li><strong>Subjects parser confidence</strong> — the exact <code>js-</code> class for <em>materias</em> is still unconfirmed against a record that actually exposes them.</li>
    <li><strong>Google Books cover ToS</strong> — display-time hotlink only, never stored; per-cover <code>license</code>/<code>source</code> tracked so a source can be purged. Re-read terms if cover usage grows.</li>
    <li><strong>Huelva-only vs network-wide copies</strong> — currently storing all-province copies and filtering at query time; the cheap path to M7, but re-validate the storage cost as the mirror grows.</li>
  </ul>
