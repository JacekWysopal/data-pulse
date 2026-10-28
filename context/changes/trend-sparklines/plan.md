# Trend Sparklines Implementation Plan

## Overview

Add a status-sequence sparkline (20 coloured dots: OK/FAIL/ERROR) to each rule row in the
dashboard rules table and to the rule_history page header. The sparkline is generated
server-side as an inline SVG strip (120 × 16 px) — no JS chart library required.
This gives the user an at-a-glance trend view without opening the history drill-down.

## Current State Analysis

- `RuleResult` (`monitor/models.py:206–229`) has `status` (OK/FAIL/ERROR), `row_count`
  (nullable), `last_record_age_hours` (nullable), and `checked_at` on every row.
- `dashboard` view (`monitor/views.py:38–62`) already calls `prefetch_related('results')` with
  no bound, loading every historical result per rule. It passes `rule_status` (list of dicts
  with `rule`, `result`, `status`) but no per-rule history slice.
- `rule_history` view (`monitor/views.py:91–93`) already slices `results.order_by('-checked_at')[:20]`
  — the data is already there, needing only SVG generation and template output.
- Dashboard table has 8 `<th>` columns; `colspan="8"` on the no-results row must become 9.
- No `templatetags/` directory exists; all logic lives in views / services (thin-template convention).
- Django 6.1.2 is in use — `Prefetch` with a sliced queryset (`[:20]`) is fully supported.
- Test suite: `monitor/tests.py`, runs with `python manage.py test monitor` against SQLite.

### Key Discoveries:

- `monitor/views.py:38` — `prefetch_related('results')` loads ALL results unbounded. The
  replacement `Prefetch(queryset=RuleResult.objects.order_by('-checked_at')[:20], to_attr='recent_results')`
  fixes the unbounded load and simultaneously provides the sparkline slice — one extra query
  total (one `IN (…)` with per-rule LIMIT 20 via Django's subquery prefetch strategy).
- `monitor/views.py:41–44` — `last_result` is derived from `rule.results.order_by(...)[:1]`
  inside the loop; after the `Prefetch` change it becomes `rule.recent_results[0]`.
- `rule_history` view already has the right 20-result slice; sparkline data passes through
  with zero additional queries.
- `templates/monitor/dashboard.html` — filter JS targets `tbody tr[data-name]`, not column
  indices — column addition is safe.
- `context/changes/ui-glass-command/plan.md:20` confirmed trend data was explicitly deferred
  from the glass-UI change; this plan picks it up.

## Desired End State

- Dashboard rules table has a "Trend" column (9th column) showing an inline SVG strip of the
  last 20 check results as coloured dots (green = OK, red = FAIL, amber = ERROR, grey = no
  data). Rules with fewer than 1 result show a single em-dash.
- Rule history page header card shows the same sparkline strip to the right of the conditions.
- SVG is generated in Python (`monitor/sparkline.py`) — pure function, fully unit-testable.
- No N+1 query regression: dashboard uses a bounded `Prefetch` loading at most 20 results per
  rule in a single extra query; rule_history already bounded at 20.

### Key Discoveries:

- Sparkline shows **status sequence** (dot-per-result), not row-count/age numeric chart —
  decided by task owner; covers custom SQL rules where both numeric fields are always null.
- 20 coloured dots in a 120 × 16 px SVG strip; dots are 6 px diameter, evenly spaced.
- Colour per dot from that result's status (not stroke colour of latest result).
- `rule_history` sparkline: pass `results` (already a list after the `[:20]` slice) as context
  variable `sparkline_svg`; computed in `rule_history` view before `render()`.

## What We're NOT Doing

- Row-count chart (numeric polyline) — deferred; `row_count` is null for all custom SQL rules.
- Age-over-time chart — deferred for same reason; both numeric sparklines require a separate
  change when/if the team decides to address the null-data case.
- Mobile hide/show of the Trend column — the table is already `overflow-x:auto`; no breakpoint
  hide added in this plan.
- New Django template tags — no `templatetags/` directory.
- Any JS chart library.
- Status-dot sparkline in any view other than dashboard table + rule_history header.

## Implementation Approach

Four phases, each independently shippable and verifiable:

1. **Dashboard view** — replace unbounded `prefetch_related` with a bounded `Prefetch` returning
   `recent_results` (up to 20, newest-first); compute `sparkline_svg` per rule in the loop;
   add it to each `rule_status` dict. `last_result` now comes from `rule.recent_results[0]`.
2. **SVG helper** — `monitor/sparkline.py` with `status_dot_sparkline(statuses, width, height)`
   returning an inline SVG string; pure function with no Django imports.
3. **Templates** — add "Trend" `<th>` + `<td>` to `dashboard.html` (fix colspan); add sparkline
   strip to `rule_history.html` meta card.
4. **Tests** — unit tests for `sparkline.py`; dashboard view integration test asserting the Trend
   column renders SVG; rule_history smoke test asserting sparkline is present.

## Critical Implementation Details

- **`to_attr` name**: use `recent_results` throughout. Dashboard loop changes from
  `rule.results.order_by('-checked_at').first()` to `rule.recent_results[0] if rule.recent_results else None`.
- **Prefetch import**: add `from django.db.models import Prefetch` to `monitor/views.py`.
- **SVG content safety**: the sparkline function receives only `status` string values from
  `RuleResult.status` — always one of `'OK'`, `'FAIL'`, `'ERROR'`. No user-controlled strings
  reach the SVG markup; no escaping needed beyond Django's existing auto-escape (the SVG is
  passed as `mark_safe` since it is generated entirely in Python from a closed value set).
- **`mark_safe` import**: `from django.utils.safestring import mark_safe` in `views.py`.

---

## Phase 1: Dashboard View Update

### Overview

Replace the unbounded `prefetch_related('results')` with a bounded `Prefetch` that loads at most
20 results per rule into `rule.recent_results`. Derive `last_result` from `recent_results[0]`.
Compute a `sparkline_svg` string per rule and add it to the `rule_status` context list.

### Changes Required:

#### 1. Dashboard queryset — `monitor/views.py`

**File**: `monitor/views.py`

**Intent**: Replace the unbounded `prefetch_related('results')` with a `Prefetch` object that
fetches at most 20 results per rule, ordered newest-first, stored in `rule.recent_results`.
This eliminates the current unbounded load and provides the history slice for sparklines.

**Contract**: Import `Prefetch` from `django.db.models` and `mark_safe` from
`django.utils.safestring`. Import `status_dot_sparkline` from `.sparkline` (Phase 2 creates
this module). Change the queryset on `dashboard` view to use the bounded Prefetch:

```python
from django.db.models import Prefetch
from django.utils.safestring import mark_safe
from .sparkline import status_dot_sparkline

# queryset
rules = (
    Rule.objects
    .select_related('connection')
    .prefetch_related(
        Prefetch(
            'results',
            queryset=RuleResult.objects.order_by('-checked_at')[:20],
            to_attr='recent_results',
        )
    )
    .filter(user=request.user)
)
```

#### 2. Dashboard loop — `monitor/views.py`

**File**: `monitor/views.py`

**Intent**: Update the loop body to derive `last_result` from `rule.recent_results` and compute
`sparkline_svg` before appending to `rule_status`.

**Contract**: Replace `rule.results.order_by('-checked_at').first()` with
`rule.recent_results[0] if rule.recent_results else None`. Add `sparkline_svg` to each dict:

```python
last_result = rule.recent_results[0] if rule.recent_results else None
statuses = [r.status for r in reversed(rule.recent_results)]  # oldest-first
sparkline_svg = mark_safe(status_dot_sparkline(statuses))
# ...
rule_status.append({
    'rule': rule,
    'result': last_result,
    'status': status,
    'sparkline_svg': sparkline_svg,
})
```

### Success Criteria:

#### Automated Verification:

- Django check passes: `python manage.py check`
- Existing test suite still green: `python manage.py test monitor`

#### Manual Verification:

- Dashboard loads without error; each rule row contains a `<svg>` element in the Trend column.
- A rule with no results shows a dash (—) in the Trend column.

**Implementation Note**: After completing this phase and automated verification passes, pause
for manual confirmation before proceeding to Phase 2. Phase blocks use plain bullets — the
corresponding `- [ ]` checkboxes live in `## Progress` below.

---

## Phase 2: SVG Generation Helper

### Overview

Create `monitor/sparkline.py` with a single pure function `status_dot_sparkline` that accepts
a list of status strings (oldest-first) and returns an inline SVG string.

### Changes Required:

#### 1. New module — `monitor/sparkline.py`

**File**: `monitor/sparkline.py`

**Intent**: Pure Python function — no Django imports, no DB access — that converts a list of
`status` strings into an inline SVG string of coloured dots. Kept in its own module so it is
independently unit-testable and importable without loading Django views.

**Contract**:

```python
def status_dot_sparkline(
    statuses: list[str],
    width: int = 120,
    height: int = 16,
) -> str:
    """Return an inline SVG strip of coloured dots representing a status sequence.

    Args:
        statuses: list of status strings, oldest-first.
                  Expected values: 'OK', 'FAIL', 'ERROR'. Unknown values → grey dot.
        width:    total SVG width in px (default 120).
        height:   total SVG height in px (default 16).

    Returns:
        Inline SVG string (no XML declaration). Returns empty string when statuses is empty.
    """
```

Dot colours: `OK` → `#22c55e` (matches `--ok` CSS var); `FAIL` → `#f87171` (matches `--fail`);
`ERROR` → `#fbbf24` (matches `--error`); anything else → `#6b7280` (muted grey).
Dot radius: 3 px. Dots are evenly spaced across `width` with equal margins.
When `len(statuses) == 1` the single dot is centred. When `statuses` is empty, return `''`.

### Success Criteria:

#### Automated Verification:

- Unit tests pass for: empty input, 1 dot, 20 dots, all-OK, all-FAIL, mixed, unknown status.
- `python manage.py test monitor` still green.

#### Manual Verification:

- Inspect SVG string in Django shell: `from monitor.sparkline import status_dot_sparkline; print(status_dot_sparkline(['OK','FAIL','ERROR']))` — output is valid SVG with three circles.

**Implementation Note**: Phase 2 can be developed before Phase 1 because `views.py` imports
`status_dot_sparkline`; Phase 1 will error at runtime until Phase 2 exists. Implement in order:
Phase 2 first, then wire Phase 1, or commit both together.

---

## Phase 3: Template Updates

### Overview

Add a "Trend" column to `dashboard.html` and a sparkline strip to `rule_history.html`.

### Changes Required:

#### 1. `templates/monitor/dashboard.html` — column header

**File**: `templates/monitor/dashboard.html`

**Intent**: Add a "Trend" `<th>` as the 8th column (before the actions column). This gives users
the at-a-glance status sequence without opening history.

**Contract**: Insert `<th>Trend</th>` after the `<th>Measured values</th>` header. Update
`colspan="8"` on the no-results row to `colspan="9"`.

#### 2. `templates/monitor/dashboard.html` — column cell

**File**: `templates/monitor/dashboard.html`

**Intent**: Render the sparkline SVG (or a dash for no-data rules) in each rule row.

**Contract**: Insert a `<td>` after the "Measured values" `<td>` and before the actions `<td>`.
Content: `{{ item.sparkline_svg }}` when non-empty, else `<span style="color:var(--text-faint)">—</span>`.
Use `{% if item.sparkline_svg %}` to branch.

#### 3. `templates/monitor/rule_history.html` — meta card sparkline

**File**: `templates/monitor/rule_history.html`

**Intent**: Show the same sparkline in the rule meta card header so users see the trend at the
top of the history page without scrolling the table.

**Contract**: The `rule_history` view (Phase 3b below) will pass `sparkline_svg` in context.
In the meta card `<div>`, add the SVG after the `cond-chips` div:
```html
{% if sparkline_svg %}
<div class="cond-chips" style="margin-top:0.5rem">
  <span style="font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;font-weight:700;margin-right:4px">Trend</span>
  {{ sparkline_svg }}
</div>
{% endif %}
```

#### 4. `monitor/views.py` — rule_history view sparkline

**File**: `monitor/views.py`

**Intent**: Compute `sparkline_svg` from the already-fetched `results` slice and pass it to the
template so `rule_history.html` can render the trend strip with no extra queries.

**Contract**: After the existing `results = rule.results.select_related('run').order_by('-checked_at')[:20]`
line, add:

```python
statuses = [r.status for r in reversed(list(results))]  # oldest-first
sparkline_svg = mark_safe(status_dot_sparkline(statuses))
```

Add `sparkline_svg` to the `render` context dict.

### Success Criteria:

#### Automated Verification:

- `python manage.py test monitor` still green.
- `python manage.py check` clean.

#### Manual Verification:

- Dashboard: each rule row shows a coloured dot strip in the Trend column; filter JS still works.
- No-results row fills all 9 columns without layout break.
- Rule history header card shows sparkline strip above or beside the condition chips.
- A rule with a mix of OK and FAIL results shows green and red dots respectively.

---

## Phase 4: Tests

### Overview

Add unit tests for `sparkline.py` and integration tests asserting the sparkline appears in
dashboard and rule_history responses.

### Changes Required:

#### 1. `monitor/tests.py` — sparkline unit tests

**File**: `monitor/tests.py`

**Intent**: Verify `status_dot_sparkline` handles all edge cases correctly without any database
or Django context.

**Contract**: Add a `SparklineTest(TestCase)` class (or use `unittest.TestCase` since no DB
needed) with test methods:
- `test_empty_returns_empty_string` — `status_dot_sparkline([])` returns `''`.
- `test_single_ok_dot` — returns SVG containing `#22c55e` and one `<circle`.
- `test_twenty_dots` — 20 statuses → SVG contains exactly 20 `<circle` elements.
- `test_fail_colour` — FAIL status → `#f87171` present in output.
- `test_error_colour` — ERROR status → `#fbbf24` present in output.
- `test_unknown_status_gets_grey` — unknown string → `#6b7280` present in output.
- `test_output_is_svg_element` — output starts with `<svg` and ends with `</svg>`.

#### 2. `monitor/tests.py` — dashboard view integration test

**File**: `monitor/tests.py`

**Intent**: Assert that the dashboard response includes the Trend `<th>` and that a rule with
results gets an SVG dot in its row.

**Contract**: Add `DashboardSparklineTest(TestCase)` with:
- `setUp`: create user, login, create rule with 3 `RuleResult` rows (OK, FAIL, OK).
- `test_trend_column_header`: GET `/` → response contains `Trend`.
- `test_sparkline_svg_in_row`: GET `/` → response contains `<svg`.

#### 3. `monitor/tests.py` — rule_history sparkline test

**File**: `monitor/tests.py`

**Intent**: Assert rule history page renders the sparkline strip.

**Contract**: Add `RuleHistorySparklineTest(TestCase)` with:
- `setUp`: user, login, rule, 3 results.
- `test_sparkline_in_history_header`: GET history URL → response contains `<svg`.

### Success Criteria:

#### Automated Verification:

- All new test methods pass: `python manage.py test monitor.tests.SparklineTest monitor.tests.DashboardSparklineTest monitor.tests.RuleHistorySparklineTest`
- Full suite still green: `python manage.py test monitor`

#### Manual Verification:

- Review test coverage — all 7 sparkline edge cases have passing assertions.

---

## Testing Strategy

### Unit Tests:

- `SparklineTest` — 7 pure-function tests, no DB, no Django context.
- Edge cases: empty list, single element, full 20, each status colour, unknown status.

### Integration Tests:

- `DashboardSparklineTest` — 2 view tests: column header present, SVG in body.
- `RuleHistorySparklineTest` — 1 view test: SVG in history header.

### Manual Testing Steps:

1. Run `python manage.py runserver`; open dashboard; verify each rule row shows dots.
2. Verify a rule with no results shows `—` in the Trend column.
3. Click a rule → history page; verify sparkline strip appears in the meta card.
4. Resize browser to mobile width; verify table scrolls horizontally without layout break.
5. Apply dashboard filters; verify filtered rows hide/show with sparkline column intact.

## Performance Considerations

- Bounded `Prefetch` replaces an unbounded load: max 20 results per rule regardless of history
  depth. For users with many rules, this is a significant memory reduction.
- `status_dot_sparkline` is O(n) where n ≤ 20; negligible CPU cost.
- No additional database queries for `rule_history` sparkline.

## Migration Notes

No model changes. No migration needed.

## References

- Research: `context/changes/trend-sparklines/research.md`
- `monitor/models.py:206–229` — RuleResult fields
- `monitor/views.py:38–62` — dashboard view (current)
- `monitor/views.py:91–93` — rule_history view (current)
- `templates/monitor/dashboard.html` — 8-column table
- `templates/monitor/rule_history.html` — meta card
- Django Prefetch docs: https://docs.djangoproject.com/en/4.2/ref/models/querysets/#prefetch-related

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Dashboard View Update

#### Automated

- [ ] 1.1 Django check passes after view change
- [ ] 1.2 Existing test suite green after view change

#### Manual

- [ ] 1.3 Dashboard loads; each rule row has SVG in Trend column
- [ ] 1.4 Rule with no results shows dash in Trend column

### Phase 2: SVG Generation Helper

#### Automated

- [ ] 2.1 Unit tests pass for sparkline edge cases
- [ ] 2.2 Full test suite green after sparkline module added

#### Manual

- [ ] 2.3 Shell smoke test: valid SVG with 3 circles for 3-status input

### Phase 3: Template Updates

#### Automated

- [ ] 3.1 Django check clean after template changes
- [ ] 3.2 Full test suite green after template changes

#### Manual

- [ ] 3.3 Dashboard Trend column renders dots; filter JS works; no-results colspan correct
- [ ] 3.4 Rule history header card shows sparkline strip

### Phase 4: Tests

#### Automated

- [ ] 4.1 SparklineTest — all 7 unit tests pass
- [ ] 4.2 DashboardSparklineTest — both view tests pass
- [ ] 4.3 RuleHistorySparklineTest — history sparkline test passes
- [ ] 4.4 Full test suite green: python manage.py test monitor

#### Manual

- [ ] 4.5 Manual walkthrough: dashboard dots, no-data dash, history strip, mobile scroll, filter JS
