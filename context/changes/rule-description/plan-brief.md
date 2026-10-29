# Rule Description Field — Plan Brief

> Full plan: `context/changes/rule-description/plan.md`
> Research: `context/changes/rule-description/research.md`

## What & Why

Add an optional `description` field to the `Rule` model so teams can record *why* a rule exists alongside its technical configuration. Rules today have a name, table target, and conditions, but no free-text explanation — teams working with many rules lose institutional context about intent.

## Starting Point

`Rule` has no `description` field (`monitor/models.py`). The latest migration is `0017_apikey.py`. `RuleForm` renders 13 fields; `description` is absent. No display surface currently shows a rule note.

## Desired End State

A `description` textarea appears on the rule create/edit form below the Rule name. The dashboard shows a muted secondary line (truncated at 80 chars) under each rule name when set. The rule-history header card shows the full description between the table name and condition chips. Fail and digest email bodies and Slack Block Kit messages include the description when non-empty.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Field type | `TextField(blank=True, max_length=500)` | `TextField` allows multi-sentence notes; 500-char cap enforced at form level | Plan |
| Placement in model | After `name`, before `schema_name` | Logically groups description with rule identity, matches `Connection.description` precedent | Research |
| Dashboard display | Muted `<div>` below rule-name link, truncated at 80 chars | Keeps the table scannable; full text available on history page | Plan |
| History display | Full description between `.rule-meta-table` and `.cond-chips` | History page is single-rule context; truncation unnecessary | Plan |
| Email subject | No change to subject | Description is a body-level annotation, not a classification signal | Plan |
| Email body | Conditional "Note:" line in fail + digest (txt and HTML) | Follows existing conditional pattern for row_count / error_message | Research |
| Slack | Fifth `fields` entry "Note" in section block, conditional | Block Kit allows up to 10 fields; matches existing field list pattern | Research |
| Form widget | `Textarea(rows=3)` | `TextField` → `Textarea`; `rows=3` is shorter than `custom_sql` (5 rows) since description is a brief note | Research |
| Migration number | `0018_rule_description` | Latest existing migration is `0017_apikey.py` | Research |
| Dashboard filter | No change to `data-name` / JS filter | Description is contextual, not an operational filter dimension | Plan |

## Scope

**In scope:**
- `Rule.description` model field + migration `0018`
- `RuleForm` textarea widget
- Dashboard: muted secondary line under rule name (truncated at 80 chars)
- Rule history: description line in header card
- Fail email (txt + HTML): "Note:" body line when non-empty
- Digest email (txt + HTML): "Note:" body line per result when non-empty
- Slack: "Note" Block Kit field when non-empty
- Tests: model, form, dashboard view, email/Slack notification coverage

**Out of scope:**
- Description in email/Slack subject lines
- Description in dashboard search/filter
- Tooltip on hover in dashboard (decided against; secondary line chosen instead)
- Changes to `make_rule()` factory (blank default makes it backward-compatible)

## Architecture / Approach

A single new `TextField` on `Rule`, propagated outward through the form layer and then into all display/notification surfaces. Each phase is independently deployable: the model+migration goes first (unblocks all others), then the form (create/edit), then UI surfaces, then notifications, then tests. All display additions guard on `{% if rule.description %}` / `if rule.description:` to avoid empty labels on existing rules.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Model + Migration | `Rule.description` column in DB via `0018` | Migration must include `default=''` for non-interactive run on existing rows |
| 2. Form Widget | Textarea on create/edit rule page | `RuleForm.Meta.fields` list order must put `description` after `name` |
| 3. Dashboard + History | Muted secondary line (dashboard) and header text (history) | Truncation filter applied correctly; no JS filter regression |
| 4. Notifications | "Note:" in email bodies; "Note" field in Slack payload | All conditional on non-empty; existing tests must not break |
| 5. Tests | Unit + integration coverage for all new behaviour | At least 8 new tests; no regressions |

**Prerequisites:** Phase 1 must complete before any other phase (field must exist before it can be read).
**Estimated effort:** ~1–2 sessions across 5 phases; no external dependencies.

## Open Risks & Assumptions

- `max_length=500` on a `TextField` is enforced by Django form validation, not at the DB level (PostgreSQL `text` type is unbounded). Existing data entered outside the form is not length-constrained. This is acceptable given the internal tool context.
- Slack Block Kit `section.fields` has a 10-item limit; currently 4 items, so adding 1 is safe.
- The digest email template uses `{% for result in failing_results %}`; `result.rule.description` is accessible via the existing `select_related`/queryset path in `services.py` — no queryset change needed.

## Success Criteria (Summary)

- A rule with a description shows its note in the form, dashboard, history page, failure email, digest email, and Slack message.
- A rule without a description shows no empty label or blank line on any surface.
- All existing tests pass; at least 8 new tests added and green.
