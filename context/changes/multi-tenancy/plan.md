# Multi-tenancy Implementation Plan

## Overview

Add full multi-tenancy to DataPulse: user registration, per-user Rules and Connections, and IDOR-safe view isolation. The Django auth framework covers all primitives (User model, session auth, password hashing, password reset). No new packages are required. Four phases deliver a deployable, user-isolated application on Render.

## Current State Analysis

DataPulse has login/logout wired (`data_pulse/urls.py:4-5`) and `@login_required` on all 13 view functions (`monitor/views.py:9-15`), but zero user isolation. Neither `Rule` (`monitor/models.py:47-80`) nor `Connection` (`monitor/models.py:28-40`) has a `user` FK. Every logged-in user sees every record. There is no signup view, no `/signup/` URL, and no password reset flow. `Connection.name` has a global `unique=True` constraint (`monitor/models.py:30`) that conflicts with two users naming a connection `production`. Production HTTPS security settings (`SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`) are absent from `data_pulse/settings.py`.

### Key Discoveries:

- `monitor/models.py:30` — `Connection.name` is `unique=True` globally; must become `unique_together = [('user', 'name')]`
- `monitor/migrations/` — last migration is `0004`; next is `0005`; two-step FK addition (nullable → data migration → required) needs migrations `0005`, `0006`, `0007`
- `monitor/forms.py:42` — `RuleForm` shows all `Connection` objects; must be filtered to the current user
- `monitor/services.py:263` — `run_all_checks()` fetches `Rule.objects.select_related('connection').all()` globally; intentional for the **cron path** (`run_scheduled` management command, a background job not tied to any user). The `run_checks` view (views.py:47-49) calls `run_all_checks()` directly — this is **UI-triggered**, not cron, and is an IDOR/cross-tenant execution risk: any logged-in user pressing "Run Checks" causes DataPulse to open connections to every other user's PostgreSQL databases using their stored credentials. Phase 3 must close this by adding a `run_checks_for_user(user)` wrapper in services.py and calling it from the view; the cron path continues calling the unscoped `run_all_checks()`
- `data_pulse/settings.py` — uses `django-environ`; new settings read from `.env` with `env()` defaults
- `monitor/tests.py` — existing `make_rule()` / `make_connection()` helpers create objects without a `user`; will break after migration `0007` makes FK required; updated in Phase 4

## Desired End State

Any visitor can register at `/signup/` using a username and password. After login, each user sees only their own Rules and Connections; no URL manipulation can expose another user's data (IDOR closed). Attempting to delete a user who still owns Rules or Connections raises a `ProtectedError` (data not silently deleted). A basic password reset flow exists at `/password-reset/` (email-based, SMTP configurable via env). All session and CSRF cookies are marked `Secure` in production.

### Key Discoveries:

- All 13 view functions need `user=request.user` added to `get_object_or_404` calls and queryset filters
- `rule_create` and `connection_create` need `form.save(commit=False)` + assign `user = request.user` before `form.save()`
- Password reset templates live in `templates/registration/`; Django resolves them via `DIRS=[BASE_DIR / 'templates']`

## What We're NOT Doing

- Email verification on signup (MVP: `UserCreationForm` only, no token email)
- Custom User model (Django's `auth.User` is sufficient)
- Per-user admin isolation (Django admin shows all records to staff; acceptable)
- Changing `run_all_checks()` for the **cron path** (keeps running all users' scheduled rules unscoped — background job, not user-triggered). The UI-triggered `run_checks` view is a separate path fixed in Phase 3 via a new `run_checks_for_user(user)` service wrapper.
- MySQL / alternative database support (separate slice S-14)
- Slack / email notifications (separate slices S-13, S-16)

## Implementation Approach

Two-step DB migration strategy: add nullable FKs first (`0005`), run a data migration to assign existing rows to the first superuser (`0006`), then tighten FKs to non-nullable in Phase 3 after views are updated to always set `user` on create (`0007`). This avoids a deployment window where views create userless rows into a required-FK column.

---

## Phase 1: User FK Migration

### Overview

Add `user` ForeignKey to `Rule` and `Connection` with `null=True` initially. Run a data migration that assigns all existing rows to the first superuser. Change `Connection.name` from globally unique to `unique_together = [('user', 'name')]`.

### Changes Required:

#### 1. Model changes

**File**: `monitor/models.py`

**Intent**: Add nullable `user` FK to both `Connection` and `Rule` with `on_delete=PROTECT` (prevents accidental user deletion while owned data exists). Change `Connection` Meta to use `unique_together` instead of `unique=True` on `name`.

**Contract**:
```python
# Connection model — add before created_at:
user = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.PROTECT,
    null=True, blank=True,
    related_name='connections',
)

# Connection.Meta — remove unique=True from name CharField, add:
class Meta:
    ordering = ['name']
    unique_together = [('user', 'name')]

# Rule model — add before created_at:
user = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.PROTECT,
    null=True, blank=True,
    related_name='rules',
)
```

#### 2. Migration 0005 — nullable user FK

**File**: `monitor/migrations/0005_user_fk_nullable.py`

**Intent**: Schema migration that adds the nullable `user` column to both tables and replaces the global `unique` constraint on `Connection.name` with `unique_together = [('user', 'name')]`.

**Contract**: Use `makemigrations` after model edits to auto-generate; verify it includes `AddField` for `user` on both models and `AlterUniqueTogether` on `Connection`. Do not hand-write if `makemigrations` produces a correct migration.

#### 3. Migration 0006 — data migration: assign to superuser

**File**: `monitor/migrations/0006_assign_to_superuser.py`

**Intent**: Assign all existing `Rule` and `Connection` rows with `user=None` to the first superuser (ordered by `pk`). If no superuser exists (fresh install), rows remain `None` — they become unreachable via normal views, which is acceptable.

**Contract**:
```python
from django.db import migrations

def assign_to_superuser(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Rule = apps.get_model('monitor', 'Rule')
    Connection = apps.get_model('monitor', 'Connection')
    superuser = User.objects.filter(is_superuser=True).order_by('pk').first()
    if superuser:
        Rule.objects.filter(user=None).update(user=superuser)
        Connection.objects.filter(user=None).update(user=superuser)

def reverse_assign(apps, schema_editor):
    pass  # irreversible data migration; reverse is a no-op

class Migration(migrations.Migration):
    dependencies = [('monitor', '0005_user_fk_nullable')]
    operations = [migrations.RunPython(assign_to_superuser, reverse_assign)]
```

### Success Criteria:

#### Automated Verification:

- Migrations apply cleanly: `python manage.py migrate --run-syncdb`
- Migration `0005` adds `user_id` columns to both tables: `python manage.py sqlmigrate monitor 0005`
- Migration `0006` runs without error; verify in Django shell: `from monitor.models import Rule; Rule.objects.filter(user=None).count()` returns 0 (if a superuser exists)
- All existing tests pass: `python manage.py test monitor`

#### Manual Verification:

- After `migrate`, `Rule` and `Connection` rows in the admin show a `user` value equal to the first superuser
- Creating a new Rule/Connection via admin sets the user FK (nullable at this point)

---

## Phase 2: Registration & Auth Flow

### Overview

Add public signup at `/signup/`, include Django's built-in password reset flow (4 URLs), configure email backend via env, add production HTTPS security settings, and update the login template with a signup link.

### Changes Required:

#### 1. Settings — email backend and HTTPS security

**File**: `data_pulse/settings.py`

**Intent**: Add email settings (default to console backend for dev; SMTP configured via env for production). Add production-only HTTPS security settings guarded by `if not DEBUG`.

**Contract**:
```python
# Email — add after AUTH_PASSWORD_VALIDATORS block:
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env('EMAIL_PORT', cast=int, default=587)
EMAIL_USE_TLS = env('EMAIL_USE_TLS', cast=bool, default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@datapulse.app')

# HTTPS security — add at the end of settings.py:
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
```

#### 2. URLs — signup and password reset

**File**: `data_pulse/urls.py`

**Intent**: Wire `/signup/` to the new signup view. Include Django's four password reset views under `/password-reset/` using the project's `templates/registration/` directory.

**Contract**: Add before `include('monitor.urls')`:
```python
path('signup/', views.signup, name='signup'),
path('password-reset/', include([
    path('', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset_form.html',
        email_template_name='registration/password_reset_email.html',
        subject_template_name='registration/password_reset_subject.txt',
    ), name='password_reset'),
    path('done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html',
    ), name='password_reset_done'),
    path('<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html',
    ), name='password_reset_confirm'),
    path('complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html',
    ), name='password_reset_complete'),
])),
```

Also import `from monitor import views` and add `from django.contrib.auth import views as auth_views` at top.

#### 3. Signup view

**File**: `monitor/views.py`

**Intent**: Add a public `signup` view (no `@login_required`) that renders a `UserCreationForm`, creates the user on valid POST, and redirects to `LOGIN_REDIRECT_URL` on success.

**Contract**:
```python
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm

def signup(request):
    if request.user.is_authenticated:
        return redirect('monitor:dashboard')
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = UserCreationForm()
    return render(request, 'signup.html', {'form': form})
```

#### 4. Signup template

**File**: `templates/signup.html`

**Intent**: New signup page that matches `login.html` style — same base layout, form fields rendered with Bootstrap classes, CSRF token, and a "Back to login" link.

**Contract**: Copy structure from `templates/login.html`. Form action posts to `{% url 'signup' %}`. Include `{% csrf_token %}`, render all form fields, add a link `Already have an account? <a href="{% url 'login' %}">Sign in</a>`.

#### 5. Login template — signup link

**File**: `templates/login.html`

**Intent**: Add a "Don't have an account? Sign up" link below the login form, and a "Forgot password?" link above the submit button.

**Contract**: Add below the submit button:
```html
<a href="{% url 'signup' %}">Don't have an account? Sign up</a>
<a href="{% url 'password_reset' %}">Forgot your password?</a>
```

#### 6. Password reset templates

**Files**: `templates/registration/password_reset_form.html`, `templates/registration/password_reset_done.html`, `templates/registration/password_reset_confirm.html`, `templates/registration/password_reset_complete.html`, `templates/registration/password_reset_email.html`, `templates/registration/password_reset_subject.txt`

**Intent**: Minimal functional templates for the four-step password reset flow. Each page matches the project's Bootstrap style. The email template sends a plain-text reset link.

**Contract**: `password_reset_form.html` — renders `{{ form }}` with the email field; `password_reset_done.html` — confirms email sent; `password_reset_confirm.html` — renders `{{ form }}` for new password; `password_reset_complete.html` — confirms success with login link. `password_reset_email.html` — plain text, includes `{{ protocol }}://{{ domain }}{% url 'password_reset_confirm' uidb64=uid token=token %}`. `password_reset_subject.txt` — one-line subject: `DataPulse — password reset`.

### Success Criteria:

#### Automated Verification:

- All existing tests pass: `python manage.py test monitor`
- `/signup/` returns 200: basic GET smoke check — run `python manage.py test monitor.tests.SignupViewTest.test_signup_get_200` (the class is written in Phase 4 but can be targeted early here to verify signup is not broken before Phase 3 modifies views.py)
- `/password-reset/` returns 200: `python manage.py runserver` + curl or test

#### Manual Verification:

- Open `/signup/` — form renders with username + password fields, no errors
- Submit valid signup data — user created, redirected to dashboard
- Open `/login/` — "Sign up" and "Forgot password?" links are visible
- Open `/password-reset/` — password reset form renders
- In dev, submitting password reset prints email token to console (EMAIL_BACKEND=console)

---

## Phase 3: View Isolation & IDOR Fix

### Overview

Filter all 13 view querysets by `request.user`. Set `user = request.user` on `rule_create` and `connection_create` before saving. Add `user=request.user` to all `get_object_or_404` calls. Pass `user` to `RuleForm` to scope its connection dropdown. Add migration `0007` to make the `user` FK required (non-nullable).

### Changes Required:

#### 1. Migration 0007 — make user FK required

**File**: `monitor/migrations/0007_user_fk_required.py`

**Intent**: Tighten `user` FK on both models to `null=False`. Safe to run only after all create views set `user` on save (done in this same phase).

**Contract**: `AlterField` on `Rule.user` and `Connection.user`, removing `null=True, blank=True`. `on_delete=PROTECT` remains.

#### 2. View isolation

**File**: `monitor/views.py`

**Intent**: Every queryset and `get_object_or_404` that touches `Rule` or `Connection` must be scoped to `request.user`. On create views, set `instance.user = request.user` before `form.save()`.

**Contract** — change each view as follows (all changes are in `monitor/views.py`):

- `dashboard` — change `Rule.objects.select_related('connection').prefetch_related('results').all()` → add `.filter(user=request.user)`. Note: `last_run = CheckRun.objects.first()` shows the global last run across all users (CheckRun has no `user` FK — out of scope for this change; acceptable for MVP, track for post-MVP cleanup).
- `run_checks` — **IDOR risk**: this view is UI-triggered, not cron. Replace the `run_all_checks()` call with `run_checks_for_user(request.user)` (new function in services.py — see section 3 below). The cron management command (`run_scheduled`) continues calling the unscoped `run_all_checks()` with no change.
- `run_single` — change `get_object_or_404(Rule, pk=rule_id)` → `get_object_or_404(Rule, pk=rule_id, user=request.user)`
- `rule_history` — same `get_object_or_404` pattern
- `rule_create` — change `form.save()` to `form.save(commit=False)` → set `form.instance.user = request.user` → call `form.instance.save()`. Also pass `user=request.user` to `RuleForm(...)` in both GET and POST branches.
- `rule_edit` — `get_object_or_404(Rule, pk=rule_id, user=request.user)`. Pass `user=request.user` to `RuleForm(...)`.
- `rule_delete` — `get_object_or_404(Rule, pk=rule_id, user=request.user)`
- `api_schema_tables` — add `get_object_or_404(Connection, pk=conn_id, user=request.user)` before the cache/service call
- `api_schema_columns` — same ownership check
- `connection_list` — change `Connection.objects.prefetch_related('rules').all()` → add `.filter(user=request.user)`
- `connection_create` — change `form.save()` to `form.save(commit=False)` → set `form.instance.user = request.user` → call `form.instance.save()`
- `connection_edit` — `get_object_or_404(Connection, pk=conn_id, user=request.user)`
- `connection_delete` — same

#### 3. run_checks_for_user service wrapper

**File**: `monitor/services.py`

**Intent**: Add a `run_checks_for_user(user)` function that scopes the rule queryset to the given user. This closes the cross-tenant execution gap for the UI-triggered `run_checks` view. The existing `run_all_checks()` function is left **untouched** — the cron management command (`run_scheduled`) relies on it to process every user's scheduled rules.

**Contract**:
```python
def run_checks_for_user(user) -> CheckRun:
    run = CheckRun.objects.create()
    rules = Rule.objects.filter(user=user).select_related('connection')
    # remainder of logic mirrors run_all_checks() for the user-scoped rule set
    ...
    return run
```
Alternatively, add a `user=None` parameter to `run_all_checks()` and, when provided, apply `.filter(user=user)` to the queryset. Either approach is acceptable; the key invariant is: the view passes `request.user`, the cron path passes nothing (unscoped).

#### 4. RuleForm connection queryset scoping

**File**: `monitor/forms.py`

**Intent**: `RuleForm.__init__` accepts a `user` keyword argument and filters the `connection` field queryset to only that user's connections. When `user=None` (e.g. admin), the full queryset is shown.

**Contract**:
```python
def __init__(self, *args, **kwargs):
    user = kwargs.pop('user', None)
    super().__init__(*args, **kwargs)
    self.fields['connection'].required = True
    self.fields['connection'].empty_label = '— Select a connection —'
    if user is not None:
        self.fields['connection'].queryset = Connection.objects.filter(user=user)
```

### Success Criteria:

#### Automated Verification:

- Migration `0007` applies cleanly: `python manage.py migrate`
- All updated view tests pass (after Phase 4 test updates): `python manage.py test monitor`
- No `Rule` or `Connection` rows have `user=None` after migration: verify in shell

#### Manual Verification:

- Log in as User A; create a rule. Log in as User B — User A's rule is not visible on dashboard
- User B cannot access User A's rule via direct URL (e.g. `/rules/1/edit/`) — gets 404, not 403 or the rule content
- Rule creation form connection dropdown shows only User A's connections when logged in as User A
- "Run Checks" button (UI) only runs checks for the logged-in user's rules — verify by checking that `RuleResult` records created after button press belong only to the logged-in user's rules
- Cron command still runs all scheduled rules regardless of user: `python manage.py run_scheduled`

---

## Phase 4: Tests

### Overview

Add new test classes for signup, password reset URLs, and per-user isolation (IDOR). Update existing helper functions and test classes that create `Rule`/`Connection` objects without a `user` — these will fail against migration `0007`'s non-nullable FK.

### Changes Required:

#### 1. Update test helpers

**File**: `monitor/tests.py`

**Intent**: Update `make_rule()` and `make_connection()` to accept an optional `user` parameter. All callers in existing tests that create objects for view tests must pass `user=self.user`.

**Contract**: Add `user=None` parameter to both helper signatures. Pass it to `Rule.objects.create(user=user, ...)` and `Connection.objects.create(user=user, ...)`.

Note: Service-layer tests (`CheckVolumeFreshnessTest`, `RunAllChecksTest`, etc.) create `Rule`/`Connection` via helpers without a user context. These must be updated to supply a user or create one inline. The simplest fix: create a shared `self.user` in `setUpTestData` for each affected class.

#### 2. Update existing view tests

**File**: `monitor/tests.py`

**Intent**: Existing `DashboardViewTest`, `RuleCRUDViewTest`, `ConnectionCRUDViewTest`, `SchemaAPITest`, `RunChecksViewTest`, and `RunScheduledCommandTest` create rules/connections with no user. After `0007`, these calls fail. Update them to pass `user=self.user`.

**Contract**: In `setUp()` for each class, `self.user = User.objects.create_user(...)` already exists. Pass it to `make_rule(user=self.user)` and `make_connection(user=self.user)`. Also update `RuleCRUDViewTest.test_rule_create_post_*` — the POST data doesn't need to change (user is set in the view), but ensure the asserted `Rule` has `user=self.user`.

#### 3. New: SignupViewTest

**File**: `monitor/tests.py`

**Intent**: Test the signup flow — GET renders form, valid POST creates user and logs in, invalid POST (mismatched passwords) re-renders with errors.

**Contract**: New `class SignupViewTest(TestCase)` with:
- `test_signup_get_200` — GET `/signup/` returns 200
- `test_signup_post_valid_creates_user` — POST with valid data → user created, redirected to `/`
- `test_signup_post_invalid_shows_form` — POST with mismatched passwords → 200, `User` count unchanged
- `test_signup_redirects_authenticated_user` — logged-in user GETting `/signup/` redirects to dashboard
- `test_signup_page_not_accessible_with_bad_data` — missing username → form invalid

#### 4. New: PasswordResetURLTest

**File**: `monitor/tests.py`

**Intent**: Verify that the four password reset URLs are wired and return expected status codes.

**Contract**: New `class PasswordResetURLTest(TestCase)` with:
- `test_password_reset_form_200` — GET `/password-reset/` returns 200
- `test_password_reset_done_200` — GET `/password-reset/done/` returns 200
- `test_password_reset_complete_200` — GET `/password-reset/complete/` returns 200

#### 5. New: PerUserIsolationTest

**File**: `monitor/tests.py`

**Intent**: Assert that user A cannot access, edit, or delete user B's Rules or Connections. This directly tests IDOR closure.

**Contract**: New `class PerUserIsolationTest(TestCase)` with `setUp` creating two users (`user_a`, `user_b`) and one Rule + one Connection owned by `user_b`. Log in as `user_a` for all tests:
- `test_dashboard_hides_other_user_rule` — dashboard renders without `user_b`'s rule name
- `test_rule_edit_other_user_404` — GET `/rules/<b_rule_pk>/edit/` returns 404
- `test_rule_delete_other_user_404` — POST `/rules/<b_rule_pk>/delete/` returns 404, rule not deleted
- `test_rule_history_other_user_404` — GET `/rules/<b_rule_pk>/history/` returns 404
- `test_connection_list_hides_other_user` — connection list page doesn't show `user_b`'s connection
- `test_connection_edit_other_user_404` — GET `/connections/<b_conn_pk>/edit/` returns 404
- `test_connection_delete_other_user_404` — POST `/connections/<b_conn_pk>/delete/` returns 404, connection not deleted
- `test_api_schema_tables_other_user_404` — GET `/api/schema/<b_conn_pk>/tables/` returns 404

### Success Criteria:

#### Automated Verification:

- Full test suite passes: `python manage.py test monitor`
- New isolation tests pass: `python manage.py test monitor.tests.PerUserIsolationTest`
- New signup tests pass: `python manage.py test monitor.tests.SignupViewTest`

#### Manual Verification:

- Run full test suite; verify zero failures and no `IntegrityError` from missing user FK
- Spot-check: create two users manually via `/signup/`, add a rule as each — confirm each user only sees their own rules

---

## Testing Strategy

### Unit Tests:

- `SignupViewTest` — form rendering, valid/invalid submission, redirect for authenticated users
- `PasswordResetURLTest` — URL wiring smoke tests (GET returns 200)
- `PerUserIsolationTest` — IDOR closure for all 8 affected endpoints

### Integration Tests:

- Updated `DashboardViewTest`, `RuleCRUDViewTest`, `ConnectionCRUDViewTest` pass with user-scoped data
- Updated service/model tests create rows with a user

### Manual Testing Steps:

1. Sign up as a new user via `/signup/` — verify redirect to dashboard, empty state shown
2. Create a Rule and a Connection — verify they appear for this user only
3. Open a second browser / incognito, sign up as a different user — verify empty state
4. From User B, guess User A's rule PK in the URL — verify 404
5. Navigate to `/password-reset/` — enter email, verify token appears in console log (dev)
6. Deploy to Render (DEBUG=False) — verify session cookie has `Secure` flag in browser DevTools

## Performance Considerations

All queries add a single equality filter on an indexed FK column (`user_id`). No performance impact expected for typical Rule/Connection counts (<500 per user). `select_related('connection')` in `dashboard` still works correctly after adding the user filter.

## Migration Notes

- Migration `0005` + `0006` are safe to run on production before Phase 3 code is deployed (adds nullable columns, no existing view breaks).
- Migration `0007` (Phase 3) must only be deployed together with the Phase 3 view changes — deploying `0007` without updated views would cause `IntegrityError` on any `rule_create` or `connection_create` request.
- Deploy order: Phase 1 migrations → Phase 2 code → Phase 3 code + migration → Phase 4 tests (CI).
- If production has existing Rules/Connections with no superuser, rows remain `user=None` after `0006`. Verify with: `python manage.py shell -c "from monitor.models import Rule; print(Rule.objects.filter(user=None).count())"` — should be 0 on any production environment with a superuser.

## References

- Research: `context/changes/multi-tenancy/research.md`
- Current models: `monitor/models.py:28-80`
- Current views: `monitor/views.py`
- Current forms: `monitor/forms.py`
- URL config: `data_pulse/urls.py`
- Settings: `data_pulse/settings.py`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: User FK Migration

#### Automated

- [x] 1.1 Migrations apply cleanly: `python manage.py migrate --run-syncdb`
- [x] 1.2 Migration 0005 adds user_id columns: `python manage.py sqlmigrate monitor 0005`
- [x] 1.3 Migration 0006 runs without error; Rule.objects.filter(user=None).count() == 0
- [x] 1.4 All existing tests pass: `python manage.py test monitor`

#### Manual

- [ ] 1.5 After migrate, Rule and Connection rows in admin show user equal to first superuser
- [ ] 1.6 Creating a new Rule/Connection via admin allows nullable user FK

### Phase 2: Registration & Auth Flow

#### Automated

- [x] 2.1 All existing tests pass: `python manage.py test monitor`
- [x] 2.2 `/password-reset/` returns 200: GET request succeeds
- [x] 2.3a `/signup/` returns 200: smoke check before Phase 3 touches views.py — run `python manage.py test monitor.tests.SignupViewTest.test_signup_get_200` (test class written in Phase 4; run a subset early here)

#### Manual

- [ ] 2.3 `/signup/` renders form with username + password fields
- [ ] 2.4 Valid signup creates user and redirects to dashboard
- [ ] 2.5 Login page shows “Sign up” and “Forgot password?” links
- [ ] 2.6 Password reset form renders at `/password-reset/`
- [ ] 2.7 Submitting password reset prints token to console in dev (EMAIL_BACKEND=console)

### Phase 3: View Isolation & IDOR Fix

#### Automated

- [x] 3.1 Migration 0007 applies cleanly: `python manage.py migrate`
- [x] 3.2 No Rule or Connection rows have user=None after migration
- [x] 3.3 All updated view tests pass: `python manage.py test monitor`

#### Manual

- [ ] 3.4 User B cannot see User A’s rules on dashboard
- [ ] 3.5 Direct URL to User A’s rule returns 404 when logged in as User B
- [ ] 3.6 Rule creation form connection dropdown shows only current user’s connections
- [ ] 3.7 Cron command runs all scheduled rules: `python manage.py run_scheduled`

### Phase 4: Tests

#### Automated

- [x] 4.1 Full test suite passes: `python manage.py test monitor`
- [x] 4.2 PerUserIsolationTest passes: `python manage.py test monitor.tests.PerUserIsolationTest`
- [x] 4.3 SignupViewTest passes: `python manage.py test monitor.tests.SignupViewTest`

#### Manual

- [ ] 4.4 Zero failures and no IntegrityError in full test suite run
- [ ] 4.5 Two manually-created users each see only their own rules and connections
