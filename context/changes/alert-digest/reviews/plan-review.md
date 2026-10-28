Now I have all the evidence needed. Let me compose the review.

## Review

### Grounding

- `monitor/email_service.py` ✓ — `send_fail_notification` at line 19, `COOLDOWN_HOURS=1` at line 16, `notify_on_fail` guard at line 33
- `monitor/services.py` ✓ — `run_checks_for_user` and `run_all_checks` confirmed with `send_fail_notification` inside rule loops; `select_related('connection')` only in `run_all_checks`
- `monitor/models.py` ✓ — no `UserProfile`; `SlackNotification` exists; `Rule.notify_on_fail` and `Rule.last_notified_at` confirmed
- `monitor/migrations/0012_rule_notify_fields.py` ✓ — confirmed as latest
- `templates/monitor/email/fail_notification.html` + `.txt` ✓ — dark-theme template confirmed
- `templates/base.html` ✓ — sidebar nav confirmed with schedule link pattern; "Schedule" is the last nav item before the Data section
- `monitor/urls.py` ✓ — no `settings/` path exists yet (correct, that's Phase 4)
- `context/foundation/lessons.md` — not present; skip prior-rules scan
- `docs/reference/contract-surfaces.md` — not present; skip contract-surfaces scan

Grounding: 8/8 paths ✓, 6/6 symbols ✓, brief↔plan ✓

---

### Findings

**F1 — `notify_on_fail=False` rules will appear in digest emails**

The per-rule opt-in guard lives in `email_service.py:33`: `if not rule.notify_on_fail: return False`. Immediate mode never emails about rules where this flag is False. But Phase 3 (both `run_checks_for_user` item 2 and `run_all_checks` item 3) collects results with `status in (FAIL, ERROR)` with no mention of checking `rule.notify_on_fail`. An implementer following the plan as written will include silent rules in the digest, expanding notification scope for users who opted certain rules out.

Fix: Add `and rule.notify_on_fail` to the condition that appends results to `failing_results` / `digest_pending`, matching the guard already present in `send_fail_notification`.

---

**F2 — `select_related` contract misses `__profile` depth, causing N+1 in `run_all_checks`**

Phase 3, item 3 says to use `select_related('connection', 'user')`. The performance section says `select_related('user')`. Neither reaches the `UserProfile` row — accessing `rule.user.profile.notification_mode` with only `'user'` in `select_related` issues one extra query per rule (N+1 for all rules owned by digest users). The current queryset is `Rule.objects.select_related('connection').all()` (`services.py:run_all_checks`). The correct depth is `select_related('connection', 'user__profile')`.

Fix: In Phase 3, item 3's contract block and in the performance section, change `select_related('connection', 'user')` to `select_related('connection', 'user__profile')`.

---

**F3 — Error branches in `run_checks_for_user` don't assign `db_result` before `continue`**

In `run_checks_for_user`, when `not rule.connection_id` or the URL is empty, the code does `RuleResult.objects.create(...); continue` without assigning the result to a named variable. Phase 3, item 2 says "append `db_result` to `failing_results` when status is FAIL or ERROR" — but an implementer cannot reference `db_result` in those branches because it is never assigned. The result is that configuration-error results (no connection, empty URL) are silently excluded from the digest even for digest-mode users. An implementer following the plan literally would need to infer the fix. The plan should make this explicit.

Fix: Phase 3, item 2 should note: "In the no-connection and empty-URL branches, assign the created result to `db_result` and append to `failing_results` before `continue` if mode is digest."

---

**F4 — `POST` with invalid mode is "400 or silently ignores" — ambiguity should be resolved**

Phase 4, item 1 and the success criteria both allow two different behaviors for an invalid POST value. Both are safe; the ambiguity is just noise. Recommend resolving to "silently ignore and keep existing value" to avoid surfacing a 400 for a user submitting a malformed form.

---

### Verdict

| Dimension | Verdict |
|---|---|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING (F1, F2) |
| Plan Completeness | WARNING (F3, F4) |

**Overall: REVISE** — two concrete behavioral gaps (F1, F2) should be fixed in the plan before implementation begins. F3 and F4 are small completeness notes. The plan's structure, phases, Progress block, and brief↔plan alignment are all clean.

---

Writing the report file and updating change.md now. Since no write tool is available in this context, returning both artifacts here for runtime persistence.

---

**`context/changes/alert-digest/reviews/plan-review.md`**

```markdown
<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Alert Digest

- **Plan**: context/changes/alert-digest/plan.md
- **Mode**: Deep
- **Date**: 2026-10-28
- **Verdict**: REVISE
- **Findings**: 0 critical, 2 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|---|---|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding

8/8 paths ✓, 6/6 symbols ✓, brief↔plan ✓

## Findings

### F1 — `notify_on_fail=False` rules included in digest

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 3, items 2 and 3 — `run_checks_for_user` and `run_all_checks` digest accumulation
- **Detail**: `send_fail_notification` guards on `rule.notify_on_fail` at `email_service.py:33` — rules with that flag False are silently excluded in immediate mode. Phase 3's digest accumulation conditions are `db_result.status in (FAIL, ERROR)` with no `notify_on_fail` check. An implementer following the plan as written will include silent rules in digest emails, expanding notification scope beyond what the user opted into.
- **Fix**: In Phase 3, items 2 and 3, add `rule.notify_on_fail` as a condition for appending to `failing_results` / `digest_pending`: `if db_result.status in (FAIL, ERROR) and rule.notify_on_fail:`. Matches the guard already present in `send_fail_notification`.
- **Decision**: PENDING

---

### F2 — `select_related` missing `__profile` depth causes N+1 in `run_all_checks`

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 3, item 3 contract block and Performance Considerations section
- **Detail**: Current queryset is `Rule.objects.select_related('connection').all()` (`services.py:run_all_checks`). Phase 3, item 3 says to change to `select_related('connection', 'user')`. The Performance section says `select_related('user')`. Neither depth reaches the `UserProfile` row — accessing `rule.user.profile.notification_mode` with only `'user'` in `select_related` issues one extra DB query per rule, N+1 for all rules owned by digest users in `run_all_checks`.
- **Fix**: In Phase 3, item 3's contract block and in the Performance Considerations section, change the queryset to `Rule.objects.select_related('connection', 'user__profile').all()`.
- **Decision**: PENDING

---

### F3 — Error branches in `run_checks_for_user` don't assign `db_result` before `continue`

- **Severity**: 👁 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 3, item 2 — `run_checks_for_user` digest branch
- **Detail**: In `run_checks_for_user`, the no-connection and empty-URL branches do `RuleResult.objects.create(...); continue` without assigning to `db_result`. Phase 3 says "append `db_result` to `failing_results` when status is FAIL or ERROR" but an implementer cannot reference `db_result` in those branches since it is never assigned. Configuration-error results would be silently excluded from digest emails unless the plan makes this explicit.
- **Fix**: Add one sentence to Phase 3, item 2: "In the no-connection and empty-URL early-exit branches, assign the created result to `db_result` and append it to `failing_results` before `continue` when mode is digest."
- **Decision**: PENDING

---

### F4 — POST with invalid mode behavior is unresolved

- **Severity**: 👁 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 4, item 1 and Phase 4 success criteria
- **Detail**: Both the view contract ("returns a 400 or silently ignores") and the test criterion ("returns 400 or is handled safely") allow two different behaviors. Both are safe; the ambiguity is noise that an implementer must resolve at code time.
- **Fix**: Resolve to one choice. Recommended: silently ignore invalid values and redirect back with the existing setting unchanged. Update the view contract and success criterion accordingly.
- **Decision**: PENDING
```

---

**`context/changes/alert-digest/change.md`** (updated):

```markdown
---
change_id: alert-digest
title: Alert digest — group notifications, avoid alert fatigue
status: plan_reviewed
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

Instead of one email/Slack per rule failure, group all FAILs from a single run into one digest message. Options per user: immediate (per rule) or digest (one message per run). For runs with 10+ failures, send summary: "8 rules FAILED, 2 ERROR — see dashboard". Digest includes table of all failures with measured values.
```

---

## Review

- Correct: Plan structure, phases, Progress block, and brief↔plan alignment are all clean. Progress section correctly mirrors every phase and every success criterion with numbered checkboxes. Architecture choice (UserProfile OneToOne, post_save signal, `_get_notification_mode` fallback) is sound and fits the existing codebase. `run_single_rule` correctly excluded from digest scope. Template and sidebar approach matches real base.html structure.
- Finding: **P1** — `notify_on_fail=False` rules included in digest (F1), `email_service.py:33` guard absent from Phase 3 accumulation logic — fix is adding `and rule.notify_on_fail` to the append condition.
- Finding: **P1** — `select_related('connection', 'user')` in Phase 3 item 3 contract should be `select_related('connection', 'user__profile')` to avoid N+1 on profile access in `run_all_checks` (F2).
- Finding: **P2** — Error branches in `run_checks_for_user` don't assign `db_result` before `continue`; plan should note the implementer must assign before appending to `failing_results` (F3).
- Finding: **P2** — POST invalid-mode behavior is left ambiguous between 400 and silent-ignore (F4).
- Merge verdict: **OK with notes** — implement after applying F1 and F2 fixes to the plan; F3 and F4 can be resolved at implementation time.