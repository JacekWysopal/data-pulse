---
date: 2026-10-28T00:00:00+00:00
researcher: worker-subagent
git_commit: 991d6ae
branch: dev
repository: data-pulse
topic: "Rule severity — critical/warning/info levels affecting badge color and notifications"
tags: [research, codebase, monitor, Rule, notifications, dashboard, migrations]
status: complete
last_updated: 2026-10-28
last_updated_by: worker-subagent
---

# Research: Rule severity — critical/warning/info levels affecting badge color and notifications

**Date**: 2026-10-28  
**Researcher**: worker-subagent  
**Git Commit**: 991d6ae  
**Branch**: dev  
**Repository**: data-pulse

## Research Question

Where and how to add `Rule.severity` (critical/warning/info, default: critical) to the model, what notification routing to change, how dashboard badges map severity to CSS, and what migration number to use.

## Summary

The `Rule` model (`monitor/models.py`) has no severity field today. The `TextChoices` pattern is already used on the same model (for `RuleType` and `ScheduleType`), so adding `Severity` follows the established pattern exactly. The last migration is `0017_apikey.py`, so the new migration is `0018_rule_severity.py`. Notification routing passes through a single coordinator `notify_rule_result` (`email_service.py:137`) which calls both email and Slack senders; each sender already has a `notify_on_fail` / `notify_slack` flag guard as the first check. Severity routing is best added at the `notify_rule_result` level. The WARNING consecutive-failure requirement (notify only after 3 failures) has no existing counter — it requires a new `Rule` field or an inline query of recent `RuleResult` records. Dashboard badges use CSS classes `dp-badge-{ok,fail,error,never}` defined in `base.html:486-493`; CSS variables `--ok` (green), `--fail` (red), `--error` (amber) already exist but no blue variable or `dp-badge-info` class exists for INFO severity — both need adding. The severity badge is an attribute of the rule, not the check result; it sits alongside the status badge on each rule row.

## Detailed Findings

### 1. Rule model — adding severity CharField

The `Rule` class in `monitor/models.py` currently defines two inner `TextChoices` enums: `RuleType` (`models.py:87-90`) and `ScheduleType` (`models.py:131-139`). Neither is `Severity`.

The pattern to follow:

```python
class Severity(models.TextChoices):
    CRITICAL = 'critical', 'Critical'
    WARNING  = 'warning',  'Warning'
    INFO     = 'info',     'Info'

severity = models.CharField(
    max_length=20,
    choices=Severity.choices,
    default=Severity.CRITICAL,
    verbose_name='Severity',
)
```

This is consistent with how `ScheduleType` is declared at `models.py:131-139` and its corresponding field at `models.py:141-147`. No other field currently on `Rule` carries severity semantics.

The `CheckConstraint` at `models.py:172-180` covers conditions (freshness/volume/custom_sql) and does not need updating for a new optional enum field with a default.

### 2. Notification routing — where to add severity logic

All rule-result notifications flow through a single call site: `notify_rule_result(rule, result)` in `email_service.py:137-149`. It calls `send_fail_notification` (email) and `send_slack_notification` (Slack) and returns `{'email': bool, 'slack': bool}`.

`notify_rule_result` is called from `services.py` at 12 locations (lines 374, 385, 400, 408, 416, 448, 463, 484, 499, 549, 567, 591) — all conditioned on `result.status in (FAIL, ERROR)`. The call in `run_single_rule` (`services.py:373-374`) is representative; all callers follow the same guard pattern.

**Severity routing to add at `notify_rule_result` (`email_service.py:137`):**

| Severity | Current behavior | Required change |
|----------|-----------------|-----------------|
| `critical` | Send immediately on FAIL/ERROR | No change needed |
| `warning`  | (not yet implemented) | Send only after 3 consecutive FAIL/ERROR results |
| `info`     | (not yet implemented) | Never notify — early-return False for both channels |

The INFO case is the simplest: add a guard `if rule.severity == 'info': return {'email': False, 'slack': False}` at the top of `notify_rule_result`.

The WARNING consecutive-failure requirement requires knowing how many consecutive FAIL/ERROR results the rule has accumulated. **No such counter exists today.** Two implementation options:

- **Option A — new `Rule` field** `consecutive_fail_count = PositiveIntegerField(default=0)`. Increment on each FAIL/ERROR result, reset on OK. Checked against threshold 3 in `notify_rule_result`. Requires including it in the migration.
- **Option B — inline query** at `notify_rule_result` time: query the last 3 `RuleResult` records for the rule ordered by `checked_at DESC` and check if all 3 are FAIL/ERROR. No new model field needed, but adds a DB query per notification decision.

This is an open product decision (see Open Questions). The plan must resolve it before implementation.

Both `send_fail_notification` (`email_service.py:25`) and `send_slack_notification` (`slack_service.py:29`) already start with flag guards (`notify_on_fail`, `notify_slack`). Severity routing should sit in `notify_rule_result` before those calls, not inside the individual senders, to keep the senders single-responsibility.

The digest path (`send_digest_notification`, `email_service.py:81`) does not check severity today. Failing results are collected at `services.py:446-501` (immediate mode gates on `notify_rule_result`; digest mode collects into `failing_results` list for `send_digest_notification` at `services.py:518`). Digest severity filtering would need to happen where results are added to `failing_results` (lines 450, 465, 486, 501).

### 3. Dashboard badge colors — severity-to-CSS mapping

The badge system in `base.html:480-493` defines:

```
.dp-badge-ok    — color: var(--ok)    = #22c55e (green)
.dp-badge-fail  — color: var(--fail)  = #f87171 (red)
.dp-badge-error — color: var(--error) = #fbbf24 (amber)
.dp-badge-never — color: var(--text-muted) (grey)
```

CSS variables at `base.html:38-47`: `--ok` (#22c55e), `--fail` (#f87171), `--error` (#fbbf24). **No blue variable or info variant exists.**

Severity-to-badge-class mapping required:

| Severity | Badge color | CSS var needed | CSS class needed |
|----------|-------------|----------------|-----------------|
| `critical` | Red | `--fail` (exists) | `dp-badge-severity-critical` |
| `warning`  | Amber | `--error` (exists) | `dp-badge-severity-warning` |
| `info`     | Blue | `--info` (new) | `dp-badge-severity-info` |

The severity badge is a *rule* attribute displayed on each row of the rule table in `templates/monitor/dashboard.html:424-480`. The existing status badge (`dp-badge-ok/fail/error/never`) at `dashboard.html:474-480` remains unchanged — it reflects the check result, not the rule's severity. Severity badge will be a second badge on the same row.

Adding `--info` and `--info-dim` to `base.html` (inside the `:root {}` block, near `--error-dim` at line 47) is the minimal change. The `dp-badge-severity-*` classes can be defined inline in `base.html` next to the existing `dp-badge-*` block.

### 4. Form — RuleForm must include severity

`forms.py:57-59` lists `RuleForm.Meta.fields`. The new `severity` field must be added to that list. Widget: `forms.Select(attrs={'class': 'form-select'})`. No custom validation needed — Django's `CharField(choices=...)` handles the choice constraint.

`rule_form.html` renders the Notifications section at the bottom of the form. A "Severity" section can be added before or within Notifications, as it directly affects notification behavior.

### 5. Migration number

Inspected migration files in `monitor/migrations/`:

- The last migration in the directory (by number prefix) is `0017_apikey.py`, which has dependency `('monitor', '0016_ruleresult_sample_rows')`.
- The new migration file must be named **`0018_rule_severity.py`** with dependency `('monitor', '0017_apikey')`.

## Code References

- `monitor/models.py:87-90` — `Rule.RuleType` TextChoices (pattern to follow for Severity)
- `monitor/models.py:131-147` — `Rule.ScheduleType` TextChoices + field declaration (pattern)
- `monitor/models.py:172-180` — `CheckConstraint` (not affected by severity addition)
- `email_service.py:137-149` — `notify_rule_result` coordinator — primary routing insertion point
- `email_service.py:25-79` — `send_fail_notification` — flag guard at line 29
- `slack_service.py:29-38` — `send_slack_notification` — flag guard at line 29
- `monitor/services.py:373-374` — representative `notify_rule_result` call site (FAIL/ERROR guard)
- `monitor/services.py:446-501` — digest mode failure collection (12 call sites total in services.py)
- `monitor/forms.py:57-59` — `RuleForm.Meta.fields` list
- `templates/base.html:38-47` — CSS variable declarations (--ok, --fail, --error, missing --info)
- `templates/base.html:480-493` — `dp-badge-*` class definitions
- `templates/monitor/dashboard.html:474-480` — status badges on rule rows
- `monitor/migrations/0017_apikey.py` — last migration; new migration is `0018_rule_severity.py`

## Architecture Insights

1. The model follows `TextChoices` inner-class pattern consistently; `Severity` is the third such enum on `Rule`.
2. All notification dispatch is centralised in `notify_rule_result`; the individual senders (`send_fail_notification`, `send_slack_notification`) check their own flags independently. Severity is correctly inserted at the coordinator level.
3. The CSS badge system is a flat `.dp-badge-{variant}` class per variant. Severity badges for the rule row are a parallel concept to the result-status badges and should use a distinct naming convention (e.g. `dp-badge-severity-*`) to avoid confusion.
4. No consecutive-failure counter exists anywhere in the current codebase (confirmed by full search across `monitor/` Python files).

## Historical Context (from prior changes)

No prior changes found in `context/changes/` or `context/archive/` relating to severity, notification routing, or badge colors.

## Related Research

None.

## Open Questions

1. **WARNING consecutive-failure strategy** — Option A (new `Rule.consecutive_fail_count` field, reset on OK, increment on FAIL/ERROR) vs Option B (inline query of last 3 RuleResults). Option A is testable and avoids repeated DB queries; Option B avoids schema change. Plan must choose before implementation.

2. **Severity badge placement on rule row** — Before or after the result-status badge? Before the name, or in a dedicated column? Dashboard table layout is at `dashboard.html:424-480`.

3. **Digest mode + severity** — Should INFO rules be excluded from the digest `failing_results` list (consistent with "no notification") or included in the digest but not in immediate mode? Recommend exclusion for consistency; plan must confirm.
