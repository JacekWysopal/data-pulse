Good. All 8 SQL templates confirmed. None contain `EXECUTE` or `CALL`. The F3 finding is about the test spec omitting these two keywords from its forbidden-keyword check list, not about the templates themselves.

Now writing the two files:

**File 1: `context/changes/check-templates/reviews/plan-review.md`**
**File 2: updated `context/changes/check-templates/change.md`** (status: plan_reviewed)

Note: The `write` tool is not explicitly listed in the available tools for this session. The tools available are: `contact_supervisor`, `find`, `grep`, `watchdog_diff`, `ls`, `read`. There is no `write` or `edit` tool available to me as a reviewer subagent in this environment.

Per the skill instructions: "If an output path is configured but no write-capable tool is available, return the complete artifact in your final response; the runtime will persist it."

I'll return both artifacts in my final response.

---

## Review

```
═══════════════════════════════════════════════════════════
  PLAN REVIEW: Built-in Rule Check Templates Implementation Plan
  Mode: Deep  |  Date: 2026-10-28
  Findings: 0 critical  3 warnings  2 observations
═══════════════════════════════════════════════════════════

  End-State Alignment    PASS    ✅
  Lean Execution         PASS    ✅
  Architectural Fitness  PASS    ✅
  Blind Spots            WARNING ⚠️   (2 findings)
  Plan Completeness      WARNING ⚠️   (1 finding)

  Grounding: 5/5 paths ✓, 5/5 symbols ✓, brief↔plan ✓
  ► Overall: REVISE
═══════════════════════════════════════════════════════════
  WARNING FINDINGS ⚠️
═══════════════════════════════════════════════════════════

  F1 — Scope contradicts Phase 2: forms.py is modified
  ╌╌╌╌╌╌╌
    Severity:  ⚠️ WARNING
    Impact:    🔎 MEDIUM — real tradeoff; pause to reason through it
    Dimension: Plan Completeness
    Location:  "What We're NOT Doing" (plan.md:47) vs. Phase 2 Change 1

    Detail:
    plan.md:47 states "No change to services.py, forms.py, or any model."
    Phase 2 Change 1 (plan.md:~140) explicitly modifies monitor/forms.py to add
    the data-providers JSON attribute on RuleForm's connection widget. The change
    is correct and necessary — the scope line is wrong. An implementer reading
    scope first could skip forms.py and ship a broken provider-detection path.

    Fix: Remove "forms.py" from the "What We're NOT Doing" bullet, or rewrite it
    as: "No change to services.py validation logic or any model" to acknowledge
    the forms.py widget-attr addition is in scope.
      Strength:   Removes the contradiction; the phase plan is correct as written.
      Tradeoff:   None — the phase plan already describes the correct change.
      Confidence: HIGH — verified against forms.py source and phase description.
      Blind spot: None.

  ···

  F2 — Phase 3 test spec omits EXECUTE and CALL from forbidden-keyword list
  ╌╌╌╌╌╌╌╌╌╌╌╌╌╌
    Severity:  ⚠️ WARNING
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Blind Spots
    Location:  Phase 3 — CheckTemplatesTests contract; also forms.py:clean()

    Detail:
    services.py:179 SQL_FORBIDDEN regex enforces 11 keywords:
      INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER, CREATE, GRANT, REVOKE,
      EXECUTE, CALL
    Phase 3 test contract (plan.md:~252) lists only 9 — omits EXECUTE and CALL.
    Tests written per the spec will silently leave two enforced constraints
    uncovered. A separate pre-existing divergence: forms.py:clean() (line ~86)
    also enforces only 9 keywords (without EXECUTE/CALL) — tests against forms
    validation will pass for those keywords even if a template somehow included
    them. Note: none of the 8 current templates contain EXECUTE or CALL, so
    this is a coverage gap, not a runtime bug.

    Fix: Add EXECUTE and CALL to the forbidden-keyword list in the Phase 3 test
    contract. Optionally, add a follow-up note that forms.py:clean() should also
    be brought into sync with services.py (pre-existing; outside this change's
    scope but worth flagging for the next cleanup).
      Confidence: HIGH — services.py:179 verified directly.
      Blind spot: None.

  ···

  F3 — Progress↔Phase gap: Phase 2 manual criterion 7 missing from Progress
  ╌╌╌╌╌╌
    Severity:  ⚠️ WARNING
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Plan Completeness
    Location:  Phase 2 Manual Verification (plan.md:223) vs. Progress Phase 2

    Detail:
    Phase 2 Manual Verification has 7 bullets (plan.md:217–223). Progress
    section Phase 2 Manual has only 6 entries (2.2–2.7). Missing:
      "Editing the generated SQL manually before saving works as before"
    Per the progress-format contract, every Manual Verification bullet in a
    Phase block must have a corresponding - [ ] entry in Progress. The missing
    step means /10x-implement cannot record completion of that verification
    gate. It also won't appear in /10x-status output.

    Fix: Add `- [ ] 2.8 Editing the generated SQL manually before saving works
    as before` under `#### Manual` in `### Phase 2: rule_form.html template
    gallery UI` in the Progress section.

═══════════════════════════════════════════════════════════
  OBSERVATION FINDINGS
═══════════════════════════════════════════════════════════

  F4 — pattern_match: !~ requires POSIX regex; parameter placeholder doesn't hint
  ╌╌╌╌╌╌
    Severity:  OBSERVATION
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Blind Spots
    Location:  check_templates.py template spec, pattern_match entry

    Detail:
    The PostgreSQL variant uses !~ (POSIX regex negation). Users familiar with
    SQL LIKE or glob patterns (e.g. %value%) will supply wrong patterns and
    get false-OK results silently. The plan specifies a plain text input with
    no placeholder or description to guide the user. MySQL REGEXP similarly
    requires POSIX regex, not SQL LIKE syntax.

    Fix: Set the params entry for pattern in pattern_match to use a placeholder
    such as "^[A-Z]{2}-[0-9]+" and add a description like "POSIX regex" to
    the template's description or params label. A one-line note in the
    generated SQL (as a SQL comment above the SELECT) is also an option.

  F5 — Module name mismatch between research.md and plan (resolved in plan)
  ╌╌╌╌╌╌
    Severity:  OBSERVATION
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Plan Completeness
    Location:  research.md "Storage decision" vs. plan throughout

    Detail:
    research.md names the module monitor/templates_catalog.py; the plan names
    it monitor/check_templates.py. The plan is the implementation contract and
    is correct; the research file is reference only. No code impact. Note for
    implementers: do not create templates_catalog.py.

    Fix: No action required. The plan already uses the canonical name.

═══════════════════════════════════════════════════════════
  ► Overall verdict: REVISE
    Fix F1 (scope line), F2 (test keyword list), F3 (Progress entry) before
    starting /10x-implement.
═══════════════════════════════════════════════════════════
```

No write-capable tool is available in this reviewer session. The complete artifacts to persist are below.

---

**Artifact 1 — save to `context/changes/check-templates/reviews/plan-review.md`:**

```markdown
<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Built-in Rule Check Templates Implementation Plan

- **Plan**: context/changes/check-templates/plan.md
- **Mode**: Deep
- **Date**: 2026-10-28
- **Verdict**: REVISE
- **Findings**: 0 critical  3 warnings  2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding

5/5 paths ✓, 5/5 symbols ✓, brief↔plan ✓

Paths verified: `monitor/check_templates.py` (new — correct), `templates/monitor/rule_form.html:181` (`#custom-sql-section` confirmed), `monitor/forms.py` (exists; `RuleForm.__init__` confirmed), `monitor/views.py:145` (schema AJAX pattern confirmed), `monitor/urls.py:17–19` (schema API block confirmed).

Symbols verified: `setType` at rule_form.html:342, `SQL_FORBIDDEN` at services.py:178–181, `Connection.provider` at models.py:30, `api_schema_tables` pattern at views.py:160–174, `RuleForm.__init__` at forms.py:64.

## Findings

### F1 — Scope contradicts Phase 2: forms.py is modified

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Completeness
- **Location**: "What We're NOT Doing" (plan.md:47) vs. Phase 2 Change 1
- **Detail**: plan.md:47 states "No change to `services.py`, `forms.py`, or any model." Phase 2 Change 1 explicitly modifies `monitor/forms.py` to add the `data-providers` JSON attribute on `RuleForm`'s connection widget. The phase change is correct and necessary. An implementer reading the scope section first could skip `forms.py` and ship a broken provider-detection path.
- **Fix**: Remove "forms.py" from the "What We're NOT Doing" bullet, or narrow it to: "No change to `services.py` validation logic or any model." The forms.py widget-attr addition belongs in scope.
  - Strength: Removes the contradiction; the phase plan is already correct as written.
  - Tradeoff: None — no phase change needed, only the scope bullet.
  - Confidence: HIGH — verified against forms.py source and phase description.
  - Blind spot: None.
- **Decision**: PENDING

### F2 — Phase 3 test spec omits EXECUTE and CALL from forbidden-keyword list

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 3 — CheckTemplatesTests contract (plan.md ~line 252)
- **Detail**: `services.py:179` SQL_FORBIDDEN enforces 11 keywords: `INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER, CREATE, GRANT, REVOKE, EXECUTE, CALL`. The Phase 3 test contract lists only 9 — omitting `EXECUTE` and `CALL`. Tests written per the plan spec will silently leave two enforced constraints uncovered. Separate pre-existing note: `forms.py:clean()` (~line 86) also enforces only 9 keywords; a follow-up cleanup is warranted but is outside this change's scope.
- **Fix**: Add `EXECUTE` and `CALL` to the forbidden-keyword assertion list in the Phase 3 `CheckTemplatesTests` contract.
  - Confidence: HIGH — services.py:179 verified directly.
  - Blind spot: None.
- **Decision**: PENDING

### F3 — Progress↔Phase gap: Phase 2 manual criterion 7 missing from Progress

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 Manual Verification (plan.md:223) vs. Progress `### Phase 2` Manual subsection
- **Detail**: Phase 2 Manual Verification has 7 bullets (plan.md lines 217–223). The Progress `### Phase 2` Manual subsection has only 6 entries (2.2–2.7). The missing criterion is: "Editing the generated SQL manually before saving works as before." Per the progress-format contract, every Manual Verification bullet must have a corresponding `- [ ]` entry in Progress. The missing step cannot be recorded as complete by `/10x-implement` and will not appear in `/10x-status` output.
- **Fix**: Add `- [ ] 2.8 Editing the generated SQL manually before saving works as before` under `#### Manual` in `### Phase 2: rule_form.html template gallery UI` in the Progress section.
- **Decision**: PENDING

### F4 — pattern_match: !~ requires POSIX regex; parameter placeholder gives no hint

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: check_templates.py template spec, pattern_match entry
- **Detail**: The PostgreSQL variant uses `!~` (POSIX regex negation). Users familiar with SQL LIKE or glob patterns (`%value%`) will supply wrong patterns and get false-OK results silently. MySQL `NOT REGEXP` has the same syntax requirement. The plan specifies a plain text input with no placeholder to guide the user.
- **Fix**: Set the `pattern` param placeholder to something like `^[A-Z]{2}-[0-9]+` and note "POSIX regex" in the template's description or params label.
- **Decision**: PENDING

### F5 — Module name mismatch between research.md and plan (resolved in plan)

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: research.md "Storage decision" section vs. plan throughout
- **Detail**: `research.md` names the module `monitor/templates_catalog.py`; the plan names it `monitor/check_templates.py`. The plan is the implementation contract and is correct. No code impact. Note for implementers: do not create `templates_catalog.py`.
- **Fix**: No action required. The plan already uses the canonical name.
- **Decision**: PENDING
```

---

**Artifact 2 — updated `context/changes/check-templates/change.md`** (change `status: planned` → `status: plan_reviewed` and `updated: 2026-10-28` → `updated: 2026-10-28`):

```markdown
---
change_id: check-templates
title: Built-in rule check templates — null, uniqueness, referential integrity
status: plan_reviewed
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

Template gallery on rule creation: click a template and the SQL field pre-fills. Templates: null_check (no NULLs in column), uniqueness (no duplicate values), referential_integrity (FK exists in parent table), not_negative (numeric >= 0), future_date (date not in future), pattern_match (regex), row_count_equals, completeness_rate (% non-null >= threshold). Each template takes parameters filled in a simple form that generates the SQL.
```

---

## Review

- **Correct**: End-state is clearly defined and reachable through the three phases. All 8 templates satisfy `SQL_ALLOWED`/`SQL_FORBIDDEN` constraints confirmed in `services.py:177–181`. Grounding is solid — 5/5 paths exist, all referenced symbols verified. The `setType` custom-event bridge design is sound and preserves existing IIFE encapsulation. Provider detection via `data-providers` JSON on the `<select>` element is a clean, additive approach. Progress structure is well-formed except for one missing entry. No unnecessary abstractions or scope creep beyond the stated goal.

- **Finding**: F1 — P1 WARNING, Plan Completeness — "What We're NOT Doing" says no change to `forms.py` (plan.md:47) but Phase 2 Change 1 modifies `monitor/forms.py`. Fix: narrow the scope bullet to exclude only `services.py` validation logic and models.

- **Finding**: F2 — P1 WARNING, Blind Spots — Phase 3 test contract lists 9 forbidden keywords; `services.py:179` enforces 11 (`EXECUTE` and `CALL` omitted). Fix: add `EXECUTE` and `CALL` to the test assertion list.

- **Finding**: F3 — P1 WARNING, Plan Completeness — Phase 2 has 7 manual verification bullets; Progress has only 6 (2.2–2.7). Item "Editing the generated SQL manually before saving works as before" has no Progress entry. Fix: add `- [ ] 2.8 Editing the generated SQL manually before saving works as before`.

- **Finding**: F4 — P2 OBSERVATION, Blind Spots — `pattern_match` uses `!~` (POSIX regex); the plan's parameter form has no placeholder hinting at regex syntax. Users supplying LIKE-style patterns will get silent false-OKs.

- **Finding**: F5 — P2 OBSERVATION, Plan Completeness — `research.md` named the module `templates_catalog.py`; plan correctly uses `check_templates.py`. No action needed; noted for implementers.

- **Merge verdict**: REVISE — fix F1, F2, and F3 in `plan.md` before starting `/10x-implement`. All three are small edits (one line each). F4 and F5 can be addressed during implementation or deferred.