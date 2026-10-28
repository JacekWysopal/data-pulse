I see the pattern. The review file format is a markdown file with `<!-- PLAN-REVIEW-REPORT -->` marker. Since I have a write tool available (`read`/find/grep but no `write` tool visible), I need to check if writing is possible. Looking at the task instructions: "Save: C:/Users/jwysopal/Desktop/10x Devs 4.0/data-pulse/context/changes/row-sampling/reviews/plan-review.md". The task expects me to save it. Let me check what tools are actually available to write files.

The tools available are: `contact_supervisor`, `find`, `grep`, `ls`, `read`, `watchdog_diff`. There is no `write` or `edit` tool available. Per the skill instruction: "If an output path is configured but no write-capable tool is available, return the complete artifact in your final response; the runtime will persist it."

I'll return the full review artifacts in my final response.

## Review

```
═══════════════════════════════════════════════════════════
  PLAN REVIEW: Row-level Sampling on Failure — Implementation Plan
  Mode: Deep  |  Date: 2026-10-28
  Findings: 2 critical  1 warning  2 observations
═══════════════════════════════════════════════════════════

  End-State Alignment    WARNING ⚠️   (1 finding)
  Lean Execution         PASS    ✅
  Architectural Fitness  PASS    ✅
  Blind Spots            PASS    ✅
  Plan Completeness      CRITICAL ❌  (2 findings)

  Grounding: 5/5 paths ✓ (monitor/models.py, monitor/services.py,
  monitor/migrations/0012_rule_notify_fields.py,
  templates/monitor/rule_history.html, monitor/tests.py);
  3/3 symbols ✓ (_check_custom_sql @184, _check_volume_freshness @241,
  RuleResult @236); brief↔plan ⚠️ (security decision contradicts plan body)

  ► Overall: REVISE

═══════════════════════════════════════════════════════════
  CRITICAL FINDINGS ❌
═══════════════════════════════════════════════════════════

  F1 — Phase 3 custom SQL contract uses wrong cursor for timeout
  ╌╌╌╌╌╌╌
    Severity:  ❌ CRITICAL
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Plan Completeness
    Location:  Phase 3 — _check_custom_sql contract

    Detail:
    The plan's sampling block for _check_custom_sql reads:
      with conn.cursor() as sample_cur:
          cur.execute(timeout_sql)   # <-- uses outer 'cur', already closed
          result['sample_rows'] = _fetch_sample_rows(sample_cur, sql)

    The outer `with conn.cursor() as cur:` block (services.py:209–219)
    exits — and closes `cur` — before the FAIL determination at lines
    220–231. The sampling block then opens `sample_cur` but mistakenly
    calls `cur.execute(timeout_sql)` on the closed cursor. In psycopg2
    this raises InterfaceError: "cursor already closed"; the bare
    except Exception in _fetch_sample_rows would swallow it, but the
    timeout would never be applied to sample_cur either.

    Fix: Replace `cur.execute(timeout_sql)` with
         `sample_cur.execute(timeout_sql)` in the plan's Phase 3
         _check_custom_sql contract snippet.

  F2 — Early-return in _check_custom_sql bypasses the sampling block
  ╌╌╌╌╌╌╌╌╌
    Severity:  ❌ CRITICAL
    Impact:    🔎 MEDIUM — real tradeoff; pause to reason through it
    Dimension: Plan Completeness
    Location:  Phase 3 — _check_custom_sql contract

    Detail:
    _check_custom_sql has two FAIL paths:
      (a) `if row is None: result['status'] = FAIL; return result`
          (services.py:220–222) — early return
      (b) `if val_norm in falsy: result['status'] = FAIL`
          (services.py:230–231) — falls through

    The plan places the sampling block "at the end of the try block",
    which path (a) never reaches because it returns immediately. The
    `return result` statement at line 222 exits the function before
    any sampling can execute. Path (a) — where the custom SQL returns
    no rows at all — produces FAIL with `sample_rows = None` under
    the current plan.

    Fix A ⭐ Recommended: Remove the early return; restructure both paths
    to fall through to a single end-of-try sampling block.
    Replace:
      if row is None:
          result['status'] = RuleResult.Status.FAIL
          return result
    With:
      if row is None:
          result['status'] = RuleResult.Status.FAIL
    Then let the existing falsy-check and the new sampling block
    follow in sequence.
      Strength:   Single sampling location; no duplicate code.
      Tradeoff:   Requires reading the plan context carefully; slight
                  refactor of existing logic.
      Confidence: HIGH — the function sets error_message='' in the
                  no-rows case so removing early return has no side
                  effect on the returned dict.
      Blind spot: Confirm no test relies on the early return for a
                  non-trivially empty result.

    Fix B: Inline sampling at each FAIL assignment.
    Add sampling immediately after each `result['status'] = FAIL`
    statement (both the early-return path and the falsy path), then
    keep the early return.
      Strength:   Minimal restructure of existing code paths.
      Tradeoff:   Duplicate sampling call sites; harder to maintain.
      Confidence: HIGH — isolates risk to two small additions.
      Blind spot: None significant.

═══════════════════════════════════════════════════════════
  WARNING FINDINGS ⚠️
═══════════════════════════════════════════════════════════

  F3 — plan-brief.md and plan.md contradict each other on information_schema validation
  ╌╌╌╌╌╌╌╌
    Severity:  ⚠️ WARNING
    Impact:    🔎 MEDIUM — real tradeoff; pause to reason through it
    Dimension: End-State Alignment
    Location:  plan-brief.md Security row vs plan.md "What We're NOT Doing"

    Detail:
    plan-brief.md Key Decisions table (Security row) says:
      "Validate schema/table/column names exist in information_schema
       before sampling — Closes identifier injection vector pre-existing
       in check functions"
    This implies the guard IS in scope.

    plan.md "What We're NOT Doing" says:
      "Changing the existing identifier quoting mechanism (pre-existing
       risk accepted; guard already approved for this change via security
       decision)"
    This implies the guard is NOT in scope — the security decision
    approved skipping it.

    No phase in plan.md implements information_schema validation for
    sampling, confirming it is excluded. But plan-brief.md lists it
    as a settled in-scope decision. An implementor reading the brief
    first, or an orchestrator using the brief as the authoritative
    summary, will believe the validation IS required and find no phase
    to execute it.

    Fix: Align plan-brief.md Security row with plan.md.
    Update the plan-brief.md Security row text to:
      "Accept pre-existing identifier injection risk — information_schema
       validation deferred; sampling queries reuse the existing quoting
       pattern (`q = '`' if provider == 'mysql' else '\"'`)"
    This makes the brief match the plan body and removes the
    contradiction.

═══════════════════════════════════════════════════════════
  OBSERVATIONS 📝
═══════════════════════════════════════════════════════════

  F4 — Stale line number references in Current State Analysis and References
  ╌╌╌╌╌╌╌╌
    Severity:  📝 OBSERVATION
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Plan Completeness
    Location:  Current State Analysis bullet list; References section

    Detail:
    Plan states:
      - monitor/models.py:131–153 — RuleResult model
      - monitor/services.py:94–175 — check functions
    Actual code locations (verified):
      - RuleResult class: models.py:236
      - _check_custom_sql: services.py:184
      - _check_volume_freshness: services.py:241
    The References section repeats the same stale numbers. Navigation
    friction only — no code defect introduced.

    Fix: Update the line numbers in Current State Analysis and References.

  F5 — Template condition does not guard on r.status == 'FAIL'
  ╌╌╌╌
    Severity:  📝 OBSERVATION
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Blind Spots
    Location:  Phase 4 — Template row contract

    Detail:
    The template contract uses `{% if r.sample_rows %}` as the sole
    display condition. The end state says ERROR results must never show
    the toggle. This currently holds because ERROR paths never set
    sample_rows. But if a future code path sets sample_rows on an ERROR
    result, the toggle would appear incorrectly. The condition in the
    Overview also says "When r.sample_rows is present and r.status ==
    'FAIL'" — but the actual contract snippet omits the status check.

    Fix: Change the template condition to
         `{% if r.sample_rows and r.status == 'FAIL' %}`
         to match the stated intent and guard defensively.
```

---

Saving the artifacts now. The `reviews/` directory for `row-sampling` does not yet exist and no write tool is available, so both file contents are returned in full below for the runtime to persist.

---

**File 1 — Save to: `context/changes/row-sampling/reviews/plan-review.md`**

```markdown
<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Row-level Sampling on Failure — Implementation Plan

- **Plan**: context/changes/row-sampling/plan.md
- **Mode**: Deep
- **Date**: 2026-10-28
- **Verdict**: REVISE
- **Findings**: 2 critical  1 warning  2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | WARNING |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | PASS |
| Plan Completeness | FAIL |

## Grounding

5/5 paths ✓ (monitor/models.py, monitor/services.py, monitor/migrations/0012_rule_notify_fields.py, templates/monitor/rule_history.html, monitor/tests.py); 3/3 symbols ✓ (_check_custom_sql @services.py:184, _check_volume_freshness @services.py:241, RuleResult @models.py:236); brief↔plan ⚠️ (security decision contradicts plan body — see F3)

## Findings

### F1 — Phase 3 custom SQL contract uses wrong cursor for timeout

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 3 — _check_custom_sql contract snippet
- **Detail**: The plan's sampling block for `_check_custom_sql` reads `cur.execute(timeout_sql)` inside `with conn.cursor() as sample_cur:`. The outer `with conn.cursor() as cur:` block (services.py:209–219) closes `cur` before the FAIL determination at lines 220–231. Calling `cur.execute(...)` on a closed psycopg2 cursor raises `InterfaceError: cursor already closed`. `_fetch_sample_rows` would swallow the error (bare `except Exception`) but the timeout would never be applied to `sample_cur`.
- **Fix**: Replace `cur.execute(timeout_sql)` with `sample_cur.execute(timeout_sql)` in the Phase 3 `_check_custom_sql` contract snippet.
- **Decision**: PENDING

### F2 — Early-return in _check_custom_sql bypasses the sampling block

- **Severity**: ❌ CRITICAL
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Completeness
- **Location**: Phase 3 — _check_custom_sql contract; services.py:220–222
- **Detail**: `_check_custom_sql` has two FAIL paths: (a) `if row is None: result['status'] = FAIL; return result` (early return, services.py:220–222) and (b) `if val_norm in falsy: result['status'] = FAIL` (falls through). The plan places the sampling block "at the end of the try block". Path (a) returns immediately and never reaches the sampling block, so a custom SQL rule that returns zero rows produces FAIL with `sample_rows = None` — no sample rows captured despite a clear diagnostic opportunity.
- **Fix A ⭐ Recommended**: Remove the early return. Replace the `return result` at line 222 with a bare status assignment and let both paths fall through to a single end-of-try sampling block.
  - Strength: Single sampling code location; no duplication.
  - Tradeoff: Slight restructure of existing logic.
  - Confidence: HIGH — the no-rows case sets no other fields; removing early return has no side effect on the returned dict.
  - Blind spot: Confirm no test asserts the specific early-return behavior for the empty-result path.
- **Fix B**: Inline sampling immediately after each `result['status'] = FAIL` assignment (both the early-return path and the falsy path), preserving the early return.
  - Strength: Minimal restructure; isolates risk to two additions.
  - Tradeoff: Duplicate sampling call sites.
  - Confidence: HIGH.
  - Blind spot: None significant.
- **Decision**: PENDING

### F3 — plan-brief.md and plan.md contradict each other on information_schema validation

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: plan-brief.md Security row vs plan.md "What We're NOT Doing"
- **Detail**: plan-brief.md Key Decisions table (Security row) says "Validate schema/table/column names exist in `information_schema` before sampling — Closes identifier injection vector pre-existing in check functions", implying the guard is in scope. plan.md "What We're NOT Doing" says "Changing the existing identifier quoting mechanism (pre-existing risk accepted; guard already approved for this change via security decision)", implying validation is explicitly excluded. No phase implements `information_schema` validation. An implementor using the brief as authoritative will expect a phase that does not exist.
- **Fix**: Update plan-brief.md Security row to read: "Accept pre-existing identifier injection risk — `information_schema` validation deferred; sampling queries reuse the existing quoting pattern (`q = '`' if provider == 'mysql' else '\"'`)". This aligns the brief with plan.md and removes the contradiction.
- **Decision**: PENDING

### F4 — Stale line number references in Current State Analysis and References

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Current State Analysis bullet list; References section
- **Detail**: Plan cites `monitor/models.py:131–153` for RuleResult and `monitor/services.py:94–175` for check functions. Actual locations: RuleResult at models.py:236; `_check_custom_sql` at services.py:184; `_check_volume_freshness` at services.py:241. Navigation friction only; no code defect.
- **Fix**: Update the cited line numbers in Current State Analysis and the References section.
- **Decision**: PENDING

### F5 — Template condition does not guard on r.status == 'FAIL'

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 4 — Template row contract
- **Detail**: The plan's template contract uses `{% if r.sample_rows %}` as the sole display condition. The Phase 4 Overview states "when r.sample_rows is present and r.status == 'FAIL'" but the actual contract snippet omits the status check. Currently harmless because ERROR paths never populate `sample_rows`, but defensive coding and stated intent alignment both favor the explicit guard.
- **Fix**: Change the template condition to `{% if r.sample_rows and r.status == 'FAIL' %}`.
- **Decision**: PENDING
```

**File 2 — Save to: `context/changes/row-sampling/change.md`** (update `status` and `updated` fields only):

```markdown
---
change_id: row-sampling
title: Row-level sampling on failure — show example failing rows
status: plan_reviewed
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

When a FAIL result occurs, run a follow-up query to fetch up to 5 sample rows that violate the condition. For volume check: show 5 most recent rows. For freshness: show the MAX(ts_col) row. For custom SQL: run the SQL and show the result rows. Store sample as JSON in RuleResult.sample_rows (JSONField). Display in history view as expandable "Sample rows" section.
```

---

## Review

**Correct:**
- All 5 file paths verified to exist: `monitor/models.py`, `monitor/services.py`, `monitor/migrations/0012_rule_notify_fields.py`, `templates/monitor/rule_history.html`, `monitor/tests.py`.
- All 3 symbols confirmed: `RuleResult` at models.py:236, `_check_custom_sql` at services.py:184, `_check_volume_freshness` at services.py:241, `_check_rule` dispatcher at services.py:170.
- Three `RuleResult.objects.create` call sites identified and confirmed to use explicit keyword unpacking — the `data.get('sample_rows')` pattern is safe.
- `_check_volume_freshness` sampling block (after-the-`with`-block placement) is architecturally correct: Python's non-block scoping means `table` and `q` remain accessible. The sampling opens a fresh `sample_cur` correctly.
- Migration dependency chain is correct: `0012_rule_notify_fields.py` exists; `0013` depending on it is valid.
- `_serialize_row` contract handles all non-JSON-native types psycopg2 emits (datetime, date, Decimal). JSONField will handle the rest.
- Progress section is well-formed: exactly one `## Progress` heading, 5 `### Phase N:` blocks matching the 5 plan phases, all items `- [ ]`, no checkboxes in phase bodies.

**Finding:** P0 — F1: Phase 3 `_check_custom_sql` contract calls `cur.execute(timeout_sql)` on the already-closed outer cursor. Fix: change to `sample_cur.execute(timeout_sql)`.

**Finding:** P0 — F2: `_check_custom_sql`'s `if row is None: return result` early return (services.py:220–222) exits before the sampling block the plan places at end-of-try. The no-rows FAIL path will never capture sample rows. Fix A (recommended): remove the early return and let both FAIL paths fall through to one sampling block.

**Finding:** P1 — F3: plan-brief.md Security row says `information_schema` validation is in scope; plan.md "What We're NOT Doing" says the risk is accepted and validation excluded. No phase implements it. Fix: update plan-brief.md Security row to reflect the accepted-risk decision.

**Finding:** P2 — F4: Line numbers in Current State Analysis and References are stale (plan cites models.py:131–153 and services.py:94–175; actual is models.py:236 and services.py:184/241).

**Finding:** P2 — F5: Template condition `{% if r.sample_rows %}` should also check `r.status == 'FAIL'` to match the stated intent and guard defensively.

**Merge verdict:** BLOCK — two critical code-contract bugs (F1, F2) will produce incorrect runtime behavior. Fix both in plan.md Phase 3 before implementing.