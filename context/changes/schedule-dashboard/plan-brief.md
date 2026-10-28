# Schedule Dashboard — Plan Brief

> Full plan: `context/changes/schedule-dashboard/plan.md`
> Research: `context/changes/schedule-dashboard/research.md`

## What & Why

Add a dedicated `/schedule/` page showing all of a user's scheduled monitoring rules together with their next computed run time and last result. Users currently have no single view of what is scheduled and when it will next fire — they must open each rule individually.

## Starting Point

`Rule` already has `schedule_type` (7 choices) and `schedule_cron` fields, and `croniter` is installed and used by the `run_scheduled` management command. The existing dashboard lists all rules but has no schedule-centric view. No `/schedule/` URL, view, or template exists today.

## Desired End State

A logged-in user clicks "Schedule" in the sidebar and sees a table of all their rules whose `schedule_type != 'disabled'`. Each row shows the rule name, source table, schedule label, next UTC run time (computed live via croniter), last run timestamp, last run status badge, and a quick-run button. A "Disable" toggle per row POSTs to a new endpoint that flips the rule's `schedule_type` to `disabled` (or back to `preset_1x`), providing a fast pause/resume without opening the full edit form.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| PREDEFINED cron map location | Extract to `monitor/schedule_utils.py` | Shared between the management command and the new view; avoids duplicating the dict. | Plan |
| next_run computation | `croniter(cron_str, now).get_next(datetime)` per request | Stateless, no extra DB field needed; runs O(n) in Python for small rule sets. | Research |
| Toggle behaviour | `disabled` ↔ `preset_1x` only | Simple and safe; full schedule editing goes through the existing rule edit form (out of scope). | Plan |
| Template approach | New `schedule_dashboard.html` extending `base.html` | Follows the existing pattern for every other monitor page. | Research |
| Sidebar placement | After "Add rule", before "Data" section | Groups schedule with monitoring-related nav; matches nav section semantics. | Research |
| Scope: no timeline/calendar view | Deferred | Low signal from change notes; list table covers the stated need. | Plan |

## Scope

**In scope:**
- `monitor/schedule_utils.py` — `PREDEFINED` map + `resolve_cron(rule)` helper
- `schedule_dashboard` view + `toggle_schedule` POST view
- Two new URL patterns under `/schedule/`
- `templates/monitor/schedule_dashboard.html`
- "Schedule" sidebar nav item in `base.html`
- 10 new test cases in `monitor/tests.py`

**Out of scope:**
- Calendar / timeline visualisation
- Bulk enable/disable
- In-page cron expression editor
- Pagination
- WebSocket / live refresh of next-run times
- New model fields or migrations

## Architecture / Approach

`schedule_utils.py` centralises the cron-string resolution logic (used by both the existing management command and the new view). The view queries `Rule` objects filtered by `user` and `schedule_type != disabled`, prefetches `results` in one query, computes `next_run` in Python with croniter, and passes `rule_rows` to the template. The toggle view is a thin POST handler that does a single `update_fields=['schedule_type']` save and redirects back.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. View + URL | `schedule_dashboard` + `toggle_schedule` views, 2 new URL patterns | croniter import / resolve_cron edge cases with blank custom_cron |
| 2. Template | `schedule_dashboard.html` — table, badges, quick-run, toggle buttons | Dark-theme CSS class consistency with existing dashboard |
| 3. Sidebar | "Schedule" link + clock icon in `base.html` | Active-state condition must match `schedule_dashboard` url_name exactly |
| 4. Tests | 10 new test cases covering auth, toggle, cron math | Existing test suite must stay green |

**Prerequisites:** No migrations, no new dependencies. `croniter==6.2.4` already in `requirements.txt`. All changes are additive.

**Estimated effort:** ~1–2 sessions across 4 small phases.

## Open Risks & Assumptions

- Custom-cron rules with a blank `schedule_cron` will show "—" for next run (handled gracefully via `resolve_cron` returning `None`).
- Toggle re-enables to `preset_1x` regardless of the original schedule; users wanting a different schedule must use the edit form. This is an intentional simplification.
- `croniter` is called once per scheduled rule per page load; with < 200 rules this is negligible.

## Success Criteria (Summary)

- `/schedule/` returns 200 for authenticated users and lists all rules with `schedule_type != 'disabled'`, showing a correctly computed next-run UTC time.
- Toggle POST flips `schedule_type` between `disabled` and `preset_1x` and redirects correctly; attempting it on another user's rule returns 404.
- All 10 new test cases pass alongside the existing test suite.
