# Rule Severity (critical/warning/info) — Plan Brief

> Full plan: `context/changes/rule-severity/plan.md`
> Research: `context/changes/rule-severity/research.md`

## What & Why

Add a `severity` field to the `Rule` model with three levels — critical, warning, and info — that gates dashboard badge color and notification routing. The motivation is alert fatigue: today every failing rule notifies immediately, with no way to mark a rule as "informational only" or to delay noisy low-priority alerts until they accumulate.

## Starting Point

`Rule` has no severity field today. All FAIL/ERROR results route through `notify_rule_result` (`email_service.py:137`) which calls both email and Slack senders unconditionally (subject to per-rule flags and a 1-hour cooldown). Dashboard badges show only the check result status (OK/FAIL/ERROR/No data) with no severity indicator.

## Desired End State

Every rule carries a severity level visible as a color-coded badge on the dashboard. Creating or editing a rule exposes a severity dropdown. INFO rules never generate notifications; WARNING rules hold back until 3 consecutive failures accumulate; CRITICAL rules behave exactly as today.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Severity levels | critical / warning / info (default: critical) | Matches common monitoring conventions; default critical preserves existing behavior | Plan |
| WARNING consecutive-fail strategy | New `Rule.consecutive_fails` IntegerField (default 0) | Avoids extra DB query per notification decision; testable with simple counter assertions | Plan |
| WARNING threshold | 3 consecutive FAIL/ERROR | Pre-approved product decision | Plan |
| Counter placement | `_update_consecutive_fails` helper in services.py, called at every result-save site | Centralises counter logic; keeps `notify_rule_result` a pure in-memory decision | Plan |
| Routing insertion point | `notify_rule_result` in `email_service.py` | Single coordinator for all outbound notifications; individual senders stay single-responsibility | Research |
| Severity badge position | Before the result-status badge in the same `<td>` | Severity is a rule attribute, not a result attribute; keeps per-row info dense | Plan |
| Digest INFO exclusion | Exclude from `failing_results` list in services.py | Consistent with "no notification" semantics; prevents INFO results appearing in digest emails | Plan |
| CSS approach | New `dp-badge-severity-*` classes alongside existing `dp-badge-*` in base.html | Follows flat badge naming convention; avoids collision with result-status classes | Research |

## Scope

**In scope:**
- `Rule.Severity` TextChoices + `severity` CharField + `Rule.consecutive_fails` IntegerField
- Migration `0018_rule_severity.py`
- `notify_rule_result` severity routing (INFO skip, WARNING threshold, CRITICAL unchanged)
- `_update_consecutive_fails` helper + call sites in `run_single_rule` and `run_all_checks`
- INFO exclusion from digest `failing_results`
- `--info` / `--info-dim` CSS variables and `dp-badge-severity-*` CSS classes
- Severity badge on dashboard rule rows
- `severity` field + widget in `RuleForm`
- Severity selector in `rule_form.html`
- Unit tests: routing branches, counter logic, form field, model default

**Out of scope:**
- Changes to result-status badge (OK/FAIL/ERROR/No data) appearance or behavior
- Per-user configurable WARNING threshold
- Severity filtering on API layer
- Backfill migration for `consecutive_fails`
- Slack message content changes

## Architecture / Approach

Four layers touched in dependency order:

1. **Model/migration** — new fields on `Rule`, no data migration needed (defaults cover existing rows).
2. **Notification routing** — severity guard at the top of `notify_rule_result`; counter update at every result-save site in `services.py`.
3. **Dashboard presentation** — CSS variables + classes in `base.html`; severity badge in `dashboard.html` before the status badge.
4. **Form** — `severity` in `RuleForm.Meta.fields` + widget; severity section in `rule_form.html` above Notifications.

The INFO path short-circuits in `notify_rule_result` before any sender is called. The WARNING path reads `rule.consecutive_fails` (already in memory after `refresh_from_db`) and defers if < 3. CRITICAL is a no-op change to the existing code path.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Model + Migration | `Rule.severity` and `Rule.consecutive_fails` fields; migration `0018` | Migration conflicts if another branch added fields after `0017` |
| 2. Notification Routing | Severity-gated `notify_rule_result`; counter increment/reset at 12 services.py sites | Missing a result-save site leaves counter out-of-sync |
| 3. Dashboard Badge | CSS variables + severity badge classes; severity badge on rule rows | Blue `--info` color contrast on dark theme |
| 4. Form Widget | Severity dropdown in rule create/edit form | None — pure form field addition |
| 5. Tests | 8 unit tests covering routing, counter, form, model default | Test isolation for DB counter (use `Rule.objects.create` not `Rule()`) |

**Prerequisites:** Django migrations up to `0017_apikey` applied; existing test suite green on `dev` branch.
**Estimated effort:** ~2–3 focused sessions across 5 phases.

## Open Risks & Assumptions

- The 12 `notify_rule_result` call sites in `services.py` were counted from `grep` output; a missed site would leave counter-reset logic incomplete for that error path. Phase 2 implementation must verify each site individually.
- `rule.refresh_from_db(fields=['consecutive_fails'])` is needed after the `F()` increment update — if omitted, `notify_rule_result` reads a stale in-memory value and WARNING threshold check fails silently.
- No test infrastructure (`monitor/tests/`) exists yet; the test module must be created from scratch following Django's `TestCase` pattern.

## Success Criteria (Summary)

- `python manage.py migrate` applies `0018_rule_severity` cleanly; `python manage.py test monitor` passes all existing and new tests.
- Dashboard shows a color-coded severity badge on every rule row.
- INFO rules generate zero notifications; WARNING rules notify only on the 3rd consecutive failure; CRITICAL behavior is unchanged.
