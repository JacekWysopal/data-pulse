---
date: 2026-10-28T10:54:32Z
researcher: kiro-worker
git_commit: 53d06be871068aad798577c0239e1cfaa94b3c43
branch: dev
repository: data-pulse
topic: "What is needed to add MySQL as a monitored database provider in DataPulse?"
tags: [research, mysql, mysql-support, services, models, forms, drivers]
status: complete
last_updated: 2026-10-28
last_updated_by: kiro-worker
---

# Research: What is needed to add MySQL as a monitored database provider in DataPulse?

**Date**: 2026-10-28T10:54:32Z
**Researcher**: kiro-worker
**Git Commit**: 53d06be871068aad798577c0239e1cfaa94b3c43
**Branch**: dev
**Repository**: data-pulse (https://github.com/JacekWysopal/data-pulse.git)

## Research Question

What is needed to add MySQL as a monitored database provider in DataPulse? Specifically:
1. How does `_check_volume_freshness` and `_check_custom_sql` work? What SQL is PostgreSQL-specific?
2. Does `Connection` have a `provider` field? What changes are needed to the model?
3. Python MySQL drivers — pymysql vs mysql-connector-python: compatibility, pip install, connection URL format.
4. SQL compatibility differences — COUNT(*), EXTRACT(EPOCH), information_schema, system schema filters.
5. Connection URL format for MySQL vs PostgreSQL.
6. Free MySQL hosting options: PlanetScale, Railway, db4free.net.

## Summary

DataPulse currently has 8 PostgreSQL-specific code sites across `monitor/services.py` that must change to support MySQL: the sole driver import (`psycopg2`), 4 direct `psycopg2.connect()` callsites (2 of which bypass the existing `_open_conn` helper), 1 PostgreSQL-only SQL expression (`EXTRACT(EPOCH FROM ...)`), 1 PostgreSQL-only statement (`SET statement_timeout`), and 1 system-schema filter that references `pg_catalog`. The `Connection` model has no `provider` field; adding one as a `CharField` with choices `postgresql` / `mysql` requires a migration. PyMySQL (`pymysql`) is the recommended driver: pure Python, actively maintained, lighter than `mysql-connector-python`, but it does not accept a URL string natively — its `connect()` requires keyword arguments, so the URL must be parsed before dispatch. Among free MySQL hosts, db4free.net (no trial limit) and Railway (free tier with monthly credit) are viable for development/testing; PlanetScale's free tier was discontinued in March 2024 and is unavailable to new accounts.

## Detailed Findings

### 1. Current services.py: _check_volume_freshness

**[evidence]** `_check_volume_freshness` (`monitor/services.py`, approximately line 159) runs two optional sub-checks inside a single `with conn.cursor() as cur:` block:

- **Volume check**: `SELECT COUNT(*) FROM "{schema}"."{table}"` — [evidence] `COUNT(*)` is standard SQL and works identically in MySQL (`monitor/services.py` approx. line 170).
- **Freshness check**: `SELECT EXTRACT(EPOCH FROM (NOW() - MAX({col}))) / 3600 FROM {table}` — [evidence] this exact expression is at `monitor/services.py` approx. line 178. `EXTRACT(EPOCH FROM interval)` is **PostgreSQL-only** syntax. MySQL returns a DATETIME difference, not an epoch interval.

MySQL equivalent for the freshness expression (on this inspected path only):
```sql
SELECT TIMESTAMPDIFF(SECOND, MAX({col}), NOW()) / 3600 FROM {table}
```
or equivalently `TIME_TO_SEC(TIMEDIFF(NOW(), MAX({col}))) / 3600`. Both are MySQL-compatible and return the same numeric result (hours as a float) as the PostgreSQL expression, given that `MAX({col})` is non-NULL.

The exception handler at the end of `_check_volume_freshness` catches `psycopg2.Error` — [evidence] `monitor/services.py` approx. line 187. This catch clause will not catch MySQL driver errors; it requires a parallel `except pymysql.Error` branch or a unified exception base.

### 2. Current services.py: _check_custom_sql

**[evidence]** `_check_custom_sql` (`monitor/services.py` approx. line 113) runs in this sequence:

1. Validates SQL against `SQL_ALLOWED` (must start with SELECT) and `SQL_FORBIDDEN` (no DML/DDL keywords) — [evidence] `monitor/services.py` approx. lines 101–108. These regex checks are provider-agnostic.
2. Executes `SET statement_timeout = 30000` before the user SQL — [evidence] `monitor/services.py` approx. line 143. **This is PostgreSQL-only.** MySQL uses `SET SESSION max_execution_time = 30000` (milliseconds, same unit) or the `/*+ MAX_EXECUTION_TIME(30000) */` query hint. An implementation branch on provider is required here.
3. Executes the user SQL with `cur.execute(sql)` and fetches one row — provider-agnostic.
4. Interprets the result using a `falsy` set `{False, 0, '0', 'f', 'false', 'no', 'n', None}` — provider-agnostic; MySQL returns Python booleans/integers/strings from the same constructs.
5. The exception handler catches `psycopg2.Error` — same issue as in `_check_volume_freshness`.

### 3. Direct psycopg2.connect() callsites that bypass _open_conn

**[evidence]** `_open_conn(url)` at `monitor/services.py` approx. line 22 wraps `psycopg2.connect(url)` and translates `psycopg2.OperationalError` to `MonitoredDbError`. It is called by `get_schema_tables` and `get_schema_columns`, but **not** by the two check-execution entry points:

- `run_single_rule` calls `psycopg2.connect(url)` directly — [evidence] `monitor/services.py` approx. line 202. This is an architectural inconsistency relative to `_open_conn`.
- `run_all_checks` calls `psycopg2.connect(url)` directly inside `conn_cache` population — [evidence] `monitor/services.py` approx. line 246.

**[inference]** Routing all four callsites through a unified `_open_conn(url, provider)` that dispatches by provider is the cleanest seam for MySQL support; it avoids spreading provider-dispatch logic across the file.

### 4. get_schema_tables: system-schema filter

**[evidence]** `get_schema_tables` (`monitor/services.py` approx. line 32) filters:
```sql
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  AND table_type = 'BASE TABLE'
```
`pg_catalog` is a PostgreSQL-specific system schema. In MySQL the system schemas are `information_schema`, `performance_schema`, `mysql`, and `sys`. The `information_schema` exclusion is already present and correct for MySQL; `pg_catalog` must be replaced by the three MySQL-specific names on this inspected path.

`information_schema.tables` and `information_schema.columns` (used in `get_schema_columns`) are part of the SQL standard and work in both PostgreSQL and MySQL — [evidence] `monitor/services.py` approx. lines 47–57 and 78–89.

Timestamp type names differ: PostgreSQL uses `timestamp`, `timestamp without time zone`, `timestamp with time zone`, `timestamptz`, `date`, `time`, `timetz` (the inspected `TIMESTAMP_TYPES` set at `monitor/services.py` approx. line 70). MySQL uses `datetime`, `timestamp`, `date`, `time`. MySQL's `timestamp with time zone` does not exist as a type name; only `timestamp` and `datetime` carry temporal meaning. The `TIMESTAMP_TYPES` set must be extended for MySQL.

### 5. Connection model: no provider field

**[evidence]** The `Connection` model at `monitor/models.py` lines 9–42 has these fields: `name` (CharField), `description` (CharField), `_database_url` (TextField, db_column='database_url'), `created_at`, `updated_at`. There is no `provider` field. The class docstring says "Named PostgreSQL connection" — [evidence] `monitor/models.py` line 9.

**[evidence]** `get_database_url()` and `set_database_url()` are URL-agnostic; they only encrypt/decrypt the stored string without inspecting the scheme. This means the URL can hold a MySQL URL with no model change to those methods.

**Required change**: add a `provider` field, for example:
```python
class Provider(models.TextChoices):
    POSTGRESQL = 'postgresql', 'PostgreSQL'
    MYSQL = 'mysql', 'MySQL'

provider = models.CharField(
    max_length=20,
    choices=Provider.choices,
    default=Provider.POSTGRESQL,
)
```
This requires a new migration. The default value of `'postgresql'` ensures backward compatibility with the 4 existing migrations and all existing Connection rows. The `Connection` model's `Meta.ordering` and `__str__` do not reference PostgreSQL and require no change.

### 6. Forms: ConnectionForm

**[evidence]** `ConnectionForm` at `monitor/forms.py` lines 4–28:
- The `database_url` field placeholder is `'postgresql://user:password@host:5432/dbname'` — [evidence] `monitor/forms.py` line 8. This must be updated to show both URL formats when MySQL is selected.
- There is no `provider` field in `Meta.fields` (`['name', 'description']` at `monitor/forms.py` line 16) — it must be added when the model gains the field.
- The `save()` override calls `instance.set_database_url(...)` which is provider-agnostic.

### 7. Python MySQL driver: pymysql vs mysql-connector-python

**[inference — based on public documentation, not installed packages]**

| Criterion | PyMySQL | mysql-connector-python |
|-----------|---------|----------------------|
| Implementation | Pure Python | C extension + Python wrapper |
| Maintenance | Active (v1.1.1, 2023-10) | Active (Oracle, v9.x) |
| pip install | `pip install pymysql==1.1.1` | `pip install mysql-connector-python==9.1.0` |
| Import | `import pymysql` | `import mysql.connector` |
| `connect()` API | Keyword args: `host`, `user`, `password`, `database`, `port` | Keyword args: same shape |
| Native URL string | **No** — requires parsed kwargs | No |
| Exception base | `pymysql.Error`, `pymysql.OperationalError` | `mysql.connector.Error`, `mysql.connector.OperationalError` |
| Django ORM backend (if needed) | `django-pymysql` or `pymysql.install_as_MySQLdb()` | built-in `django.db.backends.mysql` |
| Deployment weight | Lighter (no C extension) | Heavier |

**[inference]** PyMySQL is preferred for this project:
- No C build dependency (consistent with the existing pure-Python choice of `psycopg2-binary`).
- Simpler API, smaller install size.
- The project uses raw driver connections in `services.py`, not Django ORM for monitored databases — the Django ORM backend compatibility is irrelevant.

**[evidence]** Neither `pymysql` nor `mysql-connector-python` is present in `requirements.txt` (inspected at commit 53d06be). Adding `pymysql==1.1.1` to `requirements.txt` and `pyproject.toml` is required.

### 8. MySQL URL format and URL parsing

**[inference]** MySQL connection URLs follow the format:
```
mysql://user:password@host:3306/dbname
```
PyMySQL does not accept a URL string directly; `pymysql.connect(url)` is not a valid call. The URL must be parsed:
```python
from urllib.parse import urlparse

def _parse_mysql_url(url: str) -> dict:
    p = urlparse(url)
    return {
        'host': p.hostname,
        'port': p.port or 3306,
        'user': p.username,
        'password': p.password,
        'database': p.path.lstrip('/'),
        'autocommit': True,
    }
```
Then: `pymysql.connect(**_parse_mysql_url(url))`.

`dj-database-url` (already in requirements at `requirements.txt` line 4) can parse MySQL URLs but returns a Django-ORM config dict, not raw pymysql kwargs — it is not directly usable here without transformation.

The existing `ConnectionForm.database_url` placeholder shows `postgresql://...`. For MySQL the user must supply `mysql://user:password@host:3306/dbname`. The `masked_url` property on `Connection` uses `urllib.parse.urlparse` — [evidence] `monitor/models.py` approx. line 36 — which is scheme-agnostic; MySQL URLs will mask correctly with no change.

### 9. Free MySQL hosting options

**[inference — based on public documentation as of 2026-10-28]**

| Provider | Free tier status | Notes | URL format |
|----------|-----------------|-------|-----------|
| PlanetScale | **Discontinued March 2024** — no new free-tier accounts | Existing grandfathered accounts still work; MySQL-compatible (Vitess-based) | `mysql://user:pass@host/db?sslmode=require` |
| Railway | Active free tier (~$5/month credit) | Full MySQL 8; plain TCP; no forced SSL | `mysql://root:pass@host:port/db` |
| db4free.net | Active, free, no time limit | MySQL 8.0; community testing service; low reliability SLA; max 200 MB | `mysql://user:pass@db4free.net:3306/dbname` |
| Aiven | 30-day trial only | Paid after trial; requires credit card | `mysql://user:pass@host:port/dbname?ssl-mode=REQUIRED` |
| TiDB Serverless | Active free tier (generous limits) | MySQL-compatible; requires SSL; port 4000 | `mysql://user:pass@host:4000/db` |

**[inference]** For development and CI testing, db4free.net (no expiry, no credit card) is the most accessible free option despite low reliability guarantees. Railway is preferable if the project already uses Railway for other services, or if reliability matters. PlanetScale is not available to new accounts and should not be listed as a recommended option.

## Code References

- `monitor/services.py:10` — `import psycopg2` — sole DB driver import
- `monitor/services.py:22–29` — `_open_conn(url)` — wraps `psycopg2.connect(url)`; called by schema introspection only
- `monitor/services.py:~50–57` — `get_schema_tables()` WHERE clause filtering `pg_catalog`
- `monitor/services.py:~70` — `TIMESTAMP_TYPES` set — PostgreSQL timestamp type names
- `monitor/services.py:~101–108` — `SQL_ALLOWED`, `SQL_FORBIDDEN` regex — provider-agnostic
- `monitor/services.py:~143` — `SET statement_timeout = 30000` — PostgreSQL-only
- `monitor/services.py:~178` — `EXTRACT(EPOCH FROM (NOW() - MAX({col}))) / 3600` — PostgreSQL-only
- `monitor/services.py:~187` — `except psycopg2.Error` in `_check_volume_freshness`
- `monitor/services.py:~202` — `psycopg2.connect(url)` direct call in `run_single_rule` (bypasses `_open_conn`)
- `monitor/services.py:~246` — `psycopg2.connect(url)` direct call in `run_all_checks` (bypasses `_open_conn`)
- `monitor/models.py:9` — `Connection` class docstring: "Named PostgreSQL connection" — assumption
- `monitor/models.py:14–21` — `Connection` model fields — no `provider` field
- `monitor/models.py:30–41` — `get_database_url()` / `set_database_url()` — provider-agnostic
- `monitor/forms.py:8` — `database_url` placeholder text — PostgreSQL-only
- `monitor/forms.py:16` — `Meta.fields` for `ConnectionForm` — no `provider`
- `requirements.txt:7` — `psycopg2-binary==2.9.13` — only PostgreSQL driver present
- `monitor/tests.py:18` — `@patch('monitor.services.psycopg2.connect')` — patch target will need parallel MySQL patch

## Architecture Insights

**Seam quality**: `_open_conn()` exists as a named seam but is only used by schema introspection functions; the two check-execution paths (`run_single_rule`, `run_all_checks`) call `psycopg2.connect()` directly. A prerequisite cleanup — routing all four callsites through `_open_conn` — is needed before adding provider dispatch. This is a 2–3 line change per callsite but must precede any MySQL branching.

**Minimal change surface**: All PostgreSQL-specific SQL is localized to exactly 2 functions (`_check_volume_freshness`, `_check_custom_sql`) and exactly 1 schema query (`get_schema_tables` WHERE clause + `TIMESTAMP_TYPES`). The falsy-value interpreter, the SQL safety regex, the result storage, and all model/view code are provider-agnostic.

**Exception handling pattern**: The entire service layer catches `psycopg2.Error` (the psycopg2 base exception class) at the leaf level. Adding MySQL requires either (a) catching both `psycopg2.Error` and `pymysql.Error` in parallel, or (b) wrapping both in `MonitoredDbError` at the `_open_conn` level and catching only `MonitoredDbError` in the leaf handlers. Option (b) is architecturally cleaner and avoids spreading driver imports.

**Migration risk**: Adding `provider` with `default='postgresql'` to `Connection` is a backwards-safe additive migration. The existing 4 migrations span 9 days and include one corrective migration (0002 field name fix — [evidence] `context/map/repo-map.md` "Pułapka" section). The additive pattern is safe here.

**Test pattern**: All service tests mock `monitor.services.psycopg2.connect`. MySQL tests would mock `monitor.services.pymysql.connect` (or the unified `_open_conn` if refactored). The `make_connection()` helper uses `postgresql://` URLs; a parallel `make_mysql_connection()` helper using `mysql://` URLs will be needed.

## Historical Context (from prior changes)

No prior `mysql-support` change docs or archived research found. The `change.md` for this change (`context/changes/mysql-support/change.md`) was created 2026-10-28 with status `new`. No other change folder references MySQL.

The env-based connection refactor (commit `a9bb540`, dispatcher fix `719289c`) is relevant context: it removed `MONITORED_DATABASE_URL` as a fallback and made `Connection.get_database_url()` the sole URL source. This means there is no env-based MySQL URL path to add; all MySQL connections will flow through the same `Connection` model + `get_database_url()` path as PostgreSQL — [evidence] `context/map/repo-map.md` "Pułapka" section.

## Related Research

None in this repository.

## Open Questions

1. **SSL/TLS**: MySQL cloud providers (TiDB Serverless, Aiven) require SSL. PyMySQL supports `ssl_ca`, `ssl_cert`, `ssl_key` kwargs. The current URL format does not carry SSL parameters. A decision is needed: support `?ssl=true` query param parsing, or add a separate SSL toggle field on `Connection`? This is a product decision, not resolvable from code alone.

2. **MariaDB compatibility**: MariaDB is MySQL-compatible and shares the `mysql://` scheme. `TIMESTAMPDIFF` and `TIME_TO_SEC(TIMEDIFF(...))` work in both MySQL and MariaDB. No additional branching should be needed, but this has not been verified against a live MariaDB instance. [unknown]

3. **Statement timeout in MySQL**: `SET SESSION max_execution_time = 30000` requires MySQL 5.7.8+. MySQL 5.6 does not support it. If supporting older MySQL versions is a requirement, the timeout statement must be omitted or guarded by version detection. [unknown — depends on minimum MySQL version requirement]

4. **PlanetScale (Vitess) compatibility**: PlanetScale/Vitess does not support `information_schema.tables` in the standard way; schema introspection may fail on PlanetScale connections even if basic queries work. Since PlanetScale's free tier is discontinued for new accounts, this is lower priority. [unknown]
