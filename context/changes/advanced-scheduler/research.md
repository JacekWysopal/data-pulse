---
change_id: advanced-scheduler
research_question: What is needed to replace the single schedule_time field with a flexible scheduler supporting multiple daily runs and cron expressions?
researcher: kiro (worker subagent)
date: 2026-10-28
status: complete
---

# Research — Advanced Scheduler

## Summary answer

Replacing `Rule.schedule_time` (a single `TimeField`) with a flexible scheduler requires:
1. Adding `schedule_type` (CharField with predefined-option choices + `custom_cron` + `disabled`) and `schedule_cron` (CharField holding the canonical cron string) to `Rule`.
2. Adding `croniter` (PyPI) to project dependencies for cron expression validation and matching.
3. Rewriting `run_scheduled` to use `croniter.match()` instead of `filter(schedule_time=now)`.
4. Adding a Render Cron Job (`type: cron`, `schedule: "* * * * *"`) to `render.yaml` — currently missing.
5. A two-step migration: add new fields + data-migrate existing `schedule_time` values → then remove `schedule_time`.

All five investigation areas have sufficient evidence from the codebase. No external unknown blocks planning.

---

## 1. Current schedule implementation

**Evidence — `monitor/models.py` lines 124–130:**
```python
schedule_time = models.TimeField(
    null=True, blank=True,
    verbose_name='Schedule time (UTC)',
    help_text='Daily run time in UTC, e.g. 06:00. Leave empty to run manually only.',
)
```
`schedule_time` is a `TimeField(null=True)` on `Rule`. It stores a single UTC HH:MM. There is no `schedule_type`, no `schedule_cron`, no `schedule_enabled` field on this model. [evidence: monitor/models.py:124]

**Evidence — `monitor/management/commands/run_scheduled.py` lines 15–24:**
```python
now = timezone.now().time().replace(second=0, microsecond=0)
rules = Rule.objects.filter(schedule_time=now).select_related('connection')
```
The management command is designed to be called every minute by a Render Cron Job. It extracts the current UTC HH:MM, filters rules by exact `schedule_time` match, and calls `run_single_rule(rule)` for each. One rule → at most one daily fire. [evidence: monitor/management/commands/run_scheduled.py:15–17]

**Evidence — `monitor/forms.py` lines 35, 51:**
- `schedule_time` is in `RuleForm.Meta.fields` (line 35).
- Widget: `forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M')` — standard HTML `<input type="time">` picker. (line 51)
No validation logic beyond null-OK. [evidence: monitor/forms.py:35,51]

**Evidence — `monitor/migrations/0003_rule_schedule_time.py`:**
Migration was a simple `AddField` with no constraints. Reversible. The field was added in a standalone migration (depends on `0002`). Current latest migration is `0004_rule_custom_sql`. Next migration will be `0005`. [evidence: monitor/migrations/0003_rule_schedule_time.py]

**Evidence — `monitor/tests.py` lines 956–989:**
`RunScheduledCommandTest` has 2 tests — both mock `run_single_rule`. Tests work against an in-memory SQLite DB (no live DB). They set `rule.schedule_time = now_time` / `time(0, 0)` and invoke `Command().handle()`. These tests will need to be updated for the new scheduler. [evidence: monitor/tests.py:956–989]

---

## 2. Cron expression validation — library vs. regex

**Evidence — `requirements.txt` and `pyproject.toml`:** Neither `croniter`, `apscheduler`, nor `python-crontab` is present in the project. Runtime check confirmed: `croniter not installed`. [evidence: requirements.txt, pyproject.toml]

### Option A — `croniter` library (recommended)

`croniter` is a well-known PyPI package for cron expression matching and next-run calculation. It provides:
- `croniter.is_valid("0 8 * * *")` → `True/False` — semantic validation including field ranges (minute 0–59, hour 0–23).
- `croniter.match("0 8 * * *", datetime_obj)` → `True/False` — checks if a datetime falls on a cron hit.
- Standard 5-field cron (`m h dom mon dow`) supported.

Form validation would be:
```python
from croniter import croniter
if not croniter.is_valid(value):
    raise forms.ValidationError('Invalid cron expression.')
```

Addition to `pyproject.toml`: `"croniter>=5.0.1"`. Must also be reflected in `requirements.txt` via `uv pip compile`.

### Option B — Regex-only (no new dependency)

A regex can structurally validate 5-field cron syntax but cannot validate field ranges or combinations (e.g. `"60 25 * * *"` would pass). Example:
```python
CRON_RE = re.compile(
    r'^(\*|(\*/)?[0-9]+((-[0-9]+)?(,[0-9]+(-[0-9]+)?)*))\s+'  # minute
    r'(\*|(\*/)?[0-9]+((-[0-9]+)?(,[0-9]+(-[0-9]+)?)*))\s+'   # hour
    r'(\*|(\*/)?[0-9]+((-[0-9]+)?(,[0-9]+(-[0-9]+)?)*))\s+'   # dom
    r'(\*|(\*/)?[0-9]+((-[0-9]+)?(,[0-9]+(-[0-9]+)?)*))\s+'   # month
    r'(\*|(\*/)?[0-9]+((-[0-9]+)?(,[0-9]+(-[0-9]+)?)*))$'     # dow
)
```
For matching at runtime, regex alone cannot replace `croniter.match()`. An ad-hoc time-list evaluator would be needed for predefined options only, and custom cron would require a separate computation path. [inference: no cron library currently installed]

**Decision needed for plan:** Whether to add `croniter` (1 dependency) or use regex + ad-hoc time evaluator.

The regex-only path is more complex for the `run_scheduled` matching logic and provides weaker validation. `croniter` is the cleanest fit.

---

## 3. Model design options

### Option A — Extend `Rule` with two new fields (recommended)

Add directly to `Rule`:
```python
class ScheduleType(models.TextChoices):
    DISABLED   = 'disabled',    'Disabled (manual only)'
    ONCE_DAILY = 'once_daily',  '1× / day  (08:00 UTC)'
    TWICE_DAILY= 'twice_daily', '2× / day  (00:00, 12:00 UTC)'
    EVERY_8H   = 'every_8h',    '3× / day  (00:00, 08:00, 16:00 UTC)'
    EVERY_4H   = 'every_4h',    '6× / day  (every 4 h)'
    HOURLY     = 'hourly',      'Every hour'
    CUSTOM_CRON= 'custom_cron', 'Custom cron expression'

schedule_type = models.CharField(
    max_length=20, choices=ScheduleType.choices,
    default=ScheduleType.DISABLED, verbose_name='Schedule',
)
schedule_cron = models.CharField(
    max_length=100, blank=True, verbose_name='Cron expression',
    help_text='Only when schedule_type = custom_cron. 5-field UTC cron, e.g. 0 6 * * *',
)
```

Predefined types map to fixed cron strings that `run_scheduled` resolves at runtime:
| schedule_type | effective cron string | UTC fire times |
|---|---|---|
| `once_daily` | `0 8 * * *` | 08:00 |
| `twice_daily` | `0 0,12 * * *` | 00:00, 12:00 |
| `every_8h` | `0 0,8,16 * * *` | 00:00, 08:00, 16:00 |
| `every_4h` | `0 0,4,8,12,16,20 * * *` | every 4 h |
| `hourly` | `0 * * * *` | :00 every hour |
| `custom_cron` | value of `schedule_cron` | user-defined |

Pros: no new table, Ca=4 already (forms, services, views, run_scheduled all import models.py), simple FK/join, consistent with existing Rule field pattern.
Cons: Rule model grows by 2 fields. Acceptable for a single-schedule-per-rule feature.

### Option B — Separate `Schedule` model

A new `Schedule(rule, schedule_type, cron_expression)` model linked via OneToOneField or FK to `Rule`.

Pros: cleaner separation; future multi-schedule-per-rule possible.
Cons: additional table, new FK joins, `run_scheduled` needs `schedule_set` join, `RuleForm` must handle inline formset or a separate form, `Ca` increases for models.py. Migration complexity is higher. At MVP scale (no multi-schedule requirement stated), this is over-engineering.

**Recommendation:** Option A. The change note says "per-rule enable/disable toggle" and "configurable per-rule" — one schedule per rule. Separate model adds complexity without a stated requirement for multiple schedules per rule. [inference: change.md notes, roadmap.md S-15]

---

## 4. Render Cron Jobs — architecture

**Evidence — `render.yaml` (full file read):** The current `render.yaml` defines only a `type: web` service. There is **no `type: cron` entry** in the file. The `run_scheduled.py` command's docstring says "Called by Render Cron Job every minute" — this is the intended architecture, but the Render Cron Job is not yet configured. [evidence: render.yaml]

**Evidence — `run_scheduled.py` line 3:** `Called by Render Cron Job every minute: python manage.py run_scheduled` — confirms intended call cadence.

Render's `type: cron` service in `render.yaml` uses standard 5-field cron syntax for the `schedule` field. A single `"* * * * *"` (every minute) cron job calling `python manage.py run_scheduled` is sufficient — the command itself decides which rules fire at each minute.

The Render Cron Job addition to `render.yaml`:
```yaml
- type: cron
  name: data-pulse-scheduler
  runtime: python
  schedule: "* * * * *"
  buildCommand: "pip install -r requirements.txt"
  startCommand: "python manage.py run_scheduled"
  envVars:
    - key: DATABASE_URL
      sync: false
    - key: SECRET_KEY
      sync: false
    - key: FIELD_ENCRYPTION_KEY
      sync: false
    - key: DEBUG
      value: "False"
```

One job per minute is sufficient for all supported schedules (even `hourly` only fires at minute 0 of each hour, which a per-minute caller evaluates correctly). Multiple Render Cron Jobs would not improve resolution and would add cost/complexity. [inference: Render docs — one cron job per schedule is the standard pattern; all per-minute granularity needed by `croniter.match()`]

---

## 5. Predefined schedule options — storage and evaluation

**How `run_scheduled` would evaluate the new model:**

```python
# New run_scheduled.py logic (sketched, not final)
from croniter import croniter
from django.utils import timezone
from monitor.models import Rule

PREDEFINED = {
    'once_daily':  '0 8 * * *',
    'twice_daily': '0 0,12 * * *',
    'every_8h':    '0 0,8,16 * * *',
    'every_4h':    '0 0,4,8,12,16,20 * * *',
    'hourly':      '0 * * * *',
}

def handle(self, *args, **options):
    now = timezone.now().replace(second=0, microsecond=0)
    rules = Rule.objects.exclude(schedule_type='disabled').select_related('connection')
    due = []
    for rule in rules:
        cron_str = PREDEFINED.get(rule.schedule_type) or rule.schedule_cron
        if cron_str and croniter.match(cron_str, now):
            due.append(rule)
    ...
```

The `PREDEFINED` dict keeps the cron strings out of the DB for predefined options, making them easy to change without a migration. `custom_cron` uses the stored `rule.schedule_cron` value. [inference: croniter API — `croniter.match(expr, dt)` is the correct method]

**Alternative: store cron string in DB for all schedule_types**
Each predefined option could store its cron string in `schedule_cron` at save time (populated by the form's `clean()` or model's `save()`). This means `run_scheduled` only needs to read `schedule_cron` and never needs the `PREDEFINED` dict. Simpler runtime logic at the cost of coupling the stored value to the predefined mapping (must migrate stored cron strings if defaults change).

Both sub-options are valid. The PREDEFINED dict approach is easier to change in code; the DB-stored approach is easier to debug ("what cron runs this rule?"). Decision belongs in plan.

---

## 6. Migration from existing schedule_time TimeField

**Current state:**
- `Rule.schedule_time` is a `TimeField(null=True, blank=True)` — in production, some rows may have a non-null value.
- Migration origin: `monitor/migrations/0003_rule_schedule_time.py` — simple `AddField`, no constraints.
- Latest migration: `0004_rule_custom_sql`. Next auto-number: `0005`.

**Forward migration path:**

Step 1 — `0005_rule_schedule_type_cron.py`:
- `AddField`: `schedule_type` CharField default `'disabled'`
- `AddField`: `schedule_cron` CharField blank=True default `''`
- Data migration: for each Rule where `schedule_time IS NOT NULL`, set `schedule_type='once_daily'` and optionally store the old time as a custom cron (e.g. `schedule_time = time(6, 0)` → `schedule_cron = '0 6 * * *'`, `schedule_type = 'custom_cron'`). Since the existing `schedule_time` field is a single HH:MM and the closest predefined option is `once_daily` at 08:00, the safest data migration is `schedule_type='custom_cron'`, `schedule_cron='0 <hour> * * *'` — preserving the user's chosen time exactly.

Step 2 — `0006_remove_rule_schedule_time.py` (can be in same PR or deferred):
- `RemoveField`: `schedule_time`
- No data loss risk after step 1 completes.

**Reversibility:** Both migrations are reversible (AddField → RemoveField, RemoveField → AddField with re-population from `schedule_cron` if needed). [evidence: monitor/migrations/0003_rule_schedule_time.py, 0004_rule_custom_sql.py patterns]

**Risk:** If rows exist in production with a `schedule_time` set but `schedule_type` defaults to `'disabled'` before the data migration step runs, those rules would silently stop running. The data migration must run atomically with field addition. Using `migrations.RunPython` in `0005` is the correct pattern.

---

## Open choices for plan

These are product/architecture decisions not resolvable from code evidence alone:

| # | Question | Options | Impact |
|---|---|---|---|
| OC-1 | Add `croniter` dependency or regex-only? | croniter (1 dep) vs. regex + ad-hoc evaluator | Affects validation quality and `run_scheduled` match logic |
| OC-2 | Store cron string in DB for all types vs. PREDEFINED dict in code? | DB-stored (simpler runtime) vs. code dict (simpler migration) | Affects `run_scheduled` logic and data migration |
| OC-3 | Default time for `once_daily`? | 08:00 UTC (sensible business-hours default) vs. configurable | Affects predefined cron string and UI label |
| OC-4 | Remove `schedule_time` in same migration or deferred PR? | same PR (clean) vs. deferred (safer for rollback) | Risk/reversibility tradeoff |
| OC-5 | Add Render Cron Job to render.yaml? | Yes (required for scheduler to work on Render) vs. manual Render dashboard config | Infrastructure scope |

---

## File contract surface

Files that will need changes (based on current evidence):

| File | Change needed |
|---|---|
| `monitor/models.py` | Add `schedule_type`, `schedule_cron` fields; remove `schedule_time` |
| `monitor/migrations/0005_*.py` | AddField + data migration |
| `monitor/migrations/0006_*.py` | RemoveField `schedule_time` (may merge with 0005) |
| `monitor/forms.py` | Replace `schedule_time` widget with schedule type selector + conditional cron input |
| `monitor/management/commands/run_scheduled.py` | Replace `filter(schedule_time=now)` with `croniter.match()` loop |
| `monitor/tests.py` | Update `RunScheduledCommandTest` (currently 2 tests at lines 956–989) |
| `render.yaml` | Add `type: cron` service for every-minute execution |
| `pyproject.toml` | Add `croniter>=5.0.1` |
| `requirements.txt` | Regenerate after pyproject.toml update |

Blast radius: `monitor/models.py` has Ca=4 — forms, services, views, and run_scheduled all import it. Removing `schedule_time` breaks `monitor/forms.py:35`, `monitor/forms.py:51`, `monitor/tests.py:963,981`. All contained within the monitor app. [evidence: context/map/repo-map.md — Ca=4 for models.py]

---

## Cron library note

`croniter` package on PyPI: actively maintained, 10+ years history, 2000+ GitHub stars. Current stable release is in the 5.x series. The `croniter.match(expr, dt)` API is available from 1.3.x. No known security advisories relevant to this use case (validation + matching only; no execution). [inference: public PyPI metadata; not independently verified against PyPI at research time — recommend checking `uv add croniter` dry-run during plan phase]

---

## What this research does NOT determine

- Exact UI layout for the schedule picker (radio group? dropdown? conditional JS panel?) — UX decision.
- Whether the Render Cron Job free-tier minute-granularity is sufficient for production or if Render charges extra for `type: cron` — check Render pricing.
- Whether `once_daily` default time should be 08:00 UTC or configurable per-rule (the latter requires a 3rd new field `schedule_time_utc`).
