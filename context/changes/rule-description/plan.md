# Rule Description Field — Implementation Plan

## Overview

Add an optional `description` field (`TextField`, `blank=True`, `max_length=500`) to the `Rule` model. The field gives teams a place to record *why* a rule exists. It surfaces in: the rule form (textarea below Rule name), the dashboard rule row (muted secondary line, truncated at 80 chars), the rule-history header card, email notifications (fail + digest), and Slack Block Kit messages.

## Current State Analysis

- `Rule` has no `description` field. `Connection.description` (`CharField(max_length=500, blank=True)`, `models.py:26`) is the closest existing precedent but uses `CharField`; the decision is `TextField` for `Rule` to allow multi-sentence notes without a hard UI cap.
- Latest migration is `0017_apikey.py`; next number is `0018`.
- `RuleForm.Meta.fields` (`forms.py:49`) lists 13 fields; `description` is absent and must be added after `name`.
- Dashboard rule row (`templates/monitor/dashboard.html:430–432`) renders `rule.name` inside `<a class="rule-link">`; the `<td>` has no secondary content yet.
- Rule history header (`templates/monitor/rule_history.html:76–78`) shows `.rule-meta-name` then `.rule-meta-table` then `.cond-chips`; no description line.
- Email fail notification subject (`email_service.py:50`): `f'[DataPulse] {rule.name} — {result.status}'`. Decision: no change to subject; description goes into the body only.
- Slack payload (`slack_service.py`): four `fields` in the `section` block; a fifth "Note" field added when description is non-empty.
- `make_rule()` factory (`tests.py:24`) does not pass `description`; the new `blank=True` default means no factory change is needed.

## Desired End State

After this plan is complete:
- `Rule.description` is a `TextField(blank=True, max_length=500)` column backed by migration `0018`.
- Creating or editing a rule shows a "Description" textarea below "Rule name".
- Dashboard: a muted `<div>` below the rule-name link shows the first 80 chars of the description when non-empty.
- Rule history header: the description appears as a muted `<div>` between the table name and condition chips, when non-empty.
- Fail email body (.txt and .html): a "Note:" line / table row shows the description when non-empty.
- Digest email body (.txt and .html): a "Note:" indented line per result shows the description when non-empty.
- Slack Block Kit: a fifth field "Note" is appended to the section `fields` list when non-empty.
- Tests cover: model field defaults, form save round-trip, dashboard truncation rendering, email/Slack body content when description is set and when blank.

### Key Discoveries

- `Connection.description` at `models.py:26` uses `CharField(max_length=500)` — `Rule.description` intentionally uses `TextField` (approved).
- Dashboard `<td>` at `dashboard.html:430–432` already contains only the `<a class="rule-link">`; the description `<div>` is appended inside the same `<td>` without touching any JS filter attributes.
- The JS filter at `dashboard.html:551` searches only `data-name`; no `data-description` attribute is needed.
- Slack `fields` list has exactly 4 items; Slack Block Kit allows up to 10 fields per `section`, so adding a fifth is safe.
- Email subject line decision: description is **not** added to the subject — it appears in the body only.

## What We're NOT Doing

- Not adding `description` to the email or Slack *subject* lines.
- Not making `description` searchable in the dashboard filter bar.
- Not adding a `max_length` validator to `Rule.description` at the model level — the 500-char cap is enforced by the form `max_length` widget attribute only, matching the decision.
- Not adding a tooltip on hover in the dashboard (tooltip was listed as a display option in the task; the approved display is a truncated secondary line, not a tooltip).
- Not modifying `make_rule()` factory — the blank default makes existing calls work unchanged.

## Implementation Approach

Five sequential phases, each independently verifiable:
1. Model field + migration — unblocks everything else.
2. Form — adds the textarea to create/edit flows.
3. Dashboard + history templates — display in the two main UI surfaces.
4. Notifications — email and Slack bodies.
5. Tests — unit + integration coverage for all new behaviour.

---

## Phase 1: Model Field and Migration

### Overview

Add `Rule.description = TextField(blank=True, max_length=500)` and generate migration `0018_rule_description`.

### Changes Required

#### 1. `Rule` model — add `description` field

**File**: `monitor/models.py`

**Intent**: Insert `description` as the second field on `Rule`, immediately after `name`, so it is logically grouped with the rule's identity fields and matches the position used by `Connection.description`.

**Contract**: New field declaration placed between `name` (line ~80) and `schema_name` (line ~81):

```python
description = models.TextField(
    blank=True,
    max_length=500,
    verbose_name='Description',
    help_text='Optional note explaining why this rule exists.',
)
```

`blank=True` makes it optional in forms and at the DB level. `max_length=500` enforces the 500-char cap via form validation (Django does not enforce `max_length` on `TextField` at the DB level for most backends, but it does via model validation and form widgets).

#### 2. Migration `0018_rule_description`

**File**: `monitor/migrations/0018_rule_description.py`

**Intent**: Add the `description` column to the `monitor_rule` table. All existing rows receive `''` (empty string) as their value.

**Contract**: Generated migration that adds `models.TextField(blank=True, default='', max_length=500, verbose_name='Description', help_text='...')` to `monitor.Rule`. The `default=''` is required for the migration to run non-interactively against existing rows; it does not need to be retained on the model field itself (Django treats `blank=True` TextField as implicitly defaulting to `''` in forms, but the migration writer includes it for the DB ALTER).

### Success Criteria

#### Automated Verification

- Migration applies cleanly: `python manage.py migrate --run-syncdb 2>&1 | tail -5`
- `python manage.py migrate --check` exits 0 (no pending migrations)
- `Rule.description` is accessible on a freshly created rule instance with value `''`

#### Manual Verification

- `python manage.py shell -c "from monitor.models import Rule; print(Rule._meta.get_field('description'))"` prints `<django.db.models.fields.TextField: description>`

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding to Phase 2. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Form Widget

### Overview

Add `description` to `RuleForm` so users can enter and edit it on the create/edit rule pages.

### Changes Required

#### 1. `RuleForm.Meta.fields` — add `description`

**File**: `monitor/forms.py`

**Intent**: Include `description` in the list of fields rendered by `RuleForm`, positioned after `name` so it appears below the Rule name input in the form.

**Contract**: `fields` list at `forms.py:49` becomes:
```python
fields = ['name', 'description', 'schema_name', 'table_name', 'connection',
          'rule_type', 'custom_sql', 'timestamp_column', 'max_age_hours',
          'min_row_count', 'schedule_type', 'schedule_cron',
          'notify_on_fail', 'notify_slack']
```

#### 2. `RuleForm.Meta.widgets` — add `description` widget

**File**: `monitor/forms.py`

**Intent**: Render `description` as a `Textarea` with `rows=3` and a helpful placeholder.

**Contract**: Add to the `widgets` dict (after the `name` entry):
```python
'description': forms.Textarea(attrs={
    'class': 'form-control',
    'rows': 3,
    'placeholder': 'Optional note explaining why this rule exists',
}),
```

#### 3. `rule_form.html` — add description field block

**File**: `templates/monitor/rule_form.html`

**Intent**: Display the description textarea below the Rule name input and above the connection selector, inside the "Rule identity" section.

**Contract**: Insert a new `<div class="mb-3">` block after the closing `</div>` of the `name` field block (currently at line ~208) and before the `<div class="mb-4">` that wraps the `connection` field:

```html
<div class="mb-3">
  <label for="{{ form.description.id_for_label }}" class="form-label">{{ form.description.label }}</label>
  {{ form.description }}
  {% if form.description.errors %}<div class="field-error">✗ {{ form.description.errors|join:", " }}</div>{% endif %}
</div>
```

### Success Criteria

#### Automated Verification

- `RuleForm` instantiates without errors with `description` in fields
- Saving a form with `description='Test note'` persists the value to DB
- Saving a form with `description=''` persists empty string (optional field)
- Form validation rejects `description` longer than 500 chars

#### Manual Verification

- Navigate to create-rule page: "Description" textarea is visible below "Rule name"
- Enter text, save; edit the rule: description is pre-populated
- Leave blank, save: no validation error

---

## Phase 3: Dashboard and History Display

### Overview

Show `description` in two UI surfaces: the dashboard rule-list row (truncated at 80 chars) and the rule-history header card.

### Changes Required

#### 1. Dashboard rule-name cell — add secondary description line

**File**: `templates/monitor/dashboard.html`

**Intent**: Show a muted secondary line below the rule-name link when `description` is non-empty. Truncate at 80 chars to avoid overflowing the narrow rule-name column.

**Contract**: Inside the `<td>` that contains `<a href="..." class="rule-link">` (lines 430–432), append after the closing `</a>`:

```html
{% if item.rule.description %}
<div style="font-size:0.72rem;color:var(--text-muted);margin-top:2px;line-height:1.3">{{ item.rule.description|truncatechars:80 }}</div>
{% endif %}
```

The `data-name` attribute on the `<tr>` is unchanged; the description is not added to filter data.

#### 2. Rule history header — add description line

**File**: `templates/monitor/rule_history.html`

**Intent**: Show the description between the `.rule-meta-table` line and the `.cond-chips` block so readers see the rule's purpose immediately after its table target.

**Contract**: After the `<div class="rule-meta-table">` closing tag (line ~77) and before the `<div class="cond-chips">` opening tag (line ~78), insert:

```html
{% if rule.description %}
<div style="font-size:0.82rem;color:var(--text-muted);margin-top:4px">{{ rule.description }}</div>
{% endif %}
```

No truncation here — the history page has more vertical space and the user is viewing a single rule.

### Success Criteria

#### Automated Verification

- Template renders without errors when `rule.description` is non-empty
- Template renders without errors when `rule.description` is `''`
- `truncatechars:80` filter is applied in the dashboard (verified via rendered HTML in tests)

#### Manual Verification

- Dashboard: rule with description shows muted text below the rule name; rule without description shows no extra line
- History page: rule with description shows text between table name and condition chips

---

## Phase 4: Notifications

### Overview

Surface `description` in email fail notification (txt + HTML), email digest notification (txt + HTML), and Slack Block Kit — all conditioned on non-empty description.

### Changes Required

#### 1. Fail email — plain text

**File**: `templates/monitor/email/fail_notification.txt`

**Intent**: Show a "Note:" line after the "Rule:" line when the rule has a description.

**Contract**: After `Rule:   {{ rule.name }}` and before `Status: {{ result.status }}`, insert:

```
{% if rule.description %}Note:   {{ rule.description }}
{% endif %}
```

#### 2. Fail email — HTML

**File**: `templates/monitor/email/fail_notification.html`

**Intent**: Add a "Note" row to the details table when the rule has a description.

**Contract**: After the `<h1>` that shows `rule.name` (line ~37), or more precisely, inside the details table — append a new table row conditional on `rule.description`. Inspect the template for the exact table row pattern and mirror it:

```html
{% if rule.description %}
<tr>
  <td style="padding:10px 12px;font-size:0.8rem;color:#94a3b8;font-weight:600">Note</td>
  <td style="padding:10px 12px;font-size:0.8rem;color:#e2e8f0">{{ rule.description }}</td>
</tr>
{% endif %}
```

#### 3. Digest email — plain text

**File**: `templates/monitor/email/digest_notification.txt`

**Intent**: Show a "Note:" line per result inside the `{% for result in failing_results %}` block, after the rule name line.

**Contract**: After `Rule:     {{ result.rule.name }}`, insert:

```
{% if result.rule.description %}Note:     {{ result.rule.description }}
{% endif %}
```

#### 4. Digest email — HTML

**File**: `templates/monitor/email/digest_notification.html`

**Intent**: Show the description as a small secondary line inside the Rule column cell of the failure table.

**Contract**: After `{{ result.rule.name }}` inside the Rule `<td>` (line ~64), append:

```html
{% if result.rule.description %}<br><em style="font-size:0.75em;color:#64748b">{{ result.rule.description|truncatechars:80 }}</em>{% endif %}
```

#### 5. Slack Block Kit — add Note field

**File**: `monitor/slack_service.py`

**Intent**: Append a "Note" field to the section `fields` list when `rule.description` is non-empty.

**Contract**: After the `threshold_str` field is appended to the `fields` list, add:

```python
if rule.description:
    fields.append({'type': 'mrkdwn', 'text': f'*Note*\n{rule.description}'})
```

The existing `fields` list is built as a Python list literal; the new entry is appended conditionally before the list is embedded in the block.

### Success Criteria

#### Automated Verification

- `send_fail_notification` with non-empty `rule.description` produces email body containing "Note:" and the description text
- `send_fail_notification` with `rule.description=''` produces email body **without** "Note:"
- `send_digest_notification` with non-empty description includes description in body
- Slack payload includes `*Note*` field when description is non-empty; does not include it when empty
- All existing email notification tests pass unchanged

#### Manual Verification

- Trigger a test failure for a rule with a description; inspect the received email body and Slack message

---

## Phase 5: Tests

### Overview

Add unit and integration tests covering the new field, form, display, and notification behaviour.

### Changes Required

#### 1. `RuleModelTest` — description field

**File**: `monitor/tests.py`

**Intent**: Verify that `Rule.description` defaults to `''` and that the field round-trips correctly.

**Contract**: Add to `RuleModelTest`:
- `test_description_defaults_to_empty`: create rule via `make_rule()`, assert `rule.description == ''`
- `test_description_saved`: create rule with `description='Tracks late orders'`, fetch from DB, assert value persists

#### 2. `RuleFormTest` — description field

**File**: `monitor/tests.py`

**Intent**: Verify form accepts, saves, and validates description.

**Contract**: Add a new `RuleFormTest` class (or extend existing form tests if present):
- `test_description_optional`: form valid when `description` is absent / empty
- `test_description_saved_via_form`: form with `description='Tracks late orders'` saves correctly
- `test_description_max_length_rejected`: form with 501-char description raises `ValidationError`

#### 3. `DashboardViewTest` — description display

**File**: `monitor/tests.py`

**Intent**: Verify the dashboard response includes the truncated description for a rule that has one, and omits the description div for a rule without one.

**Contract**:
- `test_dashboard_shows_description`: create rule with `description='My note'`, GET dashboard, assert `'My note'` in response content
- `test_dashboard_omits_empty_description`: create rule with `description=''`, GET dashboard, assert the description `<div>` is not rendered (check for the absence of the `--text-muted` style div following the rule-link, or use a sentinel string)

#### 4. Notification tests — description in body

**File**: `monitor/tests.py`

**Intent**: Verify description appears in email and Slack payloads when set, and is absent when not set.

**Contract**: Extend the existing `SendFailNotificationTest` and Slack notification test classes:
- `test_fail_email_body_includes_description`: rule with description, assert `'Note:' in mail.outbox[0].body`
- `test_fail_email_body_excludes_description_when_blank`: rule with `description=''`, assert `'Note:' not in mail.outbox[0].body`
- `test_slack_payload_includes_note_field`: mock the HTTP call in `slack_service`, capture payload, assert `'*Note*'` in the fields when `rule.description` is set
- `test_slack_payload_excludes_note_field_when_blank`: same mock, assert `'*Note*'` not in fields when `rule.description == ''`

### Success Criteria

#### Automated Verification

- All new tests pass: `python manage.py test monitor --verbosity=2`
- All previously passing tests continue to pass (no regressions)
- Test count increases by at least 8 (4 model/form + 2 dashboard + 4 notification)

#### Manual Verification

- Review test output for correct failure messages if any assertion fails

---

## Testing Strategy

### Unit Tests

- `Rule.description` default and persistence (Phase 5.1)
- `RuleForm` validation — optional, saved, max-length boundary (Phase 5.2)
- Email body content with and without description (Phase 5.4)
- Slack payload field presence with and without description (Phase 5.4)

### Integration Tests

- Dashboard GET response includes/excludes description text (Phase 5.3)
- Rule create → edit round-trip via form (Phase 5.2)

### Manual Testing Steps

1. `python manage.py runserver` → create a rule with a description → verify textarea renders and saves.
2. Edit the rule → verify description is pre-filled.
3. View dashboard → verify muted secondary line appears below the rule name (truncated if > 80 chars).
4. Click rule → verify description appears on the history page header.
5. Trigger a rule check failure → check email inbox for "Note:" line and Slack message for "Note" field.

## Performance Considerations

`Rule.description` is a plain `TextField`; no index is added. Dashboard queries already `select_related('connection')` and access `rule.description` from the same ORM row — no additional query.

## Migration Notes

Migration `0018_rule_description` adds one nullable-equivalent column (`TextField` with `default=''`). The migration is non-destructive and fully reversible via `python manage.py migrate monitor 0017`.

## References

- Research: `context/changes/rule-description/research.md`
- Model field precedent: `monitor/models.py:26` (`Connection.description`)
- Form pattern: `monitor/forms.py:49–52` (`RuleForm.Meta`)
- Dashboard row: `templates/monitor/dashboard.html:425–432`
- History header: `templates/monitor/rule_history.html:74–78`
- Fail email (txt): `templates/monitor/email/fail_notification.txt`
- Fail email (HTML): `templates/monitor/email/fail_notification.html`
- Digest email (txt): `templates/monitor/email/digest_notification.txt`
- Digest email (HTML): `templates/monitor/email/digest_notification.html`
- Slack service: `monitor/slack_service.py`
- Email service: `monitor/email_service.py`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Model Field and Migration

#### Automated

- [ ] 1.1 Migration applies cleanly (migrate --check exits 0)
- [ ] 1.2 Rule.description accessible with empty-string default on new instance

#### Manual

- [ ] 1.3 Shell confirm: Rule._meta.get_field('description') returns TextField

### Phase 2: Form Widget

#### Automated

- [ ] 2.1 RuleForm instantiates with description in fields
- [ ] 2.2 Form save with description='Test note' persists to DB
- [ ] 2.3 Form save with description='' persists empty string
- [ ] 2.4 Form validation rejects description longer than 500 chars

#### Manual

- [ ] 2.5 Description textarea visible below Rule name on create/edit page
- [ ] 2.6 Description pre-populated when editing an existing rule

### Phase 3: Dashboard and History Display

#### Automated

- [ ] 3.1 Dashboard template renders without errors when description is non-empty
- [ ] 3.2 Dashboard template renders without errors when description is empty
- [ ] 3.3 truncatechars:80 applied in dashboard (verified via rendered HTML)

#### Manual

- [ ] 3.4 Dashboard: muted secondary line visible under rule name when description set
- [ ] 3.5 History page: description appears between table name and condition chips

### Phase 4: Notifications

#### Automated

- [ ] 4.1 Fail email body includes 'Note:' and description when rule.description is set
- [ ] 4.2 Fail email body excludes 'Note:' when rule.description is blank
- [ ] 4.3 Digest email body includes description per result when set
- [ ] 4.4 Slack payload includes *Note* field when description is non-empty
- [ ] 4.5 Slack payload excludes *Note* field when description is blank
- [ ] 4.6 All existing notification tests pass unchanged

#### Manual

- [ ] 4.7 Triggered failure email shows Note line; Slack message shows Note field

### Phase 5: Tests

#### Automated

- [ ] 5.1 All new tests pass: python manage.py test monitor --verbosity=2
- [ ] 5.2 No regressions in existing test suite
- [ ] 5.3 Test count increases by at least 8

#### Manual

- [ ] 5.4 Review test output for correct failure messages
