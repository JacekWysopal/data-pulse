# Email Notifications on FAIL — Implementation Plan

## Overview

When a rule check returns FAIL or ERROR, send an email alert to the rule owner so
they can act before the problem escalates. The feature is gated behind a per-rule
opt-in toggle and protected by a 1-hour cooldown to prevent alert spam.

This plan assumes **S-12 (multi-tenancy) is already merged**, so `Rule` has an
`owner` ForeignKey to `django.contrib.auth.User`.

> ⛔ **Prerequisite gate**: Phase 1 CANNOT start until multi-tenancy (S-12) is merged
> and `Rule.owner` FK exists in production. Verify `multi-tenancy/change.md` shows
> `status: implemented` before beginning any phase of this change.

## Current State Analysis

- `monitor/models.py` — `Rule` model has no notification fields. `RuleResult.Status`
  has `OK`, `FAIL`, `ERROR` (models.py:142–148). `Rule` will gain `owner` FK from S-12.
- `monitor/services.py` — Two result-creation sites:
  - `run_single_rule(rule)` (services.py:215–261): creates one `RuleResult`, returns it.
  - `run_all_checks()` (services.py:263–314): creates one `RuleResult` per rule in a loop.
- `monitor/forms.py` — `RuleForm.Meta.fields` lists all current Rule fields explicitly
  (forms.py:34); new fields must be appended here.
- `data_pulse/settings.py` — No `EMAIL_*` settings present. Uses `django-environ` for
  all env var reading (pattern: `env('KEY', default=None)`).
- `render.yaml` — Four env vars declared; none email-related. New email vars need
  `sync: false` (secrets).
- Latest migration: `0004_rule_custom_sql.py`. New migration will be `0005`.

## Desired End State

A user editing a Rule sees a "Notify on failure" checkbox. When checked, any FAIL or
ERROR result for that rule triggers a plain-text + HTML email to `rule.owner.email`.
If the same rule fails again within 1 hour, the email is suppressed. The feature is
inactive for rules with `notify_on_fail = False` (default).

### Key Discoveries:

- `run_single_rule` and `run_all_checks` both call `RuleResult.objects.create(...)` at
  multiple branches; the cleanest injection is a helper `send_fail_notification(rule, result)`
  called after each `RuleResult.objects.create(...)` when `status` is FAIL or ERROR.
- `Rule` will have `owner = ForeignKey(User, ...)` after S-12. `owner.email` is the
  recipient. Django's built-in `User.email` is blank by default — the user must fill it
  in admin or profile. The email service must guard against blank email.
- SendGrid SMTP: host `smtp.sendgrid.net`, port `587`, TLS, username `apikey`, password
  = `SENDGRID_API_KEY`. No extra package needed — Django's `EmailMultiAlternatives`
  covers plain-text + HTML in one call.
- `django.core.mail.backends.console.EmailBackend` is used as the default for local dev
  (no credentials needed); SMTP backend activates when `EMAIL_HOST` env var is set.
- Cooldown: `Rule.last_notified_at` DateTimeField (null, blank). Check
  `timezone.now() - rule.last_notified_at < timedelta(hours=1)` before sending.
  Update the field after a successful send. No extra model needed.

## What We're NOT Doing

- No Slack, webhook, or SMS notifications (out of scope — Slack is S-16).
- No notification history / audit log model (cooldown lives on `Rule` field only).
- No per-user SMTP settings — single shared SMTP config in settings.
- No email verification flow for the rule owner's address.
- No retry logic for failed email sends — log the exception and continue.
- No unsubscribe link or bounced-address handling.
- No distinction between FAIL and ERROR in the email template — both trigger the same
  template (change.md requirement: "FAIL or ERROR").

## Implementation Approach

Five sequential phases, each deployable independently:

1. **Model** — add `notify_on_fail` (bool) and `last_notified_at` (datetime) to `Rule`,
   generate and apply migration `0005`.
2. **Email service** — `monitor/email_service.py` with `send_fail_notification(rule, result)`.
   Reads settings, guards against blank email and cooldown, builds plain + HTML email.
3. **Hook into services.py** — call `send_fail_notification` after every FAIL/ERROR
   `RuleResult.objects.create(...)` in both `run_single_rule` and `run_all_checks`.
4. **UI** — add `notify_on_fail` toggle to `RuleForm` and `rule_form.html`.
5. **Settings & docs** — add `EMAIL_*` settings to `settings.py` and env var entries
   to `render.yaml`. Update `.env.example` with SendGrid instructions.

---

## Phase 1: Model Changes

### Overview

Add two new fields to `Rule` and generate migration `0005`. No service logic changes
in this phase.

### Changes Required:

#### 1. Rule model — new fields

**File**: `monitor/models.py`

**Intent**: Add `notify_on_fail` boolean (default `False`, so existing rules are
opt-out by default) and `last_notified_at` datetime (nullable) to `Rule`. These are
the only model changes for this feature.

**Contract**:
```python
# Inside class Rule(models.Model):
notify_on_fail = models.BooleanField(
    default=False,
    verbose_name='Notify on failure',
    help_text='Send an email to the rule owner when this rule returns FAIL or ERROR.',
)
last_notified_at = models.DateTimeField(
    null=True,
    blank=True,
    verbose_name='Last notified at',
)
```
Both fields go after `schedule_time` and before `created_at`. The `CheckConstraint`
(`rule_has_at_least_one_condition`) is unaffected.

#### 2. Migration 0005

**File**: `monitor/migrations/0005_rule_notify_fields.py`

**Intent**: Auto-generated by `python manage.py makemigrations monitor --name notify_fields`.
Run it with `python manage.py migrate` to apply. No data migration needed — `notify_on_fail`
defaults to `False` and `last_notified_at` defaults to `NULL`.

### Success Criteria:

#### Automated Verification:

- `python manage.py makemigrations --check` exits 0 after adding fields
- `python manage.py migrate` applies cleanly on SQLite and Supabase
- `python manage.py test monitor` passes (existing tests unaffected)

#### Manual Verification:

- Open Django admin → Rule; confirm `notify_on_fail` checkbox and `last_notified_at`
  datetime field are visible on an existing rule record.

---

## Phase 2: Email Service

### Overview

Create `monitor/email_service.py` with a single public function
`send_fail_notification(rule, result)`. The function is pure (no Django view, no
request object). All email logic lives here; services.py only calls it.

> ⚠️ **Legacy-data guard**: If `Rule.owner` is `None` (legacy data predating S-12),
> skip notification for that rule. The function already returns `False` early when
> `rule.owner is None` — do not remove or weaken this guard.

### Changes Required:

#### 1. New module: email_service.py

**File**: `monitor/email_service.py`

**Intent**: Encapsulate all notification logic. Guard against: `notify_on_fail=False`,
blank owner email, and cooldown (< 1h since last send). On successful send, update
`rule.last_notified_at`.

**Contract**:

```python
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

COOLDOWN_HOURS = 1


def send_fail_notification(rule, result) -> bool:
    """
    Send a failure notification email for a rule result.

    Returns True if email was sent, False if skipped or failed.
    Skips silently when:
      - rule.notify_on_fail is False
      - rule.owner is None or rule.owner.email is blank
      - last notification was < COOLDOWN_HOURS ago
    Logs (not raises) on send failure.
    """
    ...
```

The function must:
- Return early (False) if `rule.notify_on_fail` is False.
- Return early (False) if `rule.owner` is None or `rule.owner.email` is blank.
- Return early (False) if `rule.last_notified_at` is set and
  `timezone.now() - rule.last_notified_at < timedelta(hours=COOLDOWN_HOURS)`.
- Build subject: `f"[DataPulse] {rule.name} — {result.status}"`.
- Render plain-text body from `monitor/email/fail_notification.txt`.
- Render HTML body from `monitor/email/fail_notification.html`.
- Send via `EmailMultiAlternatives` using `settings.DEFAULT_FROM_EMAIL`.
- On success: set `rule.last_notified_at = timezone.now()`,
  call `Rule.objects.filter(pk=rule.pk).update(last_notified_at=...)` to avoid a
  full `rule.save()` (which would touch `updated_at` auto_now).
- On `Exception`: log at ERROR level, return False.
- Return True on successful send.

#### 2. Email templates

**File**: `templates/monitor/email/fail_notification.txt`

**Intent**: Plain-text fallback for email clients that don't render HTML.

**Contract**: Template context variables: `rule` (Rule instance), `result` (RuleResult
instance). Include: rule name, status, table or SQL rule type, measured value if
available (`result.row_count`, `result.last_record_age_hours`), error message if ERROR,
and a manual run URL hint.

**File**: `templates/monitor/email/fail_notification.html`

**Intent**: HTML version of the same email. Should be simple — avoid inline images or
complex layouts that break in email clients. A plain `<table>`-based layout or a
single-column `<div>` with inline styles is sufficient.

**Contract**: Same context variables as plain-text template. Status badge with
conditional color (red for FAIL/ERROR). No JavaScript. All styles inline.

### Success Criteria:

#### Automated Verification:

- `python manage.py test monitor` — new unit tests for `send_fail_notification`:
  - Returns False when `notify_on_fail=False`.
  - Returns False when `owner.email` is blank.
  - Returns False when `last_notified_at` is within the cooldown window.
  - Calls `django.core.mail.send_mail` (or `EmailMultiAlternatives.send`) when all
    guards pass (use `django.test.utils.override_settings` with `EMAIL_BACKEND =
    'django.core.mail.backends.locmem.EmailBackend'`).
  - Updates `rule.last_notified_at` after a successful send.
  - Returns False (does not raise) when the send raises an exception.

#### Manual Verification:

- Run `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend python manage.py shell`
  and call `send_fail_notification(rule, result)` directly; confirm email prints to console.

---

## Phase 3: Hook into services.py

### Overview

Import `send_fail_notification` from `monitor.email_service` and call it after every
`RuleResult.objects.create(...)` that records FAIL or ERROR in both `run_single_rule`
and `run_all_checks`. The hook is fire-and-forget — a send failure must not raise.

### Changes Required:

#### 1. run_single_rule hook

**File**: `monitor/services.py`

**Intent**: After each `RuleResult.objects.create(...)` call in `run_single_rule`,
call `send_fail_notification(rule, result)` when `result.status` is FAIL or ERROR.
There are five create sites in this function; all must be covered.

**Contract**: Add import at top of file:
```python
from .email_service import send_fail_notification
```
After each `result = RuleResult.objects.create(...)`:
```python
if result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
    send_fail_notification(rule, result)
```
The `send_fail_notification` function already swallows exceptions, so no try/except
wrapper is needed here.

#### 2. run_all_checks hook

**File**: `monitor/services.py`

**Intent**: Same pattern as `run_single_rule` but in `run_all_checks`. The loop
calls `RuleResult.objects.create(...)` in **five** branches; all must be covered:
1. No connection object (line 273)
2. Empty connection URL (line 282)
3. Connection error branch (line 298)
4. Successful check result (line 305)
5. Outer `except Exception` block (line 314) — creates `RuleResult.Status.ERROR`;
   the return value is not currently captured, so capture it before adding the hook.

In branches that use a local `result` variable, call `send_fail_notification(rule, result)`.
In branches that call `RuleResult.objects.create(...)` without capturing the return value,
capture it first.

**Contract**: Same import as above (already added in step 1). For each create call,
capture result if not already, then add the status check and notification call.

### Success Criteria:

#### Automated Verification:

- `python manage.py test monitor` — existing tests pass.
- New integration tests (in `monitor/tests.py`):
  - `run_single_rule` with a FAIL result calls `send_fail_notification` with the rule
    and result (mock the function, assert `mock.called`).
  - `run_all_checks` with one FAIL rule and `notify_on_fail=True` calls
    `send_fail_notification` once (mock).
  - `run_single_rule` with OK result does NOT call `send_fail_notification`.

#### Manual Verification:

- Click "Run check" on a rule with `notify_on_fail=True` and `owner.email` set;
  confirm email appears in console (dev) or SendGrid activity (production).

---

## Phase 4: UI — notify_on_fail Toggle

### Overview

Add the `notify_on_fail` field to `RuleForm` and the rule form template. The toggle
appears under the Schedule section as a simple checkbox.

### Changes Required:

#### 1. RuleForm — add notify_on_fail

**File**: `monitor/forms.py`

**Intent**: Expose `notify_on_fail` in the create/edit form so users can opt-in
per rule. No custom widget needed — the default `CheckboxInput` is appropriate.

**Contract**: Append `'notify_on_fail'` to `RuleForm.Meta.fields`:
```python
fields = [
    'name', 'schema_name', 'table_name', 'connection',
    'rule_type', 'custom_sql', 'timestamp_column',
    'max_age_hours', 'min_row_count', 'schedule_time',
    'notify_on_fail',  # NEW
]
```
Add widget override in `Meta.widgets`:
```python
'notify_on_fail': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
```

#### 2. Rule form template — checkbox UI

**File**: `templates/monitor/rule_form.html`

**Intent**: Render the `notify_on_fail` checkbox after the Schedule section, before
the Save button row. Use the project's existing form-card styling for consistency.

**Contract**: Add a new section between `<!-- ── Schedule ── -->` block and the
save button `<div class="d-flex ...">`:

```html
<!-- ── Notifications ── -->
<div class="form-section-label">Notifications</div>
<div class="mb-4">
  <div class="form-check">
    {{ form.notify_on_fail }}
    <label class="form-check-label" for="{{ form.notify_on_fail.id_for_label }}">
      Notify me on failure
    </label>
  </div>
  <div class="form-text" style="margin-top:4px">
    Send an email when this rule returns FAIL or ERROR.
    Requires your account to have an email address set.
    Cooldown: at most one email per hour per rule.
  </div>
  {% if form.notify_on_fail.errors %}
    <div class="field-error">✗ {{ form.notify_on_fail.errors|join:", " }}</div>
  {% endif %}
</div>
```

### Success Criteria:

#### Automated Verification:

- `python manage.py test monitor` passes.
- POST to rule create/edit with `notify_on_fail=True` saves correctly (add form test).

#### Manual Verification:

- Open the rule form in browser; confirm "Notify me on failure" checkbox renders in
  the Notifications section.
- Create a new rule with the checkbox checked; confirm `Rule.notify_on_fail=True` in
  the admin.
- Edit an existing rule; confirm checkbox state reflects the saved value.

---

## Phase 5: Settings & Docs

### Overview

Wire Django's email backend to SendGrid via SMTP. Add env var declarations to
`render.yaml`. Document the setup in `.env.example`.

### Changes Required:

#### 1. settings.py — EMAIL_* config

**File**: `data_pulse/settings.py`

**Intent**: Configure Django to send email via SMTP by reading env vars. Fall back
to console backend in dev when `EMAIL_HOST` is not set, so local dev works without
credentials.

**Contract**: Add after `LOGIN_REDIRECT_URL` / at the end of the file:

```python
# Email — SendGrid SMTP (or any SMTP provider)
# Set EMAIL_HOST in environment to activate SMTP; falls back to console in dev.
EMAIL_BACKEND = env(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.console.EmailBackend',
)
EMAIL_HOST = env('EMAIL_HOST', default='smtp.sendgrid.net')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='apikey')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='DataPulse <no-reply@example.com>')
```

#### 2. render.yaml — add email env vars

**File**: `render.yaml`

**Intent**: Declare the six email env vars in the Render service so they can be
populated in the Render dashboard. `EMAIL_HOST_PASSWORD` (SendGrid API key) must be
`sync: false` (secret). Others are non-secret values.

**Contract**: Add to `envVars` list:
```yaml
      - key: EMAIL_BACKEND
        value: "django.core.mail.backends.smtp.EmailBackend"
      - key: EMAIL_HOST
        value: "smtp.sendgrid.net"
      - key: EMAIL_PORT
        value: "587"
      - key: EMAIL_USE_TLS
        value: "True"
      - key: EMAIL_HOST_USER
        value: "apikey"
      - key: EMAIL_HOST_PASSWORD
        sync: false
      - key: DEFAULT_FROM_EMAIL
        value: "DataPulse <no-reply@yourdomain.com>"
```

#### 3. .env.example — document SendGrid setup

**File**: `.env.example` (create if absent, append if present)

**Intent**: Document the email env vars for local developers and the README. Include
a short comment explaining how to get a SendGrid API key.

**Contract**: Append:
```
# Email — SendGrid SMTP
# Sign up at sendgrid.com, create an API key with "Mail Send" permission.
# EMAIL_BACKEND defaults to console in dev; set smtp backend for real sends.
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=SG.your-api-key-here
DEFAULT_FROM_EMAIL=DataPulse <no-reply@yourdomain.com>
```

### Success Criteria:

#### Automated Verification:

- `python manage.py check` exits 0 with the new settings applied.
- `python manage.py test monitor` passes.

#### Manual Verification:

- On local dev (no `EMAIL_HOST` env var): send a test email via shell confirm it prints
  to console (console backend active).
- On Render: set `EMAIL_HOST_PASSWORD` in the Render dashboard; trigger a FAIL rule;
  confirm email arrives in inbox and SendGrid activity log shows a sent event.
- Confirm `DEFAULT_FROM_EMAIL` matches the sender address in the received email.

---

## Testing Strategy

### Unit Tests:

- `send_fail_notification` guard conditions (all four: disabled, no email, cooldown, exception).
- `send_fail_notification` happy path: correct subject, correct recipient, `last_notified_at` updated.
- Cooldown boundary: `last_notified_at` exactly 1h ago → sends; 59m ago → skips.

### Integration Tests:

- `run_single_rule` FAIL → `send_fail_notification` called (mocked).
- `run_all_checks` with mixed rules → notification called only for FAIL/ERROR rules with `notify_on_fail=True`.
- Rule form POST with `notify_on_fail=True` → `Rule.notify_on_fail` saved as True.

### Manual Testing Steps:

1. Create a rule with `notify_on_fail=True`, set an email on the owner account.
2. Run the rule manually; expect email in console/inbox.
3. Run the rule again immediately; expect no second email (cooldown).
4. Wait 1 hour (or set `last_notified_at` to > 1h ago in admin); run again; expect email.
5. Create a rule with `notify_on_fail=False`; run it to FAIL; confirm no email.
6. Test a rule whose owner has a blank email; confirm no crash, no email, log entry.

## Performance Considerations

Email sending is synchronous in this plan. For the current single-user/small-scale
deployment on Render, this is acceptable — Django's SMTP send is typically < 500ms.
If the project grows to many rules per run, the email calls inside `run_all_checks`
will add latency proportional to rule count. Mitigation path (not in scope): move
to async task queue (Celery/django-rq). For now, the cooldown ensures at most one
SMTP call per rule per hour.

## Migration Notes

- Migration `0005` adds two nullable/defaulted fields — no data migration needed.
- `notify_on_fail` defaults to `False`: all existing rules are opt-out.
- `last_notified_at` defaults to NULL: no cooldown applies until first send.
- Migration is safe to deploy ahead of the email service code.

## References

- Research: `context/changes/email-notifications/research.md`
- Change: `context/changes/email-notifications/change.md`
- Roadmap item: S-13 in `context/foundation/roadmap.md`
- Depends on: S-12 (multi-tenancy) — `Rule.owner` FK must exist
- services.py result creation sites: `monitor/services.py:215–261` (run_single_rule), `monitor/services.py:263–314` (run_all_checks)
- RuleResult.Status: `monitor/models.py:142–148`
- RuleForm.Meta.fields: `monitor/forms.py:34`
- settings.py env pattern: `data_pulse/settings.py` (uses `django-environ`)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Model Changes

#### Automated

- [x] 1.1 makemigrations check exits 0 after adding fields
- [x] 1.2 migrate applies cleanly on SQLite
- [x] 1.3 existing test suite passes after migration

#### Manual

- [ ] 1.4 notify_on_fail and last_notified_at visible in Django admin

### Phase 2: Email Service

#### Automated

- [x] 2.1 unit test — returns False when notify_on_fail=False
- [x] 2.2 unit test — returns False when owner email blank
- [x] 2.3 unit test — returns False when within cooldown window
- [x] 2.4 unit test — sends email and returns True when all guards pass
- [x] 2.5 unit test — updates last_notified_at after successful send
- [x] 2.6 unit test — returns False (no raise) on send exception

#### Manual

- [ ] 2.7 console email prints when send_fail_notification called directly in shell

### Phase 3: Hook into services.py

#### Automated

- [x] 3.1 run_single_rule FAIL calls send_fail_notification (mocked)
- [x] 3.2 run_all_checks FAIL/notify_on_fail=True calls send_fail_notification (mocked)
- [x] 3.3 run_single_rule OK does NOT call send_fail_notification
- [x] 3.4 all existing tests pass

#### Manual

- [ ] 3.5 manual rule run with notify_on_fail=True triggers console email

### Phase 4: UI

#### Automated

- [x] 4.1 form POST with notify_on_fail=True saves correctly
- [x] 4.2 full test suite passes

#### Manual

- [ ] 4.3 notify_on_fail checkbox renders in rule form
- [ ] 4.4 checkbox state persists on edit
- [ ] 4.5 new rule created with checkbox checked saves notify_on_fail=True

### Phase 5: Settings & Docs

#### Automated

- [x] 5.1 python manage.py check exits 0 with new EMAIL_* settings
- [x] 5.2 full test suite passes

#### Manual

- [ ] 5.3 console backend active on local dev without EMAIL_HOST env var
- [ ] 5.4 email arrives in inbox on Render with SendGrid credentials set
- [ ] 5.5 cooldown suppresses second email on immediate re-run
