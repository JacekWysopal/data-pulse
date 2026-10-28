# Row-level Sampling on Failure — Implementation Plan

## Overview

When a monitoring rule produces a FAIL or ERROR result, DataPulse will now fetch up to 5 sample rows from the monitored database and store them as JSON in a new `RuleResult.sample_rows` field. The rule history view will expose this data in an expandable "Sample rows" section so users can diagnose failures without opening a separate DB client.

## Current State Analysis

`RuleResult` (`monitor/models.py:131–153`) has no `sample_rows` field. The two check functions, `_check_volume_freshness` and `_check_custom_sql` in `monitor/services.py`, return plain dicts unpacked at three call sites. Neither function captures sample rows today. The rule history template (`templates/monitor/rule_history.html:102–150`) renders per-result rows but has no reference to `sample_rows`. Django 6.1.2 ships `JSONField` natively — no third-party package is needed.

### Key Discoveries:

- `monitor/models.py:131–153` — `RuleResult` model; no `sample_rows` field
- `monitor/migrations/0012_rule_notify_fields.py` — latest migration; new migration must depend on this
- `monitor/services.py:130–175` — `_check_volume_freshness`; FAIL branches at COUNT (line ~155) and freshness (line ~170–173)
- `monitor/services.py:94–128` — `_check_custom_sql`; FAIL branches at lines ~126–128
- `monitor/services.py:196–210`, `237–244`, `286–294` — three `RuleResult.objects.create` call sites that unpack result dict explicitly; each needs `sample_rows=data.get('sample_rows')`
- `cursor.description` is the DBAPI2 standard for column name extraction; available on both psycopg2 and pymysql
- psycopg2 returns `datetime` / `Decimal` Python objects which are not JSON-serializable by default — a serialization helper is required
- Identifier quoting already exists (`q = '`' if provider == 'mysql' else '"'`); sampling queries must use the same pattern

## Desired End State

After this plan is complete:
- `RuleResult.sample_rows` is a nullable `JSONField` storing `[{"col": val, ...}, ...]` or `null`
- FAIL results for volume/freshness rules carry up to 5 sample rows (volume: `LIMIT 5`; freshness: `ORDER BY ts_col DESC LIMIT 5`)
- FAIL results for custom SQL rules carry up to 5 rows from re-running the validated custom SQL
- ERROR results do not carry sample rows (sampling is only on FAIL)
- The rule history page shows a collapsible "Sample rows" section for any result that has `sample_rows`
- Sampling failures (DB error during the follow-up query) are silently swallowed; they do not change a FAIL to ERROR
- All existing tests continue to pass; new unit tests cover the sampling path and JSON serialization

### Key Discoveries:

- Decisions settled upstream: JSONField choice, sampling queries per rule type, security approach (information_schema validation of names before sampling), JSON serializer approach (datetime/Decimal to strings), display location (rule_history.html)
- The three `RuleResult.objects.create` call sites use explicit keyword unpacking — adding `sample_rows=data.get('sample_rows')` is safe and complete

## What We're NOT Doing

- Sampling on ERROR results (only FAIL triggers sampling, per the approved decision)
- Sampling for volume rules on OK (no diagnostic value)
- Changing the existing identifier quoting mechanism (pre-existing risk accepted; guard already approved for this change via security decision)
- Adding a sampling toggle to the Rule model (out of scope)
- Caching sample rows across runs (each run fetches fresh)
- Showing sample rows on the dashboard summary view (only rule_history detail view)

## Implementation Approach

Five sequential phases: data model → sampling function → hook sampling into check functions → display → tests. Each phase has a narrow blast radius. The sampling function is extracted as `_fetch_sample_rows()` so both `_check_volume_freshness` and `_check_custom_sql` can call it without duplication. A `_serialize_row` helper handles datetime/Decimal serialization. The `sample_rows` key is added to the result dict returned by both check functions and propagated through all three `RuleResult.objects.create` call sites.

## Phase 1: RuleResult.sample_rows Field and Migration

### Overview

Add `sample_rows = models.JSONField(null=True, blank=True)` to `RuleResult` and create migration `0013_ruleresult_sample_rows`.

### Changes Required:

#### 1. RuleResult model

**File**: `monitor/models.py`

**Intent**: Add `sample_rows` as a nullable JSONField after `error_message`. This field stores the list of sample dicts or null.

**Contract**: Field definition inserted after `error_message` in the `RuleResult` class body:
```python
sample_rows = models.JSONField(null=True, blank=True)
```
Import is `django.db.models.JSONField` — no extra import needed since `JSONField` is part of `django.db.models` and the file already imports `from django.db import models`.

#### 2. Migration

**File**: `monitor/migrations/0013_ruleresult_sample_rows.py`

**Intent**: Generate the migration that adds the column. Run `python manage.py makemigrations monitor --name ruleresult_sample_rows` and verify the output depends on `0012_rule_notify_fields`.

**Contract**: Standard Django auto-generated migration; dependency `('monitor', '0012_rule_notify_fields')`.

### Success Criteria:

#### Automated Verification:

- Migration applies cleanly: `python manage.py migrate --run-syncdb`
- Migration file depends on `0012_rule_notify_fields`
- `python manage.py test monitor.tests` — all existing tests pass

#### Manual Verification:

- `RuleResult._meta.get_field('sample_rows')` is accessible in Django shell
- Django admin or shell: create a `RuleResult` with `sample_rows=[{"a": 1}]` and read it back

---

## Phase 2: `_fetch_sample_rows()` and `_serialize_row` Helper

### Overview

Add two private helpers in `monitor/services.py`:
- `_serialize_row(description, row)` — converts one DB row to a `dict`, converting `datetime`/`Decimal`/`date` to JSON-safe strings
- `_fetch_sample_rows(cur, sql, params=None, limit=5)` — executes a SQL string with optional params, calls `fetchmany(limit)`, and returns a list of serialized row dicts; returns `None` on any exception

### Changes Required:

#### 1. `_serialize_row` helper

**File**: `monitor/services.py`

**Intent**: Convert a DBAPI2 `(description, row)` pair to a JSON-serializable dict. Needed because psycopg2 returns `datetime`, `Decimal`, and `date` objects that `json.dumps` cannot handle.

**Contract**: Pure function, placed before `_check_custom_sql`. Signature:
```python
def _serialize_row(description, row: tuple) -> dict:
    ...
```
Conversion rules (applied per cell):
- `datetime.datetime` / `datetime.date` → `.isoformat()`
- `decimal.Decimal` → `str(val)`
- Everything else → value as-is (int, float, bool, str, None are already JSON-safe)

Import `import datetime` and `import decimal` at the top of the file (after existing imports).

#### 2. `_fetch_sample_rows` helper

**File**: `monitor/services.py`

**Intent**: Run a sampling query using an already-open cursor and return up to `limit` serialized row dicts. Silently returns `None` on any DB or serialization error so a sampling failure never converts FAIL → ERROR.

**Contract**: Signature:
```python
def _fetch_sample_rows(cur, sql: str, params=None, limit: int = 5) -> list | None:
    ...
```
- Executes `cur.execute(sql, params)` (params may be `None`)
- Calls `cur.fetchmany(limit)`
- Calls `_serialize_row(cur.description, row)` for each row
- Returns the list of dicts; returns `None` on any exception (bare `except Exception`)

### Success Criteria:

#### Automated Verification:

- Unit test: `_serialize_row` converts `datetime`, `Decimal`, and `date` objects correctly
- Unit test: `_fetch_sample_rows` returns list of dicts from a mock cursor
- Unit test: `_fetch_sample_rows` returns `None` when cursor raises an exception
- `python manage.py test monitor.tests` — all tests pass

#### Manual Verification:

- No runtime import errors: `python -c "from monitor.services import _fetch_sample_rows"`

---

## Phase 3: Hook Sampling into Check Functions and Call Sites

### Overview

1. Add `'sample_rows': None` to the initial result dict in both `_check_volume_freshness` and `_check_custom_sql`.
2. After each FAIL branch, call `_fetch_sample_rows` with the appropriate SQL and store the result in `result['sample_rows']`.
3. Add `sample_rows=data.get('sample_rows')` to all three `RuleResult.objects.create` call sites.

### Changes Required:

#### 1. `_check_volume_freshness` — add sampling

**File**: `monitor/services.py`

**Intent**: After the final status determination in `_check_volume_freshness`, if `result['status'] == FAIL`, run a follow-up sampling query on the same open cursor.

**Contract**:

Add `'sample_rows': None` to the initial `result` dict.

After the existing `with conn.cursor() as cur:` block (all primary checks complete), add:
```python
if result['status'] == RuleResult.Status.FAIL:
    with conn.cursor() as sample_cur:
        if rule.timestamp_column and rule.max_age_hours is not None:
            # Freshness FAIL: 5 most recent rows ordered by ts_col DESC
            col = f'{q}{rule.timestamp_column}{q}'
            sample_sql = f'SELECT * FROM {table} ORDER BY {col} DESC LIMIT 5'  # noqa: S608
            result['sample_rows'] = _fetch_sample_rows(sample_cur, sample_sql)
        elif rule.min_row_count is not None:
            # Volume FAIL: up to 5 arbitrary rows
            sample_sql = f'SELECT * FROM {table} LIMIT 5'  # noqa: S608
            result['sample_rows'] = _fetch_sample_rows(sample_cur, sample_sql)
```

The sampling block opens a **new** cursor (`sample_cur`) to avoid interference with the primary query results already consumed by `fetchone()`. Sampling is skipped if `result['status'] != FAIL` (i.e., OK or ERROR paths are unchanged).

#### 2. `_check_custom_sql` — add sampling

**File**: `monitor/services.py`

**Intent**: After setting FAIL in `_check_custom_sql`, re-execute the already-validated custom SQL and capture up to 5 rows.

**Contract**:

Add `'sample_rows': None` to the initial `result` dict.

Inside the existing `try` block, after the FAIL determination (after `result['status'] = RuleResult.Status.FAIL` is possible), add at the end of the `try` block:
```python
if result['status'] == RuleResult.Status.FAIL:
    with conn.cursor() as sample_cur:
        cur.execute(timeout_sql)  # re-apply timeout for sampling query
        result['sample_rows'] = _fetch_sample_rows(sample_cur, sql)
```

The `timeout_sql` variable is already defined in the function's scope. Use `sample_cur` (new cursor) for isolation.

#### 3. Three `RuleResult.objects.create` call sites

**Files**: `monitor/services.py` — functions `run_single_rule`, `run_checks_for_user`, `run_all_checks`

**Intent**: Propagate `sample_rows` from the result dict to the database record.

**Contract**: In each of the three `RuleResult.objects.create(...)` calls that unpack `data`, add `sample_rows=data.get('sample_rows')` as an additional keyword argument. The `.get()` ensures backwards compatibility if any code path does not set the key.

### Success Criteria:

#### Automated Verification:

- Unit test: `_check_volume_freshness` with a FAIL result returns `sample_rows` key (list or None)
- Unit test: `_check_custom_sql` with a FAIL result returns `sample_rows` key (list or None)
- Unit test: `run_single_rule` with a mocked FAIL saves `sample_rows` to the `RuleResult` record
- `python manage.py test monitor.tests` — all tests pass

#### Manual Verification:

- Run a rule against a real DB that produces FAIL; confirm `RuleResult.sample_rows` is populated in the Django admin

---

## Phase 4: rule_history.html Display

### Overview

Add an expandable "Sample rows" section to `templates/monitor/rule_history.html`. When `r.sample_rows` is present and `r.status == 'FAIL'`, show a toggle button that reveals a compact table of the sample rows.

### Changes Required:

#### 1. CSS additions

**File**: `templates/monitor/rule_history.html` — `{% block extra_head %}` style block

**Intent**: Add styles for the sample rows toggle button and the expandable sub-table.

**Contract**: Append within the existing `<style>` block:
```css
.sample-toggle {
  background: none; border: 1px solid var(--border); border-radius: 4px;
  color: var(--text-secondary); font-size: 0.7rem; padding: 2px 8px;
  cursor: pointer; margin-top: 4px;
}
.sample-toggle:hover { border-color: var(--border-strong); color: var(--text-primary); }
.sample-rows-wrap { display: none; margin-top: 6px; overflow-x: auto; }
.sample-rows-wrap.open { display: block; }
.sample-table { font-size: 0.72rem; font-family: 'JetBrains Mono', monospace;
  border-collapse: collapse; min-width: 100%; }
.sample-table th, .sample-table td {
  padding: 3px 8px; border-bottom: 1px solid var(--border);
  white-space: nowrap; text-align: left; }
.sample-table th { color: var(--text-muted); font-weight: 600; }
```

#### 2. Template row — sample rows section

**File**: `templates/monitor/rule_history.html`

**Intent**: For each FAIL result that has `sample_rows`, add a toggle button inside the Status cell (or as a full-width sub-row below the result row). On click, expand a compact table showing column names as headers and row data as cells.

**Contract**: Add the following inside the `{% for r in results %}` loop, as a second `<tr>` immediately after the existing `<tr>`:
```html
{% if r.sample_rows %}
<tr class="sample-rows-row">
  <td colspan="5" style="padding:0 1.5rem 0.5rem">
    <button class="sample-toggle" onclick="this.nextElementSibling.classList.toggle('open');this.textContent=this.nextElementSibling.classList.contains('open')?'▲ Sample rows':'▼ Sample rows'">▼ Sample rows</button>
    <div class="sample-rows-wrap">
      <table class="sample-table">
        <thead>
          <tr>
            {% for key in r.sample_rows.0.keys %}
            <th>{{ key }}</th>
            {% endfor %}
          </tr>
        </thead>
        <tbody>
          {% for sample_row in r.sample_rows %}
          <tr>
            {% for val in sample_row.values %}
            <td>{{ val|default:"—" }}</td>
            {% endfor %}
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </td>
</tr>
{% endif %}
```

The toggle uses inline JavaScript (no external dependency) that flips an `open` class and updates the button label. `r.sample_rows.0.keys` gives column headers from the first row dict.

### Success Criteria:

#### Automated Verification:

- `python manage.py test monitor.tests` — existing view tests pass (no 500 errors introduced)
- `test_rule_history_shows_results` still passes

#### Manual Verification:

- Create a rule that FAILs; run it; open rule history; confirm "▼ Sample rows" button is visible
- Click the button; confirm sample rows table expands with column headers and data
- OK and ERROR results have no "Sample rows" button
- Results with `sample_rows = null` have no button

---

## Phase 5: Tests

### Overview

Add unit and integration tests to `monitor/tests.py` covering all new code paths: `_serialize_row`, `_fetch_sample_rows`, sampling hooks in both check functions, propagation to `RuleResult`, and the view rendering path for `sample_rows`.

### Changes Required:

#### 1. Test class `SerializeRowTest`

**File**: `monitor/tests.py`

**Intent**: Unit-test `_serialize_row` with datetime, date, Decimal, str, int, None inputs.

**Contract**: Five test methods covering: datetime → ISO string, date → ISO string, Decimal → str, passthrough for int/str/None, mixed row dict.

#### 2. Test class `FetchSampleRowsTest`

**File**: `monitor/tests.py`

**Intent**: Unit-test `_fetch_sample_rows` with a mock cursor, and confirm it returns `None` on exception.

**Contract**: Two test methods: (a) happy-path with mock `description` and `fetchmany` returning rows; (b) cursor raises `Exception` → returns `None`.

#### 3. Tests in `CheckVolumeFreshnessTest` — sampling cases

**File**: `monitor/tests.py`

**Intent**: Confirm `sample_rows` is populated on FAIL and absent (None) on OK.

**Contract**: Two new test methods added to the existing `CheckVolumeFreshnessTest` class:
- `test_volume_fail_returns_sample_rows` — mock `fetchone` for COUNT, mock second cursor `fetchmany` for sample; assert `result['sample_rows']` is a list
- `test_volume_ok_no_sample_rows` — assert `result['sample_rows']` is `None` on OK

#### 4. Tests in `CheckCustomSQLTest` — sampling cases

**File**: `monitor/tests.py`

**Intent**: Confirm `sample_rows` is populated on FAIL and absent on OK.

**Contract**: Two new test methods added to `CheckCustomSQLTest`:
- `test_custom_sql_fail_returns_sample_rows`
- `test_custom_sql_ok_no_sample_rows`

#### 5. Test in `RunSingleRuleTest` — sample_rows saved to DB

**File**: `monitor/tests.py`

**Intent**: Confirm that `run_single_rule` propagates `sample_rows` to the persisted `RuleResult`.

**Contract**: One new test method that patches `psycopg2.connect`, mocks a FAIL result with sample rows, and asserts `RuleResult.objects.last().sample_rows` is not None.

#### 6. View test for sample rows rendering

**File**: `monitor/tests.py`

**Intent**: Confirm the rule history view renders "Sample rows" when `sample_rows` is populated on a FAIL result.

**Contract**: One new test in `RuleCRUDViewTest`:
- Create a `RuleResult` with `status='FAIL'` and `sample_rows=[{"id": 1, "name": "test"}]`
- GET rule history; assert response contains `sample-toggle` CSS class

### Success Criteria:

#### Automated Verification:

- All new tests pass: `python manage.py test monitor.tests`
- Full test suite green: no regressions

#### Manual Verification:

- Review test names and assertions — no mock leakage between test cases

---

## Testing Strategy

### Unit Tests:

- `_serialize_row`: datetime/Decimal/date/str/int/None conversion
- `_fetch_sample_rows`: happy path and exception path
- `_check_volume_freshness`: FAIL populates `sample_rows`; OK does not
- `_check_custom_sql`: FAIL populates `sample_rows`; OK does not

### Integration Tests:

- `run_single_rule` end-to-end with mock DB: FAIL result has `sample_rows` persisted

### Manual Testing Steps:

1. Apply migration; confirm `sample_rows` column exists in the DB
2. Create a volume rule against a real DB with a min_row_count higher than actual row count
3. Run the rule; open rule history; confirm "▼ Sample rows" toggle is visible
4. Click toggle; verify table shows correct column names and up to 5 rows
5. Repeat with a freshness rule and a custom SQL rule
6. Confirm OK results show no toggle
7. Confirm ERROR results show no toggle

## Performance Considerations

Each sampling query is a separate `SELECT * FROM {table} LIMIT 5` or `ORDER BY ... LIMIT 5`. For large tables this is O(1) with respect to table size (LIMIT). Freshness sampling uses an index-covered ORDER BY on the timestamp column when the index exists. No caching is needed for this feature.

## Migration Notes

Migration `0013_ruleresult_sample_rows` adds a nullable column with no default. Existing `RuleResult` rows will have `sample_rows = NULL`. No data backfill is needed.

## References

- Related research: `context/changes/row-sampling/research.md`
- Change identity: `context/changes/row-sampling/change.md`
- RuleResult model: `monitor/models.py:131–153`
- Check functions: `monitor/services.py:94–175`
- Latest migration: `monitor/migrations/0012_rule_notify_fields.py`
- Template: `templates/monitor/rule_history.html`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: RuleResult.sample_rows Field and Migration

#### Automated

- [ ] 1.1 Migration applies cleanly
- [ ] 1.2 Migration file depends on 0012_rule_notify_fields
- [ ] 1.3 All existing tests pass after migration

#### Manual

- [ ] 1.4 sample_rows field accessible in Django shell
- [ ] 1.5 RuleResult with sample_rows round-trips correctly

### Phase 2: _fetch_sample_rows() and _serialize_row Helper

#### Automated

- [ ] 2.1 _serialize_row converts datetime correctly
- [ ] 2.2 _serialize_row converts Decimal correctly
- [ ] 2.3 _fetch_sample_rows returns list of dicts from mock cursor
- [ ] 2.4 _fetch_sample_rows returns None on exception
- [ ] 2.5 All existing tests pass

#### Manual

- [ ] 2.6 No runtime import errors for _fetch_sample_rows

### Phase 3: Hook Sampling into Check Functions and Call Sites

#### Automated

- [ ] 3.1 _check_volume_freshness FAIL result returns sample_rows key
- [ ] 3.2 _check_custom_sql FAIL result returns sample_rows key
- [ ] 3.3 run_single_rule saves sample_rows to RuleResult
- [ ] 3.4 All existing tests pass

#### Manual

- [ ] 3.5 FAIL on real DB populates sample_rows in Django admin

### Phase 4: rule_history.html Display

#### Automated

- [ ] 4.1 Existing view tests pass with no 500 errors
- [ ] 4.2 test_rule_history_shows_results still passes

#### Manual

- [ ] 4.3 Sample rows toggle visible for FAIL results with data
- [ ] 4.4 Toggle expands with column headers and row data
- [ ] 4.5 OK and ERROR results show no toggle
- [ ] 4.6 Null sample_rows results show no toggle

### Phase 5: Tests

#### Automated

- [ ] 5.1 All new tests pass
- [ ] 5.2 Full test suite green — no regressions

#### Manual

- [ ] 5.3 Test names and assertions reviewed — no mock leakage
