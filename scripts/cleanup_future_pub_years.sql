-- One-off data cleanup: null out implausible future publication years.
--
-- Context: the parser/canon plausibility band used to cap at a fixed 2100, so
-- near-future years (e.g. 2029, 2033) from source MARC typos or the T260
-- 4-digit-run fallback were stored as real pub_years and — because browse sorts
-- by pub_year DESC — floated to the top of the catalogue. The parser now caps
-- at the current year + 1 (forthcoming-title buffer); this fixes rows already
-- ingested before that change.
--
-- Idempotent and safe to re-run. Run inside a transaction; inspect the SELECTs
-- first, then COMMIT.

BEGIN;

-- Preview what will change (run these first):
SELECT 'bibliographic_records' AS tbl, count(*) AS rows_affected
FROM bibliographic_records
WHERE pub_year > extract(year FROM now())::int + 1;

SELECT 'canon_seed' AS tbl, count(*) AS rows_affected
FROM canon_seed
WHERE pub_year > extract(year FROM now())::int + 1;

-- Apply:
UPDATE bibliographic_records
SET pub_year = NULL
WHERE pub_year > extract(year FROM now())::int + 1;

UPDATE canon_seed
SET pub_year = NULL
WHERE pub_year > extract(year FROM now())::int + 1;

-- Review the row counts above, then:
-- COMMIT;   -- or ROLLBACK; to abort
