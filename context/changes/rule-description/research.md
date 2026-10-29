---
change_id: rule-description
last_updated: 2026-10-28
last_updated_by: 10x-research
last_updated_note: initial research pass
---

# Research — rule-description

## Research questions

1. Rule model current fields — where does `description` fit?
2. Which templates show rule info (dashboard, history, emails, Slack)?
3. Form widget for description (textarea)?
4. Migration number needed?

---

## Finding 1 — Rule model fields (no description yet)

Source: `monitor/models.py` lines 73–185

`Rule` currently has these fields (in declaration order):

| Field | Type | blank/null |
|---|---|---|
| `name` | CharField(200) | — |
| `schema_name` | CharField(100) | blank=True |
| `table_name` | CharField(100) | blank=True |
| `user` | ForeignKey | required |
| `connection` | ForeignKey | null=True, blank=True |
| `rule_type` | CharField choices | — |
| `custom_sql` | TextField | blank=True |
| `timestamp_column` | CharField(100) | blank=True |
| `max_age_hours` | PositiveIntegerField | null=True, blank=True |
| `min_row_count` | PositiveIntegerField | null=True, blank=True |
| `schedule_type` | CharField choices | — |
| `schedule_cron` | CharField(100) | blank=True |
| `notify_on_fail` | BooleanField | default=False |
| `last_notified_at` | DateTimeField | null=True, blank=True |
| `notify_slack` | BooleanField | default=False |
| `last_slack_notified_at` | DateTimeField | null=True, blank=True |
| `created_at` | DateTimeField auto_now_add | — |
| `updated_at` | DateTimeField auto_now | — |

**No `description` field exists on `Rule` today.**

Reference pattern: `Connection.description` is `CharField(max_length=500, blank=True)` at `models.py:26`. For `Rule.description` the change specifies a `TextField(blank=True)`, which is correct — `TextField` has no length cap and suits a human-readable multi-line note.

The new field must be placed logically after `name` (the adjacent identity field) and before `schema_name`.

---

## Finding 2 — Templates that show rule info

### 2a. Dashboard (`templates/monitor/dashboard.html`)

Rule table columns: Rule (name as link), Source (connection badge), Table, Conditions, Schedule, Status, Measured values, Actions.

`description` is not shown anywhere in this template. The rule name cell (`rule-link`) is the natural candidate for a truncated secondary line: place `description` as a small muted `<div>` below the rule name link inside the `<td>`.

Each `<tr>` carries `data-name="{{ item.rule.name|lower }}"` for the JS filter. No `data-description` attribute is present. The filter-bar searches `data-name` only.

### 2b. Rule history (`templates/monitor/rule_history.html`)

The `rule-meta-card` div (lines 52–72) shows: `rule.name` (`.rule-meta-name`), `rule.schema_name.rule.table_name` (`.rule-meta-table`), and condition chips (`.cond-chips`). `description` is not shown. The natural placement is a `<div>` between `.rule-meta-table` and `.cond-chips`.

### 2c. Email — `fail_notification.txt` (`templates/monitor/email/fail_notification.txt`)

Fields shown: `rule.name`, `result.status`, `result.checked_at`, table or "Custom SQL", optional `row_count`, optional `last_record_age_hours`, optional `error_message`. No description. If `description` is non-empty, a new "Note:" line after "Rule:" is the natural insertion point.

### 2d. Email — `fail_notification.html` (`templates/monitor/email/fail_notification.html`)

Details table rows: Table or Rule type, optional Row count, optional Record age, optional Error. The rule name is in the `<h1>`. No description. If non-empty, a "Note" row can be appended to the details table before Error.

### 2e. Email — `digest_notification.txt` (`templates/monitor/email/digest_notification.txt`)

Per-result block shows: `result.rule.name`, status, table or "Custom SQL", optional row_count, optional age, optional error_message. No description.

### 2f. Email — `digest_notification.html` (`templates/monitor/email/digest_notification.html`)

Rule column in the failure table shows `result.rule.name`. No description. The Rule column cell is the candidate for a small italicised secondary line.

### 2g. Slack Block Kit (`monitor/slack_service.py`)

Section fields: Rule name, Status, Measured, Threshold. If `description` is non-empty, a fifth field "Note" can be appended to the `fields` list.

### 2h. `rule_form.html` — create / edit form (`templates/monitor/rule_form.html`)

Current "Rule identity" section shows only `name` then `connection`. No description widget. The description textarea belongs between the `name` field block (`mb-3`, lines 147–152) and the `connection` field block (`mb-4`, lines 154–158).

---

## Finding 3 — Form widget

`RuleForm.Meta.fields` at `forms.py:49`:

```python
fields = ['name', 'schema_name', 'table_name', 'connection', 'rule_type',
          'custom_sql', 'timestamp_column', 'max_age_hours', 'min_row_count',
          'schedule_type', 'schedule_cron', 'notify_on_fail', 'notify_slack']
```

`description` is absent from this list. It must be added (after `name`) and a widget entry added to `Meta.widgets`. Appropriate widget:

```python
'description': forms.Textarea(attrs={
    'class': 'form-control',
    'rows': 3,
    'placeholder': 'Optional note explaining why this rule exists',
}),
```

`Textarea` with `rows=3` matches the project pattern for short-to-medium text (`custom_sql` uses `rows=5`; `description` is a shorter note). No existing widget entry needs editing.

`ConnectionForm` uses `TextInput` for its `description` (single-line); `Rule.description` should use `Textarea` given it's a `TextField` and the intent is a multi-sentence note.

---

## Finding 4 — Migration number

Migrations directory: `monitor/migrations/`

Files 0001 through 0017 exist; the latest is `0017_apikey.py`.

**Next migration number: `0018`.**

Suggested name: `0018_rule_description.py`.

The migration must add a single `TextField(blank=True, default='')` column. `default=''` allows a non-interactive migration on existing rows; it can be removed from the model field after migration if desired (Django will set `default=''` implicitly for blank=True TextFields).

---

## Finding 5 — Test factory compatibility

`make_rule()` factory at `tests.py:27–34`:

```python
def make_rule(name='test_rule', schema='public', table='orders',
              min_rows=None, ts_col=None, max_age=None,
              rule_type='volume_freshness', custom_sql='',
              connection=None, user=None):
    return Rule.objects.create(
        ...
    )
```

The factory does not pass `description` and does not set it. After adding `description = TextField(blank=True, default='')`, existing factory calls continue to work unchanged — Django will use the default. No existing tests need modification for the field addition itself.

---

## Display surface summary

| Surface | File | Currently shows description? | Recommended action |
|---|---|---|---|
| Dashboard rule row | `templates/monitor/dashboard.html` | No | Muted secondary line below rule name (truncated ~80 chars), conditional on non-empty |
| Rule history header | `templates/monitor/rule_history.html` | No | `<div>` between table name and cond-chips, conditional |
| Email fail (txt) | `templates/monitor/email/fail_notification.txt` | No | "Note:" line after "Rule:", conditional |
| Email fail (HTML) | `templates/monitor/email/fail_notification.html` | No | Extra table row, conditional |
| Email digest (txt) | `templates/monitor/email/digest_notification.txt` | No | Indented note line per result, conditional |
| Email digest (HTML) | `templates/monitor/email/digest_notification.html` | No | Small secondary line in Rule cell, conditional |
| Slack Block Kit | `monitor/slack_service.py` | No | Fifth field in section.fields, conditional |
| Rule form | `templates/monitor/rule_form.html` | No | Textarea between name and connection fields |

All display additions should guard with `{% if rule.description %}` (or equivalent Python `if rule.description`) to avoid introducing empty labels.

---

## Open questions / unresolved

None — the four research questions are fully resolved with source anchors. Display scope (which surfaces to update) is a product decision for the plan phase.
