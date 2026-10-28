---
date: 2026-10-28T20:43:46+01:00
researcher: worker-subagent
git_commit: c2ad8dfe7dc6ab19e456ba6dab557d0808a806ad
branch: dev
repository: data-pulse
topic: "Row sampling on failure — what is needed to implement sample_rows in RuleResult"
tags: [research, codebase, monitor, models, services, row-sampling, security]
status: complete
last_updated: 2026-10-28
last_updated_by: worker-subagent
---

# Research: Row sampling on failure — what is needed to implement sample_rows in RuleResult

**Date**: 2026-10-28T20:43:46+01:00  
**Researcher**: worker-subagent  
**Git Commit**: c2ad8dfe7dc6ab19e456ba6dab557d0808a806ad  
**Branch**: dev  
**Repository**: data-pulse

## Research Question

What exactly is needed to implement row-level sampling on failure?
Specifically: the RuleResult model gap, where sampling queries must be injected in services.py, what the sampling queries should look like for each rule type, whether Django 6.1.2 provides a native JSONField, and whether the table/column name inputs create a SQL injection risk.

## Summary

`RuleResult` has no `sample_rows` field today (`monitor/models.py:131–153`). Django 6.1.2 ships `django.db.models.JSONField` natively for all backends including SQLite; no third-party package is needed. The two check functions `_check_volume_freshness` and `_check_custom_sql` in `monitor/services.py` already use identifier quoting (`q = '`' if provider == 'mysql' else '"'`) that covers schema/table names; the timestamp column also needs the same quoting. Custom SQL is validated by `SQL_ALLOWED` / `SQL_FORBIDDEN` regex before execution. No sampling queries run today; they must be added after each FAIL branch inside those two functions. The rule_history view renders results from `results[:20]` without a `sample_rows` field reference; the template must be extended to show sample rows for FAIL results.

## Detailed Findings

### 1. RuleResult model — missing `sample_rows` field

`monitor/models.py:131–153` defines `RuleResult`. The current fields are:

- `run` (FK to CheckRun)
- `rule` (FK to Rule)
- `checked_at` (DateTimeField)
- `status` (CharField with OK/FAIL/ERROR choices)
- `row_count` (PositiveIntegerField, nullable)
- `last_record_age_hours` (FloatField, nullable)
- `error_message` (TextField, blank)

There is no `sample_rows` field. A new `JSONField(null=True, blank=True)` named `sample_rows` must be added to this model and a migration created.

### 2. Django JSONField availability in Django 6.1.2

`requirements.txt:8` records `django==6.1.2`. `django.db.models.JSONField` was added in Django 3.1 for all backends (PostgreSQL, MySQL, SQLite). In Django 6.1.2 (confirmed via requirements.txt) `JSONField` is available without any additional package from `django.db.models`. No third-party `jsonfield` library is needed.

### 3. Sampling query insertion points in `_check_volume_freshness`

`monitor/services.py:130–175` contains `_check_volume_freshness`. The function:

1. Builds an identifier-quoted `table` at line ~148: `f'{q}{rule.schema_name}{q}.{q}{rule.table_name}{q}'`
2. Executes a `COUNT(*)` if `rule.min_row_count is not None` (lines ~150–155)
3. Sets `result['status'] = RuleResult.Status.FAIL` if count is below the threshold (line ~155)
4. Executes a freshness query if `rule.timestamp_column and rule.max_age_hours is not None` (lines ~157–168)
5. Sets `result['status'] = RuleResult.Status.FAIL` if age exceeds threshold (lines ~170–173)

The function currently returns a dict with keys `row_count`, `last_record_age_hours`, `status`, `error_message`. There is no `sample_rows` key. A `sample_rows` key (defaulting to `None`) must be added to the result dict, and populated with up to 5 rows when the final `result['status']` is `FAIL`.

For this inspected path, the sampling queries are:

- **Volume FAIL** (min_row_count condition triggers): `SELECT * FROM {table} LIMIT 5` — returns the 5 most recent rows as a best-effort sample.
- **Freshness FAIL** (max_age_hours condition triggers): `SELECT * FROM {table} ORDER BY {col} DESC LIMIT 5` — returns the 5 rows with the largest timestamp value.

Both sampling queries must use the same identifier-quoted `table` and `col` variables already computed in the function. The cursor result should be serialized to a list of dicts using `cursor.description` for column names. Sampling errors must be caught and silently ignored (set `sample_rows` to `None`) so a sampling failure does not convert a FAIL into ERROR.

### 4. Sampling query insertion points in `_check_custom_sql`

`monitor/services.py:94–128` contains `_check_custom_sql`. The function:

1. Validates `rule.custom_sql` via `SQL_ALLOWED` / `SQL_FORBIDDEN` regexes (lines ~103–116)
2. Executes the user SQL with a statement timeout (lines ~118–124)
3. Sets `result['status'] = RuleResult.Status.FAIL` when the fetched row's first column is falsy or the cursor returns no rows (lines ~126–128)

A `sample_rows` key must be added to the result dict. On FAIL, the implementation should re-execute the same user SQL (which is already validated) and call `fetchmany(5)` to collect up to 5 rows, serializing them with `cursor.description`. The same statement timeout must be set again. Sampling errors must be silently caught.

### 5. SQL injection risk assessment for identifier inputs

`monitor/services.py:148` builds the table identifier as:

```python
q = '`' if provider == 'mysql' else '"'
table = f'{q}{rule.schema_name}{q}.{q}{rule.table_name}{q}'
```

`rule.schema_name` and `rule.table_name` are CharField(max_length=100) values saved by the authenticated user via the rule form (`monitor/models.py:23–24`). The quoting pattern wraps each component with the appropriate quote character. This is safe against naive injection (e.g., `public; DROP TABLE`) because the quote character wraps the entire value. However, a value that itself contains the quote character (e.g., `schema"name` for PostgreSQL or schema`name` for MySQL) would break out of the identifier quotes. Neither psycopg2 nor pymysql expose a standard identifier-escaping API that is used here.

**Risk**: A user who controls `schema_name` or `table_name` and embeds a matching quote character could potentially terminate the identifier quote and inject SQL. In the existing code this risk is accepted for `COUNT(*)` and freshness queries — the sampling queries will use the same already-quoted identifiers. Introducing sampling does not increase this risk. The same finding applies to `rule.timestamp_column` at `monitor/services.py:160` (`col = f'{q}{rule.timestamp_column}{q}'`), which is used for the freshness ORDER-BY column in sampling queries.

**Mitigation available**: A simple guard — rejecting schema/table/column names that contain the provider's quote character before building the query — would close this vector. That guard does not exist today and is not required by the change notes, but is worth flagging for plan consideration.

### 6. result dict propagation to `RuleResult.objects.create`

`monitor/services.py` calls `RuleResult.objects.create(...)` in three places:

- `run_single_rule`: lines ~200–205  
- `run_checks_for_user`: lines ~240–244  
- `run_all_checks`: lines ~290–294

All three unpack `data['status']`, `data['row_count']`, `data['last_record_age_hours']`, and `data['error_message']` explicitly as keyword arguments. Adding `sample_rows=data.get('sample_rows')` to each call will propagate the new field. None of the three sites use `**data` unpacking, so there is no risk of unexpected keyword arguments being passed to the ORM.

### 7. Template for displaying sample rows

`monitor/views.py:66–68` passes `results` (last 20 `RuleResult` objects) to `templates/monitor/rule_history.html`. The template at `templates/monitor/rule_history.html:102–150` renders a table row per result but has no reference to `sample_rows`. An expandable "Sample rows" section tied to `r.sample_rows` and `r.status == 'FAIL'` must be added inside the per-result row or as a collapsible sub-row.

## Code References

- `monitor/models.py:131–153` — `RuleResult` model definition; no `sample_rows` field
- `monitor/models.py:23–24` — `Rule.schema_name` and `Rule.table_name` CharField definitions
- `monitor/models.py:84` — `Rule.timestamp_column` CharField definition
- `monitor/services.py:94–128` — `_check_custom_sql`; FAIL branches at lines ~126–128
- `monitor/services.py:130–175` — `_check_volume_freshness`; FAIL branches at lines ~155 and ~170–173
- `monitor/services.py:148` — identifier quoting: `q = '`' if provider == 'mysql' else '"'`
- `monitor/services.py:160` — timestamp column quoting: `col = f'{q}{rule.timestamp_column}{q}'`
- `monitor/services.py:196–210` — `run_single_rule` creates RuleResult with explicit kwargs
- `monitor/services.py:237–244` — `run_checks_for_user` creates RuleResult with explicit kwargs
- `monitor/services.py:286–294` — `run_all_checks` creates RuleResult with explicit kwargs
- `templates/monitor/rule_history.html:102–150` — per-result table rows; no `sample_rows` rendering
- `requirements.txt:8` — `django==6.1.2`
- `monitor/migrations/0012_rule_notify_fields.py` — latest migration; new migration must depend on this

## Architecture Insights

- The `_check_*` functions return plain dicts that are unpacked at call sites. Adding `sample_rows` to the dict and to each `RuleResult.objects.create` call is the minimal path; no new abstraction is needed.
- Django 6.1.2 `JSONField` serializes Python lists/dicts to JSON automatically. Storing `[{"col": val, ...}, ...]` is straightforward.
- `cursor.description` is the standard DBAPI2 way to get column names from a query result; it is available on both psycopg2 and pymysql cursors.
- Sampling must happen inside the same `conn.cursor()` context as the primary check, because `_check_volume_freshness` reuses a single `with conn.cursor() as cur:` block. A second `cur.execute` for sampling can share the same cursor since it follows the primary query.
- Statement timeout must be set again for the sampling query or the sampling must be done within the same timeout context.

## Historical Context (from prior changes)

- `context/changes/mysql-support/research.md` — establishes the dual-provider quoting pattern (`q = '`' if provider == 'mysql' else '"'`) and the `_MYSQL_SYSTEM_SCHEMAS` exclusion. The sampling queries must respect this pattern.
- `context/changes/multi-tenancy/plan.md` — introduced ownership guards (rule → user FK). The sampling queries execute on the user's monitored DB (external connection), not the Django app DB, so multi-tenancy scoping does not change.
- `context/changes/email-notifications/plan.md` — established the pattern of passing `result` (a `RuleResult` instance) to notification functions after `RuleResult.objects.create`. The `sample_rows` field will be visible in those instances automatically once the field and migration exist.

## Related Research

- `context/changes/mysql-support/research.md` — provider-specific quoting and connection handling
- `context/changes/email-notifications/research.md` — RuleResult usage in notification flow

## Open Questions

1. **Identifier sanitization**: Should the plan include a guard rejecting schema/table/column names containing the provider's quote character? This closes a low-severity injection vector that pre-exists this change.
2. **Freshness-only FAIL**: When only the freshness condition is configured (no `min_row_count`), the sampling query `SELECT * FROM {table} ORDER BY {col} DESC LIMIT 5` returns the 5 most recent rows. Is that the intended sample, or should it be rows where `{col} < NOW() - INTERVAL {max_age_hours} HOUR` (rows that are stale)? The change note says "show the MAX(ts_col) row" which aligns with ORDER BY DESC LIMIT; this interpretation is used above.
3. **Custom SQL re-execution**: Re-running the user's custom SQL for sampling assumes it is side-effect free and deterministic. For non-deterministic queries the two runs may return different results. The change note says "run the SQL and show the result rows", which implies re-execution.
4. **Column types and JSON serialization**: psycopg2 returns Python datetime/Decimal objects that are not JSON serializable by default. A serialization helper converting non-JSON-native types (datetime → ISO string, Decimal → float/str) is needed before storing in JSONField. This is implementation detail for the plan.
