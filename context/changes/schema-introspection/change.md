---
change_id: schema-introspection
title: S-04 Schema introspection — read tables and columns from connected PostgreSQL
status: implemented
created: 2026-10-25
updated: 2026-10-25
archived_at: null
---

## Goal

When creating or editing a rule, the user can browse available tables and columns
from the selected Connection instead of typing them manually.

## What was done

### Backend (S-04)
- services.py: get_schema_tables(conn_id) — queries information_schema.tables
- services.py: get_schema_columns(conn_id, schema, table) — queries information_schema.columns
- views.py: api_schema_tables, api_schema_columns — AJAX endpoints, session-cached 5 min
- urls.py: /api/schema/<conn_id>/tables/ and /api/schema/<conn_id>/columns/<schema>/<table>/
- Session cache key pattern: dp_schema_tables_{conn_id}, dp_schema_cols_{conn_id}_{schema}_{table}

### Frontend (S-05)
- rule_form.html: table browser panel — appears when connection selected
- Tables grouped by schema, scrollable list (max-height 180px)
- Clicking table: fills schema_name + table_name inputs + loads column browser
- Column browser: shows only timestamp/date columns with type label
- Clicking column: fills timestamp_column input
- Selected state (purple highlight) on active table and column
- Loading spinners during fetch
- Error states: connection failed, no tables, no timestamp columns
- Graceful fallback: text inputs always visible and editable
- Edit mode: pre-selects table/column from existing values, deferred column load

## BU-03 resolution

information_schema is available via Supabase pooler (port 6543).
No special handling needed — standard psycopg2 connection works.

## Key files changed

- monitor/services.py — get_schema_tables, get_schema_columns
- monitor/views.py — api_schema_tables, api_schema_columns, CACHE_KEY constants
- monitor/urls.py — 2 new API routes
- templates/monitor/rule_form.html — full rewrite with schema browser JS

## Progress

- [x] get_schema_tables() in services.py
- [x] get_schema_columns() in services.py
- [x] AJAX endpoints in views.py
- [x] URL routes
- [x] Table browser UI with grouping by schema
- [x] Column browser (timestamp only)
- [x] Session cache
- [x] Loading spinners
- [x] Error states
- [x] Edit mode pre-selection
- [x] Fallback text inputs always available
