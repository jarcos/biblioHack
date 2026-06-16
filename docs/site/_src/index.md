---
title: "biblioHack — Project Summary"
h1: "📚 biblioHack"
tagline: 'A reverse catalogue, availability tracker &amp; AI recommender for the Andalusian public-library network — live at <a href="https://biblio.josearcos.me" style="color:#e8c891">biblio.josearcos.me</a>'
raw_html: true
---
  <p><strong>Status snapshot — 13 June 2026.</strong> The project has gone from research draft (May 2026) to a <strong>live, public, multi-user application</strong> in roughly six weeks. Every planned milestone through the identity milestone's Phase 5 hardening has shipped. Most recently the crawler got a <strong>throughput overhaul</strong> — a pooled browser session plus a higher discovery cap took it from ~2.4k to ~9.6k records/day within the same 1 req/s politeness budget. What remains is a short tail of engineering follow-ups, a handful of operational loose ends, and the long-horizon roadmap items (other provinces, mobile, and a MARC-dump request that would close the full catalogue gap).</p>

  <div class="stats">
    <div class="stat"><span class="n">2.66M</span><span class="l">TITN record space</span></div>
    <div class="stat"><span class="n">8</span><span class="l">Bounded contexts</span></div>
    <div class="stat"><span class="n">12</span><span class="l">Alembic migrations</span></div>
    <div class="stat"><span class="n">463</span><span class="l">Backend tests (green)</span></div>
    <div class="stat"><span class="n">84%</span><span class="l">Backend coverage</span></div>
    <div class="stat"><span class="n">56</span><span class="l">Frontend tests (green)</span></div>
  </div>

  <h2>What it is</h2>
  <div class="panel">
    <p>The official OPAC (AbsysNET, run by the Junta de Andalucía) is fine if you already know the title you want. biblioHack keeps a <strong>polite, local mirror</strong> of the catalogue — bootstrapped from the Biblioteca Provincial de Huelva — so you can explore it like a bookshop: accent-insensitive Spanish full-text search, semantic "more like this", live per-branch availability badges, book covers, a Goodreads-imported personal shelf, and per-user AI recommendations. Python/FastAPI hexagonal backend, Astro + React-islands frontend, Postgres (TimescaleDB + pgvector), self-hosted on a Synology NAS behind a Cloudflare Tunnel. Full design in <a href="architecture.html">Architecture</a>.</p>
  </div>

  <h2>The plan, executed</h2>

  <h3>Product milestones (docs/design/architecture.md §11)</h3>
  <table>
    <tr><th>Milestone</th><th>Outcome</th><th>Status</th></tr>
    <tr><td><strong>M0</strong> Foundations</td><td>Repo scaffold, Docker Compose, CI (ruff + mypy + pytest + vitest), hello FastAPI/Astro</td><td><span class="badge b-done">SHIPPED</span></td></tr>
    <tr><td><strong>M1</strong> Catalog ingest</td><td>AbsysNet adapter + parser, first polite crawl, FTS search API/UI. TITN high-water mark probed: 2,662,739. Encoding (mojibake) bug found &amp; fixed before wide crawl</td><td><span class="badge b-done">SHIPPED</span></td></tr>
    <tr><td><strong>M2</strong> Availability history</td><td>Snapshot worker, TimescaleDB hypertable, "N disponibles ahora" badges</td><td><span class="badge b-done">SHIPPED</span></td></tr>
    <tr><td><strong>M2.5</strong> Book covers</td><td><code>covers</code> context, async resolution chain (Open Library → Google Books → placeholder), MinIO content-addressed store, immutable serving</td><td><span class="badge b-done">SHIPPED</span></td></tr>
    <tr><td><strong>M3</strong> Semantic search</td><td>BGE-M3 embeddings via HuggingFace Inference API (deviation: not local — NAS RAM), pgvector HNSW, <code>?mode=semantic</code> + similar-records. Hybrid keyword+vector fusion deferred</td><td><span class="badge b-done">SHIPPED 2026-06-08</span></td></tr>
    <tr><td><strong>M4</strong> Goodreads import</td><td><code>reading_history</code> context, CSV importer, ISBN-13 + trigram matching, shelf UI</td><td><span class="badge b-done">SHIPPED 2026-06-08</span></td></tr>
    <tr><td><strong>M5</strong> Recommender v1</td><td>Shipped as identity Phase 4 — per-user taste centroid + pgvector KNN, OpenRouter rationales</td><td><span class="badge b-done">SHIPPED 2026-06-10</span></td></tr>
    <tr><td><strong>M6</strong> Public deploy</td><td>NAS + Cloudflare Tunnel, same-origin path routing, backups</td><td><span class="badge b-done">LIVE 2026-05-30</span></td></tr>
    <tr><td><strong>M6.5</strong> CI/CD auto-deploy</td><td>Green push to <code>main</code> auto-deploys to the NAS; red pipeline never deploys</td><td><span class="badge b-done">SHIPPED</span></td></tr>
    <tr><td>APM / tracing</td><td>OpenTelemetry on the api (FastAPI + asyncpg auto-instrumented) → OTLP → shared collector → Grafana Tempo + SigNoz</td><td><span class="badge b-done">LIVE 2026-06-04</span></td></tr>
    <tr><td>Autonomous crawler</td><td>On-NAS <code>bibliohack-crawler</code> container, supercronic: hourly cursor-advancing discover+worker, 6-hourly refresh</td><td><span class="badge b-done">LIVE 2026-06-03</span></td></tr>
    <tr><td><strong>Relevance</strong> milestone</td><td><code>relevance_score</code> (demand + holdings + recency + completeness) → default browse sort + search tiebreak; nightly recompute. (<a href="relevance-and-libraries.html">plan</a>)</td><td><span class="badge b-pending">PLANNED</span></td></tr>
    <tr><td><strong>Libraries</strong> milestone</td><td>Follow branches by proximity; hard-filter browse/search/recs to "my libraries → province → full". (<a href="relevance-and-libraries.html">plan</a>)</td><td><span class="badge b-pending">PLANNED</span></td></tr>
    <tr><td><strong>M7</strong> Other provinces</td><td>Generalised SUBC handling, Sevilla + Cádiz</td><td><span class="badge b-defer">ROADMAP</span></td></tr>
    <tr><td><strong>M8</strong> Mobile app</td><td>React Native / Expo client over the same API</td><td><span class="badge b-defer">ROADMAP</span></td></tr>
  </table>

  <h3>Identity milestone — single-reader → public multi-user (all phases shipped 2026-06-10)</h3>
  <table>
    <tr><th>Phase</th><th>Outcome</th><th>Commit</th><th>Status</th></tr>
    <tr><td><strong>0 + 1</strong> Schema + auth</td><td><code>users</code> + one-time-token tables, full <code>identity</code> context (Argon2id, Redis sessions, mailer, Turnstile), <code>/api/auth/*</code></td><td><code>7992892</code></td><td><span class="badge b-done">SHIPPED</span></td></tr>
    <tr><td><strong>2A</strong> Shelf scoping</td><td><code>shelf_entries.user_id</code> NOT NULL, per-user uniqueness, auth-gated <code>GET /api/shelf</code>, CLI <code>--user-email</code></td><td><code>b36fa73</code></td><td><span class="badge b-done">SHIPPED</span></td></tr>
    <tr><td><strong>2B</strong> Background imports</td><td><code>POST /api/shelf/import</code> (202 + job id), <code>import_jobs</code>, Dramatiq worker on the NAS, polling endpoint</td><td><code>d485cfb</code></td><td><span class="badge b-done">SHIPPED</span></td></tr>
    <tr><td><strong>3</strong> Frontend auth</td><td>Auth pages, <code>/privacy</code> + <code>/terms</code>, consent at signup, upload UI. Deviation: static build → client-side guards</td><td><code>f4e9971</code></td><td><span class="badge b-done">SHIPPED</span></td></tr>
    <tr><td><strong>4</strong> Recommendations</td><td>User-scoped <code>recommendations</code> context: taste centroid + pgvector cosine KNN, shelf excluded, OpenRouter rationales, fingerprint-keyed cache</td><td><code>62b2cce</code></td><td><span class="badge b-done">SHIPPED</span></td></tr>
    <tr><td><strong>5</strong> Hardening</td><td>Redis rate limits (register/login/reset/import), GDPR export + password-confirmed account deletion, cross-user isolation test suite</td><td><code>5ce696c</code></td><td><span class="badge b-done">SHIPPED</span></td></tr>
  </table>
  <p>Full phase-by-phase detail, decisions and deviations: <a href="identity-milestone.html">Identity Milestone</a>.</p>

  <h2>What's still pending</h2>
  <div class="panel">
    <p><strong>Catalog navigator (requirement, in progress 2026-06-11):</strong> a <code>/browse</code> faceted explorer over the mirror — filter by author, genre (CDU-derived), language, publication year, audience/literary form and live availability, with facet counts and author search. Tier C (true author country/nationality) needs BNE/Wikidata authority enrichment and stays deferred.</p>
    <p><strong>Engineering follow-ups (closed 2026-06-11):</strong> ✓ schemathesis contract tests · ✓ otel-redis · ✓ token-endpoint rate limits · ✓ hybrid FTS+vector fusion (RRF) · ✓ Junta attribution (footer/README/export) · ✓ README refresh · ✓ shelf re-import UX (collapse to link; upsert updates in place).</p>
    <p><strong>Operational loose ends:</strong> ✓ José's shelf re-imported; ✓ <code>privacy@josearcos.me</code> delivery verified (Cloudflare route added 2026-06-13); <code>OPENROUTER_API_KEY</code> on the NAS or rationales stay empty; OTel for the crawl/worker plane.</p>
    <p>The full annotated list, with the long-horizon roadmap and open risks: <a href="pending-and-ops.html">Pending &amp; Operations</a>.</p>
  </div>

  <h2>Dive deeper</h2>
  <div class="cards">
    <a class="card" href="architecture.html"><strong>Architecture →</strong><span>Bounded contexts, stack, data model, the polite crawler, deployment topology, observability.</span></a>
    <a class="card" href="identity-milestone.html"><strong>Identity Milestone →</strong><span>How the app went multi-user: phases 0–5, locked decisions, and the deviations that mattered.</span></a>
    <a class="card" href="relevance-and-libraries.html"><strong>Relevance &amp; Libraries →</strong><span>Planned: a relevance score driving browse/search, and following branches by proximity to scope the catalogue.</span></a>
    <a class="card" href="pending-and-ops.html"><strong>Pending &amp; Operations →</strong><span>Everything not done yet, the ops runbook, and the open questions worth re-visiting.</span></a>
    <a class="card" href="kanban.html"><strong>Kanban →</strong><span>The board: done, in progress (including the autonomous crawl), and what's to do, at a glance.</span></a>
  </div>
