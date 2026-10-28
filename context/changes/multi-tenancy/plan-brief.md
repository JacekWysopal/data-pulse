# Multi-tenancy — Plan Brief

> Full plan: `context/changes/multi-tenancy/plan.md`
> Research: `context/changes/multi-tenancy/research.md`

## What & Why

DataPulse currently has login/logout but zero user isolation — every logged-in user sees every Rule and Connection. This change adds public self-service registration, per-user data scoping, IDOR protection across all 13 views, and a production-safe HTTPS configuration. It is the M-04 star slice and a prerequisite for email notifications (S-13).

## Starting Point

Django auth infrastructure is fully present (`django.contrib.auth` in `INSTALLED_APPS`, `@login_required` on all views, `LoginView`/`LogoutView` wired). Neither `Rule` nor `Connection` has a `user` FK. No signup view, no password reset flow, and no production HTTPS security settings exist today.

## Desired End State

Any visitor can register at `/signup/` with a username and password. After login, each user sees only their own Rules and Connections; guessing another user's object PK in a URL returns 404. Attempting to delete a user while they own data raises a `ProtectedError`. Basic password reset works via email (configurable SMTP). Session and CSRF cookies are `Secure` on Render.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| `on_delete` for user FK | `PROTECT` | Prevents silent data loss when a user account is deleted | Plan |
| Connection.name uniqueness | `unique_together = [('user', 'name')]` | Two users can both have a connection named `production` | Research |
| FK nullability strategy | Nullable → data migration → required (3 migrations) | Safe phased deploy; required-FK migration ships with views that always set user | Research |
| Existing data assignment | Assign to first superuser (by pk) in migration `0006` | No data loss on upgrade; fresh installs have no data to assign | Research |
| Signup | Public `/signup/` using `UserCreationForm`, no email verification | MVP scope per roadmap; Django `UserCreationForm` covers all password validation | Plan |
| Password reset | Include standard Django 4-URL flow, SMTP via env | Enables self-service recovery; env-controlled so dev uses console backend | Plan |
| Cron scope | `run_all_checks()` keeps running all users' scheduled rules unchanged | Cron has no user context; changing scope would break scheduled checks | Research |
| RuleForm connection filter | Pass `user` to `RuleForm.__init__`, filter connection queryset | Without this, User A sees User B's connections in the rule form dropdown | Research |

## Scope

**In scope:**
- User FK on `Rule` and `Connection` (nullable → required via 3 migrations)
- Data migration: assign existing rows to first superuser
- Public signup at `/signup/` (no email verification)
- Django password reset flow at `/password-reset/` (4 URLs, email-configurable)
- `@login_required` remains; all 13 view querysets scoped to `request.user`
- `api_schema_tables` / `api_schema_columns` ownership check before service call
- `RuleForm` connection dropdown filtered to current user
- Production HTTPS security settings (`SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`) guarded by `if not DEBUG`
- IDOR tests, signup tests, password reset URL smoke tests

**Out of scope:**
- Email verification on signup
- Custom User model
- Per-user Django admin isolation
- MySQL/alternative DB support (S-14)
- Email notifications on rule failure (S-13)
- Slack notifications (S-16)

## Architecture / Approach

Three Django migrations handle the DB change safely: `0005` adds nullable `user` FKs and replaces `Connection.name unique=True` with `unique_together = [('user', 'name')]`; `0006` is a data migration assigning existing rows to the first superuser; `0007` removes nullable and enforces the FK. Migrations `0005`/`0006` can deploy before Phase 3 code; `0007` must ship together with the updated views. Views use `get_object_or_404(Model, pk=pk, user=request.user)` for single-object lookups and `.filter(user=request.user)` for querysets. No new packages are required.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. User FK Migration | Nullable user FK on both models, data migration, `unique_together` | Data migration is irreversible; fresh installs with no superuser leave rows as `None` |
| 2. Registration & Auth Flow | Signup page, password reset flow, HTTPS settings, login template links | Email backend unconfigured on Render until env vars are set |
| 3. View Isolation & IDOR Fix | All 13 views scoped to request.user, migration `0007` makes FK required | Migration `0007` must deploy simultaneously with updated views |
| 4. Tests | Updated helpers, isolation tests, signup tests, password reset URL tests | Existing tests that create Rule/Connection without a user will fail if helpers aren't updated |

**Prerequisites:** A superuser must exist on the production Render instance before running migration `0006`, or existing rows will be left with `user=None`.
**Estimated effort:** ~3 sessions across 4 phases; no new packages, all Django built-ins.

## Open Risks & Assumptions

- If the Render production database has no superuser when migration `0006` runs, existing rows stay `user=None` and become unreachable via normal views after `0007`. Mitigation: verify with `python manage.py createsuperuser` before deploying Phase 1.
- `FIELD_ENCRYPTION_KEY` absence means `Connection._database_url` is stored in plaintext — pre-existing gap, out of scope here but should be noted in deploy runbook.
- Password reset requires SMTP env vars (`EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`) to be set in Render dashboard before it works in production. Dev defaults to console backend.

## Success Criteria (Summary)

- A new user can self-register, log in, and see an empty Rule/Connection list
- User A cannot see, edit, or delete User B's rules or connections via any URL
- All 13 views are covered by tests asserting per-user isolation
