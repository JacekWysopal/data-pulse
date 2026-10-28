No write tool is available in this session. Per the skill instructions: "If an output path is configured but no write-capable tool is available, return the complete artifact in your final response; the runtime will persist it."

Returning complete artifacts for both output paths:

---

**OUTPUT PATH: `C:/Users/jwysopal/Desktop/10x Devs 4.0/data-pulse/context/changes/email-notifications/reviews/plan-review.md`**

```markdown
<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Email Notifications on FAIL — Implementation Plan

- **Plan**: context/changes/email-notifications/plan.md
- **Mode**: Deep
- **Date**: 2026-10-28
- **Verdict**: REVISE
- **Findings**: 1 critical, 1 warning, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | FAIL |
| Plan Completeness | WARNING |

## Grounding

5/5 paths ✓ (monitor/models.py, monitor/services.py, monitor/forms.py, data_pulse/settings.py, render.yaml), 3/3 symbols ✓ (RuleResult.Status confirmed at models.py:189+, RuleForm.Meta.fields confirmed at forms.py:35, django-environ pattern confirmed in settings.py), brief↔plan ✓

## Findings

### F1 — S-12 prerequisite not merged: Rule.owner FK does not exist

- **Severity**: ❌ CRITICAL
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Blind Spots
- **Location**: Plan Overview / Phase 2 — Email Service / Open Risks & Assumptions
- **Detail**: The plan opens with "This plan assumes S-12 (multi-tenancy) is already merged, so Rule has an owner ForeignKey to django.contrib.auth.User." Evidence shows this assumption is false. `grep` of `monitor/models.py` finds zero matches for `owner` or `ForeignKey.*User` on `Rule`. The `multi-tenancy/change.md` shows `status: planned` — S-12 has not been implemented. Phase 2's `email_service.py` contract accesses `rule.owner` and `rule.owner.email`; at runtime this will raise `AttributeError: 'Rule' object has no attribute 'owner'`. The plan notes this as a risk but does not gate Phase 1 or provide a fallback. Phase 1 can be safely implemented (adding `notify_on_fail` and `last_notified_at` is additive and independent), but Phases 2–5 cannot be completed until S-12 lands.
- **Fix ⭐ Recommended**: Add an explicit prerequisite gate to `change.md` notes and to the plan's Phase 2 overview: "Do not start Phase 2 until multi-tenancy/change.md shows status: implemented." No plan restructuring needed — just make the gate explicit so an implementor running `/10x-implement` does not attempt Phase 2 on the current codebase.
- **Decision**: PENDING

---

### F2 — run_all_checks has 5 create sites, Phase 3 says 4

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Completeness
- **Location**: Phase 3 — Hook into services.py, "run_all_checks hook" section
- **Detail**: Phase 3 states "The loop calls `RuleResult.objects.create(...)` in four branches; all must be covered." The actual code at `monitor/services.py:263–314` has **five** `RuleResult.objects.create()` calls: lines 273 (no connection), 282 (empty URL), 298 (conn_error branch), 305 (successful check), and 314 (outer `except Exception`). The fifth create (line 314) is in the outer `except Exception` block that catches any unhandled exception for a given rule — it creates a result with `RuleResult.Status.ERROR` but does not capture the return value, so the notification hook cannot be added without also capturing the result. The Phase 3 contract does mention capturing return values for branches that don't already do so, but the count mismatch means an implementor following "four branches" literally will miss line 314.
- **Fix**: In Phase 3 "run_all_checks hook" section, change "four branches" to "five branches" and explicitly list line 314 (outer `except Exception`) as the fifth, noting that the return value must be captured before the notification check.
- **Decision**: PENDING

---

### F3 — Stale line numbers for services.py functions in References

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Current State Analysis section; References section
- **Detail**: The plan states `run_single_rule(rule)` is at `services.py:130–164` and `run_all_checks()` is at `services.py:167–228`. Actual code has `run_single_rule` starting at line 215 and `run_all_checks` at line 263. Line numbers appear to have been captured at an earlier commit (research was done at SHA 53d06be) before additional code was added to services.py. An implementor opening services.py at the referenced lines will land in the middle of a different function.
- **Fix**: Update Current State Analysis and References to `services.py:215–261` (run_single_rule) and `services.py:263–314` (run_all_checks).
- **Decision**: PENDING
```

---

**OUTPUT PATH: `C:/Users/jwysopal/Desktop/10x Devs 4.0/data-pulse/context/changes/email-notifications/change.md`**

```markdown
---
change_id: email-notifications
title: Email notifications on FAIL — send alert when rule check fails
status: plan_reviewed
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

When a rule result is FAIL or ERROR, send an email to the rule owner.
Requires: email backend config (SMTP or SES), per-rule notification toggle, cooldown to avoid spam,
email template. Depends on multi-tenancy (need user email address).
```

---

## Review

**Correct:**
- End state is specific and observable: "user sees a Notify on failure checkbox; FAIL/ERROR triggers email to owner; 1-hour cooldown suppresses repeats." Fully satisfies the requirement.
- Architecture is lean: thin `email_service.py` module, no new model, cooldown via one nullable field. Matches the project's "add abstraction when needed" pattern.
- Progress section is well-formed: one `## Progress` heading at the bottom, each `## Phase N:` has a matching `### Phase N:` in Progress, `#### Automated` / `#### Manual` split is correct, all items are `- [ ]`, no `- [ ]` items appear outside the Progress block.
- Settings fallback pattern (console when `EMAIL_BACKEND` not set) is correct and matches existing `django-environ` usage.

**Finding: P0 — S-12 not merged, `Rule.owner` FK absent**
`monitor/models.py` confirms no `owner` field on `Rule`. `multi-tenancy/change.md` is `status: planned`. Phase 2's `email_service.py` accesses `rule.owner.email` — this raises `AttributeError` on the current codebase. Phase 1 is safe to implement now; Phases 2–5 are blocked. Fix: add explicit gate in plan Phase 2 overview: "Prerequisites: S-12 change must be status: implemented before starting this phase."

**Finding: P1 — `run_all_checks` has 5 create sites, Phase 3 says 4**
`monitor/services.py:263–314` has five `RuleResult.objects.create()` calls (lines 273, 282, 298, 305, 314). Phase 3 says "four branches." Line 314 (outer `except Exception`) will be missed. Fix: change "four branches" to "five branches" in Phase 3, explicitly list line 314.

**Finding: P2 — Stale line number references**
Plan references `run_single_rule` at lines 130–164 and `run_all_checks` at 167–228; actual positions are 215 and 263 respectively. Minor — implementor lands in the wrong place.

**Merge verdict:** REVISE — the S-12 prerequisite block must be made explicit in Phase 2 before implementation begins. The `run_all_checks` count fix should also be applied to prevent a missed notification hook on the outer exception branch.