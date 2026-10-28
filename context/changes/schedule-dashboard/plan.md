# Schedule Dashboard Implementation Plan

## Overview

Add a dedicated "Schedule" page at `/schedule/` that shows all of the authenticated user's rules with a schedule configured, their computed next-run time, last-run result, and a quick enable/disable toggle per rule.

## Current State Analysis

- `Rule` already has `schedule_type` (7 choices incl. `disabled`) and `schedule_cron` fields (`monitor/models.py:95–130`).
- `PREDEFINED` cron-string map and `croniter` are live in `run_scheduled.py:15–21`; `croniter==6.2.4` is in `requirements.txt`.
- `Rule.last_result` property returns the most recent `RuleResult` ordered by `checked_at` (`models.py:162–164`).
- All existing views filter by `user=request.user`; single-object views use `get_object_or_404(Rule, pk=..., user=request.user)`.
- Sidebar nav in `base.html` has a Monitor section with Dashboard and Add rule; a new Schedule item belongs there.
- No schedule-focused view or URL exists today.

## Desired End State

A logged-in user navigates to `/schedule/` (or clicks "Schedule" in the sidebar) and sees a table of all their rules with `schedule_type != 'disabled'`. Each row shows: rule name, source table, schedule label, next scheduled UTC run, last-run timestamp, last-run status badge, and a quick-run button. A toggle button per row POSTs to `/schedule/<rule_id>/toggle/` and flips the rule between `disabled` and its previous preset (or `preset_1x` if no previous preset applies).

### Key Discoveries

- `croniter(cron_str, base_datetime).get_next(datetime)` computes the next occurrence; `base_datetime` should be `timezone.now()` (`run_scheduled.py`, croniter docs).
- The `PREDEFINED` map must be imported/duplicated in `views.py` (or moved to a shared constant) to resolve cron strings for presets.
- Toggle behavior: when disabling, store nothing extra — the cron or preset is still on the rule and is re-used on re-enable. When enabling a currently-disabled rule, the toggle must have a target schedule type. The simplest safe behaviour: toggle switches `disabled` ↔ `preset_1x`; if the rule already has a non-disabled `schedule_type` and we just want to pause it, that is a rule-edit concern (out of scope).
- `Rule.results` must be prefetched to avoid N+1 in the table loop.

## What We're NOT Doing

- No calendar/timeline visualisation (listed in change.md notes as "Visual timeline" — deferred).
- No bulk enable/disable.
- No in-page cron editor; schedule changes go through the existing rule edit form.
- No pagination (schedule page only shows scheduled rules, expected small set).
- No WebSocket / live refresh.

## Implementation Approach

Four tightly scoped phases: (1) backend — views + URLs, (2) template — schedule_dashboard.html, (3) sidebar link, (4) tests. Each phase is independently verifiable. The toggle is a POST-only view that owns a single `schedule_type` field flip; no new model fields or migrations are required.

## Phase 1: View + URL

### Overview

Add `schedule_dashboard` (GET) and `toggle_schedule` (POST) views to `monitor/views.py`, and wire two new URL patterns in `monitor/urls.py`.

### Changes Required

#### 1. Shared PREDEFINED constant

**File:** `monitor/management/commands/run_scheduled.py`

**Intent:** `PREDEFINED` is currently local to the management command. Both the command and the new view need it. Move it to `monitor/services.py` (or a small `monitor/schedule_utils.py`) so it can be imported without loading the management command module. The management command then imports it from there.

**Contract:** New module `monitor/schedule_utils.py` (or constant added to `monitor/services.py`). Exports `PREDEFINED: dict[str, str]` and `resolve_cron(rule) -> str | None` — returns the 5-field cron string for a rule's current `schedule_type`, or `None` if disabled/custom_cron-with-blank-expr.

```python
# monitor/schedule_utils.py
from monitor.models import Rule

PREDEFINED = {
    'preset_1x':   '0 8 * * *',
    'preset_2x':   '0 8,20 * * *',
    'preset_3x':   '0 6,14,22 * * *',
    'preset_6x':   '0 */4 * * *',
    'hourly':      '0 * * * *',
}

def resolve_cron(rule: Rule) -> str | None:
    """Return the cron expression for rule, or None if unresolvable."""
    if rule.schedule_type == 'disabled':
        return None
    cron = PREDEFINED.get(rule.schedule_type) or rule.schedule_cron
    return cron or None
```

#### 2. `schedule_dashboard` view

**File:** `monitor/views.py`

**Intent:** Render the schedule dashboard for the authenticated user. Compute `next_run` for each scheduled rule using croniter and attach it alongside `last_result`.

**Contract:** `@login_required` GET view. Queries rules with `schedule_type != 'disabled'` for `request.user`, prefetches `results` and selects `connection`. For each rule calls `resolve_cron(rule)`; if a cron string is available, computes `next_run = croniter(cron_str, now).get_next(datetime)` (UTC). If cron is missing/invalid, `next_run = None`. Passes `rule_rows` (list of dicts with `rule`, `next_run`, `last_result`) to template.

```python
from datetime import datetime
from croniter import croniter
from django.utils import timezone
from .schedule_utils import resolve_cron

@login_required
def schedule_dashboard(request):
    now = timezone.now()
    rules = (
        Rule.objects
        .select_related('connection')
        .prefetch_related('results')
        .filter(user=request.user)
        .exclude(schedule_type='disabled')
    )
    rule_rows = []
    for rule in rules:
        cron_str = resolve_cron(rule)
        next_run = None
        if cron_str:
            try:
                next_run = croniter(cron_str, now).get_next(datetime)
            except (ValueError, TypeError):
                next_run = None
        rule_rows.append({
            'rule': rule,
            'next_run': next_run,
            'last_result': rule.last_result,
        })
    return render(request, 'monitor/schedule_dashboard.html', {
        'rule_rows': rule_rows,
        'now': now,
    })
```

#### 3. `toggle_schedule` view

**File:** `monitor/views.py`

**Intent:** POST-only view that flips a rule between `disabled` and `preset_1x`. Provides a quick pause/resume without opening the full edit form.

**Contract:** `@login_required` POST-only view (return 405 for GET). Uses `get_object_or_404(Rule, pk=rule_id, user=request.user)`. If `rule.schedule_type == 'disabled'`, sets it to `'preset_1x'`. Otherwise sets it to `'disabled'`. Saves only `schedule_type`. Redirects to `monitor:schedule_dashboard`.

#### 4. URL patterns

**File:** `monitor/urls.py`

**Intent:** Expose the two new views under `/schedule/`.

**Contract:** Append to `urlpatterns`:
```python
path('schedule/', views.schedule_dashboard, name='schedule_dashboard'),
path('schedule/<int:rule_id>/toggle/', views.toggle_schedule, name='toggle_schedule'),
```

### Success Criteria

#### Automated Verification

- `python manage.py check` passes with no errors.
- `python manage.py test monitor` passes (existing tests unbroken).
- `/schedule/` returns 302→login for anonymous users.
- `/schedule/` returns 200 for authenticated user (verified in Phase 4 tests).
- `toggle_schedule` POST for own rule returns redirect; for other-user rule returns 404.

#### Manual Verification

- Visit `/schedule/` as authenticated user — page renders without 500.
- Clicking toggle on a scheduled rule disables it; clicking again re-enables to `preset_1x`.

---

## Phase 2: Template

### Overview

Create `templates/monitor/schedule_dashboard.html` extending `base.html`. Renders the schedule table with next-run times, last-run status badges, and quick-run + toggle buttons, matching the existing dark-theme design system.

### Changes Required

#### 1. Template file

**File:** `templates/monitor/schedule_dashboard.html`

**Intent:** Provide the schedule dashboard UI consistent with the existing table style used on `monitor/dashboard.html`. Show each scheduled rule with its computed next run time (UTC), last run timestamp, status badge, and action buttons.

**Contract:** Extends `base.html`. Uses `dp-table`, `dp-badge`, `btn-dp`, and `dp-panel` CSS classes already defined in `base.html`. For each `row` in `rule_rows`:
- Rule name (links to `monitor:rule_history`).
- Table: `rule.schema_name`.`rule.table_name` (or "—" if blank).
- Schedule: `rule.get_schedule_type_display()`.
- Next run: `row.next_run|date:"Y-m-d H:i"` UTC, or "—".
- Last run: `row.last_result.checked_at|date:"Y-m-d H:i"` UTC, or "Never".
- Last status: `dp-badge` with `dp-badge-ok/fail/error/never` matching the status value, or "Never" badge.
- Quick run: POST form to `monitor:run_single` (existing view).
- Toggle: POST form to `monitor:toggle_schedule`; button label "Disable" when scheduled, "Enable" when (only shows if navigated to via deep link — normally excluded from table, but the toggle endpoint is accessible from rule edit too).

Empty state: when `rule_rows` is empty, show a call-to-action card directing the user to the rule edit form to enable scheduling.

### Success Criteria

#### Automated Verification

- `python manage.py test monitor` passes.
- `python manage.py check --deploy` (template syntax) passes.

#### Manual Verification

- `/schedule/` renders correctly with at least one scheduled rule: next run time shows in UTC, status badge colour matches `last_result.status`.
- Empty state renders when no rules have a schedule.
- "Disable" toggle POST disables rule; page reloads and rule disappears from table.
- Quick run button triggers a run and shows flash message on return.

---

## Phase 3: Sidebar Link

### Overview

Add a "Schedule" nav item to the Monitor section in `templates/base.html`, below "Add rule".

### Changes Required

#### 1. Sidebar nav item

**File:** `templates/base.html`

**Intent:** Let users reach the schedule dashboard from anywhere in the app.

**Contract:** Insert after the "Add rule" `<a>` block and before `<div class="dp-nav-section">Data</div>`. Follows the exact `.dp-nav-item` pattern with `data-tip="Schedule"`, active condition `request.resolver_match.url_name == 'schedule_dashboard'`, and a clock SVG icon (16×16, `currentColor` stroke):

```html
<a href="{% url 'monitor:schedule_dashboard' %}"
   class="dp-nav-item {% if request.resolver_match.url_name == 'schedule_dashboard' %}active{% endif %}"
   data-tip="Schedule">
  <span class="dp-nav-icon">
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.4"/>
      <path d="M8 5v3.5l2.5 1.5" stroke="currentColor" stroke-width="1.4"
            stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
  </span>
  <span class="dp-nav-label">Schedule</span>
</a>
```

### Success Criteria

#### Automated Verification

- `python manage.py test monitor` passes.
- Template renders without syntax error (`python manage.py check`).

#### Manual Verification

- "Schedule" link appears in sidebar on all pages.
- Link is highlighted (active) when on `/schedule/`.
- Collapsed sidebar shows clock icon with "Schedule" tooltip.

---

## Phase 4: Tests

### Overview

Add test coverage for `schedule_dashboard` view (200/auth), `toggle_schedule` POST behaviour, and `resolve_cron` / next-run calculation correctness.

### Changes Required

#### 1. Test cases

**File:** `monitor/tests.py`

**Intent:** Verify the three testable behaviours: authentication gate, page content, toggle ownership and state transition, and cron-to-next-run calculation.

**Contract:** Add a `ScheduleDashboardTests(TestCase)` class using the existing `make_rule` factory. Cover:

1. **Dashboard 200** — authenticated user with one scheduled rule sees 200; response contains the rule name.
2. **Dashboard redirects anonymous** — unauthenticated GET to `/schedule/` returns 302 to login.
3. **Dashboard empty state** — user with no scheduled rules gets 200 (no crash).
4. **Toggle disable** — POST to `toggle_schedule` for a `preset_1x` rule flips it to `disabled`; response redirects.
5. **Toggle enable** — POST to `toggle_schedule` for a `disabled` rule flips it to `preset_1x`; response redirects.
6. **Toggle 404 for other user's rule** — POST by user B on user A's rule returns 404.
7. **resolve_cron preset** — `resolve_cron(rule)` returns `'0 8 * * *'` for `preset_1x`.
8. **resolve_cron custom** — returns the `schedule_cron` value for `custom_cron`.
9. **resolve_cron disabled** — returns `None` for `disabled`.
10. **next_run computation** — given a fixed `now` and `'0 8 * * *'`, `croniter('0 8 * * *', now).get_next(datetime)` returns a datetime with hour 8 and minute 0 (UTC).

### Success Criteria

#### Automated Verification

- `python manage.py test monitor` passes with all new test cases green.
- No new failures in existing test cases.

#### Manual Verification

- Test output confirms all 10 new test methods pass.

---

## Testing Strategy

### Unit Tests

- `resolve_cron` with all three branches (preset, custom_cron, disabled).
- Next-run datetime is parseable and in the future relative to `now`.

### Integration Tests (Django TestCase)

- Authenticated GET `/schedule/` → 200.
- Anonymous GET `/schedule/` → 302.
- POST `toggle_schedule` own rule → redirect + DB state flip.
- POST `toggle_schedule` other user's rule → 404.

### Manual Testing Steps

1. Add a rule with `preset_1x` schedule, visit `/schedule/`, verify next run shows `08:00 UTC`.
2. Click "Disable" toggle, verify rule disappears from table.
3. Visit rule via edit form, re-enable schedule, return to `/schedule/`, verify it reappears.
4. Run quick-run button, verify flash message and last-status badge updates.

## Performance Considerations

The view prefetches `results` and selects `connection` in a single query. Next-run computation is O(n) pure Python with croniter — no database calls. Acceptable for the expected rule count (< 200 per user).

## Migration Notes

No model changes. No migrations required.

## References

- Research: `context/changes/schedule-dashboard/research.md`
- PREDEFINED cron map: `monitor/management/commands/run_scheduled.py:15`
- Rule scheduling fields: `monitor/models.py:95`
- Sidebar nav pattern: `templates/base.html` (`.dp-nav-item`)
- Existing view auth pattern: `monitor/views.py:26`

---

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: View + URL

#### Automated

- [x] 1.1 `python manage.py check` passes
- [x] 1.2 `python manage.py test monitor` passes (existing tests unbroken)
- [x] 1.3 Anonymous GET `/schedule/` returns 302

#### Manual

- [ ] 1.4 `/schedule/` renders without 500 for authenticated user
- [ ] 1.5 Toggle POST disables and re-enables rule correctly

### Phase 2: Template

#### Automated

- [x] 2.1 `python manage.py test monitor` passes
- [x] 2.2 `python manage.py check` passes (template syntax)

#### Manual

- [ ] 2.3 Next run column shows UTC time for scheduled rule
- [ ] 2.4 Empty state renders with no scheduled rules
- [ ] 2.5 Disable toggle removes rule from table on reload
- [ ] 2.6 Quick run button triggers run and shows flash message

### Phase 3: Sidebar Link

#### Automated

- [x] 3.1 `python manage.py test monitor` passes
- [x] 3.2 `python manage.py check` passes (no template error)

#### Manual

- [ ] 3.3 "Schedule" link visible in sidebar on all pages
- [ ] 3.4 Link is highlighted when on `/schedule/`
- [ ] 3.5 Clock icon + tooltip visible in collapsed sidebar

### Phase 4: Tests

#### Automated

- [x] 4.1 All 10 new test cases in `ScheduleDashboardTests` pass
- [x] 4.2 No regressions in existing tests
