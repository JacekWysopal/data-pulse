# Advanced Scheduler — Implementation Plan

## Overview

Replace `Rule.schedule_time` (a single `TimeField`) with a flexible scheduler supporting
predefined multi-run options and custom cron expressions. The feature adds `schedule_type`
and `schedule_cron` fields to `Rule`, adds `croniter` for cron matching, updates
`run_scheduled` to use `croniter.match()`, adds a Render Cron Job to `render.yaml`,
and replaces the time-input widget in the rule form with a schedule picker.

## Current State Analysis

`Rule.schedule_time` is a `TimeField(null=True)` storing a single UTC HH:MM
(`monitor/models.py:124`). The `run_scheduled` management command filters rules by
`schedule_time=now` — one exact match per minute, at most one daily fire per rule
(`monitor/management/commands/run_scheduled.py:15–17`). `RuleForm` exposes it as an
`<input type="time">` widget (`monitor/forms.py:35,51`). There is no `schedule_type`,
no `schedule_cron`, and no `croniter` dependency in the project. Two tests cover the
command at `monitor/tests.py:956–989`. The next migration number is `0005`.

`render.yaml` has only a `type: web` service; a `type: cron` entry calling
`run_scheduled` every minute is missing and is required for the scheduler to function
on Render.

## Desired End State

`Rule` has `schedule_type` (choices: disabled / preset_1x / preset_2x / preset_3x /
preset_6x / hourly / custom_cron) and `schedule_cron` (CharField). The old
`schedule_time` field is gone. `run_scheduled` uses `croniter.match()` against a
per-rule resolved cron string. The rule form shows a dropdown for preset + optional
cron text input for the custom mode. Render deploys a `type: cron` job that calls the
command every minute. All schedule-related tests pass.

### Key Discoveries:

- `monitor/models.py:124` — `schedule_time TimeField(null=True)` is the only schedule
  field; safe to add alongside it in migration 0005.
- `monitor/migrations/0004_rule_custom_sql.py` — latest migration; next is `0005`.
- `monitor/forms.py:35,51` — `schedule_time` referenced in `fields` list and `widgets`
  dict; both need replacement.
- `monitor/tests.py:956–989` — two `RunScheduledCommandTest` tests assert against
  `schedule_time`; must be updated.
- `render.yaml` — no `type: cron` entry; add in Phase 2.
- `pyproject.toml` — `croniter` not in `dependencies`; add in Phase 2.

## What We're NOT Doing

- Multiple schedules per rule (one per rule only, matching change scope).
- Per-rule timezone support — all cron strings are UTC.
- Render Cron Job cost analysis — verify on Render dashboard.
- Configurable time for `once_daily` preset — the preset cron strings are fixed in code.
- Email/Slack notifications triggered by schedule — separate slice (S-16+).
- Non-Render deployment documentation for the cron caller.

## Implementation Approach

Five phases: model fields first (with data migration preserving existing `schedule_time`
values as `custom_cron` entries), then dependency + command rewrite + render.yaml, then
field removal, then UI, then test update. This order keeps the app functional on deploy
after each phase: phases 1–2 add the scheduler without breaking the old field, phase 3
cleanly removes it after everything is wired up, phase 4 updates the UI, and phase 5
verifies all paths.

The `PREDEFINED` dict approach is used: cron strings for preset types live in
`run_scheduled.py` code (not the DB). Only `custom_cron` rules store a cron string in
`schedule_cron`. This avoids a data-migration step to populate cron strings for presets
and keeps the predefined strings easy to change without a migration.

## Critical Implementation Details

- **Data migration ordering**: Migration `0005` must atomically add both fields
  **and** run the `RunPython` data migration in a single migration file so that no
  window exists where rows have `schedule_time != NULL` but `schedule_type = 'disabled'`.
- **croniter.match datetime argument**: `croniter.match(expr, dt)` expects a naive
  or timezone-aware `datetime`, not a `time`. Pass `timezone.now().replace(second=0,
  microsecond=0)` (keep timezone-aware). If the Render Cron Job runs UTC, this is safe.
- **Rule.schedule_time constraint**: The DB-level `CheckConstraint`
  (`rule_has_at_least_one_condition`) on `Rule` does not reference `schedule_time`, so
  removing it in phase 3 will not violate any existing constraint.

---

## Phase 1: Model fields + data migration

### Overview

Add `schedule_type` and `schedule_cron` to `Rule`. Create migration `0005` that adds
the fields and data-migrates any existing `schedule_time` values to `custom_cron` rows.
`schedule_time` stays in place (removed in Phase 3).

### Changes Required:

#### 1. Rule model — add ScheduleType inner class and two new fields

**File**: `monitor/models.py`

**Intent**: Add `ScheduleType` TextChoices and the two new fields immediately after the
`# Schedule` comment block, above the existing `schedule_time` line. Keep `schedule_time`
untouched.

**Contract**:
- Inner class `Rule.ScheduleType(models.TextChoices)` with values:
  `DISABLED='disabled'`, `PRESET_1X='preset_1x'`, `PRESET_2X='preset_2x'`,
  `PRESET_3X='preset_3x'`, `PRESET_6X='preset_6x'`, `HOURLY='hourly'`,
  `CUSTOM_CRON='custom_cron'`.
- `schedule_type = CharField(max_length=20, choices=ScheduleType.choices, default='disabled', verbose_name='Schedule')`.
- `schedule_cron = CharField(max_length=100, blank=True, default='', verbose_name='Cron expression', help_text='5-field UTC cron, e.g. 0 8 * * *. Only when schedule_type = custom_cron.')`.
- `schedule_time` remains; no changes to it or any other field.

#### 2. Migration 0005 — add fields + data migration

**File**: `monitor/migrations/0005_rule_schedule_type_cron.py`

**Intent**: Add both fields in a single migration that also runs a `RunPython` step to
convert non-null `schedule_time` values into `custom_cron` entries, so no scheduled rule
silently becomes disabled.

**Contract**: The `RunPython` forward function iterates `Rule.objects.filter(schedule_time__isnull=False)`, sets `schedule_type='custom_cron'` and `schedule_cron=f'0 {rule.schedule_time.hour} * * *'` for each, and bulk-saves. Reverse function is a no-op (data cannot be cleanly recovered; acceptable).

### Success Criteria:

#### Automated Verification:

- Migration applies cleanly: `python manage.py migrate`
- No pending migrations: `python manage.py migrate --check`
- Django system check passes: `python manage.py check`
- Existing tests still pass: `python manage.py test monitor`

#### Manual Verification:

- `Rule` model has `schedule_type`, `schedule_cron`, and `schedule_time` in `python manage.py shell` inspect.
- A rule with `schedule_time=time(6,0)` migrates to `schedule_type='custom_cron'`, `schedule_cron='0 6 * * *'`.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: croniter dependency + run_scheduled rewrite + render.yaml

### Overview

Add `croniter` to `pyproject.toml`, regenerate `requirements.txt`, rewrite
`run_scheduled` to use `croniter.match()`, and add the Render Cron Job entry to
`render.yaml`.

### Changes Required:

#### 1. Add croniter dependency

**File**: `pyproject.toml`

**Intent**: Add `croniter` (pinned to `>=5.0.1`) to `dependencies` so it is installed in
all environments.

**Contract**: Append `"croniter>=5.0.1"` to the `dependencies` list.

#### 2. Regenerate requirements.txt

**File**: `requirements.txt`

**Intent**: Reflect the new `croniter` entry so Render's `pip install -r requirements.txt`
installs it.

**Contract**: Run `uv pip compile pyproject.toml -o requirements.txt` (or equivalent) to
regenerate. Verify `croniter` appears in the output file.

#### 3. Rewrite run_scheduled command

**File**: `monitor/management/commands/run_scheduled.py`

**Intent**: Replace the `schedule_time=now` filter with a `croniter.match()` loop over
all non-disabled rules. Use the `PREDEFINED` dict to resolve cron strings for preset
schedule types.

**Contract**:
- Define module-level `PREDEFINED` dict:
  `{'preset_1x': '0 8 * * *', 'preset_2x': '0 8,20 * * *', 'preset_3x': '0 6,14,22 * * *', 'preset_6x': '0 */4 * * *', 'hourly': '0 * * * *'}`.
- `now = timezone.now().replace(second=0, microsecond=0)` — keep timezone-aware.
- Query: `Rule.objects.exclude(schedule_type='disabled').select_related('connection')`.
- For each rule: `cron_str = PREDEFINED.get(rule.schedule_type) or rule.schedule_cron`;
  if `not cron_str`: emit `self.stderr.write(f'Rule {rule.id} has schedule_type=custom_cron but schedule_cron is blank — skipping')` and continue; call `croniter.match(cron_str, now)` to decide fire.
- Import: `from croniter import croniter`.

#### 4. Add Render Cron Job to render.yaml

**File**: `render.yaml`

**Intent**: Add a `type: cron` service that calls `python manage.py run_scheduled` every
minute so the scheduler works on Render without manual dashboard configuration.

**Contract**: Add a second entry under `services:` with `type: cron`,
`name: data-pulse-scheduler`, `runtime: python`, `schedule: "* * * * *"`,
`buildCommand: "pip install -r requirements.txt"`,
`startCommand: "python manage.py run_scheduled"`,
`envVars` block with `DATABASE_URL` (sync: false), `SECRET_KEY` (sync: false),
`FIELD_ENCRYPTION_KEY` (sync: false), `DEBUG` (value: "False").

### Success Criteria:

#### Automated Verification:

- `croniter` importable: `python -c "from croniter import croniter; print(croniter.match('0 8 * * *', __import__('datetime').datetime(2025, 1, 1, 8, 0)))"`
- Django system check passes: `python manage.py check`
- Existing tests still pass: `python manage.py test monitor`

#### Manual Verification:

- A rule with `schedule_type='preset_1x'` fires at 08:00 UTC when `run_scheduled` is
  invoked at that time (can be verified by calling `Command().handle()` in shell with
  mocked time, or by reading the revised logic).
- `render.yaml` is valid YAML and the cron entry has the expected fields.
- `requirements.txt` contains a `croniter` entry.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Remove schedule_time field

### Overview

Remove `Rule.schedule_time` from the model and create migration `0006`. After this phase,
`schedule_time` no longer exists anywhere in the codebase.

### Changes Required:

#### 1. Remove schedule_time from Rule model

**File**: `monitor/models.py`

**Intent**: Delete the `schedule_time` field definition (lines 124–130 of current file)
from `Rule`.

**Contract**: Remove the `schedule_time = models.TimeField(...)` block including its
comment line `# Schedule — optional HH:MM UTC, run by cron`. No other fields change.

#### 2. Migration 0006 — remove schedule_time

**File**: `monitor/migrations/0006_remove_rule_schedule_time.py`

**Intent**: Drop the `schedule_time` column from the DB. The data migration in `0005`
already preserved values; this is safe.

**Contract**: `RemoveField(model_name='rule', name='schedule_time')`. Depends on `0005`.

#### 3. Remove schedule_time from forms.py

**File**: `monitor/forms.py`

**Intent**: Remove `schedule_time` from `RuleForm.Meta.fields` and `RuleForm.Meta.widgets`
so the old time-input widget is gone.

**Contract**: Remove `'schedule_time'` from `fields` list (line 35) and its `widgets`
entry (lines 51–52 area). The form now has no schedule fields — UI wiring comes in
Phase 4.

### Success Criteria:

#### Automated Verification:

- Migration applies cleanly: `python manage.py migrate`
- No pending migrations: `python manage.py migrate --check`
- Django system check passes: `python manage.py check`
- No reference to `schedule_time` in source code: `grep -r "schedule_time" monitor/ --include="*.py" --exclude-dir=migrations` returns empty.
- Tests pass: `python manage.py test monitor`

#### Manual Verification:

- Rule admin / shell shows no `schedule_time` attribute on a `Rule` instance.
- Existing rules load without error in the rule list page.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 4: UI — schedule picker in rule form

### Overview

Add schedule pickers to `RuleForm`: a dropdown for `schedule_type` and a conditional
text input for `schedule_cron` (shown only when `schedule_type='custom_cron'`). Add
form validation for the custom cron field using `croniter.is_valid()`.

### Changes Required:

#### 1. Add schedule_type and schedule_cron to RuleForm

**File**: `monitor/forms.py`

**Intent**: Add `schedule_type` and `schedule_cron` to `RuleForm.Meta.fields` and
provide matching widget definitions. Add a `clean_schedule_cron` method that validates
the cron expression with `croniter.is_valid()` when `schedule_type='custom_cron'`.

**Contract**:
- Add `'schedule_type'` and `'schedule_cron'` to the `fields` list after `'min_row_count'`.
- Widgets:
  - `schedule_type`: `forms.Select(attrs={'class': 'form-select', 'id': 'id_schedule_type'})`.
  - `schedule_cron`: `forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0 8 * * *', 'id': 'id_schedule_cron'})`.
- `clean_schedule_cron` method: if `schedule_type == 'custom_cron'` and `schedule_cron`
  is empty → `ValidationError('Cron expression is required for custom schedule.')`;
  if non-empty and `not croniter.is_valid(schedule_cron)` →
  `ValidationError('Invalid cron expression. Use 5-field format, e.g. 0 8 * * *.')`.
  Return `schedule_cron` unchanged otherwise.
- Import `from croniter import croniter` at top of `forms.py`.

#### 2. Update rule form template to show/hide cron input

**File**: `templates/monitor/rule_form.html`

**Intent**: Render the `schedule_type` dropdown and a `schedule_cron` text field that is
hidden until the user selects "Custom cron expression". Use inline JS (no new framework)
following the existing `rule_form.html` pattern for the rule-type radio toggle.

**Contract**: Wrap the cron input in a `<div id="custom-cron-row" style="display:none">`.
Add a `<script>` block that listens to `change` on `#id_schedule_type` and toggles the
`display` of `#custom-cron-row` when value is `'custom_cron'`. On page load, run the
same toggle to handle re-render with existing data. Follow the Bootstrap `mb-3` form
group pattern already used in the template.

### Success Criteria:

#### Automated Verification:

- Django system check passes: `python manage.py check`
- Tests pass: `python manage.py test monitor`

#### Manual Verification:

- Rule form shows "Schedule" dropdown with all preset labels and "Custom cron expression" option.
- Selecting "Custom cron expression" reveals the cron text input.
- Selecting any other option hides the cron input.
- Submitting with `schedule_type='custom_cron'` and empty cron shows validation error.
- Submitting with `schedule_type='custom_cron'` and `'60 99 * * *'` shows validation error.
- Submitting with `schedule_type='preset_1x'` saves correctly (no cron field required).
- Editing an existing rule with `schedule_type='custom_cron'` pre-fills cron field.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 5: Tests

### Overview

Update the two existing `RunScheduledCommandTest` tests to use `schedule_type` and
`schedule_cron` instead of `schedule_time`. Add tests for cron-form validation and the
PREDEFINED map coverage.

### Changes Required:

#### 1. Update RunScheduledCommandTest

**File**: `monitor/tests.py`

**Intent**: Replace `schedule_time`-based setup with `schedule_type='preset_1x'` (or
`custom_cron`) and patch `timezone.now()` to return a datetime that matches the preset's
cron string, so the tests don't depend on the real clock.

**Contract**:
- `test_runs_rules_matching_current_time`: create rule with `schedule_type='preset_1x'`;
  patch `monitor.management.commands.run_scheduled.timezone.now` to return
  `datetime(2025, 1, 1, 8, 0, tzinfo=utc)` (matches `0 8 * * *`); assert
  `mock_run.assert_called_once_with(rule)`.
- `test_skips_rules_with_different_time`: create rule with `schedule_type='preset_1x'`;
  patch `timezone.now` to `datetime(2025, 1, 1, 9, 0, tzinfo=utc)` (does not match
  `0 8 * * *`); assert `mock_run.assert_not_called()`.
- Add `test_disabled_rule_is_skipped`: rule with `schedule_type='disabled'`; assert
  not called regardless of time.
- Add `test_custom_cron_rule_fires`: rule with `schedule_type='custom_cron'`,
  `schedule_cron='30 14 * * *'`; patch time to `datetime(2025, 1, 1, 14, 30, tzinfo=utc)`;
  assert called.

#### 2. Add RuleForm schedule validation tests

**File**: `monitor/tests.py`

**Intent**: Cover the `clean_schedule_cron` form validation paths: missing cron when
custom selected, invalid cron expression, valid cron expression, preset with no cron.

**Contract**: Add a `RuleFormScheduleTest(TestCase)` class with at minimum:
- `test_custom_cron_required_when_type_is_custom`
- `test_invalid_cron_expression_rejected`
- `test_valid_custom_cron_accepted`
- `test_preset_requires_no_cron_field`

### Success Criteria:

#### Automated Verification:

- All monitor tests pass: `python manage.py test monitor`
- No `schedule_time` references in tests: `grep -n "schedule_time" monitor/tests.py` returns empty.

#### Manual Verification:

- Test output shows all new tests in `RunScheduledCommandTest` and `RuleFormScheduleTest` passing.

**Implementation Note**: After completing this phase and all automated verification passes, this change is complete.

---

## Testing Strategy

### Unit Tests:

- `RunScheduledCommandTest` — updated to use schedule_type, patched timezone.now
- `RuleFormScheduleTest` — validates custom cron path, invalid expression, preset path
- Disabled rule skip test

### Integration Tests:

- Full rule create/edit flow with each schedule_type via `django.test.Client`

### Manual Testing Steps:

1. Create a new rule via UI; verify schedule dropdown appears and all options are present.
2. Select "Custom cron expression"; verify cron input appears.
3. Enter invalid cron `'60 99 * * *'`; verify form error shown.
4. Enter valid cron `'0 8 * * *'`; verify save succeeds.
5. Run `python manage.py run_scheduled` from shell with a rule due at current time; verify it fires.
6. Verify disabled rules are skipped by `run_scheduled`.

## Migration Notes

- `0005` adds fields and data-migrates `schedule_time != NULL` rows to `schedule_type='custom_cron'` / `schedule_cron='0 <hour> * * *'`. Existing scheduled rules are preserved.
- `0006` removes `schedule_time`. Must run after `0005`.
- Both migrations are in separate files to keep rollback surface small.

## References

- Change: `context/changes/advanced-scheduler/change.md`
- Research: `context/changes/advanced-scheduler/research.md`
- Current model: `monitor/models.py:124`
- Current command: `monitor/management/commands/run_scheduled.py:15`
- Existing tests: `monitor/tests.py:956–989`
- Forms: `monitor/forms.py:35,51`
- render.yaml: `render.yaml`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Model fields + data migration

#### Automated

- [ ] 1.1 Migration applies cleanly
- [ ] 1.2 No pending migrations
- [ ] 1.3 Django system check passes
- [ ] 1.4 Existing tests still pass

#### Manual

- [ ] 1.5 Rule model has schedule_type, schedule_cron, and schedule_time in shell inspect
- [ ] 1.6 A rule with schedule_time migrates correctly to custom_cron

### Phase 2: croniter dependency + run_scheduled rewrite + render.yaml

#### Automated

- [ ] 2.1 croniter importable and match works
- [ ] 2.2 Django system check passes
- [ ] 2.3 Existing tests still pass

#### Manual

- [ ] 2.4 preset_1x rule fires at 08:00 UTC
- [ ] 2.5 render.yaml is valid YAML with cron entry
- [ ] 2.6 requirements.txt contains croniter

### Phase 3: Remove schedule_time field

#### Automated

- [ ] 3.1 Migration applies cleanly
- [ ] 3.2 No pending migrations
- [ ] 3.3 Django system check passes
- [ ] 3.4 No schedule_time references in source
- [ ] 3.5 Tests pass

#### Manual

- [ ] 3.6 Rule instance has no schedule_time attribute in shell
- [ ] 3.7 Rule list page loads without error

### Phase 4: UI — schedule picker in rule form

#### Automated

- [ ] 4.1 Django system check passes
- [ ] 4.2 Tests pass

#### Manual

- [ ] 4.3 Schedule dropdown shows all options
- [ ] 4.4 Custom cron input shows/hides correctly
- [ ] 4.5 Validation errors shown for empty/invalid cron
- [ ] 4.6 Preset type saves without cron field
- [ ] 4.7 Editing existing custom_cron rule pre-fills cron field

### Phase 5: Tests

#### Automated

- [ ] 5.1 All monitor tests pass
- [ ] 5.2 No schedule_time references in tests

#### Manual

- [ ] 5.3 New test classes visible in test output and passing
