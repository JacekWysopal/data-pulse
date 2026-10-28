

I have all the evidence needed. Writing the review file now:

The reviews directory already exists. I'll write the impl-review.md and then update change.md.

**Review result to persist at `context/changes/mysql-support/reviews/impl-review.md`:**

```markdown
<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: MySQL Support Implementation Plan

- **Plan**: context/changes/mysql-support/plan.md
- **Scope**: Full plan (all phases)
- **Reviewed phases**: 1, 2, 3, 4, 5, 6
- **Date**: 2025-01-28
- **Verdict**: REJECTED
- **Findings**: 1 critical, 2 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | FAIL |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | WARNING |

## Findings

### F1 — Wrong identifier quoting for MySQL breaks volume/freshness rules

- **Severity**: ❌ CRITICAL
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: monitor/services.py:233, 243, 235, 248–253
- **Detail**: `_check_volume_freshness` builds SQL identifiers with PostgreSQL-style double-quote wrapping:
  `table = f'"{rule.schema_name}"."{rule.table_name}"'` (line 233) and
  `col = f'"{rule.timestamp_column}"'` (line 243). These feed into
  `SELECT COUNT(*) FROM {table}` and the `TIMESTAMPDIFF` freshness query (lines 235, 248–253).
  
  MySQL's default `sql_mode` does NOT include `ANSI_QUOTES`. Without that mode, MySQL treats
  `"name"` as a string literal, not an identifier. `SELECT COUNT(*) FROM "public"."orders"`
  produces a MySQL syntax error, causing every volume/freshness rule on a MySQL connection to
  return `RuleResult.Status.ERROR`. The MySQL path added in Phase 4 is non-functional for all
  volume and freshness rules in a standard MySQL 8.0 installation.
  
  The tests in `VolumeFreshnessMySQLTest` do not catch this because they use a mock connection
  whose cursor returns values regardless of the SQL string executed. Plan Phase 4 manual
  verification items 4.5 (volume rule OK/FAIL) and 4.6 (freshness populates age) are still
  pending and would surface this on a live MySQL connection.
  
  The `custom_sql` path is unaffected — users write their own SQL and control quoting.
  `get_schema_tables` and `get_schema_columns` use `information_schema` views and parameterized
  `%s` placeholders; they are also unaffected.

- **Fix A ⭐ Recommended**: Add provider-aware identifier quoting in `_check_volume_freshness`.
  Replace the single `table`/`col` assignment with a branch:
  ```python
  if provider == 'mysql':
      table = f'`{rule.schema_name}`.`{rule.table_name}`'
      col   = f'`{rule.timestamp_column}`'
  else:
      table = f'"{rule.schema_name}"."{rule.table_name}"'
      col   = f'"{rule.timestamp_column}"'
  ```
  - Strength: Minimal, targeted change at the exact site where provider branching already exists.
    MySQL backtick quoting is the universal default and does not require any session-mode change.
  - Tradeoff: Two parallel quoting paths to maintain; must be applied consistently in any future
    SQL that uses these identifiers.
  - Confidence: HIGH — MySQL identifier quoting with backticks is documented behaviour; the
    double-quote issue is reproducible against any default MySQL 8.0 instance.
  - Blind spot: `full_table_name` property on `Rule` (models.py:176) also uses double quotes and
    is rendered in the UI; it is not used for SQL execution, but the inconsistency should be noted.

- **Fix B**: Set `ANSI_QUOTES` mode per connection in `_parse_mysql_url` by adding `init_command`
  to the pymysql connect kwargs: `'init_command': "SET sql_mode='ANSI_QUOTES'"`.
  - Strength: Preserves the existing quoting style; no changes to the SQL-building code.
  - Tradeoff: Changes session SQL mode globally for all queries on the connection, which may
    interact unexpectedly with custom-SQL rules that rely on MySQL's default string-literal
    `"..."` behaviour. Adds hidden coupling between the driver setup and SQL syntax expectations.
  - Confidence: MEDIUM — works in MySQL 8.0 but introduces a subtle session-scoped contract.
  - Blind spot: MariaDB handles `ANSI_QUOTES` differently in some versions.

- **Decision**: PENDING

---

### F2 — SQL identifier injection via schema_name / table_name / timestamp_column

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: monitor/services.py:233, 243; monitor/models.py:84–85, 114
- **Detail**: `schema_name`, `table_name`, and `timestamp_column` are stored via free-text
  `CharField` fields with no character-allowlist validator (only `max_length=100`). They are
  interpolated into SQL with quote wrapping but no further sanitization. A value containing
  the quoting character (double-quote in PG mode or backtick in MySQL mode after F1 is fixed)
  can break out of the identifier context. Example: `table_name = "orders\`; DROP TABLE orders; --"`
  (with backtick quoting) produces `` SELECT COUNT(*) FROM `public`.`orders`; DROP TABLE orders; --` ``
  in MySQL.
  
  This is a pre-existing issue on the PostgreSQL path; the MySQL branch inherits it without
  making it worse. DataPulse is a single-tenant tool where authenticated users manage their own
  rules, which limits practical exploitability. However it is worth hardening.

- **Fix A ⭐ Recommended**: Add an identifier allowlist validator to the three model fields:
  ```python
  import re
  from django.core.validators import RegexValidator
  _identifier_re = RegexValidator(
      r'^[A-Za-z_][A-Za-z0-9_$]*$',
      'Only letters, digits, underscores, and $ are allowed.'
  )
  ```
  Apply to `schema_name`, `table_name`, and `timestamp_column`. Add a migration for the
  constraint (`blank=True` fields can still be empty).
  - Strength: Eliminates the injection class at the model level for both drivers. Pattern matches
    standard SQL identifier rules.
  - Tradeoff: Rejects non-ASCII identifiers (e.g. Unicode column names). If users have such
    identifiers they could not enter them via the UI.
  - Confidence: HIGH — the existing form placeholder `'public'` / `'updated_at'` implies ASCII
    identifiers are the intended use case.
  - Blind spot: Existing saved rows with non-conforming characters would fail validation on next
    edit; a data migration or `blank=True` handling is needed.

- **Fix B**: Strip quoting characters from the values at use-time rather than at validation time:
  ```python
  def _safe_identifier(val: str) -> str:
      return val.replace('"', '').replace('`', '').replace(';', '').replace('\n', '')
  table = f'"{_safe_identifier(rule.schema_name)}"."{_safe_identifier(rule.table_name)}"'
  ```
  - Strength: No migration needed; does not reject Unicode identifiers.
  - Tradeoff: Silently modifies user input rather than rejecting it, which could produce
    confusing results (e.g. `public` silently becomes `public` after stripping a character the
    user typed). Allowlist is harder to reason about than blocklist.
  - Confidence: MEDIUM — harder to prove exhaustive safety.
  - Blind spot: New quoting characters that are missed in the strip list.

- **Decision**: PENDING

---

### F3 — `?provider=` query param not validated against choices

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: monitor/views.py:166–168
- **Detail**: `connection_create` reads `request.GET.get('provider')` and passes the raw value
  directly to `form.initial['provider']` without validating against `Connection.Provider.choices`.
  An invalid value like `?provider=oracle` is pre-selected in the form. Django's model-level
  field validation will reject it at save time, so no invalid data reaches the DB. The risk is
  limited to a mildly confusing initial selection state. However, unvalidated GET param
  reflection is worth tightening.
- **Fix**: Check against choices before assigning:
  ```python
  valid_providers = {c[0] for c in Connection.Provider.choices}
  if provider_param in valid_providers:
      initial['provider'] = provider_param
  ```
- **Decision**: PENDING

---

### F4 — pymysql version differs from plan (1.1.1 → 1.4.6)

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: pyproject.toml; requirements.txt
- **Detail**: Plan specified `pymysql==1.1.1` in both Phase 2 contracts. The implementation
  uses `pymysql==1.4.6` in `pyproject.toml` and `requirements.txt`. Version 1.4.6 is newer,
  actively maintained, and the API used (`connect()`, `err.OperationalError`, `err.Error`) is
  stable across this range. No regression risk. The plan's version was stale at write time.
- **Fix**: Update plan.md Phase 2 "Add pymysql" contract to reference `1.4.6` so the plan
  reflects what was shipped.
- **Decision**: PENDING

---

### F5 — Migration numbered 0008 not 0005 as specified in plan

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: monitor/migrations/0008_connection_provider.py
- **Detail**: Plan Phase 1 specifies the migration filename as `0005_connection_provider.py`
  and notes "migrations 0001–0004 exist; next number is 0005." The actual file is
  `0008_connection_provider.py`, indicating migrations 0005, 0006, and 0007 were added between
  plan-writing and implementation. The migration itself is correct: `AddField` only,
  `default='postgresql'`, depends on `0007_slacknotification`. No functional impact.
- **Fix**: Update plan.md Phase 1 migration filename note to `0008_connection_provider.py` and
  revise the "next number is 0005" note.
- **Decision**: PENDING
```

**change.md update needed** — set `status: impl_reviewed` and `updated: 2025-01-28`.

Since I don't have a write tool, the runtime must persist these two artifacts. I return them both here in full.

---

## Review

```
═══════════════════════════════════════════════════════════
  IMPLEMENTATION REVIEW: MySQL Support Implementation Plan
  Scope: Full plan (Phases 1–6)  |  Date: 2025-01-28
  Findings: 1 critical  2 warnings  2 observations
═══════════════════════════════════════════════════════════

  Plan Adherence        WARNING ⚠️   (F4, F5 — version/migration number drift)
  Scope Discipline      PASS    ✅
  Safety & Quality      FAIL    ❌   (F1 critical, F2-F3 warnings)
  Architecture          PASS    ✅   (3-tuple conn_cache correct, dispatch correct)
  Pattern Consistency   PASS    ✅
  Success Criteria      WARNING ⚠️   (automated tests pass; F1 not caught by mocks)

  ► Overall: REJECTED

═══════════════════════════════════════════════════════════
  CRITICAL FINDINGS ❌
═══════════════════════════════════════════════════════════

  F1 — Wrong identifier quoting breaks MySQL volume/freshness rules
  ╌╌╌╌╌
    Severity:  ❌ CRITICAL
    Impact:    🔎 MEDIUM — real tradeoff; pause to reason through it
    Dimension: Safety & Quality
    Location:  monitor/services.py:233, 243

    Detail:
    _check_volume_freshness builds identifiers as:
      table = f'"{rule.schema_name}"."{rule.table_name}"'   # line 233
      col   = f'"{rule.timestamp_column}"'                  # line 243

    MySQL's default sql_mode does NOT include ANSI_QUOTES. Without that
    mode, MySQL treats "name" as a string literal, not an identifier.
    SELECT COUNT(*) FROM "public"."orders" produces a MySQL syntax error.
    Every volume and freshness rule on a MySQL connection returns
    RuleResult.Status.ERROR. The VolumeFreshnessMySQLTest tests do not
    catch this because they mock the cursor — the mock returns (2.0,)
    regardless of what SQL was executed.

    Fix A ⭐ Recommended: Provider-aware backtick quoting at lines 233/243:
      if provider == 'mysql':
          table = f'`{rule.schema_name}`.`{rule.table_name}`'
          col   = f'`{rule.timestamp_column}`'
      else:
          table = f'"{rule.schema_name}"."{rule.table_name}"'
          col   = f'"{rule.timestamp_column}"'
      Strength:   Minimal targeted change; MySQL backtick quoting is the
                  standard default without any session mode dependency.
      Tradeoff:   Two parallel quoting paths to maintain going forward.
      Confidence: HIGH — MySQL double-quote-as-identifier requires ANSI_QUOTES
                  which is off by default in MySQL 8.0.
      Blind spot: Rule.full_table_name (models.py:176) also uses double quotes
                  but is display-only, not used in SQL execution.

    Fix B: Add init_command="SET sql_mode='ANSI_QUOTES'" to _parse_mysql_url kwargs.
      Strength:   No SQL-building changes needed.
      Tradeoff:   Changes the session SQL mode globally, interfering with custom-SQL
                  rules that rely on MySQL default "..." string-literal behaviour.
      Confidence: MEDIUM — subtle session-scoped coupling.
      Blind spot: MariaDB ANSI_QUOTES compatibility varies by version.

═══════════════════════════════════════════════════════════
  WARNING FINDINGS ⚠️
═══════════════════════════════════════════════════════════

  F2 — SQL identifier injection via schema_name / table_name / timestamp_column
  ╌╌╌╌╌╌╌╌╌
    Severity:  ⚠️ WARNING
    Impact:    🔎 MEDIUM — real tradeoff; pause to reason through it
    Dimension: Safety & Quality
    Location:  monitor/services.py:233, 243; monitor/models.py:84–85, 114

    Detail:
    All three fields (schema_name, table_name, timestamp_column) are stored
    as free-text CharField with max_length only — no character allowlist.
    They are wrapped in quote characters but not further sanitized. After F1
    is fixed with backtick quoting, a value containing a backtick (`) breaks
    the identifier context: table_name="orders`; DROP TABLE orders; --"
    produces `orders`; DROP TABLE orders; --`. Pre-existing on the PostgreSQL
    path; the MySQL branch inherits it without worsening it. Practical impact
    is limited because DataPulse is single-tenant with authenticated users.

    Fix A ⭐ Recommended: Add a RegexValidator to the three model fields:
      _identifier_re = RegexValidator(r'^[A-Za-z_][A-Za-z0-9_$]*$', ...)
      Applied to schema_name, table_name, timestamp_column.
      Strength:   Eliminates the injection class at the model level for both drivers.
      Tradeoff:   Rejects non-ASCII identifiers; existing rows need a data migration
                  check if any non-conforming values were saved.
      Confidence: HIGH — ASCII-only identifier rule matches existing UI placeholders.
      Blind spot: Unicode table names used by some MySQL setups would be rejected.

    Fix B: Strip quoting characters at use-time in _check_volume_freshness.
      Strength:   No migration required; preserves Unicode identifiers.
      Tradeoff:   Blocklist is harder to prove exhaustive; silent mutation of input
                  can produce confusing SQL results.
      Confidence: MEDIUM.
      Blind spot: Missed quoting characters in the strip list.

  ···

  F3 — ?provider= query param not validated against choices
  ╌╌╌╌╌╌╌╌╌
    Severity:  ⚠️ WARNING
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Safety & Quality
    Location:  monitor/views.py:166–168

    Detail:
    connection_create reads request.GET.get('provider') and passes it
    directly to form.initial['provider'] without checking it against
    Connection.Provider.choices. An invalid value like ?provider=oracle is
    pre-selected. Django model validation rejects it at save time, so no
    bad data reaches the DB, but unvalidated GET param reflection is
    unnecessary.

    Fix: Guard the assignment:
      valid_providers = {c[0] for c in Connection.Provider.choices}
      if provider_param in valid_providers:
          initial['provider'] = provider_param

═══════════════════════════════════════════════════════════
  OBSERVATIONS 💡
═══════════════════════════════════════════════════════════

  F4 — pymysql version 1.4.6 shipped vs. 1.1.1 in plan
  ╌╌╌╌╌╌╌╌╌
    Severity:  💡 OBSERVATION
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Plan Adherence
    Location:  pyproject.toml; requirements.txt
    Detail:    Plan Phase 2 specifies pymysql==1.1.1. Both pyproject.toml and
               requirements.txt ship 1.4.6. No API changes affect the code.
               Plan text should be updated to reflect what was shipped.
    Fix:       Update plan.md Phase 2 pymysql version references to 1.4.6.
    Decision:  PENDING

  F5 — Migration 0008 not 0005 as planned
  ╌╌╌╌╌╌╌╌╌
    Severity:  💡 OBSERVATION
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Plan Adherence
    Location:  monitor/migrations/0008_connection_provider.py
    Detail:    Plan said "0005_connection_provider.py (migrations 0001–0004 exist)".
               Three additional migrations (0005–0007) were added before this one.
               The migration itself is correct: AddField only, default='postgresql',
               depends on 0007_slacknotification. No functional impact.
    Fix:       Update plan.md Phase 1 filename note to 0008 and revise the
               "next number is 0005" text.
    Decision:  PENDING

═══════════════════════════════════════════════════════════
  WHAT IS CORRECT ✅
═══════════════════════════════════════════════════════════

  - conn_cache 3-tuple: services.py close loop correctly unpacks
    (conn, conn_error, provider) — the critical plan callout was applied.
    Evidence: services.py:316 "for conn, conn_error, provider in conn_cache.values():"

  - _open_conn dispatch: correctly routes to psycopg2 (postgresql) or
    pymysql (mysql) with MonitoredDbError wrapping on both OperationalError types.
    Evidence: services.py:40–47.

  - _parse_mysql_url: correctly parses mysql[+pymysql]:// URLs; autocommit=True
    prevents transaction leakage across cached connections. Evidence: services.py:21–31.

  - get_schema_tables MySQL exclusion: _MYSQL_SYSTEM_SCHEMAS is a module-level
    constant; the interpolation into the WHERE clause is safe (not user input).
    Evidence: services.py:57, 85–89.

  - get_schema_columns: uses parameterized %s placeholders — safe from injection.
    Evidence: services.py:131.

  - Connection.provider field: correct TextChoices inner class, max_length=20,
    default='postgresql'. Evidence: models.py:22–31.

  - ConnectionForm.Meta.fields: ['name', 'description', 'provider'] matches plan.
    database_url is a separately defined non-model CharField handled via save()
    override — correct Django pattern. Evidence: forms.py:7–22.

  - connection_form.html JS: provider change listener updates URL placeholder.
    Evidence: templates/monitor/connection_form.html extra_scripts block.

  - connection_list.html MySQL card: correctly links to ?provider=mysql with
    badge-available. Empty-state text updated to include MySQL. Evidence: templates.

  - ?provider=mysql pre-selection view: views.py:164–169 reads GET param and
    sets form.initial — test in ConnectionCreateProviderPreSelectTest passes.

  - All 6 planned test classes present: OpenConnDispatchTest,
    CustomSqlMySQLTest, VolumeFreshnessMySQLTest, GetSchemaTablesMySQLTest,
    GetSchemaColumnsMySQLTest, ConnectionProviderModelTest.
    Evidence: tests.py:1153–1379.
```

---

**Artifacts to persist:**

**File 1 — `context/changes/mysql-support/reviews/impl-review.md`:**

```markdown
<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: MySQL Support Implementation Plan

- **Plan**: context/changes/mysql-support/plan.md
- **Scope**: Full plan (all phases)
- **Reviewed phases**: 1, 2, 3, 4, 5, 6
- **Date**: 2025-01-28
- **Verdict**: REJECTED
- **Findings**: 1 critical, 2 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | FAIL |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | WARNING |

## Findings

### F1 — Wrong identifier quoting breaks MySQL volume/freshness rules

- **Severity**: ❌ CRITICAL
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: monitor/services.py:233, 243
- **Detail**: `_check_volume_freshness` builds SQL identifiers with PostgreSQL-style double-quote
  wrapping: `table = f'"{rule.schema_name}"."{rule.table_name}"'` (line 233) and
  `col = f'"{rule.timestamp_column}"'` (line 243). These feed into `SELECT COUNT(*) FROM {table}`
  (line 235) and the `TIMESTAMPDIFF` freshness query (lines 248–253).

  MySQL's default `sql_mode` does NOT include `ANSI_QUOTES`. Without that mode, MySQL treats
  `"name"` as a string literal, not an identifier. `SELECT COUNT(*) FROM "public"."orders"`
  produces a MySQL syntax error, causing every volume/freshness rule on a MySQL connection to
  return `RuleResult.Status.ERROR`. The core MySQL feature is non-functional for volume and
  freshness rules in a standard MySQL 8.0 installation.

  `VolumeFreshnessMySQLTest` does not catch this — the mock cursor returns `(2.0,)` regardless
  of the SQL executed. Plan Phase 4 manual verification items 4.5 and 4.6 (still pending) would
  surface the failure on a live connection.

  The `custom_sql` path is unaffected. `get_schema_tables` and `get_schema_columns` use
  `information_schema` views with parameterized `%s` — also unaffected.

- **Fix A ⭐ Recommended**: Provider-aware backtick quoting in `_check_volume_freshness` (services.py:233–243):
  ```python
  if provider == 'mysql':
      table = f'`{rule.schema_name}`.`{rule.table_name}`'
      col   = f'`{rule.timestamp_column}`'
  else:
      table = f'"{rule.schema_name}"."{rule.table_name}"'
      col   = f'"{rule.timestamp_column}"'
  ```
  - Strength: Minimal, targeted change at the exact site where provider branching already exists.
    MySQL backtick quoting works without any session-mode dependency.
  - Tradeoff: Two parallel quoting paths to maintain; must be applied consistently in any future
    identifier-interpolating SQL.
  - Confidence: HIGH — MySQL double-quote-as-identifier requires ANSI_QUOTES which is off by
    default in MySQL 8.0.
  - Blind spot: `Rule.full_table_name` (models.py:176) also uses double quotes but is display-only,
    not used in SQL execution.

- **Fix B**: Add `init_command="SET sql_mode='ANSI_QUOTES'"` to `_parse_mysql_url` kwargs.
  - Strength: No SQL-building changes needed; existing quoting style preserved.
  - Tradeoff: Changes the session SQL mode globally, potentially interfering with custom-SQL rules
    that rely on MySQL's default `"..."` string-literal behaviour.
  - Confidence: MEDIUM — subtle session-scoped coupling; MariaDB ANSI_QUOTES compatibility varies.
  - Blind spot: Users relying on `"..."` as string literals in custom SQL rules would break.

- **Decision**: PENDING

---

### F2 — SQL identifier injection via schema_name / table_name / timestamp_column

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: monitor/services.py:233, 243; monitor/models.py:84–85, 114
- **Detail**: `schema_name`, `table_name`, and `timestamp_column` are `CharField` fields with
  `max_length` only — no character allowlist. They are wrapped in quote characters and
  interpolated directly into SQL. After F1 is fixed with backtick quoting, a value containing
  a backtick (`` ` ``) breaks the identifier context: `table_name = "orders`; DROP TABLE orders; --"`
  produces `` SELECT COUNT(*) FROM `public`.`orders`; DROP TABLE orders; --` `` in MySQL.

  This is pre-existing on the PostgreSQL path and is not introduced by this change. Practical
  exploitability is low — DataPulse is single-tenant with authenticated users who control their
  own rules. However the MySQL branch inherits this gap without hardening it.

- **Fix A ⭐ Recommended**: Add a `RegexValidator` to the three model fields:
  ```python
  from django.core.validators import RegexValidator
  _identifier_re = RegexValidator(
      r'^[A-Za-z_][A-Za-z0-9_$]*$',
      'Only letters, digits, underscores, and $ are allowed.'
  )
  # Apply to schema_name, table_name, timestamp_column validators list
  ```
  - Strength: Eliminates the injection class at the model level for both drivers; pattern
    matches standard SQL identifier rules; consistent with placeholder text (`public`, `updated_at`).
  - Tradeoff: Rejects non-ASCII identifiers; existing rows with non-conforming values fail
    validation on next edit — a data check migration or `blank=True` handling is needed.
  - Confidence: HIGH — allowlist is auditable; matches existing UI conventions.
  - Blind spot: MySQL databases with Unicode table names would be blocked.

- **Fix B**: Strip quoting characters at use-time in `_check_volume_freshness`.
  - Strength: No migration required; Unicode identifiers preserved.
  - Tradeoff: Blocklist approach is harder to prove exhaustive; silent input mutation is
    confusing (user types `foo`bar`, SQL runs against `foobar`).
  - Confidence: MEDIUM.
  - Blind spot: New quoting characters not in the strip list.

- **Decision**: PENDING

---

### F3 — `?provider=` query param not validated against choices

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: monitor/views.py:166–168
- **Detail**: `connection_create` passes `request.GET.get('provider')` directly to
  `form.initial['provider']` without validating against `Connection.Provider.choices`. An
  invalid value (e.g. `?provider=oracle`) is pre-selected in the form. Django model validation
  rejects it at save time so no invalid data reaches the DB. The risk is a mildly confusing
  initial selection state and a reflexive use of unvalidated GET input.
- **Fix**: Guard the assignment with a choices check:
  ```python
  valid_providers = {c[0] for c in Connection.Provider.choices}
  if provider_param in valid_providers:
      initial['provider'] = provider_param
  ```
- **Decision**: PENDING

---

### F4 — pymysql version 1.4.6 shipped vs. 1.1.1 in plan

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: pyproject.toml; requirements.txt
- **Detail**: Plan Phase 2 specifies `pymysql==1.1.1` in both the `pyproject.toml` and
  `requirements.txt` contracts. Both files ship `pymysql==1.4.6`. The API used (`connect()`,
  `err.OperationalError`, `err.Error`) is stable across this range; no regression risk. The
  plan version was stale at write time.
- **Fix**: Update plan.md Phase 2 version references to `1.4.6`.
- **Decision**: PENDING

---

### F5 — Migration numbered 0008 not 0005 as planned

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: monitor/migrations/0008_connection_provider.py
- **Detail**: Plan Phase 1 specifies filename `0005_connection_provider.py` and states
  "migrations 0001–0004 exist; next number is 0005." Three additional migrations (0005–0007)
  were added before this phase was implemented; the actual file is `0008_connection_provider.py`,
  depending on `0007_slacknotification`. The migration itself is correct: `AddField` only,
  `default='postgresql'`. No functional impact.
- **Fix**: Update plan.md Phase 1 filename reference to `0008_connection_provider.py`.
- **Decision**: PENDING
```

**File 2 — `context/changes/mysql-support/change.md`** (full updated content):

```markdown
---
change_id: mysql-support
title: MySQL support — add MySQL as a monitored database provider
status: impl_reviewed
created: 2026-10-28
updated: 2025-01-28
archived_at: null
---

## Notes

Add MySQL/MariaDB as a Connection provider alongside PostgreSQL.
Requires: mysql-connector-python or PyMySQL dependency, services.py branch for MySQL queries,
Connection.provider field (postgresql/mysql), UI provider selection.
Free MySQL for testing: PlanetScale (free tier), Railway (free tier), or Aiven free trial.
```