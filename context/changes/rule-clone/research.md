---
date: 2026-10-29T00:00:00+00:00
researcher: kiro-worker
git_commit: 991d6ae9346728d5feecfd56d8cac6ddd7888da6
branch: dev
repository: data-pulse
topic: "Rule clone — fields to copy/reset, view pattern, dashboard button placement, name truncation"
tags: [research, codebase, rule, clone, views, dashboard, models]
status: complete
last_updated: 2026-10-29
last_updated_by: kiro-worker
---

# Research: Rule clone — fields to copy/reset, view pattern, dashboard button placement, name truncation

**Date**: 2026-10-29  
**Researcher**: kiro-worker  
**Git Commit**: 991d6ae9346728d5feecfd56d8cac6ddd7888da6  
**Branch**: dev  
**Repository**: data-pulse

## Research Question

For the `rule-clone` change:
1. Which Rule fields should be copied vs reset in a clone operation?
2. What view pattern fits a `POST /rules/{id}/clone/` → redirect to edit?
3. Where in the dashboard table actions column should the Clone button be inserted?
4. How should the "Copy of X" name be truncated to respect `max_length=200`?

## Summary

All four questions are resolved with high confidence from inspected source files. The Rule model has 2 timestamp fields that must be reset (`last_notified_at`, `last_slack_notified_at`), `pk`/`created_at`/`updated_at` are auto-reset by Django on a new instance, and all other content fields should be copied verbatim. The view pattern follows the existing `@login_required` + `@require_POST` + `get_object_or_404(Rule, pk=rule_id, user=request.user)` convention already used for `run_single` and `toggle_schedule`. The Clone button inserts between Run and Edit in the actions cell at `dashboard.html:514–515`. The `name` field has `max_length=200`; prefix `"Copy of "` is 8 characters, leaving 192 characters for the truncated original name.

## Detailed Findings

### 1. Fields to copy vs reset

Inspected `monitor/models.py:84–239`.

**Rule fields (all must be handled explicitly on clone):**

| Field | Type | Copy or Reset | Reason |
|---|---|---|---|
| `name` | CharField(200) | Copy (with prefix) | User identity; rename to "Copy of X" |
| `schema_name` | CharField(100) | Copy | Target table definition |
| `table_name` | CharField(100) | Copy | Target table definition |
| `connection` | ForeignKey | Copy | Same DB connection |
| `rule_type` | CharField(30) | Copy | Same check logic type |
| `custom_sql` | TextField | Copy | Same SQL |
| `timestamp_column` | CharField(100) | Copy | Same freshness condition |
| `max_age_hours` | PositiveIntegerField | Copy | Same freshness condition |
| `min_row_count` | PositiveIntegerField | Copy | Same volume condition |
| `schedule_type` | CharField(20) | **Reset to `'disabled'`** | Clone note in change.md states "reset schedule" |
| `schedule_cron` | CharField(100) | **Reset to `''`** | Paired with `schedule_type`; cron has no meaning when disabled |
| `notify_on_fail` | BooleanField | Copy | User notification preference should carry over |
| `notify_slack` | BooleanField | Copy | User notification preference should carry over |
| `last_notified_at` | DateTimeField(null) | **Reset to `None`** | Runtime state, not rule definition |
| `last_slack_notified_at` | DateTimeField(null) | **Reset to `None`** | Runtime state, not rule definition |
| `user` | ForeignKey | Set to `request.user` | Ownership — always the cloning user |
| `pk` / `id` | Auto | Auto-reset | Django assigns new PK on `instance.pk = None; instance.save()` |
| `created_at` / `updated_at` | auto_now_add / auto_now | Auto-reset | Django sets these on save |

Source: `monitor/models.py:168–188` for `last_notified_at` and `last_slack_notified_at`; `monitor/models.py:154–165` for `schedule_type`/`schedule_cron`; `monitor/models.py:91` for `name` max_length=200.

**Fields not on Rule that are irrelevant to clone:** `RuleResult`, `CheckRun`, `dbt_integrations` M2M — these belong to the original rule's history and should not be copied.

### 2. View pattern — POST /rules/{id}/clone/

Inspected `monitor/views.py` and `monitor/urls.py`.

The closest existing pattern for a state-mutating action that does not show its own form is `run_single` (`monitor/views.py:80–91`) and `toggle_schedule` (`monitor/views.py:222–231`). Both use:

```python
@login_required
@require_POST
def <action>(request, rule_id):
    rule = get_object_or_404(Rule, pk=rule_id, user=request.user)
    ...
    return redirect('monitor:dashboard')  # or 'monitor:rule_edit'
```

For `rule_clone`, the redirect target should be `rule_edit` on the new rule (so user can review and save), not `dashboard`. This matches the change.md note: "redirects to edit form pre-filled".

URL pattern follows the existing Rule action path structure (`monitor/urls.py:12–15`):

```python
path('rules/<int:rule_id>/clone/', views.rule_clone, name='rule_clone'),
```

The view creates the clone in-process (no async needed), sets `pk = None` to force INSERT, assigns `user = request.user`, then calls `instance.save()`. No new form is required — redirect to `rule_edit` URL serves as the "pre-filled edit".

### 3. Dashboard button placement

Inspected `templates/monitor/dashboard.html:506–516`.

Current actions cell (lines 506–517):

```html
<td class="actions-cell">
  <div style="display:flex;gap:4px;justify-content:flex-end;align-items:center">
    <form method="post" action="{% url 'monitor:run_single' item.rule.pk %}" style="margin:0">
      {% csrf_token %}
      <button ...>▶ Run</button>        <!-- line 510 -->
    </form>
    <a href="{% url 'monitor:rule_edit' item.rule.pk %}" ...>Edit</a>   <!-- line 514 -->
    <a href="{% url 'monitor:rule_delete' item.rule.pk %}" ...>Delete</a> <!-- line 515 -->
  </div>
</td>
```

The Clone button should be inserted **between the Edit and Delete links** (after line 514, before line 515). This follows the logical ordering: non-destructive actions (Run, Clone, Edit) before the destructive action (Delete). Clone uses a `<form method="post">` with CSRF token, matching the Run button pattern, because the clone operation is a POST.

Clone button styling should match the Edit button: `class="btn-dp btn-dp-ghost btn-dp-xs"`.

### 4. "Copy of X" name truncation

Inspected `monitor/models.py:91`: `name = models.CharField(max_length=200)`.

- Prefix `"Copy of "` is exactly 8 characters.
- Available characters for the original name: 200 − 8 = 192.
- Truncation strategy: `"Copy of " + original_name[:192]`
- This is safe for all original names: a name at max_length (200 chars) is truncated to 192 chars; shorter names are not affected.
- No ellipsis is needed unless explicitly requested; plain truncation avoids adding characters.
- Example: original `"A" * 200` → clone name = `"Copy of " + "A" * 192` = 200 chars.
- Example: original `"orders check"` (13 chars) → clone name = `"Copy of orders check"` = 21 chars.

## Code References

- `monitor/models.py:91` — `name = models.CharField(max_length=200)`
- `monitor/models.py:154–165` — `schedule_type` and `schedule_cron` fields
- `monitor/models.py:168–188` — `last_notified_at` and `last_slack_notified_at` fields
- `monitor/views.py:80–91` — `run_single` view (closest pattern for POST action)
- `monitor/views.py:222–231` — `toggle_schedule` view (second POST-only action pattern)
- `monitor/urls.py:11–15` — existing Rule URL patterns
- `templates/monitor/dashboard.html:506–516` — actions cell with Run/Edit/Delete buttons

## Architecture Insights

- All POST-only, login-required views on rules follow the same `@login_required` + `@require_POST` + `get_object_or_404(Rule, pk=rule_id, user=request.user)` guard chain. The clone view must follow this pattern for ownership isolation.
- Django's pattern for copying a model instance is: load original, set `pk = None`, set `_state.adding = True` (optional but explicit), mutate fields, call `save()`. No form needed for the clone itself.
- The `user` field must always be set explicitly to `request.user` so multi-user isolation is preserved — the same guard used by every other rule view.
- The existing action buttons are rendered inside an `actions-cell` `<td>` that uses `opacity:0` on the row with CSS hover reveal (`dashboard.html:148–149`). The new Clone button must live inside that same `<div>` to participate in the hover behaviour.
- `schedule_type` defaults to `'disabled'` in the model (`monitor/models.py:158`). Resetting to `'disabled'` on clone matches the model default, avoiding accidental scheduled execution of a newly-cloned rule.

## Historical Context (from prior changes)

No prior changes found in `context/changes/` or `context/archive/` related to rule cloning.

## Related Research

No related research artifacts found.

## Open Questions

None. All four research questions are resolved with source-backed evidence.
