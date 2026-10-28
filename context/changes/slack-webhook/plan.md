# Slack Webhook Notifications — Implementation Plan

## Overview

Add Slack Incoming Webhook notifications to DataPulse so that every FAIL/ERROR rule result fires a rich Block Kit message to a user-configured Slack channel. Users manage webhook endpoints via a new `SlackWebhook` model (one or more named URLs per user) and opt individual rules in via a `notify_slack` toggle. A coordinator function `notify_rule_result` in `email_service.py` replaces the 11 scattered `send_fail_notification` call sites in `services.py`.

## Current State Analysis

The existing email notification path (`monitor/email_service.py:21`) is self-contained: guards (`notify_on_fail`, user email, 1-hour cooldown), renders templates, sends via Django mail, and stamps `last_notified_at` via `.update()` to avoid touching the `auto_now` `updated_at` field. This exact shape — guard flag, cooldown timestamp, fire-and-forget call — maps directly onto a Slack sender.

A `SlackNotification` stub model exists (`models.py:260–275`, migration 0007, admin-registered) but carries no `name` field and is not wired to any notification path. The approved decision introduces a new `SlackWebhook` model that adds `name` and uses `url` instead of `webhook_url`; the stub remains in place untouched.

`send_fail_notification` is called at 11 sites across three service functions in `services.py` (lines 300, 311, 325, 333, 341, 405, 443, 455, 473, 484, 493). A coordinator function reduces this to a single import and 11 identical one-line calls while keeping the Slack sender fully decoupled.

No HTTP client library is present in `pyproject.toml`; `urllib.request` (stdlib) avoids any new dependency. Latest migration: `0012_rule_notify_fields.py`. Next will be `0013_...`.

### Key Discoveries:

- `monitor/email_service.py:62–63` — cooldown stamp uses `.update()` not `.save()` to skip `auto_now`; the Slack sender must do the same for `last_slack_notified_at`
- `monitor/models.py:166–171` — `Rule.notify_on_fail` + `Rule.last_notified_at` are the exact structural mirror for the new `notify_slack` + `last_slack_notified_at`
- `monitor/services.py:16` — single import of `send_fail_notification`; the coordinator replaces this import and all 11 call sites
- `monitor/forms.py:37,59` — `notify_on_fail` in `RuleForm.Meta.fields` and the `widgets` dict; `notify_slack` follows the same pattern
- `monitor/tests.py:1537–1671` — email_service test suite is the structural template for slack_service unit tests

## Desired End State

Users can create named Slack webhook URLs in a new "Slack Webhooks" settings section. Each rule exposes a "Notify via Slack" checkbox alongside the existing "Notify on failure" checkbox. When a monitored rule returns FAIL or ERROR and `notify_slack=True`, DataPulse POSTs a Slack Block Kit message (two-field section with rule name, status, measured value, threshold + a "View History" action button) to the user's first enabled `SlackWebhook`, subject to a 1-hour per-rule cooldown. Both email and Slack fire from a single `notify_rule_result(rule, result)` call — no duplicated guard logic in `services.py`.

### Key Discoveries:

- End state is verifiable: admin shows `SlackWebhook`, rule edit form has `notify_slack` checkbox, a FAIL result with `notify_slack=True` and an enabled webhook POSTs to Slack with Block Kit content
- The existing `SlackNotification` stub (migration 0007) remains in place; `SlackWebhook` is purely additive

## What We're NOT Doing

- Microsoft Teams support — v1 is Slack only; Teams (URL-prefix routing + MessageCard payload) is a follow-up slice
- Per-connection webhook URL granularity — URL lives on `SlackWebhook` (user-level), not on `Connection`
- Settings-level global fallback webhook URL — model-stored only
- Adaptive Card or MessageCard payloads — Slack Block Kit only
- Async / Celery dispatch — synchronous `urllib.request` with a 5-second timeout, matching the email pattern
- Multi-webhook fan-out per rule result — the first enabled `SlackWebhook` for the user is used in v1
- Shared email/Slack cooldown — each channel keeps its own timestamp (`last_notified_at` vs `last_slack_notified_at`)

## Implementation Approach

Mirror the email notification pattern exactly. Phase 1 adds the data model. Phase 2 builds the isolated Slack sender. Phase 3 adds the coordinator to `email_service.py` and rewires `services.py`. Phase 4 delivers user-facing CRUD and the rule toggle. Phase 5 closes test coverage. Phases are ordered so each phase is independently reviewable and leaves the test suite green.

---

## Phase 1: SlackWebhook Model + Migration

### Overview

Add the `SlackWebhook` model to `monitor/models.py`, add two new fields to `Rule`, generate migration 0013, and register `SlackWebhook` in Django admin. No service, view, or URL changes in this phase.

### Changes Required:

#### 1. New `SlackWebhook` model

**File**: `monitor/models.py`

**Intent**: Define `SlackWebhook` as a named, per-user webhook endpoint, appended after the existing `SlackNotification` class.

**Contract**: Fields: `user` (ForeignKey to `settings.AUTH_USER_MODEL`, `on_delete=CASCADE`, NOT null, `related_name='slack_webhooks'`), `name` (CharField, max_length=100), `url` (CharField, max_length=500, blank=True), `enabled` (BooleanField, default=True), `created_at` (auto_now_add=True), `updated_at` (auto_now=True). `Meta.unique_together = [('user', 'name')]`. `Meta.ordering = ['name']`. `__str__` returns `self.name`.

#### 2. `Rule.notify_slack` and `Rule.last_slack_notified_at`

**File**: `monitor/models.py`

**Intent**: Add per-rule Slack opt-in flag and cooldown timestamp, mirroring `notify_on_fail` / `last_notified_at` at `models.py:166–171`.

**Contract**: Insert both fields immediately after `last_notified_at`. `notify_slack`: `BooleanField(default=False, verbose_name='Notify via Slack', help_text='Send a Slack message to the rule owner when this rule returns FAIL or ERROR.')`. `last_slack_notified_at`: `DateTimeField(null=True, blank=True, verbose_name='Last Slack notified at')`.

#### 3. Migration 0013

**File**: `monitor/migrations/0013_rule_notify_slack_slackwebhook.py`

**Intent**: Single migration covering the new `SlackWebhook` model and the two new `Rule` fields. Generated via `python manage.py makemigrations monitor`.

**Contract**: Dependencies: `[('monitor', '0012_rule_notify_fields')]`. Additive only — no data migration required.

#### 4. Admin registration

**File**: `monitor/admin.py`

**Intent**: Expose `SlackWebhook` in Django admin for manual verification during development.

**Contract**: Add `SlackWebhook` to the import from `.models`. Register with `@admin.register(SlackWebhook)` and `list_display = ['name', 'user', 'enabled', 'created_at']`.

### Success Criteria:

#### Automated Verification:

- Migration applies cleanly: `python manage.py migrate`
- Existing test suite passes with no regressions: `python manage.py test monitor`

#### Manual Verification:

- Django admin shows `SlackWebhook` model with name, user, enabled, created_at columns
- Rule admin / inline shows `notify_slack` checkbox

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding to Phase 2.

---

## Phase 2: Slack Sender Service

### Overview

Create `monitor/slack_service.py` with `send_slack_notification(rule, result) -> bool`. This module is entirely self-contained; no changes to `services.py` or `email_service.py` in this phase.

### Changes Required:

#### 1. `monitor/slack_service.py` — new file

**File**: `monitor/slack_service.py`

**Intent**: Self-contained Slack notification sender. Mirrors the guard → cooldown → dispatch → stamp pattern from `email_service.py` exactly.

**Contract**:
- Module constant: `COOLDOWN_HOURS = 1`
- Guard sequence (returns `False` immediately on any unmet condition):
  1. `rule.notify_slack` is `True`
  2. `SlackWebhook.objects.filter(user=rule.user, enabled=True).first()` returns a record — otherwise `False`
  3. Cooldown: `rule.last_slack_notified_at is not None` and `timezone.now() - rule.last_slack_notified_at < timedelta(hours=COOLDOWN_HOURS)` → return `False`
- Block Kit payload structure: top-level `text` (required Slack fallback, format: `[DataPulse] {rule.name} — {result.status}`), `blocks` array with a `section` text block (mrkdwn summary), a `section` fields block (four `mrkdwn` fields: Rule, Status, Measured, Threshold), and an `actions` block with a single "View History" button whose `url` is built with `django.urls.reverse('monitor:rule_history', args=[rule.pk])`.
- HTTP dispatch via `urllib.request` (shown below — the only non-obvious part):

```python
import json, urllib.request

data = json.dumps(payload).encode()
req = urllib.request.Request(
    webhook.url,
    data=data,
    headers={'Content-Type': 'application/json'},
    method='POST',
)
urllib.request.urlopen(req, timeout=5)
```

- On success: `Rule.objects.filter(pk=rule.pk).update(last_slack_notified_at=timezone.now())` then update `rule.last_slack_notified_at` in-memory. Returns `True`.
- On any exception: `logger.error(...)` at ERROR level (never raises). Returns `False`.

### Success Criteria:

#### Automated Verification:

- Unit tests for `send_slack_notification` pass (added in Phase 5, but the module must be importable and not break existing tests): `python manage.py test monitor`

#### Manual Verification:

- Calling `send_slack_notification` with a FAIL result and an enabled `SlackWebhook` sends the Block Kit message to a real Slack channel in a dev environment

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding to Phase 3.

---

## Phase 3: Coordinator Function + services.py Wire-up

### Overview

Add `notify_rule_result(rule, result)` to `monitor/email_service.py`. Update `monitor/services.py` to import and call the coordinator at all 11 current `send_fail_notification` call sites.

### Changes Required:

#### 1. `notify_rule_result` coordinator in `email_service.py`

**File**: `monitor/email_service.py`

**Intent**: Single entry point for all outbound notifications on a rule result. Delegates to both email and Slack senders. Future channels extend only this function.

**Contract**: Add `from .slack_service import send_slack_notification` to the imports. Append `notify_rule_result` function after `send_fail_notification`. Signature: `notify_rule_result(rule: Rule, result) -> dict`. Body calls `send_fail_notification(rule, result)` and `send_slack_notification(rule, result)`, returns `{'email': bool, 'slack': bool}`. Never raises (both callees already handle their own exceptions).

#### 2. `services.py` import and call-site update

**File**: `monitor/services.py`

**Intent**: Replace the direct `send_fail_notification` import with `notify_rule_result` and update all 11 call sites.

**Contract**: Replace line 16 (`from .email_service import send_fail_notification`) with `from .email_service import notify_rule_result`. At each of the 11 call sites (lines 300, 311, 325, 333, 341, 405, 443, 455, 473, 484, 493), replace `send_fail_notification(rule, result)` with `notify_rule_result(rule, result)`. The return value is discarded at every call site (research confirmed), so no further changes are required.

### Success Criteria:

#### Automated Verification:

- Full test suite passes: `python manage.py test monitor`
- No remaining `send_fail_notification` import in `services.py`: `grep 'send_fail_notification' monitor/services.py` returns empty

#### Manual Verification:

- Triggering a FAIL result via "Run now" with both `notify_on_fail=True` and `notify_slack=True` configured sends both email and Slack notifications

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding to Phase 4.

---

## Phase 4: UI — SlackWebhook CRUD + Rule Toggle

### Overview

Add web CRUD for `SlackWebhook` management and wire `notify_slack` into the rule create/edit form. All changes are in views, forms, URLs, and templates — no backend notification logic changes.

### Changes Required:

#### 1. `SlackWebhookForm` in `monitor/forms.py`

**File**: `monitor/forms.py`

**Intent**: Form for creating and editing `SlackWebhook` instances, following the `ConnectionForm` pattern.

**Contract**: `class SlackWebhookForm(forms.ModelForm)` with `Meta.model = SlackWebhook`, `Meta.fields = ['name', 'url', 'enabled']`. `widgets`: `url` uses `TextInput(attrs={'placeholder': 'https://hooks.slack.com/services/...'})`, `enabled` uses `CheckboxInput(attrs={'class': 'form-check-input'})`. Import `SlackWebhook` from `.models`.

#### 2. `notify_slack` added to `RuleForm`

**File**: `monitor/forms.py`

**Intent**: Expose the `notify_slack` rule toggle in create/edit forms, directly after `notify_on_fail`.

**Contract**: Add `'notify_slack'` to `RuleForm.Meta.fields` immediately after `'notify_on_fail'` (currently at index position in line 37). Add `'notify_slack': forms.CheckboxInput(attrs={'class': 'form-check-input'})` to `RuleForm.Meta.widgets`.

#### 3. SlackWebhook CRUD views

**File**: `monitor/views.py`

**Intent**: Four login-required views for managing a user's `SlackWebhook` records, following the `connection_list` / `connection_create` / `connection_edit` / `connection_delete` pattern (`views.py:219–258`).

**Contract**:
- `slack_webhook_list(request)` — renders `request.user.slack_webhooks.all()` ordered by name; template `monitor/slack_webhook_list.html`
- `slack_webhook_create(request)` — POST creates a new `SlackWebhook` with `user=request.user`; redirects to `slack_webhook_list` on success
- `slack_webhook_edit(request, wh_id)` — retrieves via `get_object_or_404(SlackWebhook, pk=wh_id, user=request.user)`; redirects to list on save
- `slack_webhook_delete(request, wh_id)` — POST-only; scoped to `request.user`; redirects to list

#### 4. URL routes

**File**: `monitor/urls.py`

**Intent**: Four URL patterns for the SlackWebhook CRUD views, grouped with the connection routes.

**Contract**:
- `path('slack-webhooks/', views.slack_webhook_list, name='slack_webhook_list')`
- `path('slack-webhooks/new/', views.slack_webhook_create, name='slack_webhook_create')`
- `path('slack-webhooks/<int:wh_id>/edit/', views.slack_webhook_edit, name='slack_webhook_edit')`
- `path('slack-webhooks/<int:wh_id>/delete/', views.slack_webhook_delete, name='slack_webhook_delete')`

#### 5. Templates

**Files**: `monitor/templates/monitor/slack_webhook_list.html`, `monitor/templates/monitor/slack_webhook_form.html`

**Intent**: List view with Add button, enable/disable badge, edit and delete links. Form view for create/edit. Follow the visual patterns of `connection_list.html` and `connection_form.html`.

**Contract**: Both extend `monitor/base.html`. List shows name, URL (truncated to ~50 chars), enabled badge, edit/delete actions. Form has labeled fields for name, URL (with placeholder), and enabled checkbox.

#### 6. Navigation link

**File**: `monitor/templates/monitor/base.html` (or whichever template renders the sidebar/nav)

**Intent**: Make "Slack Webhooks" discoverable from the main navigation, adjacent to "Connections".

**Contract**: Add a nav entry linking to `{% url 'monitor:slack_webhook_list' %}` with label "Slack Webhooks". Follow the exact same markup pattern as the "Connections" nav entry.

### Success Criteria:

#### Automated Verification:

- All new view tests pass: `python manage.py test monitor`
- Form validation rejects a `SlackWebhook` with a blank `url`

#### Manual Verification:

- User can create, edit, and delete a `SlackWebhook` via the UI
- Enabled/disabled state toggles and persists
- Rule create/edit form shows `notify_slack` checkbox and saving with it checked persists `True`

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding to Phase 5.

---

## Phase 5: Tests

### Overview

Add targeted tests for `slack_service.py`, the coordinator function, and the CRUD views. All tests are added to the existing `monitor/tests.py`. Existing services integration tests are updated to mock `notify_rule_result` instead of `send_fail_notification`.

### Changes Required:

#### 1. `SlackWebhook` model tests

**File**: `monitor/tests.py`

**Intent**: Verify model defaults, `unique_together` constraint, and `__str__`.

**Contract**: `class SlackWebhookModelTest(TestCase)`. Tests: `enabled=True` by default, `__str__` returns `name`, `unique_together` raises `IntegrityError` on duplicate `(user, name)`.

#### 2. `send_slack_notification` unit tests

**File**: `monitor/tests.py`

**Intent**: Full guard and dispatch coverage, mirroring the email_service tests at `tests.py:1537`. Patch `urllib.request.urlopen`.

**Contract**: `class SendSlackNotificationTest(TestCase)`. Tests:
- Returns `False` when `rule.notify_slack = False`
- Returns `False` when no enabled `SlackWebhook` exists for the user
- Returns `False` when cooldown has not expired (< 1 hour ago)
- Returns `True` when cooldown has expired (≥ 1 hour ago)
- Stamps `rule.last_slack_notified_at` on successful POST
- Cooldown stamp uses `.update()` not `.save()` (verify `updated_at` unchanged)
- Returns `False` and logs at ERROR on `urllib.error.URLError`
- Block Kit payload contains rule name, result status, and `"View History"` button text

#### 3. `notify_rule_result` coordinator tests

**File**: `monitor/tests.py`

**Intent**: Verify the coordinator calls both channels and returns the correct dict shape.

**Contract**: `class NotifyRuleResultTest(TestCase)`. Patch `send_fail_notification` and `send_slack_notification`. Tests:
- Returns `{'email': True, 'slack': True}` when both succeed
- Returns `{'email': False, 'slack': True}` when email is skipped
- Returns `{'email': True, 'slack': False}` when Slack is skipped

#### 4. SlackWebhook CRUD view tests

**File**: `monitor/tests.py`

**Intent**: Auth-guard and happy-path tests for all four CRUD views, following the connection view test patterns.

**Contract**: `class SlackWebhookViewsTest(TestCase)`. Tests: unauthenticated request redirects to login, list view renders, create saves with `user=request.user`, edit is scoped to owner (another user's webhook returns 404), delete removes the record.

#### 5. Update services integration test

**File**: `monitor/tests.py`

**Intent**: The existing integration test that mocks `send_fail_notification` (tests.py:1667) must be updated to mock `notify_rule_result` in `services.py` instead, since that is now the call site.

**Contract**: In `test_run_single_rule_fail_calls_send_fail_notification` (or equivalent), change the mock target from `monitor.services.send_fail_notification` to `monitor.services.notify_rule_result`. Assert it is called once with the correct `(rule, result)` arguments.

### Success Criteria:

#### Automated Verification:

- Full test suite passes with no regressions: `python manage.py test monitor`
- At least 15 new test methods present in the added test classes

#### Manual Verification:

- Test output lists all new test classes and methods by name

---

## Testing Strategy

### Unit Tests:

- All `send_slack_notification` guards (notify_slack=False, no webhook, cooldown active, cooldown expired)
- Block Kit payload structure (rule name, status, threshold fields present, "View History" button)
- Coordinator return dict for all three outcome combinations
- `SlackWebhook` model constraints (defaults, unique_together, str)

### Integration Tests:

- FAIL result end-to-end through `run_single_rule` → `notify_rule_result` → both channels fire

### Manual Testing Steps:

1. Create a `SlackWebhook` with a real Incoming Webhook URL from a test Slack workspace
2. Create a rule targeting a table; set `notify_slack=True` and `notify_on_fail=True`
3. Force a FAIL result via "Run now"
4. Confirm a Block Kit message appears in the Slack channel with rule name, status, measured/threshold fields, and a working "View History" link
5. Trigger the same rule again within 1 hour — confirm no second Slack message is sent
6. Disable the webhook; trigger again — confirm no message is sent despite `notify_slack=True`

## Performance Considerations

The Slack POST is synchronous with a 5-second timeout, running inline during `run_single_rule`. This matches the email pattern and is acceptable for the current synchronous architecture. A single slow Slack endpoint response adds up to 5 s per FAIL/ERROR rule per run. No additional caching is needed — the per-rule cooldown timestamp is already the rate-limiting mechanism.

## Migration Notes

Migration 0013 is purely additive: a new model and two new nullable/default fields on `Rule`. No data migration required. The existing `SlackNotification` model (migration 0007) and its admin registration remain untouched in this change.

## References

- Related research: `context/changes/slack-webhook/research.md`
- Email pattern to mirror: `monitor/email_service.py:21–70`
- Rule notify fields: `monitor/models.py:166–175`
- Existing SlackNotification stub: `monitor/models.py:260–275`
- Service call sites: `monitor/services.py:300,311,325,333,341,405,443,455,473,484,493`
- Email test template: `monitor/tests.py:1537`
- Connection CRUD pattern: `monitor/views.py:219–258`, `monitor/urls.py:22–25`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: SlackWebhook Model + Migration

#### Automated

- [x] 1.1 Migration applies cleanly
- [x] 1.2 Existing test suite passes after model changes

#### Manual

- [ ] 1.3 Admin shows SlackWebhook model with correct fields
- [ ] 1.4 Rule admin shows notify_slack checkbox

### Phase 2: Slack Sender Service

#### Automated

- [x] 2.1 slack_service.py imports without error and existing tests pass

#### Manual

- [ ] 2.2 End-to-end fire with real Slack webhook URL in dev environment

### Phase 3: Coordinator + services.py Wire-up

#### Automated

- [x] 3.1 Full test suite passes
- [x] 3.2 No remaining send_fail_notification import in services.py

#### Manual

- [ ] 3.3 Existing send_fail_notification mock targets updated in tests
- [ ] 3.4 FAIL result triggers both email and Slack notifications

### Phase 4: UI — SlackWebhook CRUD + Rule Toggle

#### Automated

- [x] 4.1 New view tests pass
- [x] 4.2 Form validation rejects blank URL

#### Manual

- [ ] 4.3 User can create, edit, and delete SlackWebhook via UI
- [ ] 4.4 Rule form shows notify_slack checkbox and persists correctly

### Phase 5: Tests

#### Automated

- [x] 5.1 Full test suite passes with no regressions
- [x] 5.2 At least 15 new test methods present
