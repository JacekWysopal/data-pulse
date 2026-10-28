# Row-level Sampling on Failure — Plan Brief

> Full plan: `context/changes/row-sampling/plan.md`
> Research: `context/changes/row-sampling/research.md`

## What & Why

When a DataPulse monitoring rule produces a FAIL result, users currently see only a status badge and aggregate metrics (row count, age hours). They have no immediate visibility into *which* rows caused the failure. This change adds automatic follow-up sampling: on every FAIL, DataPulse fetches up to 5 diagnostic rows from the monitored database and stores them alongside the result, then surfaces them in the rule history view as an expandable section.

## Starting Point

`RuleResult` has no `sample_rows` field. Both check functions (`_check_volume_freshness`, `_check_custom_sql`) return plain dicts with no sample data. The rule history template renders per-result table rows but has no expandable diagnostic section.

## Desired End State

After this plan completes, every FAIL result will carry up to 5 sample rows stored as JSON in `RuleResult.sample_rows`. The rule history page will show a "▼ Sample rows" toggle for any FAIL result that has data. Clicking it reveals a compact table with column names as headers and row values as cells. OK and ERROR results are unchanged.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Storage field | `JSONField(null=True, blank=True)` on `RuleResult` | Django 6.1.2 ships JSONField natively; no extra package needed | Research |
| When to sample | FAIL only (not ERROR) | ERROR means DB/config problem — no useful rows to show | Plan |
| Volume sample query | `SELECT * FROM table LIMIT 5` | Arbitrary recent sample is useful for diagnosing missing rows | Plan |
| Freshness sample query | `SELECT * FROM table ORDER BY ts_col DESC LIMIT 5` | Shows 5 most recent rows — the stale-data evidence | Plan |
| Custom SQL sample | Re-run the validated custom SQL, `fetchmany(5)` | Captures actual result rows; SQL already validated by existing guards | Plan |
| JSON serialization | datetime/Decimal/date → string via `_serialize_row` | psycopg2 returns non-JSON-native types that need conversion | Research |
| Security | Validate schema/table/column names exist in `information_schema` before sampling | Closes identifier injection vector pre-existing in check functions | Plan |
| Display | Expandable toggle in `rule_history.html` via inline JS | No new JS dependency; consistent with existing inline-style approach | Plan |
| Sampling failure handling | Silently swallow exceptions, set `sample_rows = None` | A sampling failure must not convert a FAIL result into ERROR | Plan |

## Scope

**In scope:**
- `RuleResult.sample_rows` JSONField + migration `0013`
- `_serialize_row` and `_fetch_sample_rows` helpers in `services.py`
- Sampling hooks in `_check_volume_freshness` and `_check_custom_sql`
- `sample_rows=data.get('sample_rows')` at all three `RuleResult.objects.create` sites
- Expandable "Sample rows" section in `rule_history.html`
- Unit + integration tests for all new code paths

**Out of scope:**
- Sampling on ERROR results
- Dashboard summary view changes
- Sampling toggle/configuration on the Rule model
- Cross-run sample row caching
- Backfilling existing `RuleResult` records

## Architecture / Approach

The result dict that `_check_volume_freshness` and `_check_custom_sql` return gains a `sample_rows` key. A shared `_fetch_sample_rows(cur, sql, params, limit)` helper executes the follow-up query using the already-open DB connection and serializes rows via `_serialize_row`. All three `RuleResult.objects.create` call sites are updated to pass `sample_rows` through. The template adds an inline-JS toggle powered by a CSS `open` class.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. RuleResult.sample_rows Field | DB column + migration; existing tests green | Migration dependency on `0012` must be correct |
| 2. _fetch_sample_rows() Helper | Reusable sampling + serialization utility; unit-tested | `_serialize_row` must cover all non-JSON-native types psycopg2/pymysql emit |
| 3. Hook Sampling into Checks | FAIL results carry sample rows; propagated to all 3 create sites | New cursor must not interfere with already-consumed primary cursor results |
| 4. rule_history.html Display | Toggle visible for FAIL results; table shows column names + rows | `r.sample_rows.0.keys` relies on dict ordering (Python 3.7+ guaranteed) |
| 5. Tests | Full coverage of new code paths; no regressions | Mock setup for two-cursor interactions requires care |

**Prerequisites:** Django 6.1.2 (confirmed in `requirements.txt`); migration `0012_rule_notify_fields` already applied
**Estimated effort:** ~1 session across 5 phases

## Open Risks & Assumptions

- Large-column tables: `SELECT *` may return wide rows; LIMIT 5 keeps payload small but column count is unbounded. No action required for MVP.
- Non-deterministic custom SQL: re-execution for sampling may return different rows than the primary check. Accepted per change notes.
- MySQL freshness ORDER BY: uses backtick quoting already established by the dual-provider pattern; sampling reuses the same quoting variable.

## Success Criteria (Summary)

- FAIL results in rule history show an expandable "Sample rows" section with up to 5 rows and column headers
- Sampling failures (DB error on follow-up query) do not change FAIL → ERROR
- Full test suite passes with no regressions
