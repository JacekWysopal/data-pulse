# Alert Digest — Implementation Plan

## Overview

Replace the current one-email-per-rule-failure pattern with a per-user notification
mode. Users with `immediate` mode keep the existing behaviour. Users with `digest`
mode receive a single email per run that lists every FAIL and ERROR in one table.
The toggle lives on a new user settings page.

## Current State Analysis

`email_service.py` exposes one public function — `send_fail_notification(rule, result)`.
It fires inside the `for rule in rules` loop in both `run_checks_for_user` and
`run_all_checks` in `services.py`, and in every branch of `run_single_rule`. A
per-rule cooldown (`Rule.last_notified_at`, 1 h) is applied inside that function.

There is no per-user preference model. Django's built-in `auth.User` is used
directly; no `UserProfile` or settings model exists. Migration 0012 is the latest
(`monitor/migrations/0012_rule_notify_fields.py`).

Email is sent via `EmailMultiAlternatives`. Templates are at
`templates/monitor/email/fail_notification.{txt,html}`; both receive
`{'rule': rule, 'result': result}`.

`CheckRun` has `fail_count` and `error_count` properties that count results without
an extra query. `RuleResult` fields available per failure row: `rule.name`,
`rule.schema_name`, `rule.table_name`, `rule.rule_type`, `result.status`,
`result.row_count`, `result.last_record_age_hours`, `result.error_message`.

## Desired End State

After this plan is complete:

- A `UserProfile` model (OneToOne with `auth.User`) stores `notification_mode`
  (`immediate` | `digest`, default `immediate`).
- `immediate` mode: existing per-rule, per-hour-cooldown behaviour unchanged.
- `digest` mode: `send_fail_notification` is **never called** inside the rule loop.
  After the loop finishes, `send_digest_notification(run, failing_results, user)`
  fires once if `fail_count > 0` or `error_count > 0`. No per-run cooldown —
  one digest per run, always.
- The per-rule `Rule.last_notified_at` cooldown is **only updated in immediate mode**;
  digest mode does not touch it.
- A settings page at `GET/POST /monitor/settings/` lets the user toggle between modes.
- Two new email templates (`digest_notification.txt` / `.html`) render a table of
  failures; for ≥ 10 failures they render a summary line instead of the full table.

### Key Discoveries

- `run_single_rule` always uses immediate mode — a single-rule check never triggers
  a digest. No change needed there.
- `run_all_checks` covers **all users**; its loop must group failing results by user
  and dispatch one digest per user after the loop. `run_checks_for_user` is already
  scoped to one user — simpler.
- `CheckRun.fail_count` / `error_count` are computed properties (extra DB queries);
  passing `failing_results` list to `send_digest_notification` avoids re-querying.
- `UserProfile` will be auto-created via `post_save` signal on `User` with default
  `immediate`, ensuring the settings page never raises `RelatedObjectDoesNotExist`.

## What We're NOT Doing

- No Slack digest in this change — Slack webhook is a separate S-18 slice.
- No cooldown on the digest itself — one digest per run is the contract.
- No changes to `run_single_rule` — single-rule checks always use immediate.
- No digest for `run_single_rule` triggered from the UI "Run single" button.
- No back-fill of `last_notified_at` for digest users — the field is left as-is.
- No change to `COOLDOWN_HOURS` or per-rule cooldown logic for immediate mode.

## Implementation Approach

Four production phases in dependency order, followed by a dedicated test phase:

1. **Data model** — `UserProfile` + migration, signal for auto-creation.
2. **Email function** — `send_digest_notification()` + templates (no wiring yet).
3. **Services hook** — wire digest into `run_checks_for_user` and `run_all_checks`;
   immediate mode path unchanged.
4. **UI toggle** — settings view, URL, template, navbar link.
5. **Tests** — unit + integration coverage.

---

## Phase 1: UserProfile Model and Migration

### Overview

Add a `UserProfile` model to `monitor/models.py` with a OneToOne link to
`settings.AUTH_USER_MODEL` and a `notification_mode` field. Generate and apply
migration `0013_userprofile.py`. Wire a `post_save` signal on `User` that
auto-creates the profile with default `immediate`.

### Changes Required

#### 1. UserProfile model

**File:** `monitor/models.py`

**Intent:** Define the `UserProfile` model below `SlackNotification`. Store
`notification_mode` as a `CharField` with TextChoices `immediate` / `digest`,
defaulting to `immediate`.

**Contract:**
```python
class UserProfile(models.Model):
    class NotificationMode(models.TextChoices):
        IMMEDIATE = 'immediate', 'Immediate (one email per rule failure)'
        DIGEST    = 'digest',    'Digest (one email per run)'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    notification_mode = models.CharField(
        max_length=20,
        choices=NotificationMode.choices,
        default=NotificationMode.IMMEDIATE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

#### 2. Auto-creation signal

**File:** `monitor/models.py`

**Intent:** Add a `post_save` signal on `User` that creates a `UserProfile`
with default mode the first time a user is saved (new registration, admin creation).
Use `get_or_create` so re-saves of existing users are safe.

**Contract:** Signal function at module bottom, connected via `@receiver(post_save, sender=settings.AUTH_USER_MODEL)`. Calls `UserProfile.objects.get_or_create(user=instance)`.

#### 3. Migration

**File:** `monitor/migrations/0013_userprofile.py`

**Intent:** Create the `monitor_userprofile` table. Generated by `makemigrations`
— do not hand-write.

### Success Criteria

#### Automated Verification

- Migration applies cleanly: `python manage.py migrate --run-syncdb`
- `UserProfile.objects.filter(user=user).exists()` returns `True` after user creation
- Default mode is `immediate` for all new users
- No migration conflicts: `python manage.py migrate --check`

#### Manual Verification

- Django admin shows `UserProfile` inline or standalone with `notification_mode` field

---

## Phase 2: Digest Email Function and Templates

### Overview

Add `send_digest_notification(run, failing_results, user)` to `email_service.py`.
Create the two new email templates. The function is fully self-contained — services.py
wiring happens in Phase 3.

### Changes Required

#### 1. send_digest_notification function

**File:** `monitor/email_service.py`

**Intent:** Send one digest email to `user.email` summarising all failures in
`failing_results`. If `len(failing_results) >= DIGEST_SUMMARY_THRESHOLD` render
the compact summary template instead of the full table. Returns `True` on send,
`False` on skip or error. Logs at ERROR on failure (same pattern as
`send_fail_notification`).

**Contract:**
```python
DIGEST_SUMMARY_THRESHOLD = 10

def send_digest_notification(run, failing_results: list, user) -> bool:
    """
    Send one digest email for a completed run.

    Skips when:
      - failing_results is empty
      - user has no email address
    No cooldown — one per run is the contract.
    Returns True if sent, False if skipped or failed.
    """
```

Context passed to templates: `{'run': run, 'failing_results': failing_results,
'fail_count': …, 'error_count': …, 'is_summary': bool}`.

Subject line: `[DataPulse] {fail_count} rule(s) FAILED in run #{run.pk}`.

#### 2. Digest text template

**File:** `templates/monitor/email/digest_notification.txt`

**Intent:** Plain-text digest. When `is_summary` is True, render one line:
`"{{ fail_count }} rules FAILED, {{ error_count }} ERROR — see dashboard."` Otherwise
render an ASCII table of failures (rule name, status, table, row count, age, error).

#### 3. Digest HTML template

**File:** `templates/monitor/email/digest_notification.html`

**Intent:** HTML digest matching the dark theme of `fail_notification.html`.
When `is_summary` is True, render a single summary banner. When False, render a
`<table>` of failure rows (one per `failing_results` item) with the same columns
as the text template. Follow the existing template's color scheme and layout.

### Success Criteria

#### Automated Verification

- `send_digest_notification(run, [], user)` returns `False` (empty list guard)
- `send_digest_notification(run, results_list, user_no_email)` returns `False`
- With `len(failing_results) >= 10`, subject contains the right count and template
  context has `is_summary=True`
- Django `mail.outbox` receives exactly one message per call
- `send_digest_notification` does **not** call `Rule.objects.update()` (no cooldown stamp)

#### Manual Verification

- Rendered HTML digest email displays correctly in an email client (dark background,
  failure table with rule name / status / table / row count / record age / error)
- Summary format (≥ 10 failures) renders a single line, not a table

---

## Phase 3: Hook Digest into services.py

### Overview

Refactor notification dispatch in `run_checks_for_user` and `run_all_checks` to
branch on the user's `notification_mode`. Immediate mode keeps its existing
per-rule `send_fail_notification` calls. Digest mode suppresses per-rule calls
and fires `send_digest_notification` once after the loop.

### Changes Required

#### 1. Helper: get_notification_mode

**File:** `monitor/services.py`

**Intent:** Add a small helper that returns the user's notification mode without
raising if the profile doesn't exist (falls back to `immediate`).

**Contract:**
```python
def _get_notification_mode(user) -> str:
    """Return 'immediate' or 'digest'; default immediate on missing profile."""
    try:
        return user.profile.notification_mode
    except Exception:
        return 'immediate'
```

Import `UserProfile` is not needed — access via the reverse OneToOne `user.profile`.

#### 2. run_checks_for_user — digest branch

**File:** `monitor/services.py`

**Intent:** Before the rule loop, resolve `mode = _get_notification_mode(user)`.
Accumulate `failing_results = []` during the loop. For `mode == 'immediate'`, keep
calling `send_fail_notification` as today. For `mode == 'digest'`, skip those calls
and append `db_result` to `failing_results` when status is FAIL or ERROR. After the
loop, if `mode == 'digest'`, call `send_digest_notification(run, failing_results, user)`.

**Contract:** The `failing_results` list is built in the same loop body — no extra query.
Import `send_digest_notification` at the top of the file alongside `send_fail_notification`.

#### 3. run_all_checks — per-user digest dispatch

**File:** `monitor/services.py`

**Intent:** `run_all_checks` processes rules for all users. Accumulate a dict
`digest_pending: dict[int, tuple[user, list[RuleResult]]]` keyed by `rule.user_id`.
In the loop: if the rule's owner has `digest` mode, skip `send_fail_notification`
and append the failing result to `digest_pending[user_id]`. For immediate users,
keep existing calls. After the loop, iterate `digest_pending` and call
`send_digest_notification` once per user.

**Contract:** `rule.user` is already available via `select_related('connection')`
— add `select_related('user__profile')` or rely on the fallback helper which
catches missing profiles. Use `.select_related('connection', 'user')` to avoid N+1.

#### 4. Import update

**File:** `monitor/services.py`

**Intent:** Add `send_digest_notification` to the import line from `.email_service`.

### Success Criteria

#### Automated Verification

- `run_checks_for_user` with digest-mode user sends exactly **1** email for N failures
  (verified via `mail.outbox`)
- `run_checks_for_user` with immediate-mode user sends **N** emails (one per failure)
- `run_checks_for_user` with digest-mode user and **no failures** sends **0** emails
- `run_all_checks` with two digest-mode users sends exactly **2** emails (one per user)
- `run_all_checks` with mixed modes sends per-rule emails for immediate + one digest
  for digest user
- `Rule.last_notified_at` is **not** updated for digest-mode users after a run

#### Manual Verification

- Click "Run checks" in browser with digest mode active → one email received in
  mailbox instead of N
- Dashboard still shows all FAIL/ERROR statuses regardless of notification mode

---

## Phase 4: User Settings UI

### Overview

Add a `/monitor/settings/` page where the logged-in user can toggle notification
mode. A `GET` renders the current setting; a `POST` saves and redirects back with a
success message. Link the page from the existing sidebar navigation.

### Changes Required

#### 1. settings view

**File:** `monitor/views.py`

**Intent:** `GET` renders `monitor/settings.html` with the current profile (or default
`immediate` if none). `POST` validates the submitted `notification_mode` value
(`immediate` or `digest`) and saves it via `UserProfile.objects.update_or_create`.
On success, adds a Django `messages.success` and redirects to the settings page.

**Contract:** `@login_required`. View name: `settings`. Accepts only `immediate` and
`digest` — any other value returns a 400 or silently ignores.

#### 2. URL

**File:** `monitor/urls.py`

**Intent:** Add `path('settings/', views.settings, name='settings')`.

#### 3. settings.html template

**File:** `templates/monitor/settings.html`

**Intent:** Notification mode section with two radio inputs:
`immediate` (labelled "Immediate — one email per rule failure, with 1-hour cooldown")
and `digest` (labelled "Digest — one email per run with all failures grouped").
Follow the dark-theme styling of existing monitor templates. Submit button triggers
POST to the same URL.

#### 4. Sidebar link

**File:** `templates/` (base layout or sidebar partial)

**Intent:** Add "Settings" nav link pointing to `monitor:settings`. Identify the
correct base template from the existing layout and add one `<a>` link in the same
position as "Schedule".

### Success Criteria

#### Automated Verification

- `GET /monitor/settings/` returns 200 for authenticated user
- `GET /monitor/settings/` redirects to login for anonymous user
- `POST /monitor/settings/` with `notification_mode=digest` updates profile and
  returns 302 redirect
- `POST /monitor/settings/` with invalid mode returns 400 or is ignored safely

#### Manual Verification

- Settings page shows current mode with the correct radio pre-selected
- Toggling to digest and submitting persists the change (page reload shows new value)
- Sidebar link is visible and navigates to the settings page

---

## Phase 5: Tests

### Overview

Add test coverage in `monitor/tests.py` for all new code paths. Follow existing
test patterns: `TestCase` classes, `make_rule` / `make_connection` helpers, mock
patches for psycopg2, `mail.outbox` for email assertions.

### Changes Required

#### 1. UserProfile model tests

**File:** `monitor/tests.py`

**Intent:** Test that `UserProfile` is auto-created on user save with default
`immediate` mode; test that the signal fires for both `create_user` and admin-created
users.

#### 2. send_digest_notification unit tests

**File:** `monitor/tests.py`

**Intent:** Test all guard conditions (empty list → False, no email → False), verify
`mail.outbox` receives exactly one message, verify `is_summary=True` for ≥ 10 items,
confirm `Rule.last_notified_at` is **not** updated.

#### 3. services.py integration tests

**File:** `monitor/tests.py`

**Intent:**
- `run_checks_for_user` with digest user: mock DB checks to produce N FAILs, assert
  `len(mail.outbox) == 1`.
- `run_checks_for_user` with immediate user: assert `len(mail.outbox) == N`.
- `run_checks_for_user` with digest user and all OK: assert `len(mail.outbox) == 0`.
- `run_all_checks` with two digest users: assert `len(mail.outbox) == 2`.

#### 4. Settings view tests

**File:** `monitor/tests.py`

**Intent:** Test `GET` returns 200, `POST` with `digest` saves profile and redirects,
`POST` with invalid value is handled safely.

### Success Criteria

#### Automated Verification

- All existing tests still pass: `python manage.py test monitor`
- New tests pass: `python manage.py test monitor.tests.UserProfileTest`, etc.
- No regressions in `run_all_checks` or `run_checks_for_user` behaviour for
  immediate-mode users

#### Manual Verification

- End-to-end: log in, toggle to digest mode on settings page, click "Run checks",
  confirm only one email arrives in the console email backend output

---

## Testing Strategy

### Unit Tests

- `UserProfile` auto-creation signal
- `send_digest_notification` guard paths and mail.outbox assertions
- `_get_notification_mode` fallback to immediate when profile missing

### Integration Tests

- `run_checks_for_user` with mocked psycopg2: digest mode → 1 email
- `run_checks_for_user` with mocked psycopg2: immediate mode → N emails
- `run_all_checks` with two users, both digest mode → 2 emails
- Mixed mode `run_all_checks` → per-rule emails for immediate + digest for digest user

### Manual Testing Steps

1. Create a user, leave notification mode at default (`immediate`), run checks with
   failing rules → confirm N individual emails in console output
2. Toggle to `digest` on settings page → run checks with failing rules → confirm one
   grouped email in console output
3. Toggle to `digest` → run checks with all rules passing → confirm no email sent
4. Create 10+ failing rules (or mock) → confirm summary format in digest email

## Performance Considerations

`run_all_checks` will add `select_related('user')` to the rules queryset to avoid
N+1 when reading `rule.user.profile.notification_mode`. The `digest_pending` dict
accumulates in memory; for typical rule counts (< 1000 per run) this is negligible.
`CheckRun.fail_count` / `error_count` properties are N+1 query risks if called
repeatedly — `send_digest_notification` receives the pre-built `failing_results` list
and derives counts from `len()` to avoid extra queries.

## Migration Notes

No existing data migration needed. `UserProfile` rows are created on first access
via the `post_save` signal — new users get profiles automatically. Existing users
get profiles the first time they save (e.g., next login → session save doesn't
trigger this, but a model save does). The settings view uses `get_or_create` as a
safety net for existing users who haven't triggered the signal yet.

## References

- Research: `context/changes/alert-digest/research.md`
- Email service: `monitor/email_service.py`
- Services: `monitor/services.py`
- Models: `monitor/models.py`
- Existing email template: `templates/monitor/email/fail_notification.html:1`
- Latest migration: `monitor/migrations/0012_rule_notify_fields.py`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: UserProfile Model and Migration

#### Automated

- [ ] 1.1 Migration applies cleanly
- [ ] 1.2 Default notification_mode is immediate for new users
- [ ] 1.3 No migration conflicts

#### Manual

- [ ] 1.4 Admin shows UserProfile with notification_mode field

### Phase 2: Digest Email Function and Templates

#### Automated

- [ ] 2.1 send_digest_notification returns False for empty failing_results
- [ ] 2.2 send_digest_notification returns False for user with no email
- [ ] 2.3 Summary context (is_summary=True) used when failing_results >= 10
- [ ] 2.4 mail.outbox receives exactly one message per call
- [ ] 2.5 Rule.last_notified_at not updated by send_digest_notification

#### Manual

- [ ] 2.6 HTML digest email renders correctly in email client
- [ ] 2.7 Summary format renders single line for 10+ failures

### Phase 3: Hook Digest into services.py

#### Automated

- [ ] 3.1 run_checks_for_user digest mode sends 1 email for N failures
- [ ] 3.2 run_checks_for_user immediate mode sends N emails
- [ ] 3.3 run_checks_for_user digest mode sends 0 emails for no failures
- [ ] 3.4 run_all_checks two digest users sends 2 emails
- [ ] 3.5 run_all_checks mixed mode sends per-rule for immediate and digest for digest user
- [ ] 3.6 Rule.last_notified_at not updated for digest-mode users

#### Manual

- [ ] 3.7 Browser run checks with digest mode produces one email in console backend

### Phase 4: User Settings UI

#### Automated

- [ ] 4.1 GET /monitor/settings/ returns 200 for authenticated user
- [ ] 4.2 GET /monitor/settings/ redirects to login for anonymous user
- [ ] 4.3 POST with notification_mode=digest updates profile and redirects 302
- [ ] 4.4 POST with invalid mode handled safely

#### Manual

- [ ] 4.5 Settings page shows current mode with correct radio pre-selected
- [ ] 4.6 Toggle and save persists across page reload
- [ ] 4.7 Sidebar link visible and navigates to settings

### Phase 5: Tests

#### Automated

- [ ] 5.1 UserProfile auto-creation tests pass
- [ ] 5.2 send_digest_notification unit tests pass
- [ ] 5.3 services.py integration tests pass
- [ ] 5.4 Settings view tests pass
- [ ] 5.5 All existing tests still pass

#### Manual

- [ ] 5.6 End-to-end: digest toggle → run checks → one email in console output
