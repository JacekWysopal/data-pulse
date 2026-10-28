---
change_id: alert-digest
title: Alert digest — group notifications, avoid alert fatigue
researcher: kiro-worker
research_date: 2026-10-28
last_updated: 2026-10-28
last_updated_by: kiro-worker
last_updated_note: initial research
status: partial
---

## Research question

What is needed to implement alert digest — one grouped email per run instead of
one email per failed rule? Specifically:

1. How does current `email_service.py` send notifications?
2. Where does `run_all_checks` / `run_checks_for_user` end — where to hook digest sending?
3. What user-preference model is needed (existing profile vs. new model)?
4. Which fields to include per failed rule in the digest table?
5. How does the digest interact with the existing per-rule cooldown?

---

## 1. Current email_service.py — one email per rule

**File:** `monitor/email_service.py`

`send_fail_notification(rule, result)` is the only public function. It sends one
`EmailMultiAlternatives` per call. It enforces three guards:

- `rule.notify_on_fail` must be `True` (`email_service.py:19`)
- `rule.user` must have a non-blank `.email` (`email_service.py:23`)
- `rule.last_notified_at` must be `None` or older than `COOLDOWN_HOURS = 1`
  (`email_service.py:27–29`)

On send it stamps `Rule.last_notified_at` via a direct `Rule.objects.filter(pk=…).update(…)`
to avoid triggering `auto_now` on `updated_at` (`email_service.py:50–51`).

Templates are rendered from:
- `templates/monitor/email/fail_notification.txt`
- `templates/monitor/email/fail_notification.html`

Both templates receive `{'rule': rule, 'result': result}` — a single rule + single result pair.

---

## 2. Call sites — where per-rule notification fires

`send_fail_notification` is called in 3 places in `monitor/services.py`, all after
`RuleResult.objects.create(...)`:

| Function | Caller lines | Condition |
|---|---|---|
| `run_single_rule` | multiple branches | `result.status in (FAIL, ERROR)` |
| `run_checks_for_user` | ~line 260 area | `db_result.status in (FAIL, ERROR)` |
| `run_all_checks` | ~line 310 area | `db_result.status in (FAIL, ERROR)` |

Each `send_fail_notification` is called immediately inside the `for rule in rules` loop.

**Hook point for digest:** `run_checks_for_user` and `run_all_checks` both end with:

```python
run.finished_at = timezone.now()
run.save()
return run
```

This is the natural seam. After the loop finishes but before `return run`, collect
all non-OK results from the completed run and dispatch a single digest email per user.

For `run_single_rule` the digest concept does not apply — it is a one-rule check and
per-rule notification is correct there regardless of the user's preference.

---

## 3. User preference model — no existing profile

**Current `Rule` model** (`monitor/models.py`) has two notification fields:
- `notify_on_fail: BooleanField` (default `False`) — per-rule opt-in (`models.py:~112`)
- `last_notified_at: DateTimeField` (null, blank) — per-rule cooldown timestamp (`models.py:~117`)

**There is no `UserProfile` model.** Django's built-in `auth.User` is used directly.
The auth model does not have a notification-mode field.

**Options for storing per-user `notification_mode`:**

Option A — Add `notification_mode` to a new `UserProfile` model (one-to-one with `auth.User`).
- Clean separation; standard Django pattern.
- Requires a new model + migration.
- Requires a UI settings page or admin form to let the user choose.

Option B — Add `notification_mode` as a field on an existing model shared per user.
- No existing per-user settings model exists; this would require creating one anyway.

Option C — Default all users to `digest` mode with no per-user toggle for MVP.
- No new model or migration for the preference itself.
- Simplest to ship; loses the per-user flexibility the change notes describe.

The change notes say "Options per user: immediate (per rule) or digest (one message per run)",
which implies Option A is the intended path. This is an **unresolved product decision** —
the choice between a full `UserProfile` model vs. a simpler approach must be confirmed
before planning.

---

## 4. Digest format — fields available per failed rule

`RuleResult` stores these fields (`monitor/models.py:RuleResult`):
- `rule` (FK → `Rule`) — name, schema_name, table_name, rule_type
- `status` — `FAIL` or `ERROR`
- `row_count` — `PositiveIntegerField`, nullable
- `last_record_age_hours` — `FloatField`, nullable
- `error_message` — `TextField`, blank=True
- `checked_at` — `DateTimeField`

From `Rule` via FK:
- `rule.name`
- `rule.schema_name` / `rule.table_name` (blank for custom SQL rules)
- `rule.rule_type` — `volume_freshness` or `custom_sql`

The change notes ask for: "a table of all failures with measured values."
Recommended digest table columns (drawn from available fields):

| Column | Source field |
|---|---|
| Rule | `result.rule.name` |
| Status | `result.status` |
| Table | `rule.schema_name`.`rule.table_name` or "Custom SQL" |
| Row count | `result.row_count` (if not None) |
| Record age (h) | `result.last_record_age_hours` (if not None) |
| Error | `result.error_message` (if non-blank) |

For runs with 10+ failures the change notes say: send a summary line
"8 rules FAILED, 2 ERROR — see dashboard" instead of the full table.
`CheckRun.fail_count` and `CheckRun.error_count` properties exist on `CheckRun`
(`models.py:CheckRun`) to supply those counts without re-querying.

---

## 5. Cooldown interaction — digest vs. per-rule cooldown

The existing cooldown is stored on `Rule.last_notified_at` and checked inside
`send_fail_notification`. It is designed for per-rule, per-email throttling.

For digest mode this per-rule cooldown has conflicting semantics:
- If a digest is sent, should each rule's `last_notified_at` be stamped?
  - If yes: the 1-hour cooldown suppresses rules from appearing in the *next* digest
    even if they are still failing — this may be desirable anti-fatigue behavior.
  - If no: `last_notified_at` remains stale/unused for digest users.

A `run_digest_notification(run, results, user)` function will bypass
`send_fail_notification` entirely and call Django's mail directly, similar to
how `send_fail_notification` does, but accepting a list of `(rule, result)` pairs.
It must decide whether to stamp `last_notified_at` on each rule, or introduce a
new `last_digest_sent_at` on the `CheckRun` or `UserProfile`.

**Unresolved:** Should digest mode stamp `Rule.last_notified_at` to preserve
the 1-hour anti-fatigue window, or track cooldown at the run/user level?

The change notes do not specify. This is a **second unresolved product decision**.

---

## 6. Identified gaps before planning

| # | Gap | Impact |
|---|---|---|
| G-01 | Per-user `notification_mode` storage — `UserProfile` model vs. simpler approach | Blocks migration and settings UI design |
| G-02 | Digest cooldown semantics — stamp `Rule.last_notified_at` or new cooldown field | Affects migration scope |
| G-03 | Threshold for summary mode (change notes say "10+") — confirmed? | Minor; can default to 10 |
| G-04 | `run_digest_notification` placement — new function in `email_service.py` or separate module | Minor; email_service.py is the natural home |

---

## Summary of resolved facts

- `send_fail_notification` fires inside the `for rule in rules` loop in both
  `run_all_checks` (`services.py`) and `run_checks_for_user` (`services.py`).
- The digest hook is the block immediately before `run.finished_at = timezone.now()` in
  both functions — inspected at `services.py:run_all_checks` and `services.py:run_checks_for_user`.
- No existing user preference model exists; Django's `auth.User` has no notification mode.
- All data needed for a per-rule digest row is available in `RuleResult` + `Rule`.
- `CheckRun.fail_count` and `CheckRun.error_count` are available for the summary threshold.
- Current per-rule cooldown is stored on `Rule.last_notified_at` and is incompatible
  with digest semantics without a decision on whether to reuse or replace it.
- The 1-hour cooldown constant `COOLDOWN_HOURS = 1` is defined in `email_service.py:12`.
- Email is sent via `EmailMultiAlternatives` using Django's email backend configured in
  `settings.py` (`EMAIL_BACKEND` env var, defaults to `console.EmailBackend`).
- Digest email templates will need to be created (none exist yet);
  the existing `fail_notification.{html,txt}` templates serve only single-rule sends.
