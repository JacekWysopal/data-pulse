# Clone Rule — Implementation Plan

## Overview

Add a one-click "Clone" action to each rule row in the dashboard. A POST request to `/rules/{id}/clone/` creates a copy of the rule (with the name prefixed "Copy of …"), resets runtime/schedule fields, and redirects the user to the rule edit form pre-filled with the clone so they can review and save.

## Current State Analysis

- Rules are managed via CRUD views in `monitor/views.py` following a consistent `@login_required` + `get_object_or_404(Rule, pk=rule_id, user=request.user)` ownership guard.
- POST-only, non-form actions (e.g., `run_single`, `toggle_schedule`) use `@require_POST` and redirect after mutating state — no separate form needed.
- The dashboard actions cell (`templates/monitor/dashboard.html:506–516`) renders Run / Edit / Delete buttons inside a `<div style="display:flex;gap:4px;…">` wrapper.
- `Rule.name` has `max_length=200` (`monitor/models.py:91`).
- `last_notified_at` and `last_slack_notified_at` are nullable runtime-state fields (`monitor/models.py:168–188`).
- `schedule_type` defaults to `'disabled'` and `schedule_cron` stores the cron string (`monitor/models.py:154–165`).
- No `consecutive_fails` field exists on the model; the reset requirement is a no-op.
- URL patterns for rules follow `rules/<int:rule_id>/action/` (`monitor/urls.py:11–15`).
- Test suite lives in `monitor/tests.py` with `TestCase` classes; fixtures use `make_rule()` and `make_connection()` helpers.

### Key Discoveries

- `monitor/views.py:80–91` — `run_single` is the closest pattern: `@login_required`, method check, `get_object_or_404(Rule, pk=rule_id, user=request.user)`, message, redirect.
- `monitor/views.py:222–231` — `toggle_schedule` adds `@require_POST` decorator on top of the same pattern.
- `templates/monitor/dashboard.html:514–515` — Clone button inserts between Edit and Delete links.
- `monitor/models.py:91` — `name = models.CharField(max_length=200)`. Prefix `"Copy of "` = 8 chars, so original name is truncated at 190 chars to keep the combined name ≤ 200 chars (per approved decision, slightly more conservative than the 192-char research finding).
- Django instance copy idiom: load instance, set `pk = None`, set `_state.adding = True`, mutate fields, `save()`.

## Desired End State

A green "copy" icon button appears between Edit and Delete on every rule row. Clicking it submits a POST to `/rules/{id}/clone/`, creates a copy with `"Copy of {name}"` as the name (truncated to 190 chars if the original name is long), resets schedule to disabled, clears notification timestamps, and redirects to the rule edit page with a success flash message. Ownership is strictly enforced — a user can only clone their own rules.

### Key Discoveries

- Rule fields explicitly reset on clone: `name` (prefixed), `schedule_type` → `'disabled'`, `schedule_cron` → `''`, `last_notified_at` → `None`, `last_slack_notified_at` → `None`, `user` → `request.user`. Django auto-resets `pk`, `created_at`, `updated_at`.
- All other content fields (schema, table, connection, rule_type, custom_sql, timestamps, counts, notify flags) are copied verbatim.

## What We're NOT Doing

- No async/background processing — clone is synchronous and in-process.
- No clone of `RuleResult`, `CheckRun`, or `DbtIntegration` M2M relationships — history stays with the original.
- No separate "clone confirmation" form — POST → redirect to edit is the UX.
- No changes to the Rule model schema.
- No schedule copying — new clone always starts disabled.

## Implementation Approach

Three-phase delivery: (1) backend view + URL, (2) dashboard clone button, (3) tests. This order lets each phase be independently verified.

The view follows the existing `@login_required` + `@require_POST` + `get_object_or_404` guard chain. The Django copy idiom (`pk = None; _state.adding = True; save()`) avoids any form processing for the clone itself.

---

## Phase 1: Clone view + URL

### Overview

Register `POST /rules/<int:rule_id>/clone/` and implement `rule_clone` view that creates the copy and redirects to `rule_edit`.

### Changes Required

#### 1. `rule_clone` view

**File**: `monitor/views.py`

**Intent**: Add a POST-only view that loads the original rule (enforcing ownership), deep-copies its content fields with the standard Django copy idiom, applies the approved resets, and redirects to `rule_edit` for the new clone.

**Contract**:
- Decorated with `@login_required` and `@require_POST`.
- `get_object_or_404(Rule, pk=rule_id, user=request.user)` for ownership guard.
- Name: `"Copy of " + original.name[:190]`.
- Reset: `schedule_type = 'disabled'`, `schedule_cron = ''`, `last_notified_at = None`, `last_slack_notified_at = None`.
- Copy: all other content fields verbatim (schema_name, table_name, connection, rule_type, custom_sql, timestamp_column, max_age_hours, min_row_count, notify_on_fail, notify_slack).
- `rule.pk = None; rule._state.adding = True; rule.user = request.user; rule.save()`.
- On success: `messages.success(request, f'Rule "{rule.name}" cloned.')`, then `redirect('monitor:rule_edit', rule.pk)`.
- Place the function in the `# ── Rules ──` section of `views.py`, after `rule_delete`.

#### 2. URL registration

**File**: `monitor/urls.py`

**Intent**: Expose the clone action at a URL consistent with the existing rule action pattern.

**Contract**: Add `path('rules/<int:rule_id>/clone/', views.rule_clone, name='rule_clone')` to `urlpatterns`, after the `rule_delete` entry.

### Success Criteria

#### Automated Verification

- `python manage.py check` passes with no errors
- Existing test suite passes: `python manage.py test monitor`

#### Manual Verification

- `POST /rules/1/clone/` (authenticated, own rule) → 302 redirect to `/rules/<new_id>/edit/` with success message.
- `POST /rules/1/clone/` (unauthenticated) → redirect to login.
- `POST /rules/1/clone/` (other user's rule) → 404.
- GET to `/rules/1/clone/` → 405 Method Not Allowed.

---

## Phase 2: Dashboard clone button

### Overview

Add a green copy-icon `<form method="post">` button between the Edit and Delete links in the dashboard actions cell.

### Changes Required

#### 1. Clone button in actions cell

**File**: `templates/monitor/dashboard.html`

**Intent**: Insert a clone button after the Edit link and before the Delete link in the actions cell flex container. The button posts to `monitor:rule_clone` and uses the same `btn-dp btn-dp-ghost btn-dp-xs` styling as Edit, with a green accent to signal "safe copy" and a copy SVG icon.

**Contract**:
- A `<form method="post" action="{% url 'monitor:rule_clone' item.rule.pk %}" style="margin:0">` containing `{% csrf_token %}` and the submit button.
- Button class: `btn-dp btn-dp-ghost btn-dp-xs`.
- Green accent via `style="color:var(--ok);border-color:rgba(34,197,94,0.25)"` (same pattern as the Run button).
- Icon: SVG copy icon (two overlapping rectangles), `width="11" height="11"`.
- `title="Clone this rule"`.
- Inserted between the `<a … >Edit</a>` line and the `<a … >Delete</a>` line.

### Success Criteria

#### Automated Verification

- `python manage.py test monitor` passes

#### Manual Verification

- Clone button appears in each rule row between Edit and Delete.
- Button has green tint.
- Hovering shows tooltip "Clone this rule".
- Clicking clones the rule and lands on the edit form with the success message.
- Page renders without JS errors.

---

## Phase 3: Tests

### Overview

Add `RuleCloneViewTest` to `monitor/tests.py` covering the key access control, field-copy, and redirect behaviours.

### Changes Required

#### 1. `RuleCloneViewTest` class

**File**: `monitor/tests.py`

**Intent**: Cover the happy path, ownership enforcement, method enforcement, and field correctness of the clone view.

**Contract**: Add a `TestCase` class at the end of the file with these tests:

- `test_clone_creates_new_rule` — POST as owner, verify `Rule.objects.count()` increases by 1 and new rule name starts with `"Copy of "`.
- `test_clone_redirects_to_edit` — POST as owner, verify response redirects to `rule_edit` URL of the new rule.
- `test_clone_success_message` — POST as owner, verify flash message contains `"cloned"`.
- `test_clone_resets_schedule` — POST as owner, verify new rule's `schedule_type == 'disabled'` and `schedule_cron == ''`.
- `test_clone_resets_notification_timestamps` — POST as owner, verify `last_notified_at is None` and `last_slack_notified_at is None`.
- `test_clone_copies_content_fields` — POST as owner, verify `schema_name`, `table_name`, `rule_type` match original.
- `test_clone_get_not_allowed` — GET request → 405.
- `test_clone_requires_login` — unauthenticated POST → redirect to login.
- `test_clone_other_user_rule_returns_404` — POST as different user → 404.
- `test_clone_name_truncated_for_long_name` — original name 200 chars → clone name is ≤ 200 chars and starts with `"Copy of "`.

### Success Criteria

#### Automated Verification

- All new tests pass: `python manage.py test monitor.tests.RuleCloneViewTest`
- Full test suite still passes: `python manage.py test monitor`

#### Manual Verification

- Test output shows 10 passing tests in `RuleCloneViewTest`.

---

## Testing Strategy

### Unit Tests

- Ownership guard: other user's rule returns 404.
- Method guard: GET returns 405.
- Auth guard: unauthenticated POST redirects to login.
- Field correctness: copied fields match, reset fields are cleared.
- Name prefix and truncation edge case (200-char original).

### Integration Tests

- End-to-end clone → redirect → edit form visible with new rule ID.

### Manual Testing Steps

1. Log in, navigate to dashboard, click Clone on any rule.
2. Verify redirect to edit form, success message visible, rule name starts with "Copy of".
3. Verify the original rule is unchanged (still present with original name).
4. Test with a rule whose name is exactly 200 characters — confirm clone name is ≤ 200 chars.
5. Log out, attempt direct POST to `/rules/1/clone/` — verify redirect to login.

## Performance Considerations

Cloning is a single read + single write on a small model. No performance concerns.

## Migration Notes

No model changes. No migration needed.

## References

- Research: `context/changes/rule-clone/research.md`
- Pattern reference — `run_single`: `monitor/views.py:80–91`
- Pattern reference — `toggle_schedule`: `monitor/views.py:222–231`
- Dashboard actions cell: `templates/monitor/dashboard.html:506–516`
- Rule model fields: `monitor/models.py:84–239`
- URL patterns: `monitor/urls.py:11–15`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Clone view + URL

#### Automated

- [x] 1.1 `python manage.py check` passes with no errors
- [x] 1.2 Existing test suite passes: `python manage.py test monitor`

#### Manual

- [ ] 1.3 POST own rule → 302 redirect to rule_edit with success message
- [ ] 1.4 POST unauthenticated → redirect to login
- [ ] 1.5 POST other user's rule → 404
- [ ] 1.6 GET /rules/1/clone/ → 405

### Phase 2: Dashboard clone button

#### Automated

- [x] 2.1 `python manage.py test monitor` passes

#### Manual

- [ ] 2.2 Clone button appears between Edit and Delete with green tint
- [ ] 2.3 Clicking clones rule and lands on edit form with success message
- [ ] 2.4 Page renders without JS errors

### Phase 3: Tests

#### Automated

- [x] 3.1 All new tests pass: `python manage.py test monitor.tests.RuleCloneViewTest`
- [x] 3.2 Full test suite passes: `python manage.py test monitor`

#### Manual

- [ ] 3.3 Test output shows 10 passing tests in RuleCloneViewTest
