---
change_id: s01-smoke-test
title: US-01 end-to-end smoke test on production
status: implemented
created: 2026-10-20
updated: 2026-10-20
archived_at: null
---

## Goal

Verify the full user flow works on production Render URL:
add a rule → run checks → see OK/FAIL with measured value.

## What was done

- Verified app deployed at https://data-pulse-cwij.onrender.com
- Connected Supabase PostgreSQL as MONITORED_DATABASE_URL (pooler port 6543)
- Created test table public.test_table with seed data
- Added rule: schema=public, table=test_table, min_row_count=1, created_at ≤ 1h
- Ran checks → result: 1 OK, 3 rows, 0.0h ago

## Outcome

S-01 passed. M-01 north star achieved.

## Key commits

- Initial deploy: gunicorn start command fix (.venv/bin/gunicorn)
- Migration fix: added to build command
- Supabase pooler connection (port 6543)
