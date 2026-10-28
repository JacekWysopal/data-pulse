---
date: 2026-10-28T19:43:19+00:00
researcher: worker-subagent
git_commit: c2ad8df
branch: dev
repository: data-pulse
topic: "What's needed for trend sparklines — row count and age history in the rule list"
tags: [research, codebase, monitor, ruleresult, dashboard, sparkline, svg]
status: complete
last_updated: 2026-10-28
last_updated_by: worker-subagent
---

# Research: What's needed for trend sparklines?

**Date**: 2026-10-28T19:43:19+00:00
**Researcher**: worker-subagent
**Git Commit**: c2ad8df
**Branch**: dev
**Repository**: data-pulse

## Research Question

Five questions were provided for the `trend-sparklines` change:

1. `RuleResult` model — which fields are available (`row_count`, `last_record_age_hours`, `checked_at`, `status`)?
2. Dashboard view — what data is passed to the template; can last 20 results per rule be added without new queries?
3. SVG sparkline generation: inline SVG in template vs server-side calculation.
4. Performance: N+1 query risk when loading sparkline data for all rules.
5. What to show: `row_count` trend OR `last_record_age_hours` trend OR status (ok/fail sequence)?

## Summary

All four fields needed for sparklines (`row_count`, `last_record_age_hours`, `checked_at`, `status`) are present on `RuleResult`. The dashboard view iterates `rule_status`, each entry holding the rule object and its latest single result; it does **not** currently pass the last 20 results per rule. A `prefetch_related('results')` call already exists on the queryset, so fetching the last 20 results per rule can be done by slicing from the prefetch in the view loop — but that slice will trigger an extra query per rule (Django does not cache sliced prefetches). The safe, zero-extra-query approach is a single annotated `Prefetch` object with `queryset=RuleResult.objects.order_by('-checked_at')[:20]` added to the existing `prefetch_related`. Server-side SVG generation inside the view (computing path points in Python and passing them as strings to the template) avoids template-tag overhead and keeps logic testable. The dashboard template has 8 table columns; inserting one new "Trend" column is straightforward. The `rule_history` view already queries `results.order_by('-checked_at')[:20]`, so the same data is available there with no change.

## Detailed Findings

### 1. RuleResult model fields

`monitor/models.py:206–229` defines `RuleResult` with exactly these fields relevant to sparklines:

| Field | Type | Nullable |
|---|---|---|
| `status` | `CharField` (OK / FAIL / ERROR) | no |
| `row_count` | `PositiveIntegerField` | yes (`null=True`) |
| `last_record_age_hours` | `FloatField` | yes (`null=True`) |
| `checked_at` | `DateTimeField(default=timezone.now)` | no |

`row_count` and `last_record_age_hours` are both nullable. For any custom-SQL rule both will be `None`. A valid sparkline dataset requires at least 2 non-null points to draw a line; the template or view helper must guard against this case.

### 2. Dashboard view — current data shape

`monitor/views.py:38–62` (the `dashboard` view):

```python
rules = Rule.objects.select_related('connection').prefetch_related('results').filter(user=request.user)
```

- The queryset prefetches **all** results via `prefetch_related('results')` — no `Prefetch` object with a queryset limit, so every result for every rule is loaded into memory. For large histories this is wasteful but it does mean the result rows are already in the result cache; any `rule.results.order_by('-checked_at')[:20]` call inside the Python loop will hit the database again because Django cannot re-order and re-slice an already-fetched prefetch.
- The view builds `rule_status`, a list of dicts: `{'rule': rule, 'result': last_result, 'status': status}`. The template receives this list plus four integer counters. No history slice is included per rule.
- `last_result = rule.results.order_by('-checked_at').first()` at `monitor/views.py:41` is called inside the loop — this hits the prefetch cache (Django can serve `.first()` from the prefetch cache when no filtering is applied beyond the FK, but `.order_by()` on a prefetch cached set does trigger a real query unless the prefetch was already ordered). In the current code the prefetch has no order specified, so `.order_by('-checked_at').first()` likely fires one extra query per rule.

### 3. N+1 query risk for sparkline data

Current behaviour: `prefetch_related('results')` with no `Prefetch(queryset=...)` loads **all** RuleResult rows for all the user's rules in one query, then `rule.results.order_by(...)` on that cache triggers re-evaluation. The safest, query-bounded solution is:

```python
from django.db.models import Prefetch
from .models import RuleResult

rules = Rule.objects.select_related('connection').prefetch_related(
    Prefetch(
        'results',
        queryset=RuleResult.objects.order_by('-checked_at')[:20],
        to_attr='recent_results',
    )
).filter(user=request.user)
```

With `to_attr='recent_results'`, each rule gets `rule.recent_results` — a plain list of up to 20 `RuleResult` objects, already ordered newest-first, loaded in a single extra query (one `IN (…)` with `LIMIT 20` applied per rule group via Django's subquery prefetch strategy). The view loop then computes `rule.recent_results[0]` for the last result and the full list for the sparkline. This eliminates the current N+1 risk for `last_result` as well.

**Important constraint**: Django's `Prefetch` with a sliced queryset (`[:20]`) is supported since Django 4.2 (confirmed available — `django==6.1.2` per `requirements.txt`).

### 4. SVG sparkline generation: inline SVG vs server-side

Two options:

**Option A — Template arithmetic**: Django's `{% widthratio %}` tag and arithmetic filters can compute point positions in-template. This is already used in `rule_history.html:72` for the age bar. For a sparkline with N points and two data series this becomes verbose and error-prone in template syntax; it also cannot guard null values cleanly.

**Option B — Server-side Python helper**: Compute the SVG `<polyline>` points string in the view or a utility function; pass it as a string to the template. The template emits `<svg><polyline points="{{ item.row_sparkline_pts }}" .../></svg>`. This keeps arithmetic in Python where it is testable, handles null-value gaps cleanly, and keeps the template thin. This is the preferred approach given the project convention of thin templates (all server-side logic lives in `views.py` or `services.py`).

Proposed helper signature (no new file needed — can live in `views.py` or a new `monitor/sparkline.py`):

```python
def sparkline_points(values: list[float | None], width: int, height: int) -> str:
    """Return SVG polyline points string from a list of values, oldest-first.
    Skips None values. Returns '' when fewer than 2 non-null values are present."""
```

The sparkline renders inside a fixed `width×height` bounding box (e.g. 80×24 px). X is evenly spaced across the N slots; Y is scaled between `min(values)` and `max(values)`. When `min == max` all points sit on the centre line.

### 5. What to show

The change note (`change.md:12`) specifies:
- "Row count over time, age over time."
- "Color: green when OK, red when FAIL."
- Two separate sparklines per rule: one for `row_count`, one for `last_record_age_hours`.

Observed constraints from the data:
- `row_count` is only non-null when `min_row_count is not None` on the rule (`monitor/services.py:258–262` in `_check_volume_freshness`). Rules that only use a freshness check have `row_count=None` on every result.
- `last_record_age_hours` is only non-null when `timestamp_column` is set on the rule (`monitor/services.py:265–277` in `_check_volume_freshness`). Rules that only use a volume check have `last_record_age_hours=None` on every result.
- Custom SQL rules (`_check_custom_sql`) initialise both fields to `None` (`monitor/services.py:187–188`) and never set them, so every result has both fields null.

Therefore: for each rule, render only the sparkline(s) for which it has data. When both are null for all 20 results, show a dash or the status-dot sequence (ok/fail/error color sequence) as a fallback. The status sequence is always available and is the minimum viable sparkline.

The change note also says "Color: green when OK, red when FAIL". This can be applied per-segment or as a single stroke color determined by the most recent result's status. Per-point coloring requires multiple `<polyline>` segments or individual `<circle>` dots (one per point). The simpler implementation is a single `<polyline>` stroked with the latest result's status color, plus individual `<circle>` dots for each data point coloured by that point's status.

### 6. Dashboard template — column insertion point

`templates/monitor/dashboard.html` (the rules table) currently has 8 `<th>` columns (Rule, Source, Table, Conditions, Schedule, Status, Measured values, actions). The JS filter logic at `dashboard.html` (bottom `<script>`) selects `tbody tr[data-name]` and hides/shows rows — it does not reference column indices, so adding a column does not break filtering. The `colspan="8"` on the no-results row (`templates/monitor/dashboard.html`) must be updated to `colspan="9"`.

### 7. rule_history view — sparkline opportunity

`monitor/views.py:90–93` already fetches the last 20 results:

```python
results = rule.results.select_related('run').order_by('-checked_at')[:20]
```

`templates/monitor/rule_history.html` renders these results in a table. A sparkline could be added above the history table in this view with no additional queries — the `results` queryset slice already provides the data. This is a secondary placement (the change note says "show in rules table and history view").

## Code References

- `monitor/models.py:206–229` — `RuleResult` model with `status`, `row_count`, `last_record_age_hours`, `checked_at`
- `monitor/views.py:38` — `dashboard` queryset with `prefetch_related('results')`
- `monitor/views.py:41–42` — `rule_status` list initialised; loop begins iterating rules
- `monitor/views.py:44` — `rule.results.order_by('-checked_at').first()` called inside loop
- `monitor/views.py:54` — `rule_status.append({'rule': rule, 'result': last_result, 'status': status})` — no history slice included
- `monitor/views.py:56–63` — `dashboard` return with context dict (no sparkline data today)
- `monitor/views.py:91–93` — `rule_history` already slices last 20 results
- `monitor/services.py:258–262` — `row_count` set only when `min_row_count is not None` (in `_check_volume_freshness`)
- `monitor/services.py:265–277` — `last_record_age_hours` set only when `timestamp_column` is set (in `_check_volume_freshness`)
- `monitor/services.py:187–188` — custom SQL path initialises both fields to `None` and never sets them
- `templates/monitor/dashboard.html` — 8-column rules table; `colspan="8"` no-results row
- `templates/monitor/rule_history.html:72` — `widthratio` age bar (existing in-template SVG-like pattern)
- `requirements.txt:6` — `django==6.1.2` (Prefetch with sliced queryset supported)

## Architecture Insights

- Project convention is thin templates: view prepares all display data, templates only render. A Python sparkline helper passed as a string fits this pattern.
- The existing `prefetch_related('results')` (no queryset limit) loads every result for every rule. Replacing it with a bounded `Prefetch(queryset=RuleResult.objects.order_by('-checked_at')[:20], to_attr='recent_results')` would both fix the current unbounded load and provide the sparkline data slice — it is an improvement, not a scope increase.
- No JS chart library is in the project (`pyproject.toml`, `requirements.txt` verified). The change requires inline SVG only.
- No custom Django template tags exist today (no `templatetags/` directory found). A pure server-side approach avoids needing to create one.
- The dashboard table filtering JS (`dashboard.html` `<script>` block) operates on `tr[data-name]` — column count changes do not affect it, only the `colspan` on the no-results row needs updating.

## Historical Context (from prior changes)

- `context/changes/ui-glass-command/plan.md:20` — "No backend changes — no new view context variables for trend badges; KPI trend pills are omitted from the build." This explicitly deferred trend data from that change, confirming the current absence of sparkline data in the context is intentional, not an oversight.
- `context/changes/s02-rule-history/change.md` — rule history was a dedicated slice; it added `rule_history` view and template, which is where the last 20 results already live.

## Related Research

- `context/changes/ui-glass-command/research.md` — UI patterns for the glass dashboard; trend badges were scoped out.
- `context/changes/schedule-dashboard/research.md` — schedule dashboard; no sparkline work.

## Open Questions

1. **Sparkline placement on mobile**: the dashboard table is `overflow-x:auto` on small screens. A sparkline column adds ~100px. No explicit mobile breakpoint decision was found for showing/hiding the sparkline column. The plan should decide whether to hide it with `display:none` below a breakpoint.
2. **Status-dot fallback for custom SQL rules**: when all 20 results have `row_count=None` and `last_record_age_hours=None` (custom SQL rules), what to render — status-dot sequence, or nothing. The change note does not explicitly address this case.
3. **Colour per point vs colour per line**: the change note says "Color: green when OK, red when FAIL" but does not specify whether the stroke color changes per segment (complex SVG) or is a single colour (last result status). This is a product decision.
