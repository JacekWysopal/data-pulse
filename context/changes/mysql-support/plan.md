# MySQL Support Implementation Plan

## Overview

Add MySQL/MariaDB as a second monitored database provider alongside PostgreSQL.
Users will be able to create a Connection with `provider = mysql`, supply a
`mysql+pymysql://` URL, and run the same volume / freshness / custom-SQL rules
against MySQL tables as they currently run against PostgreSQL.

## Current State Analysis

DataPulse supports only PostgreSQL today. The service layer imports `psycopg2` as the
sole driver and contains 8 PostgreSQL-specific callsites. The `Connection` model has no
`provider` field. The UI shows a MySQL card marked "Soon".

### Key Discoveries

- `monitor/services.py:10` — `import psycopg2` is the only driver import; all connection
  opens go through it.
- `monitor/services.py:22–29` — `_open_conn(url)` is a named seam, but it is **only**
  called by `get_schema_tables` and `get_schema_columns`; `run_single_rule` (line ~202)
  and `run_all_checks` (line ~246) call `psycopg2.connect(url)` directly — a
  pre-existing inconsistency that must be fixed before provider dispatch can work.
- `monitor/services.py:~50` — `get_schema_tables` WHERE clause filters `pg_catalog`
  which does not exist in MySQL; MySQL system schemas are `information_schema`,
  `performance_schema`, `mysql`, `sys`.
- `monitor/services.py:~70` — `TIMESTAMP_TYPES` set is PostgreSQL-only; MySQL uses
  `datetime`, `timestamp`, `date`, `time`.
- `monitor/services.py:~143` — `SET statement_timeout = 30000` is PostgreSQL-only;
  MySQL equivalent is `SET SESSION max_execution_time = 30000`.
- `monitor/services.py:~178` — `EXTRACT(EPOCH FROM (NOW() - MAX(col))) / 3600` is
  PostgreSQL-only; MySQL equivalent is `TIMESTAMPDIFF(SECOND, MAX(col), NOW()) / 3600`.
- `monitor/services.py:~187,~202,~246` — three `except psycopg2.Error` blocks and two
  direct `psycopg2.connect()` callsites that must become provider-aware.
- `monitor/models.py:9` — `Connection` class docstring says "Named PostgreSQL connection";
  no `provider` field exists.
- `monitor/forms.py:8` — `database_url` placeholder is `postgresql://...`; needs to
  reflect both URL schemes.
- `requirements.txt` / `pyproject.toml` — `pymysql` not yet listed.
- `monitor/tests.py:18` — `@patch('monitor.services.psycopg2.connect')` is the mock
  target for all service tests; MySQL tests need `monitor.services.pymysql.connect`.

## Desired End State

When this plan is complete:
- A user can create a Connection with `provider = mysql` and a
  `mysql+pymysql://user:pass@host:3306/db` URL.
- Volume, freshness, and custom-SQL rules run against that MySQL connection and return
  correct OK / FAIL / ERROR results.
- Schema introspection (table list, column list) works for MySQL connections.
- The MySQL card in the provider grid is "Available" and links to the create connection
  form.
- All existing PostgreSQL behaviour is unchanged; existing Connection rows default to
  `provider = postgresql`.

### Verification

```
make test          # full suite; no new failures
python manage.py migrate  # clean apply
# Manual: add mysql+pymysql://... connection → rule → Run check → result shown
```

## What We're NOT Doing

- No SSL/TLS parameter support on the URL (no `?ssl=true` query param, no SSL field on
  Connection). SSL can be added in a follow-on change once the base provider is live.
- No MariaDB-specific branching. MariaDB shares MySQL SQL syntax; if it works on MySQL
  it works on MariaDB without extra code.
- No PlanetScale support. PlanetScale's free tier was discontinued March 2024; its
  Vitess layer breaks `information_schema` introspection. Not a target for this change.
- No migration of existing rules. All existing rules continue to use `provider =
  postgresql` (the model default).
- No `mysql-connector-python`. PyMySQL (pure Python, no C extension) is the chosen
  driver and is consistent with using `psycopg2-binary` (no system C lib requirement on
  Render).

## Implementation Approach

Provider dispatch is centralised in `_open_conn`. The function gains a `provider`
parameter and dispatches to `psycopg2.connect(url)` (PostgreSQL) or
`pymysql.connect(**_parse_mysql_url(url))` (MySQL). All four callsites that currently
open a connection are routed through `_open_conn`. SQL-level differences (timeout
statement, EXTRACT vs TIMESTAMPDIFF, system schema filter, TIMESTAMP_TYPES) are handled
by per-provider branches at the exact callsites where they occur.

## Critical Implementation Details

`_open_conn` must accept a `provider` string — not a `Connection` object — so it stays
a thin seam and doesn't import the ORM. Callers resolve `connection.provider` before
calling `_open_conn`.

PyMySQL does not accept a URL string. The `_parse_mysql_url(url: str) -> dict` helper
must parse a `mysql+pymysql://` (or bare `mysql://`) URL into keyword arguments before
calling `pymysql.connect()`. Using `urllib.parse.urlparse` is sufficient.

`run_all_checks` caches open connections by URL string. The cache must also carry the
provider so that `_check_rule` can use it for SQL branching. The cache value tuple
changes from `(conn, error_msg)` to `(conn, error_msg, provider)`.

---

## Phase 1: Connection.provider Field + Migration

### Overview

Add a `provider` CharField with choices `postgresql` / `mysql` and default
`postgresql` to the `Connection` model, create the migration, and expose the field in
`ConnectionForm` and the connection create/edit templates. This phase has zero runtime
impact on existing connections.

### Changes Required

#### 1. `Connection` model — add `provider` field

**File**: `monitor/models.py`

**Intent**: Introduce a `Provider` inner class with TextChoices and a `provider`
CharField that records which driver the connection uses. Update the class docstring.

**Contract**: Field name is `provider`, max_length 20, choices from `Provider.choices`,
default `'postgresql'`. The inner class must be named `Provider` to follow the pattern
of `Rule.RuleType`.

#### 2. Django migration — `0005_connection_provider`

**File**: `monitor/migrations/0005_connection_provider.py`

**Intent**: Generated migration that adds the `provider` field with the
`postgresql` default, leaving all existing rows unaffected.

**Contract**: `python manage.py makemigrations monitor --name connection_provider`
produces this file; review before committing that it is `AddField` only with
`default='postgresql'`. The generated filename will be `0005_connection_provider.py`
(migrations 0001–0004 exist; next number is 0005).

#### 3. `ConnectionForm` — add `provider` field

**File**: `monitor/forms.py`

**Intent**: Add `provider` to `Meta.fields` and render it as a select widget so users
can choose the provider when creating or editing a connection. Update `database_url`
help text to mention both URL formats.

**Contract**: `Meta.fields` becomes `['name', 'description', 'provider']`. Widget:
`forms.Select(attrs={'class': 'form-select'})`. The `database_url` help text changes to
`'PostgreSQL: postgresql://user:pass@host:5432/db · MySQL: mysql+pymysql://user:pass@host:3306/db'`.

#### 4. Connection create/edit template — provider selector

**File**: `templates/monitor/connection_form.html` (or whichever template renders
`ConnectionForm`)

**Intent**: Show the provider selector above the URL field and add a JS one-liner that
updates the URL placeholder when the user switches provider.

**Contract**: The `provider` field renders before `database_url`. A `<script>` block
reads `#id_provider` `change` event and sets `#id_database_url` placeholder to the
matching example URL. No external JS library; plain DOM events only.

### Success Criteria

#### Automated Verification

- Migration applies cleanly: `python manage.py migrate --run-syncdb` exits 0.
- Existing model tests pass: `python manage.py test monitor.tests.ConnectionModelTest`.
- `make test` (full suite) passes with no new failures.

#### Manual Verification

- Navigate to Add Connection; a Provider selector is visible above the URL field.
- Switching provider to MySQL updates the URL placeholder to `mysql+pymysql://...`.
- Saving a connection with `provider = postgresql` stores the value correctly (check
  Django admin or shell: `Connection.objects.last().provider`).

**Implementation Note**: Pause after automated verification for manual confirmation
before proceeding to Phase 2.

---

## Phase 2: PyMySQL Dependency + services.py MySQL Branch

### Overview

Add `pymysql` to the project dependencies, refactor `_open_conn` to dispatch by
provider, route all four raw `psycopg2.connect()` callsites through `_open_conn`, and
add a `_parse_mysql_url` helper. This phase is the core plumbing change.

### Changes Required

#### 1. Add `pymysql` to `pyproject.toml` and `requirements.txt`

**File**: `pyproject.toml`, `requirements.txt`

**Intent**: Register `pymysql==1.1.1` as a project dependency so it is installed on
Render and in local dev environments.

**Contract**: In `pyproject.toml` `dependencies`, add `"pymysql==1.1.1"`. In
`requirements.txt`, add the pinned line `pymysql==1.1.1` (uv recompile or manual add
both acceptable; pin the exact version).

#### 2. `_parse_mysql_url` helper

**File**: `monitor/services.py`

**Intent**: Parse a `mysql://` or `mysql+pymysql://` URL string into the keyword
arguments that `pymysql.connect()` accepts.

**Contract**:

```python
from urllib.parse import urlparse

def _parse_mysql_url(url: str) -> dict:
    """Parse mysql[+pymysql]://user:pass@host:port/db into pymysql.connect() kwargs."""
    p = urlparse(url)
    return {
        'host': p.hostname,
        'port': p.port or 3306,
        'user': p.username,
        'password': p.password or '',
        'database': p.path.lstrip('/'),
        'autocommit': True,
    }
```

The `autocommit=True` kwarg avoids transaction state leaking between rule evaluations on
a cached connection.

#### 3. Refactor `_open_conn` to accept `provider` and dispatch

**File**: `monitor/services.py`

**Intent**: Make `_open_conn` the single connection-open seam for both drivers.
PostgreSQL path unchanged; MySQL path uses `_parse_mysql_url` + `pymysql.connect()`.

**Contract**: Signature changes to `_open_conn(url: str, provider: str = 'postgresql')`.
`MonitoredDbError` is raised on both `psycopg2.OperationalError` and
`pymysql.OperationalError` so callers remain driver-agnostic.

#### 4. Route `run_single_rule` through `_open_conn`

**File**: `monitor/services.py`

**Intent**: Replace the direct `psycopg2.connect(url)` call in `run_single_rule` with
`_open_conn(url, rule.connection.provider)` so MySQL connections are opened correctly
and error handling is unified.

**Contract**: `run_single_rule` resolves `provider = rule.connection.provider` before
calling `_open_conn`. The `except psycopg2.OperationalError` block is removed; error
handling is now inside `_open_conn` (which raises `MonitoredDbError`). The outer
`except Exception` block remains as a safety net.

#### 5. Route `run_all_checks` through `_open_conn`; extend `conn_cache`

**File**: `monitor/services.py`

**Intent**: Replace direct `psycopg2.connect(url)` in `run_all_checks` with
`_open_conn(url, provider)` and update the cache tuple to carry provider.

**Contract**: `conn_cache` value type changes from `(conn, error_msg)` to
`(conn, error_msg, provider)`. Cache key remains `url` (URLs for different providers
will differ in scheme). When checking `if url not in conn_cache`, resolve
`provider = rule.connection.provider` first. Unpack `conn, conn_error, provider =
conn_cache[url]` before calling `_check_rule`.

**Close-loop update (must be done in the same commit — do not skip)**: The close loop
at `monitor/services.py:320` currently reads `for conn, _ in conn_cache.values():`
and unpacks a 2-tuple. After this step the value is a 3-tuple; the loop must become:

```python
for conn, conn_error, provider in conn_cache.values():
    if conn:
        try:
            conn.close()
        except Exception:
            pass
```

Omitting this update causes `ValueError: too many values to unpack` on every
`run_all_checks` call, raised after rules complete but before `CheckRun.finished_at`
is written.

#### 6. Pass `provider` through to `_check_rule`

**File**: `monitor/services.py`

**Intent**: `_check_rule` needs to know the provider so it can pass it to
`_check_custom_sql` and `_check_volume_freshness` for SQL branching in later phases.

**Contract**: `_check_rule(conn, rule, provider)` gains a third parameter. Both callers
(`run_single_rule`, `run_all_checks`) pass `provider`.

### Success Criteria

#### Automated Verification

- `pip install pymysql==1.1.1` (or `uv sync`) succeeds: `python -c "import pymysql"` exits 0.
- `python manage.py test monitor` passes with no new failures.
- `_open_conn` unit tests: mock both `psycopg2.connect` and `pymysql.connect`; assert
  that calling `_open_conn('postgresql://...', 'postgresql')` invokes psycopg2 and
  calling `_open_conn('mysql://...', 'mysql')` invokes pymysql with parsed kwargs.

#### Manual Verification

- No regression: run an existing PostgreSQL rule via the UI; result is unchanged.

**Implementation Note**: Pause after automated verification for manual confirmation.

---

## Phase 3: Schema Introspection for MySQL

### Overview

Update `get_schema_tables` and `get_schema_columns` so that MySQL connections return
correct table lists and column metadata. The `information_schema` tables are standard
SQL and work in both databases; only the system-schema filter and `TIMESTAMP_TYPES` set
are provider-specific.

### Changes Required

#### 1. `get_schema_tables` — provider-aware system-schema filter

**File**: `monitor/services.py`

**Intent**: Exclude MySQL-specific system schemas (`performance_schema`, `mysql`, `sys`)
instead of `pg_catalog` when the provider is `mysql`.

**Contract**: `get_schema_tables(conn_id)` resolves `provider = conn_obj.provider`
after fetching the `Connection`. The WHERE clause becomes:

- PostgreSQL (unchanged): `table_schema NOT IN ('pg_catalog', 'information_schema')`
- MySQL: `table_schema NOT IN ('information_schema', 'performance_schema', 'mysql', 'sys')`

Pass `provider` to the inner `_open_conn` call (already updated in Phase 2).

#### 2. `get_schema_columns` — extend `TIMESTAMP_TYPES` for MySQL

**File**: `monitor/services.py`

**Intent**: Recognise MySQL temporal column types (`datetime`, `timestamp`, `date`,
`time`) as timestamp-like, in addition to the existing PostgreSQL types.

**Contract**: `TIMESTAMP_TYPES` becomes:

```python
TIMESTAMP_TYPES = {
    # PostgreSQL
    'timestamp', 'timestamp without time zone', 'timestamp with time zone',
    'timestamptz', 'date', 'time', 'timetz',
    # MySQL
    'datetime',
}
```

MySQL's `timestamp` and `date`/`time` are already in the set; only `datetime` is new.

#### 3. Exception handling in `get_schema_tables` and `get_schema_columns`

**File**: `monitor/services.py`

**Intent**: Replace `except psycopg2.Error` with `except (psycopg2.Error,
pymysql.Error)` so MySQL driver errors are caught and returned as `{'error': ...}`
rather than propagating as unhandled exceptions.

**Contract**: Both functions catch `(psycopg2.Error, pymysql.Error)`.

### Success Criteria

#### Automated Verification

- Unit tests for `get_schema_tables` with a mocked MySQL connection: assert system
  schemas are excluded and table rows are returned correctly.
- Unit tests for `get_schema_columns` with a mocked MySQL connection: assert `datetime`
  columns have `is_timestamp = True`.
- `python manage.py test monitor` passes.

#### Manual Verification

- Add a MySQL connection (db4free.net or Railway) → open Add Rule → schema introspection
  dropdown shows tables from the MySQL database (no system tables).
- A column with type `datetime` is marked as a timestamp column in the column picker.

**Implementation Note**: Pause after automated verification for manual confirmation.

---

## Phase 4: SQL Execution — MySQL Branches

### Overview

Update `_check_custom_sql` and `_check_volume_freshness` to handle the two
PostgreSQL-specific SQL expressions: the query timeout statement and the epoch-based
freshness calculation. Both functions already receive `conn` and `rule`; this phase
adds `provider` as a third parameter.

### Changes Required

#### 1. `_check_custom_sql` — provider-aware statement timeout

**File**: `monitor/services.py`

**Intent**: Use `SET statement_timeout = 30000` for PostgreSQL and
`SET SESSION max_execution_time = 30000` for MySQL before executing custom SQL.

**Contract**: `_check_custom_sql(conn, rule, provider)` gains a `provider` parameter.
The timeout line becomes:

```python
timeout_sql = (
    'SET statement_timeout = 30000'
    if provider == 'postgresql'
    else 'SET SESSION max_execution_time = 30000'
)
cur.execute(timeout_sql)
```

#### 2. `_check_volume_freshness` — provider-aware freshness SQL

**File**: `monitor/services.py`

**Intent**: Use `EXTRACT(EPOCH FROM ...)` for PostgreSQL and `TIMESTAMPDIFF(SECOND,
MAX(col), NOW())` for MySQL in the freshness check.

**Contract**: `_check_volume_freshness(conn, rule, provider)` gains a `provider`
parameter. The freshness expression becomes:

```python
if provider == 'postgresql':
    freshness_sql = (
        f'SELECT EXTRACT(EPOCH FROM (NOW() - MAX({col}))) / 3600 FROM {table}'
    )
else:
    freshness_sql = (
        f'SELECT TIMESTAMPDIFF(SECOND, MAX({col}), NOW()) / 3600 FROM {table}'
    )
cur.execute(freshness_sql)  # noqa: S608
```

#### 3. Exception handling in `_check_custom_sql` and `_check_volume_freshness`

**File**: `monitor/services.py`

**Intent**: Catch both driver error types so MySQL execution errors surface as
`RuleResult.Status.ERROR` rather than unhandled exceptions.

**Contract**: `except psycopg2.Error` becomes `except (psycopg2.Error, pymysql.Error)`
in both functions.

#### 4. Update `_check_rule` to forward `provider`

**File**: `monitor/services.py`

**Intent**: `_check_rule` already receives `provider` from Phase 2; forward it to both
check functions.

**Contract**: Calls become `_check_custom_sql(conn, rule, provider)` and
`_check_volume_freshness(conn, rule, provider)`.

### Success Criteria

#### Automated Verification

- Unit test: `_check_custom_sql` with a mock MySQL conn executes
  `SET SESSION max_execution_time = 30000` (not the PostgreSQL variant).
- Unit test: `_check_volume_freshness` with a mock MySQL conn executes
  `TIMESTAMPDIFF(SECOND, ...)` in the freshness query.
- Unit test: `_check_volume_freshness` with a mock PostgreSQL conn still executes
  `EXTRACT(EPOCH FROM ...)`.
- `python manage.py test monitor` passes (all existing tests green).

#### Manual Verification

- Run a volume rule against a MySQL connection; result is OK/FAIL (not ERROR).
- Run a freshness rule against a MySQL connection; `last_record_age_hours` is populated.
- Run a custom-SQL rule against a MySQL connection; result reflects the SQL return value.

**Implementation Note**: Pause after automated verification for manual confirmation.

---

## Phase 5: UI — MySQL Card Active + URL Placeholder

### Overview

Flip the MySQL card in the provider grid from "Soon" (disabled) to "Available"
(clickable), linking to the create-connection form. Confirm the JS placeholder update
from Phase 1 works end-to-end with the new provider field.

### Changes Required

#### 1. `connection_list.html` — MySQL card from "Soon" to "Available"

**File**: `templates/monitor/connection_list.html`

**Intent**: Make the MySQL provider card clickable and styled as "available" to match
the PostgreSQL card, now that the backend supports MySQL connections.

**Contract**: Replace the `<div class="provider-card disabled">` block for MySQL with
`<a href="{% url 'monitor:connection_create' %}?provider=mysql" class="provider-card available" style="text-decoration:none;color:inherit">`.
Badge changes from `<span class="provider-badge badge-soon">Soon</span>` to
`<span class="provider-badge badge-available">Available</span>`.

The connection create view or form `__init__` should pre-select `provider = mysql` when
`?provider=mysql` is present in the query string, so the user lands with MySQL
pre-selected. This is a small view tweak: read `request.GET.get('provider')` and pass
as initial to the form.

#### 2. No-connection empty-state text update

**File**: `templates/monitor/connection_list.html`

**Intent**: Update the empty-state hint text to mention both PostgreSQL and MySQL now
that both are available.

**Contract**: Change `No connections yet — click <strong>PostgreSQL</strong> above to
add one.` to `No connections yet — click <strong>PostgreSQL</strong> or
<strong>MySQL</strong> above to add one.`

### Success Criteria

#### Automated Verification

- `python manage.py test monitor` passes.
- `?provider=mysql` pre-selection view test: `r = self.client.get(reverse('monitor:connection_create') + '?provider=mysql'); self.assertEqual(r.context['form'].initial.get('provider'), 'mysql')` — covers the `request.GET.get('provider')` view change added in step 1.

#### Manual Verification

- The MySQL card is clickable and styled "Available" (not greyed out).
- Clicking the MySQL card opens the connection create form with MySQL pre-selected.
- The URL placeholder shows `mysql+pymysql://user:pass@host:3306/db` when MySQL is
  selected.
- The PostgreSQL card behaviour is unchanged.

**Implementation Note**: Pause after automated verification for manual confirmation.

---

## Phase 6: Tests — Mock MySQL Connection Tests

### Overview

Add unit tests covering the MySQL code paths: `_open_conn` dispatch, `_check_custom_sql`
timeout branch, `_check_volume_freshness` freshness branch, `get_schema_tables` filter,
and `get_schema_columns` type extension. No live MySQL connection is required; all tests
use `unittest.mock`.

### Changes Required

#### 1. Test helpers

**File**: `monitor/tests.py`

**Intent**: Add a `make_mysql_connection` helper alongside `make_connection` so MySQL
test fixtures are easy to create.

**Contract**:

```python
def make_mysql_connection(name='test_mysql', url='mysql+pymysql://user:pass@host/db'):
    conn = Connection(name=name, provider='mysql')
    conn.set_database_url(url)
    conn.save()
    return conn
```

#### 2. `_open_conn` dispatch tests

**File**: `monitor/tests.py`

**Intent**: Assert that `_open_conn` calls `psycopg2.connect` for PostgreSQL and
`pymysql.connect` (with parsed kwargs) for MySQL; assert that `MonitoredDbError` is
raised on connection failure for both.

**Contract**: Patch `monitor.services.psycopg2.connect` and
`monitor.services.pymysql.connect` separately. Test class: `OpenConnDispatchTest`.

#### 3. `_check_custom_sql` timeout-branch tests

**File**: `monitor/tests.py`

**Intent**: Assert that the correct timeout SQL is sent for each provider.

**Contract**: Use a mock cursor. Call `_check_custom_sql(mock_conn, rule, 'mysql')` and
assert `mock_cursor.execute.call_args_list[0]` contains `SET SESSION max_execution_time`.
Repeat for `'postgresql'` → `SET statement_timeout`. Test class:
`CustomSqlMySQLTest`.

#### 4. `_check_volume_freshness` freshness-branch tests

**File**: `monitor/tests.py`

**Intent**: Assert that `TIMESTAMPDIFF` is used for MySQL and `EXTRACT(EPOCH FROM` is
used for PostgreSQL in the freshness query.

**Contract**: Mock cursor; call `_check_volume_freshness(mock_conn, rule, 'mysql')` and
assert the execute call contains `TIMESTAMPDIFF`. Repeat for PostgreSQL. Test class:
`VolumeFreshnessMySQLTest`.

#### 5. `get_schema_tables` system-schema filter tests

**File**: `monitor/tests.py`

**Intent**: Assert that `pg_catalog` is excluded for PostgreSQL connections and
`performance_schema` / `mysql` / `sys` are excluded for MySQL connections.

**Contract**: Patch `_open_conn` to return a mock connection. Pass a MySQL `Connection`
object. Assert the SQL string passed to `cur.execute` does not contain `pg_catalog` and
does contain `performance_schema`. Test class: `GetSchemaTablesMySQLTest`.

#### 6. `get_schema_columns` `is_timestamp` tests

**File**: `monitor/tests.py`

**Intent**: Assert that columns with type `datetime` (MySQL) have `is_timestamp = True`.

**Contract**: Patch `_open_conn` to return a mock cursor yielding `[('created_at',
'datetime')]`. Assert the returned column has `is_timestamp = True`. Test class:
`GetSchemaColumnsMySQLTest`.

### Success Criteria

#### Automated Verification

- `python manage.py test monitor` passes with all new test classes green.
- No existing test broken.

#### Manual Verification

- Review test names and assertions in the new test classes for coverage completeness.

---

## Testing Strategy

### Unit Tests

- `_open_conn` dispatch (psycopg2 vs pymysql, error wrapping).
- `_check_custom_sql` timeout SQL per provider.
- `_check_volume_freshness` freshness SQL per provider.
- `get_schema_tables` WHERE clause per provider.
- `get_schema_columns` `is_timestamp` for `datetime` type.
- `Connection.provider` field default, choices, save/load round-trip.

### Integration Tests

Not applicable in this change (no live MySQL instance in CI). The mock suite covers
all branching paths.

### Manual Testing Steps

1. Create a MySQL connection using db4free.net or Railway (free tier) with a valid
   `mysql+pymysql://` URL; verify "Connected" indicator (if present) or run a rule.
2. Add a Volume rule on a MySQL table with known row count; verify OK/FAIL result.
3. Add a Freshness rule on a MySQL table with a `datetime` column; verify
   `last_record_age_hours` is populated.
4. Add a Custom SQL rule (`SELECT 1`); verify OK result.
5. Verify schema introspection dropdown shows MySQL tables (no system tables).
6. Verify an existing PostgreSQL connection + rule still works unchanged.

## Performance Considerations

No new queries to the DataPulse application database. The MySQL driver (PyMySQL) is
pure Python; connection latency is comparable to psycopg2-binary for the volumes
DataPulse handles (per-rule polling, not bulk throughput).

## Migration Notes

Migration `0005_connection_provider` is additive (`AddField` with
`default='postgresql'`). All existing `Connection` rows receive `provider = 'postgresql'`
automatically. No data transformation required.

## References

- Research: `context/changes/mysql-support/research.md`
- PyMySQL docs: https://pymysql.readthedocs.io/en/latest/
- `monitor/services.py` — full source read at plan time
- `monitor/models.py` — full source read at plan time
- `monitor/forms.py` — full source read at plan time
- `templates/monitor/connection_list.html` — provider grid inspected at plan time

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Connection.provider Field + Migration

#### Automated

- [ ] 1.1 Migration applies cleanly
- [ ] 1.2 ConnectionModelTest passes
- [ ] 1.3 Full test suite passes (no new failures)

#### Manual

- [ ] 1.4 Provider selector visible on Add Connection page
- [ ] 1.5 Switching to MySQL updates URL placeholder
- [ ] 1.6 Saved connection stores provider value correctly

### Phase 2: PyMySQL Dependency + services.py MySQL Branch

#### Automated

- [ ] 2.1 pymysql importable after install
- [ ] 2.2 _open_conn dispatch unit tests pass (psycopg2 vs pymysql)
- [ ] 2.3 Full test suite passes (no new failures)

#### Manual

- [ ] 2.4 Existing PostgreSQL rule runs without regression

### Phase 3: Schema Introspection for MySQL

#### Automated

- [ ] 3.1 get_schema_tables MySQL mock test passes
- [ ] 3.2 get_schema_columns datetime is_timestamp test passes
- [ ] 3.3 Full test suite passes

#### Manual

- [ ] 3.4 MySQL connection schema introspection shows tables (no system tables)
- [ ] 3.5 datetime column marked as timestamp in column picker

### Phase 4: SQL Execution — MySQL Branches

#### Automated

- [ ] 4.1 _check_custom_sql MySQL timeout branch test passes
- [ ] 4.2 _check_volume_freshness MySQL freshness branch test passes
- [ ] 4.3 _check_volume_freshness PostgreSQL freshness branch unchanged
- [ ] 4.4 Full test suite passes

#### Manual

- [ ] 4.5 Volume rule on MySQL returns OK/FAIL
- [ ] 4.6 Freshness rule on MySQL populates last_record_age_hours
- [ ] 4.7 Custom SQL rule on MySQL returns correct result

### Phase 5: UI — MySQL Card Active + URL Placeholder

#### Automated

- [ ] 5.1 Full test suite passes
- [ ] 5.2 ?provider=mysql pre-selection view test passes

#### Manual

- [ ] 5.3 MySQL card is clickable and styled Available
- [ ] 5.4 Clicking MySQL card pre-selects MySQL provider in form
- [ ] 5.5 URL placeholder shows mysql+pymysql:// when MySQL selected
- [ ] 5.6 PostgreSQL card behaviour unchanged

### Phase 6: Tests — Mock MySQL Connection Tests

#### Automated

- [ ] 6.1 All new test classes pass (OpenConnDispatchTest, CustomSqlMySQLTest, VolumeFreshnessMySQLTest, GetSchemaTablesMySQLTest, GetSchemaColumnsMySQLTest)
- [ ] 6.2 No existing tests broken
- [ ] 6.3 make test / python manage.py test monitor exits 0

#### Manual

- [ ] 6.4 New test class coverage reviewed and approved
