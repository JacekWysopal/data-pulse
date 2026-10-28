Now I'll write the implementation review and update change.md. Based on the tools available to me (I can see `find`, `grep`, `read`, `ls`, `contact_supervisor`, `watchdog_diff` in the tool declarations), I don't have a write/edit tool directly available. Per the skill instruction: "If an output path is configured but no write-capable tool is available, return the complete artifact in your final response; the runtime will persist it."

I'll return the complete artifacts:

---

## Review

### Summary of Evidence

All 12 named files were read in full (services.py was truncated at 50KB; key patterns verified via `grep`). Three additional files were discovered and read: `monitor/email_service.py`, `monitor/migrations/0012_rule_notify_fields.py`, and the `management/commands/` directory listing.

---

<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Multi-tenancy — user accounts, per-user rules and connections

- **Plan**: `context/changes/multi-tenancy/plan.md`
- **Scope**: Full plan (Phases 1–4)
- **Reviewed phases**: 1, 2, 3, 4
- **Date**: 2026-10-29
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 3 warnings, 3 observations

## Verdicts

| Dimension | Verdict |
|---|---|
| Plan Adherence | WARNING |
| Scope Discipline | WARNING |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

## Findings

### F1 — Email notification feature added outside plan scope

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Scope Discipline
- **Location**: `monitor/email_service.py` (whole file), `monitor/migrations/0012_rule_notify_fields.py`, `monitor/models.py:167-175` (`notify_on_fail`, `last_notified_at`), `monitor/services.py:16` (import + ~8 call sites)
- **Detail**: The plan scoped email exclusively to backend configuration (`EMAIL_BACKEND`, `EMAIL_HOST`, etc. in settings.py) for the password reset flow. The implementation adds a complete parallel feature: `email_service.py` with a `send_fail_notification()` function, two new Rule fields (`notify_on_fail`, `last_notified_at`), migration `0012`, and calls to `send_fail_notification` woven into `run_single_rule`, `run_checks_for_user`, and `run_all_checks` throughout services.py. This is entirely unplanned. The plan's "What We're NOT Doing" list includes "Slack / email notifications (separate slices S-13, S-16)" which confirms this feature was explicitly deferred. The code is internally consistent and the DB migration is correct, but no tests cover this path, it is untested under the multi-tenancy change, and it conflicts with the explicit scope boundary.
- **Fix A ⭐ Recommended**: Retain the feature but document it as an addendum to the plan (update plan.md `## What We're NOT Doing` to note the exception) and add tests to `monitor/tests.py` covering `send_fail_notification` (at minimum: cooldown respected, skips when `notify_on_fail=False`, skips when user has no email).
  - Strength: The code is correct and internally consistent; removing it would lose real work. Formalising the scope change preserves the plan as source of truth.
  - Tradeoff: Plan becomes a moving target; reviewers of the next change may be surprised.
  - Confidence: HIGH — the code works and the migration is clean; the only gap is tests and plan acknowledgement.
  - Blind spot: Email template files for fail notifications (`monitor/email/fail_notification.txt` and `.html`) were not confirmed to exist; if they are missing, `send_fail_notification` will raise `TemplateDoesNotExist` at runtime.
- **Fix B**: Remove `email_service.py`, `0012`, the two Rule fields, and all `send_fail_notification` calls; defer to the planned S-13/S-16 slices.
  - Strength: Restores strict scope; future email slice starts clean.
  - Tradeoff: Loses implemented work and requires reverting the migration (data-destructive on production).
  - Confidence: MEDIUM — depends on whether there is any user-visible notification UI already exposed.
  - Blind spot: Haven't checked whether any templates or forms now reference `notify_on_fail`.
- **Decision**: PENDING

### F2 — `api_schema_columns` missing from PerUserIsolationTest

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Adherence / Success Criteria
- **Location**: `monitor/tests.py` — `PerUserIsolationTest` class (end of file); `monitor/views.py:152-160` (`api_schema_columns`)
- **Detail**: The plan (Phase 4, "New: PerUserIsolationTest") lists eight isolation tests: `test_api_schema_tables_other_user_404` is present (confirmed in tests.py), but `test_api_schema_columns_other_user_404` is absent. The `api_schema_columns` view is correctly protected in views.py:154 (`get_object_or_404(Connection, pk=conn_id, user=request.user)`), so the IDOR is actually closed. The gap is test coverage only, not a security hole. However, the plan explicitly specifies this endpoint in the contract coverage ("api_schema_columns — same ownership check").
- **Fix**: Add a single test to `PerUserIsolationTest`:
  ```python
  def test_api_schema_columns_other_user_404(self):
      r = self.client.get(f'/api/schema/{self.b_conn.pk}/columns/public/orders/')
      self.assertEqual(r.status_code, 404)
  ```
  - Strength: Closes the explicit plan gap; cost is one test method.
  - Tradeoff: None significant.
  - Confidence: HIGH — the view guard is already in place; test will pass immediately.
  - Blind spot: None significant.
- **Decision**: PENDING

### F3 — `run_all_checks` dead import in views.py

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `monitor/views.py:13`
- **Detail**: `from .services import ... run_all_checks ...` — `run_all_checks` is imported but never referenced in views.py. The view was correctly updated to call `run_checks_for_user(request.user)` instead (views.py:69). The dead import is harmless at runtime but misleading: it suggests `run_all_checks` is still used in views, and linters (flake8/ruff) will flag it as F401.
- **Fix**: Remove `run_all_checks` from the import on line 13.
  ```python
  # Before
  from .services import get_schema_columns, get_schema_tables, run_all_checks, run_checks_for_user, run_single_rule
  # After
  from .services import get_schema_columns, get_schema_tables, run_checks_for_user, run_single_rule
  ```
- **Decision**: PENDING

### F4 — Migration numbering drift from plan

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: `monitor/migrations/0009_user_fk_nullable.py`, `0010_assign_to_superuser.py`, `0011_user_fk_required.py`; plan.md Phase 1 and 3 references `0005`, `0006`, `0007`
- **Detail**: The plan was authored when the last migration was `0004`. Six more migrations existed before this change landed (0005–0008), so the actual migration numbers are 0009/0010/0011 instead of 0005/0006/0007. The migration chain and logic are correct; the plan references are stale. The progress section marks these steps `[x]` correctly. This is documentation drift only, not a functional issue.
- **Fix**: Update the three migration filename references in `plan.md` (Phase 1 section 2 and Phase 3 section 1) to use the actual numbers `0009`, `0010`, `0011`.
- **Decision**: PENDING

### F5 — Fail notification email templates existence unconfirmed

- **Severity**: 💬 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: `monitor/email_service.py:48-49` (`render_to_string('monitor/email/fail_notification.txt'` and `.html`)
- **Detail**: `send_fail_notification` calls `render_to_string('monitor/email/fail_notification.txt', context)` and `render_to_string('monitor/email/fail_notification.html', context)`. These template paths were not found in the file listing of `monitor/` or `templates/`. If the templates don't exist, every call to `send_fail_notification` will raise `TemplateDoesNotExist` at runtime — causing all rule runs to fail with an uncaught exception. The `except Exception` wrapper in `email_service.py` catches it and logs it, so it degrades gracefully, but every failed/errored rule would silently log an error even when `notify_on_fail=True` is the user's intent.
- **Fix**: Confirm the templates exist at `templates/monitor/email/fail_notification.txt` and `templates/monitor/email/fail_notification.html`. If they don't exist, create them (or remove the `send_fail_notification` integration per F1-Fix-B).
- **Decision**: PENDING

### F6 — Login.html password label in Polish ("Hasło") 

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `templates/login.html:207` (`<label for="id_password">Hasło</label>`)
- **Detail**: The login template is otherwise in English (title "Sign in", username label "Username", button "Sign in →", error text mixed with Polish). The password label renders as "Hasło" and the error message is "Nieprawidłowy login lub hasło." — Polish strings in an otherwise English-language template. The signup.html is fully English. This is a pre-existing inconsistency not introduced by this change, but it's visible to new users created via the new signup flow.
- **Fix**: Change `Hasło` to `Password` and the error string to `Invalid username or password.` in `templates/login.html`.
- **Decision**: PENDING

---

## Correct (evidence)

- **IDOR closure is complete**: All 13 view functions verified — every `get_object_or_404` call uses `user=request.user`, both list views filter by user, and create views do `commit=False` + `instance.user = request.user` before `instance.save()`. The `api_schema_tables` and `api_schema_columns` ownership gates (`get_object_or_404(Connection, pk=conn_id, user=request.user)` at views.py:138 and 154) are in place before any service call.
- **Migration safety**: Three-step migration strategy (nullable → data → required) is correctly implemented. `0009` adds nullable FKs and replaces the global `unique=True` on `Connection.name` with `unique_together = [('user', 'name')]`. `0010` runs `assign_to_superuser` with a no-op reverse. `0011` makes FKs non-nullable. The deployment ordering note in plan.md matches what was implemented.
- **run_checks_for_user isolation**: `services.py` adds a correct `run_checks_for_user(user)` function that filters `Rule.objects.filter(user=user)`. `run_all_checks()` is left untouched for the cron path. The view at views.py:69 calls `run_checks_for_user(request.user)` — confirmed via grep.
- **Password reset URL wiring**: All four password reset views are wired in `data_pulse/urls.py` with correct template names. Templates exist in `templates/registration/`. The email template (`password_reset_email.html`) correctly uses `{{ protocol }}://{{ domain }}{% url 'password_reset_confirm' uidb64=uid token=token %}`.
- **User isolation in forms**: `RuleForm.__init__` pops `user` from kwargs and filters the `connection` queryset to `Connection.objects.filter(user=user)`. All view calls to `RuleForm` pass `user=request.user`.
- **Signup view**: Correctly guards against already-authenticated users (`redirect('monitor:dashboard')`), calls `login(request, user)` after `form.save()`, and is not decorated with `@login_required`.
- **Test coverage**: `PerUserIsolationTest` covers 8 of the 9 IDOR endpoints (api_schema_columns missing — see F2). `SignupViewTest` covers 5 cases. `PasswordResetURLTest` covers 3 URL smoke tests. All existing test helpers updated with `user=` parameter.
- **EMAIL_BACKEND settings**: Correctly uses `env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')` and all 6 email settings are present. HTTPS security block (`if not DEBUG:`) correctly sets all 5 production cookie/HTTPS settings.
- **`Connection.name` unique constraint**: `unique=True` correctly removed from field definition; `unique_together = [('user', 'name')]` added to `Meta`. Confirmed in models.py and migration 0009.

---

## Save path: `context/changes/multi-tenancy/reviews/impl-review.md`
## change.md update: `status: impl_reviewed`, `updated: 2026-10-29`

---

**change.md (updated content):**

```markdown
---
change_id: multi-tenancy
title: Multi-tenancy — user accounts, per-user rules and connections
status: impl_reviewed
created: 2026-10-28
updated: 2026-10-29
archived_at: null
---

## Notes

Full user registration and login. Each user sees only their own Rules and Connections.
Requires: user registration form, email verification or simple signup, Rule/Connection FK to User,
migration to reassign existing data, full auth flow (signup, login, logout, password reset).
This is the most impactful change — blocks per-user data isolation for all other features.
```

---

Since I do not have a write tool available in this session, the complete artifacts are returned above for the runtime to persist. Per the skill instructions:

> If an output path is configured but no write-capable tool is available, return the complete artifact in your final response; the runtime will persist it.

The review report (to be saved at `context/changes/multi-tenancy/reviews/impl-review.md`) and the updated `change.md` (with `status: impl_reviewed`) are the two files above.

---

## Review

- **Correct**: IDOR closure is complete across all 13 views (verified by reading each view function). Migration three-step strategy is correctly implemented and safely sequenced. `run_checks_for_user` correctly scopes to `request.user` while the cron path uses the unscoped `run_all_checks`. Password reset flow, signup view, email settings, HTTPS security settings, and test classes (SignupViewTest, PasswordResetURLTest, PerUserIsolationTest) all match plan contracts. `RuleForm` user-scoped queryset is correctly implemented.

- **Finding F1**: ⚠️ WARNING, 🔬 HIGH — `email_service.py` + migration `0012_rule_notify_fields` + `notify_on_fail`/`last_notified_at` on Rule + `send_fail_notification` calls woven through `services.py` are entirely outside plan scope (plan explicitly deferred email notifications to S-13/S-16). Code is internally consistent and the migration is correct, but no tests cover this path. Smallest fix: document as addendum in plan.md and add tests for the notification path, OR remove everything and defer to the planned slices.

- **Finding F2**: ⚠️ WARNING, 🔎 MEDIUM — `PerUserIsolationTest` is missing `test_api_schema_columns_other_user_404`. The view is correctly protected (views.py:154 has the ownership gate) but the plan's test contract explicitly includes it. One test method closes this gap.

- **Finding F3**: ⚠️ WARNING, 🏃 LOW — `run_all_checks` is a dead import in `views.py:13`. The view correctly calls `run_checks_for_user` instead. Remove from the import line.

- **Finding F4**: 💬 OBSERVATION — Migration numbers in plan.md (0005/0006/0007) don't match actual filenames (0009/0010/0011) because prior migrations existed. Documentation drift only; logic is correct.

- **Finding F5**: 💬 OBSERVATION — `email_service.py` calls `render_to_string('monitor/email/fail_notification.txt')` and `.html`; these template files were not found in the directory listing. If absent, the except-handler degrades gracefully but every `notify_on_fail=True` rule silently fails to notify.

- **Finding F6**: 💬 OBSERVATION — `templates/login.html` contains Polish strings ("Hasło", "Nieprawidłowy login lub hasło") — pre-existing inconsistency now more visible to new users from the signup flow.

- **Merge verdict**: NEEDS ATTENTION — F1 (out-of-scope email feature with no tests, introduced alongside this change) and F2 (missing isolation test for `api_schema_columns`) should be resolved before release. F3 is a one-line fix. F1 is the deciding factor: it crosses the explicit "What We're NOT Doing" boundary and ships untested code on a critical path (every rule execution).