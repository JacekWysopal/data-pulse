# MySQL Support — Plan Brief

> Full plan: `context/changes/mysql-support/plan.md`
> Research: `context/changes/mysql-support/research.md`

## What & Why

Add MySQL/MariaDB as a second monitored database provider alongside PostgreSQL.
DataPulse currently supports only PostgreSQL; users with MySQL databases cannot use the
product at all. This change unlocks that audience by adding a `provider` field to
`Connection`, wiring a PyMySQL driver path through the service layer, and making the
MySQL card in the provider grid clickable.

## Starting Point

The service layer is 100% `psycopg2`. There are 8 PostgreSQL-specific callsites in
`monitor/services.py` (driver import, 4 direct `psycopg2.connect()` calls, 1 timeout
statement, 1 freshness SQL expression, 1 system-schema filter). `Connection` has no
`provider` field. The MySQL card in the UI shows "Soon".

## Desired End State

A user can create a `Connection` with `provider = mysql` and a
`mysql+pymysql://user:pass@host:3306/db` URL. Volume, freshness, and custom-SQL rules
execute against that MySQL connection and return correct OK / FAIL / ERROR results.
Schema introspection lists MySQL tables (no system tables). All existing PostgreSQL
connections and rules continue to work without change.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| MySQL driver | PyMySQL 1.1.1 (pure Python) | No C extension — consistent with psycopg2-binary, no extra Render build step | Research |
| URL format | `mysql+pymysql://user:pass@host:3306/db` | Standard SQLAlchemy-compatible scheme; parsed by `_parse_mysql_url` helper before pymysql.connect() call | Research / Plan |
| Connection.provider field | CharField choices=['postgresql','mysql'], default='postgresql' | Additive migration; all existing rows stay PostgreSQL automatically | Research |
| Provider dispatch location | `_open_conn(url, provider)` — single seam | Centralises driver selection; avoids spreading `if provider ==` across the file | Plan |
| Freshness SQL (MySQL) | `TIMESTAMPDIFF(SECOND, MAX(col), NOW()) / 3600` | Direct MySQL equivalent of `EXTRACT(EPOCH FROM ...)` — same numeric result | Research |
| Statement timeout (MySQL) | `SET SESSION max_execution_time = 30000` | MySQL ≥5.7.8 equivalent of `SET statement_timeout` | Research |
| System-schema filter (MySQL) | Exclude `information_schema`, `performance_schema`, `mysql`, `sys` | These are MySQL system schemas; `pg_catalog` does not exist in MySQL | Research |
| TIMESTAMP_TYPES extension | Add `datetime` to existing set | MySQL's temporal type not in the current PostgreSQL-only set | Research |
| SSL support | Out of scope | Product decision deferred; no URL query-param or field added in this change | Plan |
| PlanetScale | Out of scope | Free tier discontinued March 2024; Vitess breaks information_schema | Research |
| MariaDB | No extra branching | Shares MySQL SQL syntax; TIMESTAMPDIFF works in both | Research |

## Scope

**In scope:**
- `Connection.provider` CharField + migration 0006
- `ConnectionForm` provider selector + dynamic URL placeholder JS
- MySQL card "Available" in provider grid
- `_open_conn` provider dispatch + `_parse_mysql_url` helper
- All four `psycopg2.connect()` callsites routed through `_open_conn`
- System-schema filter, TIMESTAMP_TYPES, freshness SQL, timeout SQL per provider
- Mock unit tests for all new MySQL branches

**Out of scope:**
- SSL/TLS parameter support on Connection URL
- PlanetScale / Vitess compatibility
- MariaDB-specific branching (works by accident of shared syntax)
- Migration of existing rules or connections
- `mysql-connector-python` (rejected in favour of PyMySQL)

## Architecture / Approach

Provider dispatch is centralised at `_open_conn`. All connection-open callsites pass
`provider` from `rule.connection.provider` (or `conn_obj.provider`). SQL-level
differences are handled as inline `if provider == 'postgresql'` branches at the exact
two callsites where they occur (`_check_custom_sql`, `_check_volume_freshness`). No new
modules; all changes are within the existing `monitor/` package.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Connection.provider Field + Migration | Model field, migration, form selector, JS placeholder | Migration must be AddField-only; verify before commit |
| 2. PyMySQL Dependency + services.py MySQL Branch | `_open_conn` dispatch, `_parse_mysql_url`, all 4 connect callsites routed | `conn_cache` tuple shape change must be consistent across all readers |
| 3. Schema Introspection for MySQL | System-schema filter, TIMESTAMP_TYPES, exception handling | MySQL `datetime` type must land in TIMESTAMP_TYPES |
| 4. SQL Execution — MySQL Branches | Timeout statement, freshness SQL per provider | `TIMESTAMPDIFF` result must match `EXTRACT(EPOCH)` numeric type |
| 5. UI — MySQL Card Active | Provider card clickable, empty-state text | `?provider=mysql` pre-selection needs view tweak |
| 6. Tests — Mock MySQL Unit Tests | Full mock coverage of all new branches | All tests must pass without a live MySQL instance |

**Prerequisites:** None — this change is independent of current open work (no prereqs in roadmap S-14).
**Estimated effort:** ~3–4 focused sessions across 6 phases. Phases 1–2 are the largest; phases 3–5 are targeted edits.

## Open Risks & Assumptions

- PyMySQL 1.1.1 is the latest stable release as of research date (2026-10-28); verify
  on install in case a newer patch exists.
- `SET SESSION max_execution_time` requires MySQL ≥ 5.7.8. If a user connects to an
  older MySQL the timeout statement will fail silently or raise an error. Acceptable for
  this change; a version guard can be added later if needed.
- The `conn_cache` tuple shape change in `run_all_checks` (from 2-tuple to 3-tuple) is
  a coordinated change across Phase 2 steps 5–6; if done inconsistently it will cause
  an `unpack` ValueError at runtime. Must be done atomically in one commit.
- db4free.net and Railway are the recommended free MySQL test services; db4free.net has
  low reliability SLA (fine for development, not for CI).

## Success Criteria (Summary)

- `python manage.py test monitor` passes with all new MySQL test classes green and zero
  regressions.
- A MySQL connection created via the UI runs a volume rule and returns OK/FAIL.
- All existing PostgreSQL connections and rules are unaffected.
