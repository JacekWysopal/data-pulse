# Clone Rule — Plan Brief

> Full plan: `context/changes/rule-clone/plan.md`
> Research: `context/changes/rule-clone/research.md`

## What & Why

Add a one-click "Clone" button to each rule row in the dashboard. Users can duplicate an existing rule with all content fields copied, schedule reset to disabled, and the name prefixed with "Copy of …". The motivation is to reduce friction when creating similar rules — currently users must fill in the full rule form from scratch each time.

## Starting Point

Rules are managed via `monitor/views.py` with `@login_required` + `get_object_or_404(Rule, pk=rule_id, user=request.user)` guards. The dashboard actions cell already has Run, Edit, and Delete buttons in a flex container. POST-only, non-form actions (`run_single`, `toggle_schedule`) redirect after mutation — no separate form needed.

## Desired End State

A green copy-icon button appears between Edit and Delete on every dashboard rule row. Clicking it POSTs to `/rules/{id}/clone/`, creates a copy with `"Copy of {name}"` as the name (truncated to ≤ 200 chars total), resets the schedule to disabled and notification timestamps to null, sets ownership to the cloning user, and redirects to the rule edit form pre-filled with the clone's fields. A success flash message confirms the action.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| HTTP method | POST | Mutates state; consistent with `run_single` and `toggle_schedule` patterns | Research |
| Redirect target | `rule_edit` on new clone | User must review/confirm the clone before it runs | Plan decisions |
| Fields copied | All content fields except schedule, runtime timestamps, and PK | Schedule and timestamps represent runtime state, not rule definition | Plan decisions |
| Schedule on clone | Reset to `'disabled'` | Prevents accidental scheduled execution immediately after cloning | Research |
| Name truncation | `"Copy of " + original[:190]` → max 200 chars | `max_length=200`; prefix is 8 chars; 190 is conservative per approved decision | Plan decisions |
| Ownership guard | `get_object_or_404(Rule, pk=rule_id, user=request.user)` | Consistent with every other rule action view | Research |
| Button placement | Between Edit and Delete | Non-destructive actions before destructive | Research |
| Button style | `btn-dp btn-dp-ghost btn-dp-xs` with green accent | Matches Edit; green signals "safe copy" distinct from red Delete | Plan |

## Scope

**In scope:**
- `rule_clone` view in `monitor/views.py`
- URL entry `rules/<int:rule_id>/clone/` in `monitor/urls.py`
- Clone button in `templates/monitor/dashboard.html` actions cell
- `RuleCloneViewTest` test class in `monitor/tests.py` (10 test cases)

**Out of scope:**
- No model changes or migrations
- No copy of `RuleResult`, `CheckRun`, or `DbtIntegration` M2M history
- No clone confirmation dialog
- No bulk clone

## Architecture / Approach

Pure Django views layer. The view uses the standard Django instance copy idiom (`pk = None; _state.adding = True; save()`). No new form class, no model method, no signal — the mutation is self-contained in the view. The dashboard button is a `<form method="post">` with CSRF token (same as the Run button), placed in the existing flex actions container.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Clone view + URL | Working backend: POST /rules/{id}/clone/ creates clone and redirects | Accidental copy of runtime fields — verify reset list |
| 2. Dashboard clone button | UI trigger in actions cell; completes the user-facing feature | Button must participate in CSS hover reveal (opacity:0 on row) |
| 3. Tests | `RuleCloneViewTest` with 10 cases covering access control and field correctness | Test must cover 200-char name truncation edge case |

**Prerequisites:** None — no dependency on other in-flight changes.
**Estimated effort:** ~1 session across 3 phases.

## Open Risks & Assumptions

- `consecutive_fails` field referenced in the approved decisions does not exist in the current model (`monitor/models.py`) — treated as a no-op; no code change needed.
- If `last_slack_notified_at` or `last_notified_at` ever become non-nullable in a future migration, the explicit `None` assignment in the clone view would need updating.

## Success Criteria (Summary)

- Clicking "Clone" on a rule creates a new rule with "Copy of …" name, schedule disabled, and lands the user on the edit form with a success message.
- The original rule is unchanged.
- Attempting to clone another user's rule returns 404.
