-- biblioHack — restore Grafana read-only SELECT grants.
--
-- SYMPTOM (crawl & enrichment dashboard, 2026-06-29):
--   Every panel that reads canon_seed / shelf_entries / discovery_cursors shows
--   "No data" (TITN space covered, the whole Canon row, the whole Shelf row,
--   Backlist swept %, Backlist ETA), while panels on bibliographic_records /
--   scrape_tasks / availability_snapshots / import_jobs render fine. Tell-tale:
--   "Backlist queue depth" (scrape_tasks) works but "Backlist swept %"
--   (discovery_cursors) right beside it fails — same row, same provisioning,
--   so it is not a stale dashboard. A bare `SELECT count(*) FROM canon_seed`
--   showing "No data" instead of "0" means the query ERRORS, not that the
--   table is empty.
--
-- CAUSE (confirmed on prod 2026-06-29):
--   The Grafana datasource role is `metrics` (the only non-superuser login role).
--   has_table_privilege shows metrics CAN select bibliographic_records /
--   scrape_tasks / import_jobs / availability_snapshots but CANNOT select
--   canon_seed / discovery_cursors / shelf_entries — all three exist. SELECT was
--   granted table-by-table and these were missed (import_jobs, migration 0011,
--   was granted; the older shelf_entries, 0008, was not — an explicit-list
--   omission, not a time-ordered "GRANT ON ALL TABLES ran once" gap).
--
--   PROD role name: metrics. Grafana datasource "bibliohack-pg" connects as it.
--
-- FIX:
--   Re-grant SELECT on every current table AND set DEFAULT PRIVILEGES so any
--   table a future migration creates is readable automatically — this is the
--   part that stops the bug recurring.
--
-- HOW TO RUN (once, against PROD — this is NOT auto-applied):
--   1. Confirm the datasource role name. In Grafana: Connections → Data sources
--      → "bibliohack-pg" → the "User" field. (Or in psql: \du)
--   2. Run as the database OWNER (the `bibliohack` role) so ALTER DEFAULT
--      PRIVILEGES attaches to the role that owns/creates the tables:
--
--        psql "$DATABASE_URL_SYNC" -v grafana_role=<role-from-step-1> \
--             -f infra/postgres/grafana-ro-grants.sql
--
--      e.g. -v grafana_role=metrics
--
--   On the current NAS prod there is no psql on the host; run it inside the
--   container instead (no .env password needed — local superuser connection):
--
--        cat infra/postgres/grafana-ro-grants.sql | ssh nas-deploy \
--          '/usr/local/bin/docker exec -i bibliohack-postgres \
--             psql -U bibliohack -d bibliohack -v grafana_role=metrics -f -'
--
--   Or, equivalently, the three statements inline (what this file runs):
--        GRANT USAGE ON SCHEMA public TO metrics;
--        GRANT SELECT ON ALL TABLES IN SCHEMA public TO metrics;
--        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO metrics;
--
--   It is idempotent — safe to re-run. It only touches SELECT (read-only).
--
-- NOTE: deliberately NOT placed in infra/postgres/init/ — that directory runs
-- on fresh container init as the superuser, where :grafana_role is unset and the
-- role may not exist yet, which would abort DB initialisation. Keep it manual.

\if :{?grafana_role}
\else
  \echo '*** ERROR: pass the datasource role, e.g. -v grafana_role=grafana_ro'
  \quit
\endif

-- Fail early with a clear message if the role name is wrong. (Done outside a
-- DO block on purpose: psql does NOT substitute :variables inside dollar-quoted
-- bodies, so the check must be a plain statement piped through \gset.)
SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'grafana_role') AS role_ok \gset
\if :role_ok
\else
  \echo '*** ERROR: role' :'grafana_role' 'does not exist — check the Grafana datasource User (\\du to list roles)'
  \quit
\endif

-- (CONNECT is already held — Grafana is connecting today; nothing to grant there.)
GRANT USAGE ON SCHEMA public TO :"grafana_role";

-- Everything that exists right now (closes canon_seed, shelf_entries,
-- discovery_cursors and any other current omission in one shot).
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"grafana_role";

-- Future-proof: tables created by the owner from now on are auto-readable.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO :"grafana_role";

-- Verify the three that were dark (returns has_select = t for each):
SELECT relname,
       has_table_privilege(:'grafana_role', oid, 'SELECT') AS has_select
FROM pg_class
WHERE relname IN ('canon_seed', 'shelf_entries', 'discovery_cursors')
  AND relkind = 'r'
ORDER BY relname;
