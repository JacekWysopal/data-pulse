# Rule Severity (critical/warning/info) Implementation Plan

## Overview

Add a `severity` field to the `Rule` model with three levels — `critical`, `warning`, and `info` — that controls both the dashboard badge color and notification routing. Critical rules notify immediately on failure; warning rules notify after 3 consecutive failures; info rules never send notifications. This makes alert fatigue manageable without disabling notifications entirely.

## Current State Analysis

The `Rule` model (`monitor/models.py`) has no severity concept. All failing rules notify immediately (subject to `notify_on_fail` / `notify_slack` flags and a 1-hour cooldown). The dashboard shows one status badge per rule row reflecting the last check result (`dp-badge-ok/fail/error/never`). No consecutive-failure counter exists anywhere in the codebase.

### Key Discoveries

- `monitor/models.py:87-90` — `Rule.RuleType` TextChoices; `models.py:131-147` — `Rule.ScheduleType` TextChoices + field declaration. `Severity` follows this exact pattern as a third inner `TextChoices` class.
- `email_service.py:137-149` — `notify_rule_result(rule, result)` is the single coordinator for all outbound notifications. Severity routing inserts here, before the individual senders are called.
- `monitor/services.py` — 12 call sites for `notify_rule_result`, all guarded by `if result.status in (FAIL, ERROR)`. Consecutive-fail counter management (increment on FAIL/ERROR, reset on OK) must happen at each `RuleResult.objects.create(...)` site in `services.py`, covering both `run_single_rule` and `run_all_checks`.
- `templates/base.html:38-47` — CSS variables `--ok` (green), `--fail` (red), `--error` (amber). No `--info` (blue) exists.
- `templates/base.html:480-493` — Flat `dp-badge-{ok,fail,error,never}` class block. Severity classes (`dp-badge-severity-{critical,warning,info}`) are added in the same block.
- `templates/monitor/dashboard.html:424-480` — Rule table. Existing status badge at lines 474–480 is unchanged. A new severity badge is added as a second badge on each rule row (same `<td>` as the status badge, rendered before it).
- `monitor/forms.py:57-59` — `RuleForm.Meta.fields` list; `severity` and its `forms.Select` widget are appended.
- `templates/monitor/rule_form.html:361` — Notifications section. Severity selector is added immediately before the "Notifications" section label.
- Last migration: `monitor/migrations/0017_apikey.py` → new migration is `0018_rule_severity.py`.
- Digest mode: `failing_results` is populated at `services.py:450, 465, 486, 501`. INFO rules must be excluded here to remain consistent with the "no notification" contract.

## Desired End State

After this plan is complete:

- Every `Rule` has a `severity` attribute (`critical` by default). Creating or editing a rule in the UI presents a severity dropdown.
- The dashboard shows a small severity badge (red/amber/blue dot with label) on each rule row, alongside the existing result-status badge.
- `notify_rule_result` silently skips INFO rules; defers WARNING rules until `consecutive_fails >= 3`; sends CRITICAL rules immediately (unchanged). This applies to both email and Slack channels, in both immediate and digest notification modes.
- `Rule.consecutive_fails` is incremented for each FAIL/ERROR result and reset to 0 on each OK result, across all services.py call sites.
- All existing tests pass; new tests cover the three notification routing branches and the counter increment/reset logic.

### Verification

Run `python manage.py migrate` (clean apply), `python manage.py test monitor` (all tests pass), open the dashboard and confirm three severity badge variants render correctly, create/edit a rule and confirm the severity dropdown is present and saved.

## What We're NOT Doing

- No change to how the existing result-status badges (`dp-badge-ok/fail/error/never`) work — they still reflect the latest check outcome.
- No bulk-backfill migration for `consecutive_fails` — all existing rules start at 0.
- No per-user severity threshold configuration — the WARNING threshold is hardcoded at 3.
- No severity filtering on the API layer (separate change if needed).
- No digest-summary threshold change for WARNING — digest already filters by `notify_on_fail`; INFO exclusion is the only new filter.
- No Slack message content changes for severity — message payload is unchanged.

## Implementation Approach

Four code layers touch this change in dependency order: model/migration → notification routing → dashboard presentation → form. Tests follow as a final phase. Each phase is independently verifiable before the next begins.

The consecutive-fail counter lives on `Rule` (not as an inline DB query) per the approved decision, keeping `notify_rule_result` a pure in-memory read with no extra DB round-trips.

## Critical Implementation Details

**Counter update placement**: `_update_consecutive_fails` must be called for *every* `RuleResult.objects.create(...)` result — including OK results (to reset) — not only FAIL/ERROR results. There are approximately 12 such sites across `run_single_rule` and `run_all_checks`. For OK results, `notify_rule_result` is not called today, so the reset must be unconditional at the result-save site.

**Counter refresh after update**: `Rule.objects.filter(pk=rule.pk).update(consecutive_fails=...)` does not refresh the in-memory `rule` object. Call `rule.refresh_from_db(fields=['consecutive_fails'])` (or assign directly) after the DB update so `notify_rule_result` reads the correct value in the same request.

**Digest INFO exclusion**: The `failing_results` list is populated inside `if db_result.status in (FAIL, ERROR)` + `elif rule.notify_on_fail` branches. Add `and rule.severity != Rule.Severity.INFO` to each of those `elif` guards to exclude INFO rules from the digest without introducing a separate code path.

---

## Phase 1: Model + Migration

### Overview

Add `Rule.Severity` TextChoices, the `severity` CharField (default `critical`), and `Rule.consecutive_fails` IntegerField (default 0) to the model. Generate migration `0018_rule_severity.py`.

### Changes Required

#### 1. `Rule` model — Severity enum and fields

**File**: `monitor/models.py`

**Intent**: Add a `Severity` inner class following the `ScheduleType` pattern (lines 131–147), and declare `severity` and `consecutive_fails` fields after the existing notification fields (`last_slack_notified_at`).

**Contract**:
```python
class Severity(models.TextChoices):
    CRITICAL = 'critical', 'Critical'
    WARNING  = 'warning',  'Warning'
    INFO     = 'info',     'Info'

severity = models.CharField(
    max_length=20,
    choices=Severity.choices,
    default=Severity.CRITICAL,
    verbose_name='Severity',
)
consecutive_fails = models.IntegerField(
    default=0,
    verbose_name='Consecutive failures',
    help_text='Incremented on each FAIL/ERROR result; reset to 0 on OK. Used for WARNING threshold.',
)
```

Place `Severity` after `ScheduleType` inside `Rule`. Place both fields after `last_slack_notified_at` and before `created_at`.

#### 2. Migration

**File**: `monitor/migrations/0018_rule_severity.py`

**Intent**: Auto-generated migration adding both fields to the `rule` table with their defaults.

**Contract**: Dependency on `('monitor', '0017_apikey')`. Two `AddField` operations: `severity` (CharField, default `'critical'`, max_length 20) and `consecutive_fails` (IntegerField, default 0). No data migration required — existing rows get the defaults.

### Success Criteria

#### Automated Verification

- Migration applies cleanly with no errors: `python manage.py migrate`
- Migration is reversible: `python manage.py migrate monitor 0017`
- Re-forward migration succeeds: `python manage.py migrate`
- Model introspection shows both new fields: `python manage.py shell -c "from monitor.models import Rule; print(Rule._meta.get_fields())"`
- Existing test suite still passes: `python manage.py test monitor`

#### Manual Verification

- `python manage.py showmigrations monitor` lists `0018_rule_severity` as applied.
- Django admin `Rule` list page loads without error (both fields have defaults so no existing rule is broken).

---

## Phase 2: Notification Routing

### Overview

Add severity-aware routing to `notify_rule_result` in `email_service.py`. Add `_update_consecutive_fails` helper in `services.py` and call it at every result-save site. Exclude INFO rules from the digest `failing_results` list.

### Changes Required

#### 1. `notify_rule_result` — severity routing guard

**File**: `monitor/email_service.py`

**Intent**: Before calling either sender, short-circuit based on severity. INFO never notifies; WARNING notifies only when `rule.consecutive_fails >= 3`; CRITICAL is unchanged.

**Contract**:
```python
def notify_rule_result(rule: Rule, result) -> dict:
    # INFO: log only, never notify
    if rule.severity == Rule.Severity.INFO:
        logger.debug(
            'Skipping notification for INFO rule %s (pk=%s)', rule.name, rule.pk
        )
        return {'email': False, 'slack': False}

    # WARNING: defer until 3 consecutive failures
    if rule.severity == Rule.Severity.WARNING and rule.consecutive_fails < 3:
        logger.debug(
            'Deferring WARNING notification for rule %s (pk=%s): consecutive_fails=%s',
            rule.name, rule.pk, rule.consecutive_fails,
        )
        return {'email': False, 'slack': False}

    email_sent = send_fail_notification(rule, result)
    slack_sent = send_slack_notification(rule, result)
    return {'email': email_sent, 'slack': slack_sent}
```

Add `import logging` (already present) and use the module-level `logger`. Import `Rule` is already present.

#### 2. `_update_consecutive_fails` helper

**File**: `monitor/services.py`

**Intent**: Encapsulate counter increment (FAIL/ERROR) and reset (OK) so each result-save site calls one function rather than inlining the DB update.

**Contract**:
```python
def _update_consecutive_fails(rule: Rule, result: RuleResult) -> None:
    """Increment consecutive_fails on FAIL/ERROR, reset to 0 on OK."""
    if result.status == RuleResult.Status.OK:
        Rule.objects.filter(pk=rule.pk).update(consecutive_fails=0)
        rule.consecutive_fails = 0
    elif result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
        Rule.objects.filter(pk=rule.pk).update(
            consecutive_fails=models.F('consecutive_fails') + 1
        )
        rule.refresh_from_db(fields=['consecutive_fails'])
```

Place after the existing `_get_notification_mode` helper. Requires `from django.db import models` (already imported at the top of services.py).

#### 3. Call `_update_consecutive_fails` at every result-save site in `run_single_rule` and `run_all_checks`

**File**: `monitor/services.py`

**Intent**: After every `db_result = RuleResult.objects.create(...)` call (regardless of status), call `_update_consecutive_fails(rule, db_result)` before the subsequent `notify_rule_result` call. This covers the OK-reset path that is not reachable via the existing `if status in (FAIL, ERROR)` guards.

**Contract**: Insert `_update_consecutive_fails(rule, db_result)` immediately after each `RuleResult.objects.create(...)` assignment and before the `if db_result.status in (...)` notification guard. There are approximately 12 such sites spanning `run_single_rule` (lines ~370–416) and `run_all_checks` (lines ~443–591). For ERROR results created directly (no-connection, empty URL, connection-failed paths), the same pattern applies.

#### 4. Exclude INFO rules from digest `failing_results`

**File**: `monitor/services.py`

**Intent**: Digest mode accumulates failing results in a `failing_results` list gated by `rule.notify_on_fail`. Add a severity guard so INFO rules are excluded from the digest, consistent with "no notification" semantics.

**Contract**: At each `elif rule.notify_on_fail: failing_results.append(db_result)` site (lines ~450, 465, 486, 501 in `run_single_rule`; equivalent sites in `run_all_checks`), change to:

```python
elif rule.notify_on_fail and rule.severity != Rule.Severity.INFO:
    failing_results.append(db_result)
```

Same guard applies to the digest-mode branches in `run_all_checks` that append to `digest_pending[uid][1]`.

### Success Criteria

#### Automated Verification

- All existing notification tests pass: `python manage.py test monitor`
- New unit tests pass (see Phase 5): INFO returns `{'email': False, 'slack': False}`; WARNING with consecutive_fails=2 returns `{'email': False, 'slack': False}`; WARNING with consecutive_fails=3 passes through to senders; CRITICAL is unchanged.
- Counter increment test: `consecutive_fails` is 1 after one FAIL, 2 after two FAILs, 0 after next OK.

#### Manual Verification

- Temporarily set a rule to INFO and trigger a check — confirm no email or Slack notification is sent and a DEBUG log entry appears.
- Set a rule to WARNING, trigger two FAILs — no notification. Trigger a third FAIL — notification sent.
- Confirm `Rule.consecutive_fails` in Django admin reflects the counter accurately after each run.

---

## Phase 3: Dashboard Badge Colors + Severity Indicator

### Overview

Add `--info` CSS variable and `dp-badge-severity-{critical,warning,info}` classes to `base.html`. Render a severity badge on each rule row in `dashboard.html`, placed before the existing result-status badge.

### Changes Required

#### 1. Add `--info` CSS variable

**File**: `templates/base.html`

**Intent**: Define `--info` (blue) and `--info-dim` CSS variables inside the `:root {}` block, alongside the existing `--error` / `--error-dim` pair (line 47).

**Contract**: Add after the `--error-dim` line:
```css
--info:            #3b82f6;
--info-dim:        rgba(59,130,246,0.12);
```

#### 2. Add `dp-badge-severity-*` CSS classes

**File**: `templates/base.html`

**Intent**: Append three severity badge classes immediately after the existing `dp-badge-never` rule in the badge block (line 493), following the same `color / background / border-color / dot` pattern.

**Contract**:
```css
.dp-badge-severity-critical { color: var(--fail);  background: var(--fail-dim);  border-color: rgba(248,113,113,0.25); }
.dp-badge-severity-critical .dp-badge-dot { background: var(--fail); }
.dp-badge-severity-warning  { color: var(--error); background: var(--error-dim); border-color: rgba(251,191,36,0.25); }
.dp-badge-severity-warning  .dp-badge-dot { background: var(--error); }
.dp-badge-severity-info     { color: var(--info);  background: var(--info-dim);  border-color: rgba(59,130,246,0.25); }
.dp-badge-severity-info     .dp-badge-dot { background: var(--info); }
```

#### 3. Render severity badge on rule row

**File**: `templates/monitor/dashboard.html`

**Intent**: Add a severity badge before the existing result-status badge inside the same status `<td>` (lines 474–480), so each rule row shows severity + status in one cell.

**Contract**: Immediately before the `{% if item.status == 'OK' %}` block, add:
```html
<span class="dp-badge dp-badge-severity-{{ item.rule.severity }}"><span class="dp-badge-dot"></span>{{ item.rule.get_severity_display }}</span>
```

The Django `get_severity_display` method is auto-generated by `TextChoices` and returns the human-readable label (Critical / Warning / Info). No view change is required; `item.rule` is already the full Rule ORM object.

### Success Criteria

#### Automated Verification

- Template renders without error: `python manage.py test monitor` (existing view tests).
- CSS variables exist in rendered HTML: `grep -c 'info-dim\|dp-badge-severity' templates/base.html` returns > 0.

#### Manual Verification

- Open the dashboard; each rule row shows a severity badge (red for Critical, amber for Warning, blue for Info) alongside the result-status badge.
- Confirm the existing OK/FAIL/ERROR/No-data result-status badges are visually unchanged.
- Confirm the new blue Info badge renders correctly (no missing color, no layout overflow).

---

## Phase 4: Form Widget

### Overview

Add `severity` to `RuleForm` fields and widgets, and render the severity selector in `rule_form.html` above the Notifications section.

### Changes Required

#### 1. `RuleForm` — add `severity` field and widget

**File**: `monitor/forms.py`

**Intent**: Expose `severity` in the rule create/edit form so users can choose a severity level. Append `'severity'` to `Meta.fields` and add a `forms.Select` widget.

**Contract**: Append `'severity'` to the `fields` list in `RuleForm.Meta.fields` (line 59). Add to the `widgets` dict:
```python
'severity': forms.Select(attrs={'class': 'form-select'}),
```

#### 2. `rule_form.html` — render severity selector

**File**: `templates/monitor/rule_form.html`

**Intent**: Render the severity field as a labeled section immediately before the existing "Notifications" section label (line 361). Include help text explaining what each level means.

**Contract**: Insert before the `<!-- ── Notifications ── -->` comment:
```html
<!-- ── Severity ── -->
<div class="form-section-label">Severity</div>
<div class="mb-3">
  <label class="form-label" for="{{ form.severity.id_for_label }}">Severity level</label>
  {{ form.severity }}
  <div class="form-text" style="margin-top:4px">
    <strong>Critical</strong> — notify immediately on failure.
    <strong>Warning</strong> — notify after 3 consecutive failures.
    <strong>Info</strong> — never notify; log only.
  </div>
  {% if form.severity.errors %}
    <div class="field-error">✗ {{ form.severity.errors|join:", " }}</div>
  {% endif %}
</div>
```

### Success Criteria

#### Automated Verification

- Form renders without error: `python manage.py test monitor`.
- `severity` appears in `RuleForm().fields`: `python manage.py shell -c "from monitor.forms import RuleForm; print('severity' in RuleForm().fields)"` → `True`.

#### Manual Verification

- Open the rule create page; confirm a "Severity level" dropdown appears above "Notifications" with three choices: Critical, Warning, Info.
- Create a rule with severity = Info; confirm `rule.severity == 'info'` in Django shell.
- Edit an existing rule; confirm the current severity value is pre-selected.

---

## Phase 5: Tests

### Overview

Add unit tests covering the three notification-routing branches in `notify_rule_result`, the `_update_consecutive_fails` counter logic, and the form field presence.

### Changes Required

#### 1. Test file

**File**: `monitor/tests/test_rule_severity.py` (new file)

**Intent**: Cover all decision branches introduced by this change. Tests should be self-contained (mock DB where needed) and match the existing test style in the project.

**Contract**: The test module must cover:

1. `notify_rule_result` — INFO severity returns `{'email': False, 'slack': False}` without calling senders.
2. `notify_rule_result` — WARNING with `consecutive_fails=2` returns `{'email': False, 'slack': False}`.
3. `notify_rule_result` — WARNING with `consecutive_fails=3` calls senders (mock `send_fail_notification` and `send_slack_notification`).
4. `notify_rule_result` — CRITICAL always calls senders regardless of `consecutive_fails`.
5. `_update_consecutive_fails` — FAIL increments counter; a subsequent OK resets to 0.
6. `_update_consecutive_fails` — counter reaches 3 after three consecutive FAIL results.
7. `RuleForm` — `'severity'` is present in `RuleForm().fields`.
8. `Rule.severity` — default value is `'critical'` on a newly created Rule instance.

### Success Criteria

#### Automated Verification

- All new tests pass: `python manage.py test monitor.tests.test_rule_severity`
- Full test suite still passes: `python manage.py test monitor`
- No import errors in the new test module.

#### Manual Verification

- Run tests with verbosity 2 and confirm all 8 test cases are listed and pass.

---

## Testing Strategy

### Unit Tests

- `notify_rule_result` routing: INFO skip, WARNING threshold (2 fails = skip, 3 = send), CRITICAL pass-through.
- `_update_consecutive_fails`: increment on FAIL/ERROR, reset on OK, F() expression used for DB update.
- `RuleForm` field presence.
- `Rule.severity` default value.

### Integration Tests

- Migration apply and rollback.
- Full Django test suite: `python manage.py test monitor`.

### Manual Testing Steps

1. Apply migration and verify `showmigrations` shows `0018` applied.
2. Open dashboard — confirm severity badges appear on all rule rows (all will show Critical by default after migration).
3. Open rule edit form — confirm severity dropdown is present and saves correctly for all three levels.
4. Set a rule to INFO, trigger a check run — confirm no email/Slack notification is generated.
5. Set a rule to WARNING, trigger two check runs that FAIL — confirm no notification. Trigger a third FAIL — confirm notification is sent.
6. Set a rule to CRITICAL — confirm notification behavior is identical to current behavior.
7. After an OK result on a previously failing WARNING rule, confirm `consecutive_fails` resets to 0 in Django admin.

## Performance Considerations

`_update_consecutive_fails` issues one `UPDATE` per result, using `models.F('consecutive_fails') + 1` for the increment. This is one additional DB write per rule result, which is negligible relative to the check query itself. No index change needed.

## Migration Notes

`0018_rule_severity.py` uses `default='critical'` for `severity` and `default=0` for `consecutive_fails`. All existing rules get these defaults automatically on migration. No data migration or post-migration script required. Rollback (`migrate monitor 0017`) removes both columns cleanly.

## References

- Research: `context/changes/rule-severity/research.md`
- `Rule` model: `monitor/models.py:87` (RuleType pattern), `monitor/models.py:131` (ScheduleType pattern)
- Notification coordinator: `monitor/email_service.py:137` (`notify_rule_result`)
- Services call sites: `monitor/services.py:373` (representative), 12 total
- CSS badge block: `templates/base.html:480`
- Rule table: `templates/monitor/dashboard.html:424`
- Form fields list: `monitor/forms.py:57`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Model + Migration

#### Automated

- [ ] 1.1 Migration applies cleanly: `python manage.py migrate`
- [ ] 1.2 Migration is reversible to 0017 and re-applies: `python manage.py migrate monitor 0017` then `migrate`
- [ ] 1.3 Model introspection shows both new fields
- [ ] 1.4 Existing test suite passes: `python manage.py test monitor`

#### Manual

- [ ] 1.5 `showmigrations monitor` lists `0018_rule_severity` as applied
- [ ] 1.6 Django admin Rule list loads without error

### Phase 2: Notification Routing

#### Automated

- [ ] 2.1 INFO routing unit test passes: returns `{'email': False, 'slack': False}`
- [ ] 2.2 WARNING threshold unit tests pass (consecutive_fails=2 skip, consecutive_fails=3 send)
- [ ] 2.3 CRITICAL unchanged unit test passes
- [ ] 2.4 Counter increment/reset unit tests pass
- [ ] 2.5 Full test suite passes: `python manage.py test monitor`

#### Manual

- [ ] 2.6 INFO rule triggers no notification on check run
- [ ] 2.7 WARNING rule notifies only after 3rd consecutive FAIL
- [ ] 2.8 `consecutive_fails` counter visible and correct in Django admin

### Phase 3: Dashboard Badge Colors + Severity Indicator

#### Automated

- [ ] 3.1 CSS variables `--info` and `--info-dim` present in `templates/base.html`
- [ ] 3.2 `dp-badge-severity-critical/warning/info` classes present in `templates/base.html`
- [ ] 3.3 Template renders without error: `python manage.py test monitor`

#### Manual

- [ ] 3.4 Dashboard shows severity badges on all rule rows (red/amber/blue)
- [ ] 3.5 Existing result-status badges visually unchanged

### Phase 4: Form Widget

#### Automated

- [ ] 4.1 `severity` present in `RuleForm().fields`
- [ ] 4.2 Full test suite passes: `python manage.py test monitor`

#### Manual

- [ ] 4.3 Severity dropdown visible on rule create/edit page
- [ ] 4.4 Severity value saved and pre-selected on edit

### Phase 5: Tests

#### Automated

- [ ] 5.1 All 8 new test cases pass: `python manage.py test monitor.tests.test_rule_severity`
- [ ] 5.2 Full test suite passes: `python manage.py test monitor`
- [ ] 5.3 No import errors in test module
