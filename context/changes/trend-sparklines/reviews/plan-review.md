Now I'll write the review file. I need to create `context/changes/trend-sparklines/reviews/plan-review.md`:

```
<!-- PLAN-REVIEW-REPORT -->
```

Let me write it now. I'll use the `write` tool equivalent (in this environment I have `read`, `grep`, `find`, `ls`, `watchdog_diff`, `contact_supervisor`, and `thinking` — I don't see a `write` tool explicitly. Let me check what file-writing capabilities I have.

Looking at the available tools: `find`, `grep`, `ls`, `read`, `thinking`, `watchdog_diff`, `contact_supervisor`. I don't see a `write` or `edit` tool directly. However, the system prompt says "If an output path is configured but no write-capable tool is available, return the complete artifact in your final response; the runtime will persist it."

The task says "Save: C:/Users/jwysopal/Desktop/10x Devs 4.0/data-pulse/context/changes/trend-sparklines/reviews/plan-review.md" and "Update change.md: plan_reviewed". I cannot write files with the available tools. I'll return the complete artifacts in my response for the runtime to persist.

## Review

```
═══════════════════════════════════════════════════════════
  PLAN REVIEW: Trend Sparklines Implementation Plan
  Mode: Deep  |  Date: 2026-10-28
  Findings: 1 critical  1 warning  1 observation
═══════════════════════════════════════════════════════════

  End-State Alignment    PASS    ✅
  Lean Execution         PASS    ✅
  Architectural Fitness  PASS    ✅
  Blind Spots            WARNING ⚠️   (1 finding)
  Plan Completeness      CRITICAL ❌  (2 findings)

  Grounding: 5/5 paths ✓, 3/3 symbols ✓, brief↔plan ✓
  ► Overall: REVISE

═══════════════════════════════════════════════════════════
  CRITICAL FINDINGS ❌
═══════════════════════════════════════════════════════════

  F1 — Phase execution order causes ImportError on Phase 1
  ╌╌╌╌╌╌╌
    Severity:  ❌ CRITICAL
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Plan Completeness
    Location:  Phase 1 (Changes Required §1), Phase 2 (Implementation Note),
               and ## Progress ordering

    Detail:
    Phase 1's contract adds `from .sparkline import status_dot_sparkline` to
    `monitor/views.py`. `monitor/sparkline.py` does not exist until Phase 2
    creates it. Executing phases in canonical order (1 → 2 → 3 → 4) will raise
    an ImportError at the first request after Phase 1's view change lands.

    The plan body acknowledges this in Phase 2's own Implementation Note:
    "Phase 2 first, then wire Phase 1, or commit both together." But the
    numbered phase order and the ## Progress section both list Phase 1 before
    Phase 2 — /10x-implement reads phases sequentially from Progress order.

    Fix: Swap the phase numbers so the SVG helper is Phase 1 and the dashboard
    view update is Phase 2. Alternatively, keep the numbers but add a prominent
    prerequisite note at the top of the current Phase 1 block: "Must be
    implemented after Phase 2 (SVG helper) — import will fail otherwise" — and
    reorder Progress entries to Phase 2 first (renaming indices consistently).
    Simplest: add one sentence to Phase 1's Overview — "Implement after Phase 2;
    the import on line 1 of this phase requires sparkline.py to exist."
    /10x-implement checks the Phase block for prerequisites before executing.

═══════════════════════════════════════════════════════════
  WARNING FINDINGS ⚠️
═══════════════════════════════════════════════════════════

  F2 — rule_history double queryset evaluation contradicts "no extra queries" claim
  ╌╌╌╌╌╌╌╌╌╌╌
    Severity:  ⚠️ WARNING
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Blind Spots
    Location:  Phase 3 — Changes Required §4 (rule_history view sparkline),
               Performance Considerations

    Detail:
    Performance Considerations states: "No additional database queries for
    rule_history sparkline." Phase 3 Step 4's contract calls:

        statuses = [r.status for r in reversed(list(results))]

    `list(results)` evaluates the sliced queryset once (1 DB hit). But `results`
    is still the original sliced queryset object — `rule.results.select_related(
    'run').order_by('-checked_at')[:20]` at views.py:93. The template then
    iterates `{% for r in results %}`, re-evaluating the queryset: a second DB hit.

    Fix: Add `results = list(results)` before the sparkline computation in the
    Phase 3 Step 4 contract block, so both the sparkline and the template loop
    share the same in-memory list:

        results = list(rule.results.select_related('run').order_by('-checked_at')[:20])
        statuses = [r.status for r in reversed(results)]  # oldest-first
        sparkline_svg = mark_safe(status_dot_sparkline(statuses))

═══════════════════════════════════════════════════════════
  OBSERVATION FINDINGS 📋
═══════════════════════════════════════════════════════════

  F3 — Phase 1 manual verification gates require Phases 2 and 3 to be complete
  ╌╌╌╌╌╌╌
    Severity:  📋 OBSERVATION
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Plan Completeness
    Location:  Phase 1 Manual Verification / Progress 1.3, 1.4

    Detail:
    Phase 1 Manual Verification says "Dashboard loads; each rule row contains a
    <svg> element in the Trend column." This is physically impossible after only
    Phase 1: the Trend column doesn't exist in the template until Phase 3, and
    the sparkline function doesn't exist until Phase 2. Steps 1.3 and 1.4 in
    Progress can never go green on their own phase.

    The post-Phase-1 manual gate ("pause for manual confirmation before proceeding
    to Phase 2") will always block /10x-implement because there's nothing visually
    to confirm yet.

    Fix: Replace Phase 1 manual criteria with what is actually verifiable after
    Phase 1 alone: "No import errors in `python manage.py check`; dashboard
    responds 200 OK without a 500." Retain the SVG-visibility checks in Phase 3's
    manual criteria where they belong (they're already there as 3.3).
```

---

**Output artifacts** (to be persisted by runtime):

**File: `context/changes/trend-sparklines/reviews/plan-review.md`**

```markdown
<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Trend Sparklines Implementation Plan

- **Plan**: context/changes/trend-sparklines/plan.md
- **Mode**: Deep
- **Date**: 2026-10-28
- **Verdict**: REVISE
- **Findings**: 1 critical  1 warning  1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | FAIL |

## Grounding

5/5 paths ✓ (`monitor/views.py`, `monitor/sparkline.py` [new — expected], `templates/monitor/dashboard.html`, `templates/monitor/rule_history.html`, `monitor/tests.py`), 3/3 symbols ✓ (`Prefetch`, `mark_safe`, `status_dot_sparkline`), brief↔plan ✓

## Findings

### F1 — Phase execution order causes ImportError on Phase 1

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 Changes Required §1; Phase 2 Implementation Note; ## Progress ordering
- **Detail**: Phase 1's contract adds `from .sparkline import status_dot_sparkline` to `monitor/views.py`. `monitor/sparkline.py` does not exist until Phase 2 creates it. Executing phases in canonical numbered order (1 → 2 → 3 → 4) raises an ImportError at the first request after Phase 1's view change lands. The plan acknowledges this in Phase 2's Implementation Note ("Phase 2 first, then wire Phase 1, or commit both together") but the numbered ordering and ## Progress both list Phase 1 before Phase 2 — `/10x-implement` reads phases sequentially from Progress order.
- **Fix**: Add a prerequisite note to Phase 1's Overview: "This phase must be implemented after Phase 2 (SVG helper) — `views.py` imports `status_dot_sparkline` which requires `monitor/sparkline.py` to exist first." Alternatively swap the phase numbers so the SVG helper is Phase 1 and the view update is Phase 2. Either approach removes the ambiguity for `/10x-implement`.
- **Decision**: PENDING

---

### F2 — rule_history double queryset evaluation contradicts "no extra queries" claim

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 3 Changes Required §4 (rule_history view sparkline); Performance Considerations
- **Detail**: Performance Considerations states "No additional database queries for rule_history sparkline." Phase 3 Step 4 contract calls `reversed(list(results))` which evaluates the sliced queryset once (1 DB hit), but `results` remains the original `rule.results.select_related('run').order_by('-checked_at')[:20]` queryset object. The template `{% for r in results %}` loop re-evaluates it: a second DB hit. Verified against `monitor/views.py:93` (sliced queryset, not a list) and `rule_history.html` (iterates `results` in the table loop).
- **Fix**: Change the Phase 3 Step 4 contract to evaluate the queryset once before the sparkline computation:
  ```python
  results = list(rule.results.select_related('run').order_by('-checked_at')[:20])
  statuses = [r.status for r in reversed(results)]  # oldest-first
  sparkline_svg = mark_safe(status_dot_sparkline(statuses))
  ```
  The template loop then hits the already-evaluated list at zero cost.
- **Decision**: PENDING

---

### F3 — Phase 1 manual verification gates require Phases 2 and 3 to be complete

- **Severity**: 📋 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 Manual Verification; Progress steps 1.3, 1.4
- **Detail**: Phase 1 Manual Verification says "Dashboard loads; each rule row contains a `<svg>` element in the Trend column." This check cannot pass after Phase 1 alone — the Trend column does not exist in the template until Phase 3 and the sparkline function until Phase 2. The post-Phase-1 "pause for manual confirmation" instruction will always block `/10x-implement` because there is nothing visually to confirm at that point. The same SVG-visibility checks already appear correctly in Phase 3 Manual criteria (3.3).
- **Fix**: Replace Phase 1 manual criteria (1.3, 1.4) with what is verifiable after Phase 1 alone: (1.3) "Django dev server starts with no ImportError" and (1.4) "Dashboard responds HTTP 200 without a 500." The SVG visibility checks stay in Phase 3.
- **Decision**: PENDING
```

---

**File: `context/changes/trend-sparklines/change.md`** (updated `status` and `updated`):

```markdown
---
change_id: trend-sparklines
title: Trend sparklines — row count and age history charts in rule list
status: plan_reviewed
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

In the rules table and history view, show a tiny SVG sparkline of the last 20 check results for each rule. Row count over time, age over time. Color: green when OK, red when FAIL. Generated server-side as inline SVG from RuleResult history. No JS chart library needed. Shows trend at a glance without opening history.
```

---

The plan is **REVISE**. Two things need a fix before implementation:

1. **F1 (CRITICAL, LOW effort)**: Add a prerequisite note to Phase 1's Overview making it explicit that Phase 2 must be coded first, so `/10x-implement` doesn't run Phase 1 before `sparkline.py` exists. Swapping phase numbers is the cleanest fix.

2. **F2 (WARNING, LOW effort)**: In Phase 3 Step 4's view contract, assign `results = list(...)` before computing the sparkline so the template loop reuses the evaluated list instead of firing a second query — this keeps the "no extra queries" promise stated in Performance Considerations.

F3 is an observation: Phase 1's manual gates (1.3, 1.4) can't pass until Phase 3 is also done; they should be replaced with checks that are actually verifiable after Phase 1 alone.