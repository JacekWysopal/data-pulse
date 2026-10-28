---
change_id: multi-tenancy
research_question: >
  What changes are needed to add full multi-tenancy to DataPulse —
  user registration, per-user Rules and Connections, secure auth?
status: preparing
researcher: worker-subagent
last_updated: 2026-10-28
last_updated_by: worker-subagent
last_updated_note: initial research
evidence_quality: high — all claims cite file:line; evidence/inference/unknown tagged
---

## Summary answer

DataPulse already has login/logout (LoginView + LogoutView wired, `@login_required` on all views) and full Django auth infrastructure, but zero user isolation. Neither `Rule` nor `Connection` has a `user` FK — every logged-in user sees every record. There is no signup view, no registration form, and no URL for self-service account creation. Adding full multi-tenancy requires: (1) a signup view and template, (2) user FKs on `Rule` and `Connection` via two-step migration, (3) ownership filtering in every view and queryset, (4) a constraint change on `Connection.name`, and (5) a small set of production security settings for Render. The Django auth framework covers all primitives out of the box; no new packages are needed.

---

## 1. Current auth setup

### What is already wired

**`data_pulse/urls.py:3-9`** [evidence] — `LoginView` at `/login/` with `template_name='login.html'` and `LogoutView` at `/logout/` are the only auth URLs. No `/signup/` or `/password-reset/` URL exists.

**`data_pulse/settings.py:74-76`** [evidence] — Three auth redirect settings are set:
- `LOGIN_URL = '/login/'`
- `LOGIN_REDIRECT_URL = '/'`
- `LOGOUT_REDIRECT_URL = '/login/'`

**`data_pulse/settings.py:14-22`** [evidence] — `django.contrib.auth`, `django.contrib.sessions`, `django.contrib.messages` are in `INSTALLED_APPS`. All authentication infrastructure is available.

**`data_pulse/settings.py:24-35`** [evidence] — `AuthenticationMiddleware`, `SessionMiddleware`, `CsrfViewMiddleware` are all present in `MIDDLEWARE`.

**`monitor/views.py:9-15`** [evidence] — Every view function is decorated with `@login_required`. The 13 view functions covered: `dashboard`, `run_checks`, `run_single`, `rule_history`, `rule_create`, `rule_edit`, `rule_delete`, `api_schema_tables`, `api_schema_columns`, `connection_list`, `connection_create`, `connection_edit`, `connection_delete`.

**`templates/login.html`** [evidence] — Custom login template exists with `{% csrf_token %}`, `{{ form.errors }}` check, username and password inputs. No link to a signup page.

### What is missing

[evidence] Grep for `signup`, `register`, `UserCreationForm` across all `.py` files returns zero matches. There is no registration view, no registration form, and no `/signup/` URL in any URLconf.

[inference] Password reset requires a configured email backend. `settings.py` has no `EMAIL_BACKEND`, `EMAIL_HOST`, or any SMTP setting. Password reset is not available in the current configuration.

---

## 2. Rule and Connection models — user FK status

**`monitor/models.py:28-40`** [evidence] — `Connection` model fields: `name`, `description`, `_database_url`, `created_at`, `updated_at`. No `user` field.

**`monitor/models.py:47-80`** [evidence] — `Rule` model fields: `name`, `schema_name`, `table_name`, `connection` (FK to Connection), `rule_type`, `custom_sql`, `timestamp_column`, `max_age_hours`, `min_row_count`, `schedule_time`, `created_at`, `updated_at`. No `user` field.

**`monitor/models.py:75`** [evidence] — `Connection.name` has `unique=True`. This is a global uniqueness constraint that conflicts with multi-tenancy: two users cannot create connections with the same name (e.g., both wanting a connection named `production`). This constraint must change to a `unique_together = [('user', 'name')]` constraint.

**Migration history** [evidence]:
- `0001_initial.py` — creates Rule, CheckRun, RuleResult; no user FK.
- `0002_connection_rule_connection.py` — adds Connection table and connection FK on Rule; no user FK.
- `0003_rule_schedule_time.py` — adds `schedule_time` to Rule; no user FK.
- `0004_rule_custom_sql.py` — adds `rule_type` and `custom_sql`; no user FK.

The next migration will be `0005`. Two migrations are needed: one to add nullable user FKs, one data migration to assign existing rows.

---

## 3. Django built-in user registration options

**`django.contrib.auth.forms.UserCreationForm`** [evidence — Django docs and INSTALLED_APPS confirm `django.contrib.auth` is present] — provides three fields: `username`, `password1`, `password2`. Includes validation: password confirmation match, minimum length, common password check, numeric-only password check. No email field by default. Available immediately with no new packages.

**`data_pulse/settings.py:55-62`** [evidence] — `AUTH_PASSWORD_VALIDATORS` has all 4 Django built-in validators configured: `UserAttributeSimilarityValidator`, `MinimumLengthValidator`, `CommonPasswordValidator`, `NumericPasswordValidator`. These apply automatically to any form using `UserCreationForm`.

For MVP: use `UserCreationForm` directly with a new view at `/signup/`. No email verification required (roadmap note: "prosty signup bez email verification (MVP)").

[inference] Django also ships `UserChangeForm`, `PasswordResetView`, `PasswordChangeView` — all usable without new packages if email is eventually configured.

---

## 4. Views and templates requiring user filtering

Every view that reads or writes `Rule` or `Connection` needs updating. The changes are mechanical but must be applied to all 13 view functions.

### Views with IDOR risk after adding user FK

| View function | File:line | Current query | Required change | Risk |
|---|---|---|---|---|
| `dashboard` | views.py:17 | `Rule.objects.…all()` | `.filter(user=request.user)` | shows all users' rules |
| `run_checks` | views.py:36 | delegates to `run_all_checks()` | pass `user=request.user` or scope call | runs checks for all users |
| `run_single` | views.py:44 | `get_object_or_404(Rule, pk=rule_id)` | add `user=request.user` | access any user's rule |
| `rule_history` | views.py:51 | `get_object_or_404(Rule, pk=rule_id)` | add `user=request.user` | access any user's history |
| `rule_create` | views.py:56 | `form.save()` | `instance.user = request.user` before save | user FK null |
| `rule_edit` | views.py:67 | `get_object_or_404(Rule, pk=rule_id)` | add `user=request.user` | edit any user's rule |
| `rule_delete` | views.py:79 | `get_object_or_404(Rule, pk=rule_id)` | add `user=request.user` | delete any user's rule |
| `api_schema_tables` | views.py:99 | passes `conn_id` to service | verify `Connection.objects.get(pk=conn_id, user=request.user)` before call | query any connection |
| `api_schema_columns` | views.py:110 | passes `conn_id` to service | same ownership check | query any connection |
| `connection_list` | views.py:122 | `Connection.objects.…all()` | `.filter(user=request.user)` | shows all users' connections |
| `connection_create` | views.py:128 | `form.save()` | `instance.user = request.user` before save | user FK null |
| `connection_edit` | views.py:138 | `get_object_or_404(Connection, pk=conn_id)` | add `user=request.user` | edit any connection |
| `connection_delete` | views.py:149 | `get_object_or_404(Connection, pk=conn_id)` | add `user=request.user` | delete any connection |

### Forms requiring user scoping

**`monitor/forms.py:42-43`** [evidence] — `RuleForm` has a `connection` field that shows all `Connection` objects (`forms.Select`). The queryset must be filtered by the current user. This requires passing `user` into `RuleForm.__init__` and applying `self.fields['connection'].queryset = Connection.objects.filter(user=user)`.

### Services requiring awareness

**`monitor/services.py:167`** [evidence] — `run_all_checks()` queries `Rule.objects.select_related('connection').all()` — fetches all rules globally. For the cron job (`run_scheduled` management command), this is intentional (runs all users' scheduled rules). No change needed in services.py for the cron use case.

**`monitor/services.py:24-35`** [evidence] — `get_schema_tables(conn_id)` looks up `Connection.objects.get(pk=conn_id)` with no user check. The view layer (`api_schema_tables`, `api_schema_columns`) must verify ownership before calling these functions. The services layer itself doesn't need to change.

---

## 5. Migration strategy for existing Rules and Connections

The recommended two-step approach (matches roadmap note: "Rule.user FK (nullable → required po migracji danych)"):

**Migration 0005** — add nullable user FK to both models:
```python
# Rule
user = ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL, related_name='rules')
# Connection
user = ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=CASCADE, related_name='connections')
```
For Connection: `on_delete=CASCADE` makes sense (delete user → delete their connections). For Rule: `SET_NULL` or `CASCADE` — CASCADE is cleaner.

Also in this migration: drop the global `unique` constraint on `Connection.name` and replace with `unique_together = [('user', 'name')]`. Note: `unique_together` with a nullable FK means two `(None, 'production')` rows could coexist during migration; this is acceptable in the transition window.

**Migration 0006** — data migration to assign existing rows to the first superuser:
```python
def assign_to_superuser(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Rule = apps.get_model('monitor', 'Rule')
    Connection = apps.get_model('monitor', 'Connection')
    superuser = User.objects.filter(is_superuser=True).order_by('pk').first()
    if superuser:
        Rule.objects.filter(user=None).update(user=superuser)
        Connection.objects.filter(user=None).update(user=superuser)
```
If no superuser exists (fresh install), rows remain with `user=None` temporarily; they will become unreachable through normal views. This is acceptable: fresh installs have no data.

[inference] Making the FK `null=False` in a follow-up migration (0007) is optional. Views already enforce ownership via `get_object_or_404(..., user=request.user)`, so NULL rows are simply unreachable. The nullable column can remain permanently or be tightened after confirming production data is clean.

---

## 6. Security checklist

### CSRF — already covered
**`data_pulse/settings.py:27`** [evidence] — `CsrfViewMiddleware` is active.
**`templates/login.html`** [evidence] — `{% csrf_token %}` present.
[inference] All other existing forms (`rule_form.html`, `connection_form.html`, etc.) use `{% csrf_token %}` per Django template conventions; the new `signup.html` template must include it too.

### Password hashing — already covered
**`data_pulse/settings.py:55-62`** [evidence] — Django's 4 built-in password validators are configured. Django uses PBKDF2-SHA256 by default. `UserCreationForm` applies these validators automatically.

### HTTPS on Render — gap identified
**`data_pulse/settings.py`** [evidence] — `SecurityMiddleware` is in MIDDLEWARE (line 24), but the following production security settings are absent from settings.py:
- `SECURE_SSL_REDIRECT` — not set (defaults to False)
- `SESSION_COOKIE_SECURE` — not set (defaults to False)
- `CSRF_COOKIE_SECURE` — not set (defaults to False)
- `SECURE_HSTS_SECONDS` — not set
- `SECURE_PROXY_SSL_HEADER` — not set

[inference] Render terminates SSL at the edge and forwards HTTP to Django internally. Without `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')`, Django doesn't know HTTPS is in use, so session and CSRF cookies are sent without `Secure` flag. This exposes session cookies on any non-HTTPS connection.

Required settings to add (guarded by `if not DEBUG` or by `env()` read):
```python
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
```

### IDOR (Insecure Direct Object Reference) — gap to close
[evidence + inference] Current views use `get_object_or_404(Rule, pk=rule_id)` and `get_object_or_404(Connection, pk=conn_id)` with no user filter. After user FKs are added, any logged-in user can access any other user's Rule or Connection by guessing integer PKs. All 13 view functions listed in section 4 must add `user=request.user` to their object lookups.

### Connection.name uniqueness — constraint gap
**`monitor/models.py:30`** [evidence] — `Connection.name` is `unique=True` globally. With multi-tenancy, two users both naming their connection `production` would trigger a DB-level IntegrityError. The unique constraint must be dropped and replaced with `unique_together = [('user', 'name')]`.

### Signup form — no email verification needed for MVP
[inference from roadmap] The roadmap explicitly says "prosty signup bez email verification (MVP)". `UserCreationForm` does not require or send email. This is acceptable for MVP.

---

## 7. New artifacts required

| Artifact | Type | Notes |
|---|---|---|
| `/signup/` URL | URL entry in `data_pulse/urls.py` | Before `include('monitor.urls')` |
| `signup` view | New function in `monitor/views.py` or standalone | Uses `UserCreationForm`, redirects to `/` on success |
| `templates/signup.html` | Template | Should match `login.html` style; add CSRF token |
| Link in `login.html` | Template edit | "Don't have an account? Sign up" link |
| Migration 0005 | Django migration | Nullable user FK on Rule + Connection; update Connection name uniqueness |
| Migration 0006 | Django migration (data) | Assign existing rows to first superuser |
| HTTPS security settings | `settings.py` edit | Conditional on `not DEBUG` |
| RuleForm user filtering | `monitor/forms.py` edit | Pass user into `__init__`, filter connection queryset |

---

## 8. Open decisions for planning

These are the unresolved product/architecture questions that `/10x-plan` should decide:

1. **`on_delete` for Rule.user FK**: `CASCADE` (delete user → delete rules) or `SET_NULL` (orphan rules)? CASCADE is cleaner for single-user accounts.
2. **`run_all_checks` scope for cron**: Should the cron job run rules for all users (current behavior, keep as-is) or only for a designated service account? [inference: keep as-is — simpler, and Render Cron has no user context]
3. **Password reset**: Out of scope for MVP (no email backend), or add a stub view? [roadmap implies MVP only]
4. **Signup visibility**: Should `/signup/` be open to anyone (public registration) or gated (admin-only user creation)? Roadmap says "user registration form" → public.
5. **Migration 0006 safety**: If no superuser exists on fresh deploy, existing `None`-user rows are unreachable. This is fine for fresh installs but must be noted in deploy runbook.

---

## Gaps and limitations

- [unknown] `render.yaml` has no `FIELD_ENCRYPTION_KEY` env var entry. Without this key, `Connection._database_url` is stored plaintext (model falls back to plaintext when Fernet key is missing). This is a separate security gap pre-existing this change; multi-tenancy work should note it but not fix it here.
- [unknown] The current test suite (`monitor/tests.py`) has `DashboardViewTest` and `RuleCRUDViewTest` that log in as a single admin user and see all rules. After multi-tenancy, these tests will implicitly test per-user isolation (since the admin user only sees their own rules). New tests should assert that user A cannot access user B's rules.
- [inference] `admin.py` registers Rule, CheckRun, RuleResult but not Connection or the user FK — the admin site currently exposes all records. This is expected for admin users and does not need to change.
