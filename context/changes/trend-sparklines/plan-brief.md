# Trend Sparklines — Plan Brief

> Full plan: `context/changes/trend-sparklines/plan.md`
> Research: `context/changes/trend-sparklines/research.md`

## What & Why

Add a visual trend indicator to the rules dashboard table and the rule history page.
Each rule gets a strip of 20 coloured dots (green = OK, red = FAIL, amber = ERROR) showing
its last 20 check results at a glance — so users can spot deteriorating rules without opening
every history drill-down.

## Starting Point

The dashboard currently shows only the single latest status badge per rule.
`RuleResult` has `status`, `row_count`, `last_record_age_hours`, and `checked_at` on every row,
but the dashboard view passes only the most recent result to the template — no history slice.
The `rule_history` view already fetches the last 20 results; a sparkline there needs only
SVG generation and a template change.

## Desired End State

- Dashboard rules table: new "Trend" column (9th) with an inline 120 × 16 px SVG of 20 coloured
  dots, one per recent result, oldest left to newest right.
- Rule history header card: same sparkline strip alongside condition chips.
- Zero N+1 regression: a single bounded `Prefetch` (max 20 results per rule) replaces the
  current unbounded `prefetch_related('results')`.
- Pure-Python `monitor/sparkline.py` helper — no JS library, no template tags.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| What to show in sparkline | Status sequence (OK/FAIL/ERROR dots) | Numeric fields (row_count, age) are null for all custom SQL rules; status is always present | Plan |
| SVG generation location | Server-side Python (`monitor/sparkline.py`) | Matches thin-template convention; pure function is testable; no Django template tags needed | Research / Plan |
| Dot strip size | 120 × 16 px, 20 dots, 6 px diameter | Fits table cell without wrapping; matches existing UI density | Plan |
| Colour per dot | Per-result status colour (not latest-result stroke) | Shows trend at each point; otherwise a mixed history looks misleadingly uniform | Plan |
| History slice approach | `Prefetch(queryset=RuleResult.objects.order_by('-checked_at')[:20], to_attr='recent_results')` | Replaces unbounded prefetch, eliminates N+1, loads ≤20 rows per rule in one extra query | Research / Plan |
| rule_history sparkline | Reuse already-fetched 20-result slice, add `sparkline_svg` to context | Zero extra queries; data already available | Research / Plan |
| Mobile layout | No column hide — table is already `overflow-x:auto` | Avoids breakpoint complexity; horizontal scroll is already the fallback | Plan |
| Numeric sparklines (row_count/age) | Out of scope | Null for custom SQL rules; separate change when the data-availability gap is addressed | Plan |

## Scope

**In scope:**
- `monitor/sparkline.py` — new pure-function module
- `monitor/views.py` — dashboard view (bounded Prefetch, loop, sparkline_svg) + rule_history view (sparkline_svg)
- `templates/monitor/dashboard.html` — Trend column header + cell + colspan fix
- `templates/monitor/rule_history.html` — sparkline in meta card
- `monitor/tests.py` — unit + integration tests

**Out of scope:**
- Row-count or age-over-time numeric charts
- Mobile hide/show of Trend column
- Django template tags
- Any JS chart library
- Sparklines in schedule dashboard or any other view

## Architecture / Approach

`status_dot_sparkline(statuses: list[str], width=120, height=16) -> str` lives in
`monitor/sparkline.py`. The dashboard view replaces `prefetch_related('results')` with a
bounded `Prefetch` storing `rule.recent_results` (list, ≤20, newest-first), reverses it to
oldest-first, calls the helper, and passes `sparkline_svg` (a `mark_safe` string) per rule.
The rule_history view does the same with its already-existing `[:20]` slice. Templates emit
`{{ item.sparkline_svg }}` inside a `<td>` / card div — pure rendering, no logic.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Dashboard View Update | Bounded Prefetch + sparkline_svg in context | Import error until Phase 2 module exists — implement Phase 2 first or commit both together |
| 2. SVG Generation Helper | `monitor/sparkline.py` pure function | mark_safe usage requires confirming no user-controlled data reaches SVG |
| 3. Template Updates | Trend column in dashboard + strip in history header | colspan must be updated to 9 to avoid broken no-results row |
| 4. Tests | Unit + integration test coverage | Test DB uses SQLite — Prefetch behaviour identical |

**Prerequisites:** None — no model migrations, no new dependencies.
**Estimated effort:** ~1 session across 4 small phases (each phase ~15-30 min).

## Open Risks & Assumptions

- `mark_safe` is safe here because `status_dot_sparkline` only interpolates values from a
  closed set (`'OK'`, `'FAIL'`, `'ERROR'`, or grey for unknowns) — no user-controlled strings
  reach the SVG markup. If `RuleResult.status` were ever extended to store arbitrary strings
  this assumption would need revisiting.
- Phase 1 and Phase 2 must be deployed together (or Phase 2 committed first) — the import
  in `views.py` will raise `ImportError` at request time until `sparkline.py` exists.

## Success Criteria (Summary)

- Dashboard table shows coloured dots for each rule with history; no dots replaced by dash for
  rules with no results.
- Rule history header shows the same strip with no extra database queries.
- `python manage.py test monitor` passes with all new test methods green.
