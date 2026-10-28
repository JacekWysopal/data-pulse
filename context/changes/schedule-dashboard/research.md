# Research: schedule-dashboard

**Change ID:** schedule-dashboard
**Topic:** Schedule dashboard — scheduled rules tab with next/last run and enable/disable toggle
**Researched:** 2026-10-28
**Status:** complete

---

## Q1 — Rule scheduling fields

Source: `monitor/models.py`

`Rule` has two scheduling fields:

- `schedule_type` — `CharField(max_length=20)` with inner `ScheduleType(TextChoices)` choices (`models.py`):
  - `DISABLED = 'disabled'`
  - `PRESET_1X = 'preset_1x'` — Once daily (08:00 UTC)
  - `PRESET_2X = 'preset_2x'` — Twice daily (08:00 & 20:00 UTC)
  - `PRESET_3X = 'preset_3x'` — Three times daily (06:00, 14:00, 22:00 UTC)
  - `PRESET_6X = 'preset_6x'` — Six times daily (every 4 h)
  - `HOURLY = 'hourly'` — Hourly
  - `CUSTOM_CRON = 'custom_cron'` — Custom cron expression
  - Default: `'disabled'`

- `schedule_cron` — `CharField(max_length=100, blank=True, default='')` — 5-field UTC cron string; only used when `schedule_type == 'custom_cron'` (`models.py:122–130`)

Both fields are on `Rule`; no separate Schedule model exists.

---

## Q2 — How croniter computes next run

Source: `monitor/management/commands/run_scheduled.py`, `requirements.txt`

`croniter==6.2.4` is available (`requirements.txt`).

`run_scheduled.py` defines a `PREDEFINED` mapping from preset `schedule_type` values to 5-field cron strings (`run_scheduled.py:15–21`):

```python
PREDEFINED = {
    'preset_1x':   '0 8 * * *',
    'preset_2x':   '0 8,20 * * *',
    'preset_3x':   '0 6,14,22 * * *',
    'preset_6x':   '0 */4 * * *',
    'hourly':      '0 * * * *',
}
```

To resolve a cron string for any scheduled rule: `cron_str = PREDEFINED.get(rule.schedule_type) or rule.schedule_cron`.

`run_scheduled.py` uses `croniter.match(cron_str, now)` for the "fire now?" check. For next-run calculation the standard croniter constructor API is: `croniter(cron_str, base_datetime).get_next(datetime)`. This returns the next scheduled UTC datetime after `base_datetime`.

---

## Q3 — Sidebar/navbar structure in base.html

Source: `templates/base.html`

The sidebar (`<aside class="dp-sidebar">`) contains a single `<nav class="dp-nav">` with two `dp-nav-section` labels and their items:

```
Monitor  (dp-nav-section)
  Dashboard  → monitor:dashboard
  Add rule   → monitor:rule_create

Data  (dp-nav-section)
  Connections → monitor:connection_list
```

Each nav item follows this exact pattern (`base.html`):
```html
<a href="{% url 'monitor:...' %}"
   class="dp-nav-item {% if request.resolver_match.url_name == '<url_name>' %}active{% endif %}"
   data-tip="<Label>">
  <span class="dp-nav-icon"><svg …/></span>
  <span class="dp-nav-label"><Label></span>
</a>
```

The "Schedule" link should be added to the **Monitor** section, after "Add rule" and before the "Data" section. The `active` condition for schedule dashboard: `request.resolver_match.url_name == 'schedule_dashboard'`.

A clock SVG icon works for Schedule; 16×16 matching the other icons.

---

## Q4 — Last run: CheckRun + RuleResult models

Source: `monitor/models.py`

`Rule` has a `last_result` property that returns the most recent `RuleResult` (`models.py:162–164`):

```python
@property
def last_result(self):
    return self.results.order_by('-checked_at').first()
```

`RuleResult` relevant fields:
- `checked_at` — `DateTimeField` (when the check ran)
- `status` — `CharField` with `Status` choices: `OK`, `FAIL`, `ERROR` (`models.py:183–186`)
- `error_message` — `TextField(blank=True)`
- `run` — FK to `CheckRun`

`CheckRun` only records the overall execution wrapper; per-rule status lives in `RuleResult`. The `last_result` property is already available and avoids an extra query when `results` is prefetched.

---

## Q5 — User filtering pattern

Source: `monitor/views.py`

All views filter rules to the authenticated user. Two patterns are used:

**List query:** `Rule.objects.select_related('connection').prefetch_related('results').filter(user=request.user)` (`views.py:26–27`)

**Single object:** `get_object_or_404(Rule, pk=rule_id, user=request.user)` (`views.py:44`, `58`, `64`, `70`, `76`)

The schedule dashboard should use the list query pattern, filtered to `schedule_type != 'disabled'`:
```python
Rule.objects.select_related('connection').prefetch_related('results')
    .filter(user=request.user)
    .exclude(schedule_type='disabled')
```

The `toggle_schedule` POST view should use `get_object_or_404(Rule, pk=rule_id, user=request.user)` for ownership enforcement.

---

## Test patterns found

Source: `monitor/tests.py`

- Tests use `django.test.TestCase` + `django.test.Client`
- `User.objects.create_user(username, password=...)` for test users
- `client.login(username=..., password=...)` for authentication
- `client.get(reverse('monitor:...'))` and `client.post(reverse('monitor:...'), data)`
- `make_rule(...)` factory function exists; can extend or replicate for schedule tests

---

## Open questions

None — all facts required for planning are resolved.
