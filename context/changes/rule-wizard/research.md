---
date: 2026-10-29T12:40:00+01:00
researcher: worker-agent
git_commit: 991d6ae9346728d5feecfd56d8cac6ddd7888da6
branch: dev
repository: data-pulse
topic: "Rule creation wizard — step-by-step 3-step form"
tags: [research, codebase, rule-wizard, rule_form, schema-browser, sessionStorage, django-forms]
status: complete
last_updated: 2026-10-29
last_updated_by: worker-agent
last_updated_note: Initial research pass for rule-wizard change
---

# Research: Rule creation wizard — step-by-step 3-step form

**Date**: 2026-10-29T12:40:00+01:00
**Researcher**: worker-agent
**Git Commit**: 991d6ae9346728d5feecfd56d8cac6ddd7888da6
**Branch**: dev
**Repository**: data-pulse

## Research Question

Five questions scoped for the rule-wizard change (S-30, M-06):
1. Current `rule_form.html` structure — what sections exist and how are they organized?
2. Step persistence options — sessionStorage JS vs server-side session vs URL params.
3. Schema browser (S-04) already in `rule_form.html` — how should a wizard wrap it?
4. Step validation approach — client-side vs server-side per step.
5. Django form wizard vs custom JS multi-step approach.

---

## Summary

The existing `rule_form.html` is a single-page form with five logically distinct
sections — Rule Identity, Rule Type, Target Table, Monitoring Conditions, and
Schedule + Notifications. All 12 form fields are submitted to a single `POST
/rules/new/` request handled by `rule_create` in `views.py`. The `RuleForm` runs
all validation in one `clean()` pass.

The schema browser (S-04 / S-05) is fully implemented as client-side JS in the
same template, including table-list and column-list fetch calls to
`/api/schema/<conn_id>/tables/` and `/api/schema/<conn_id>/columns/<schema>/<table>/`.
It caches results in JS-local `tablesCache` and `columnsCache` objects (not
sessionStorage) and falls back gracefully to plain text inputs on error.

The four prerequisite slices for S-30 — S-25 (live preview), S-26 (description),
S-27 (severity), S-28 (tags) — are all `status: new` and have no model fields,
view handlers, or form fields yet. The wizard will need to include steps that
introduce these fields or treat them as optional extensions added later.

The lightest-weight approach for the wizard is custom JS multi-step within the
same `rule_form.html` template, using `sessionStorage` for step-state persistence.
This avoids adding new URL routes, new views, new form classes, or the heavy
`django-formtools` dependency. A single final POST to the existing `rule_create`
view keeps all server-side validation unchanged and backward-compatible.

---

## Detailed Findings

### 1 — Current rule_form.html structure

Inspected file: `templates/monitor/rule_form.html`.

The template extends `base.html` and uses `{% block content %}` and
`{% block extra_scripts %}`. It renders one `<form method="post" id="rule-form">` with
the following **five logical sections**, separated by `.form-section-label` dividers:

| # | Section header | Fields / elements |
|---|---|---|
| 1 | Rule identity | `name`, `connection` |
| 2 | Rule type | `rule_type` radio (hidden), two `.rule-type-tab` buttons |
| 3 | Target table (inside `#vf-section`) | `schema_name`, `table_name` + table browser (`#table-browser`) |
| 4 | Monitoring conditions (inside `#vf-section`) | `min_row_count`, `timestamp_column` + column browser, `max_age_hours` |
| 5 | Schedule | `schedule_type`, `schedule_cron`, preset quick-fill buttons |
| 6 | Notifications | `notify_on_fail`, `notify_slack` |

The `#custom-sql-section` (hidden unless rule_type=custom_sql) contains:
- Template gallery (`#tpl-gallery`) — fetches `/api/templates/` on activation
- `custom_sql` textarea

**Key CSS constructs**: `.form-card` (max-width 580px), `.rule-type-tabs`, `.schema-browser`,
`.tpl-gallery`. All styles are inlined in `{% block extra_head %}`.

**Key JS IIFE blocks** (in `{% block extra_scripts %}`):
- Rule-type toggle — switches `#custom-sql-section` / `#vf-section` visibility, syncs hidden radio.
- Schema browser — fetches tables on `change` of `#id_connection`, loads columns on table click.
- Schedule type toggle — shows/hides `#custom-cron-row` and `#preset-buttons`.
- Template gallery — fetches `/api/templates/`, renders cards and parameter sub-form.

Source: `templates/monitor/rule_form.html` (full file, no offset required).

---

### 2 — Step persistence options

Three candidate approaches for persisting wizard state across steps:

#### A — sessionStorage (JS-only, client-side)

State (field values + current step index) stored under one key (e.g.
`dp_wizard_rule`) in `window.sessionStorage`. Cleared on final submit or Cancel.

Pros:
- Zero new backend work. No new view, URL, or session key touches the server.
- Survives F5 refresh within the same tab; lost on tab close (acceptable for a
  creation form).
- Fully compatible with the existing single-POST flow to `rule_create`.

Cons:
- Storage is per-origin; if the user opens a second tab, state is shared — but for
  a wizard this is low risk.
- Must serialize/deserialize form field values manually.

#### B — Server-side Django session

Each "Next" click posts partial data to a server endpoint that stores it in
`request.session`. Final submit assembles the complete payload.

Pros: state survives across devices (same session cookie).
Cons: requires 3–4 new AJAX-POST views, CSRF tokens per step, and raises partial-
validation questions. The existing `RuleForm.clean()` expects all fields in one pass;
splitting across multiple partial POSTs would require either 3 separate form
classes or a reimplemented clean pipeline.

#### C — URL / query params

Step is encoded as `?step=2&...` or via URL segment.

Pros: bookmarkable steps.
Cons: URL gets very long, sensitive values (DB URLs) must not be in the URL.
Requires either page reloads or `history.pushState` gymnastics.

**Recommendation evidence**: The change.md note explicitly says "State preserved in
sessionStorage" (`context/changes/rule-wizard/change.md`, Notes). This matches option A.
sessionStorage is the lowest-complexity path and is already directionally approved.

---

### 3 — Schema browser (S-04) in rule_form — how the wizard wraps it

The schema browser today lives inside `#vf-section`, which maps to wizard Step 1
(Select connection + browse/select table). The browser is controlled by the IIFE at
`templates/monitor/rule_form.html` (schema browser IIFE, approximately line 280–390).

Key facts about the current browser implementation:
- `loadTables(connId)` is triggered by `#id_connection` `change` event.
- `selectTable(schema, table)` populates `#id_schema_name` and `#id_table_name` inputs
  and then calls `loadColumns(connId, schema, table)`.
- Both tables and columns are cached in JS-local `tablesCache` and `columnsCache`
  objects (not sessionStorage), keyed by `connId` and `connId:schema:table`.
- On edit-mode page load (when `connSelect.value` is already set), `loadTables` is
  called immediately; `loadColumns` is deferred 600 ms (`setTimeout(..., 600)`).
- The browser gracefully shows an error element and leaves the plain text inputs
  active if the fetch fails.

For the wizard:
- Step 1 contains `#id_connection`, the schema browser, and `#id_schema_name` /
  `#id_table_name` inputs. No structural changes to the browser JS are needed; the
  wizard JS only needs to show/hide the step container.
- The `tablesCache` and `columnsCache` JS objects persist for the tab session naturally,
  so returning to Step 1 from Step 2 does not re-fetch.
- sessionStorage persistence of `connection`, `schema_name`, and `table_name` on
  "Next" restores selected table on browser back-navigation if the user reloads.

---

### 4 — Step validation: client-side vs server-side per step

The existing form validation lives entirely in `monitor/forms.py: RuleForm.clean()`
(`forms.py:96–131`) and `clean_schedule_cron()` (`forms.py:85–94`). It is a single
pass over all fields after the final POST.

For a client-side multi-step wizard the practical choices are:

#### A — Client-side only per step

Each "Next" click runs a JS validation function checking required fields for that
step (e.g. Step 1: connection selected + table filled; Step 2: rule type chosen +
at least one condition filled). No server round-trip until the final "Save rule" submit.

Pros: instant feedback, no server state, works with the existing `rule_create` view
unchanged. Final server validation via `RuleForm.clean()` remains the authoritative gate.

Cons: client-side validation can be bypassed; users can submit invalid states via
devtools. However, the server always re-validates on final submit, so data integrity
is not affected.

#### B — Per-step AJAX validation

Each "Next" posts step data to a validation endpoint that returns JSON errors.

Pros: same error messages as the final submit.
Cons: requires new endpoint(s), partial form logic, or a reshaped `RuleForm`.

**Practical finding**: The change notes say "Each step validates before next"
(`context/changes/rule-wizard/change.md`, Notes), which is satisfied by client-side
required-field checks on each step boundary. The authoritative server-side validation
at final submit remains the safety net without any new endpoints.

---

### 5 — Django form wizard vs custom JS multi-step

#### django-formtools SessionWizardView

`django-formtools` provides `SessionWizardView` (or `CookieWizardView`) which splits
a form across multiple `GET` + `POST` HTTP requests, storing partial state in the
Django session. Each step is a separate URL `GET /rules/new/?step=0` etc.

Cons for this project:
- Requires adding `django-formtools` to `requirements.txt` (new dependency, currently
  not present — inspected `requirements.txt` not read, but `forms.py:1` imports show
  only `croniter` as non-Django dep).
- Each step needs a separate `Form` class; the current `RuleForm.clean()` cross-field
  logic (freshness + volume pair validation) must be split or deferred to the final step.
- The schema browser IIFE in `rule_form.html` would need to be replicated or adapted
  per step template.
- Session storage scales to the server but adds per-step server round-trips for a
  flow that currently needs none.

#### Custom JS multi-step (in-page)

The form stays as a single `<form>` in one template. JS shows/hides step containers,
persists values to `sessionStorage` on "Next", and re-reads them on load. Final
submit is the existing `POST /rules/new/` to `rule_create`.

Pros:
- Zero new Python files, zero new URLs, zero new dependencies.
- Schema browser, template gallery, and schedule JS IIFEs remain untouched.
- The existing `RuleForm` (12 fields, one `clean()`) is the only validation path.
- Progress indicator (`<step-1> › <step-2> › <step-3>`) is pure HTML/CSS.

**Conclusion**: Custom JS multi-step is the lower-risk approach and is consistent
with how the existing rule-type toggle and schema browser are already implemented
(in-page JS IIFEs, no server round-trips for UI state). django-formtools would add
complexity without benefit at the current scale (< 200 rules per user, no cross-step
file uploads).

---

## Code References

- `templates/monitor/rule_form.html` — full single-page form; 5 logical sections,
  4 JS IIFE blocks (rule-type toggle, schema browser, schedule toggle, template gallery)
- `monitor/forms.py:59` — `RuleForm.Meta.fields` lists 12 fields:
  `['name', 'schema_name', 'table_name', 'connection', 'rule_type', 'custom_sql',
  'timestamp_column', 'max_age_hours', 'min_row_count', 'schedule_type', 'schedule_cron',
  'notify_on_fail', 'notify_slack']`
- `monitor/forms.py:85–94` — `clean_schedule_cron()` — validates custom cron expression
- `monitor/forms.py:96–131` — `RuleForm.clean()` — cross-field validation for both
  rule types in a single pass
- `monitor/views.py:88–97` — `rule_create` view — handles GET (render form) and POST
  (validate + save, redirect to dashboard)
- `monitor/urls.py:8` — `path('rules/new/', views.rule_create, name='rule_create')`
- `monitor/models.py:84–243` — `Rule` model — 12 directly-form-mapped fields; no
  `severity`, `tags`, or `description` field exists at inspected commit
  `991d6ae9346728d5feecfd56d8cac6ddd7888da6`
- `monitor/models.py:31` — `Connection.description` CharField (max_length=500) —
  distinct from the not-yet-existing `Rule.description` planned in S-26

---

## Architecture Insights

**Single-form, single-POST contract**: The current flow is
`GET /rules/new/` → render `RuleForm` → user fills → `POST /rules/new/` → validate
→ save → redirect. This contract is preserved by the custom JS multi-step approach.
Any approach that introduces multiple partial POSTs would require changes to
`rule_create` or new views.

**Schema browser is connection-triggered**: The browser only activates after
`#id_connection` fires a `change` event. In a wizard, Step 1 must include
`#id_connection` and the browser so the user can pick a table before advancing.
Step 2 (rule type and conditions) depends on `schema_name` and `table_name` being
already filled when the template gallery needs a provider value — the gallery reads
`data-providers` from `#id_connection`.

**sessionStorage key collision risk**: If two wizard sessions run in the same browser
origin (two tabs), they share `sessionStorage` under the same key. For a creation
wizard this is low risk but worth noting; using a time-stamped key or clearing on
mount reduces the chance of stale state.

**Step 3 fields (S-26, S-27, S-28 prereqs)**: The change notes list Step 3 as
"Schedule, notifications, description, severity, tags." At the inspected commit,
`Rule` has no `description`, `severity`, or `tags` fields. The wizard plan must
decide whether Step 3 includes placeholders for those fields (to be added by their
respective change IDs) or treats them as out-of-scope for the initial wizard iteration.

---

## Historical Context (from prior changes)

- `context/changes/rule-builder-ui/change.md` — S-05 rule builder UI; schema browser
  and column dropdown implemented in `rule_form.html` JS IIFEs (no separate plan.md found).
- `context/changes/check-templates/change.md` — S-19 check templates; template gallery
  IIFE added to `rule_form.html`; `/api/templates/` endpoint in `views.py`.
- `context/changes/advanced-scheduler/plan.md` — S-15 advanced scheduler; `schedule_type`
  and `schedule_cron` fields added to `Rule` and `RuleForm`; schedule-toggle IIFE added
  to `rule_form.html`.
- `context/changes/rule-severity/change.md` — S-27; status `new`, no model fields yet.
- `context/changes/rule-description/change.md` — S-26; status `new`, no model fields yet.
- `context/changes/rule-tags/change.md` — S-28; status `new`, no model fields yet.
- `context/changes/rule-live-preview/change.md` — S-25; status `new`; planned endpoint
  `POST /api/v1/rules/preview`; no implementation yet.

---

## Related Research

Not applicable — no prior `research.md` exists for wizard-related changes in
`context/changes/` as of inspected commit.

---

## Open Questions

1. **S-26/S-27/S-28 prerequisite scope**: Roadmap marks S-30 as requiring S-25, S-26,
   S-27, and S-28 as prereqs. None of those have model fields yet. The wizard plan
   must decide: (a) implement those fields first in separate changes before the wizard,
   or (b) treat Step 3 as a forward-compatible placeholder that will expand once those
   fields land. This is a product decision, not a technical one.

2. **Edit-mode wizard**: The change notes describe the wizard for "Add Rule" only. The
   existing `rule_edit` view also uses `rule_form.html` with `action='Edit rule'`.
   Should the wizard apply to edit mode as well, or only to creation? The current
   `rule_form.html` is shared by both; a wizard-only approach may need a separate
   template or a template variable to enable/disable wizard mode.

3. **Scroll position on step change**: On mobile, hiding/showing large step containers
   may leave the viewport at an unexpected scroll position. A `window.scrollTo(0,0)`
   or `element.scrollIntoView()` call on each step transition is worth planning.

4. **Live preview (S-25) in wizard Step 2**: The change notes for `rule-live-preview`
   plan a "Test query" button at `POST /api/v1/rules/preview`. If S-25 lands before
   the wizard, Step 2 should include that button. If not, it's additive.
