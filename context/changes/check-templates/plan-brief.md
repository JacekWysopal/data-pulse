# Built-in Rule Check Templates — Plan Brief

> Full plan: `context/changes/check-templates/plan.md`
> Research: `context/changes/check-templates/research.md`

## What & Why

Add a template gallery to the Custom SQL rule form so users can pick one of 8 pre-built SQL patterns (null_check, uniqueness, not_negative, future_date, referential_integrity, completeness_rate, row_count_equals, pattern_match), fill in a short parameter form, and apply the generated SELECT statement into the custom_sql field with one click. This removes the need to know SQL syntax for common data quality checks.

## Starting Point

The Custom SQL tab (`#custom-sql-section`, rule_form.html:181–194) and its textarea already exist from the S-06 custom-sql-rule change. The form validation pipeline in `services.py` and `forms.py` accepts any SELECT that starts with `SELECT` and contains no DML/DDL keywords — all 8 templates satisfy these constraints unchanged.

## Desired End State

When a user opens the Custom SQL tab, a "Templates" section appears above the SQL textarea with 8 clickable cards in a horizontal strip. Selecting a card reveals parameter inputs; clicking Apply writes the rendered SELECT into the textarea. A GET `/api/templates/` endpoint backs the gallery. The templates are defined in `monitor/check_templates.py` — no database changes are required.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Template storage | Python dict in `monitor/check_templates.py` | Static product config; no runtime add/remove needed, no migration overhead, consistent with `ScheduleType` choices precedent in models.py | Research |
| Template count | 8 templates | Covers all templates named in change.md | Plan |
| API endpoint | GET `/api/templates/` returns JSON catalog | Decouples gallery JS from server render; consistent with existing schema AJAX endpoints | Decisions |
| UI pattern | Inline panel inside `#custom-sql-section` | No modal infrastructure exists; follows progressive-disclosure pattern already used by schema browser and cron presets | Research |
| Provider detection | `data-providers` JSON attr on `#id_connection` `<select>` | Single attribute avoids per-option attrs; lets gallery JS pick `!~` vs `REGEXP` for `pattern_match` without extra AJAX | Plan |
| SQL generation | Client-side JS string interpolation | Server-side generation would require POST round-trip; client has all needed data after template fetch | Decisions |
| referential_integrity params | 4 plain text inputs | Simpler to ship; table browser reuse is a future enhancement | Decisions |
| completeness_rate threshold | Plain number input | Consistent with existing `min_row_count` / `max_age_hours` inputs | Decisions |

## Scope

**In scope:**
- `monitor/check_templates.py` — catalog dict + `generate_sql()` function
- `monitor/views.py` — `api_templates` AJAX view
- `monitor/urls.py` — `api/templates/` route
- `monitor/forms.py` — `data-providers` attr on connection `<select>`
- `templates/monitor/rule_form.html` — gallery panel CSS, HTML, and JS
- `monitor/tests.py` — unit + integration tests for templates and endpoint

**Out of scope:**
- DB model or migration for templates
- User-created templates
- Modal overlay
- Table/column browser dropdowns in template parameter sub-form
- Changes to `services.py`, `forms.py` validation logic, or any model

## Architecture / Approach

`monitor/check_templates.py` defines a `TEMPLATES` list (8 dicts) and a `generate_sql(id, params, provider)` function. The `api_templates` view returns this list as JSON. On page load the gallery JS fetches `/api/templates/`, renders 8 cards, and listens for card clicks. On Apply, it interpolates param values into the provider-appropriate SQL string (picked using `data-providers` on the connection `<select>`), writes the result into `#id_custom_sql`, and fires `dp:setType` to activate the Custom SQL tab. All changes are additive; existing form logic is untouched.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. check_templates.py + AJAX endpoint | `check_templates.py` module with 8 templates, `api_templates` view, URL registered | SQL template strings must satisfy `SQL_ALLOWED` / `SQL_FORBIDDEN` constraints |
| 2. rule_form.html gallery UI | Scrollable card gallery, parameter sub-form, Apply button, client-side SQL rendering | `setType` encapsulation requires custom-event bridge; `pattern_match` needs correct provider detection |
| 3. Tests | Unit tests for all 8 `generate_sql` outputs × 2 providers; endpoint auth + shape tests | None; all code is pure Python / DOM |

**Prerequisites:** S-06 custom SQL rule type is merged and deployed (already done per roadmap M-02 closed).
**Estimated effort:** ~2–3 focused sessions across 3 phases.

## Open Risks & Assumptions

- `pattern_match` uses `!~` (PostgreSQL regex negation) for the PostgreSQL variant. If a PostgreSQL connection does not support `!~` (e.g. a very old version), the SQL will fail at runtime. Mitigation: add a comment in the generated SQL noting the operator.
- The `data-providers` approach requires that `Connection.provider` is set correctly for all existing connections. If a connection has a blank provider, the gallery falls back to `postgresql` SQL.
- `referential_integrity` with cross-schema FKs may need `schema.table` format in both child and parent params — plain text inputs support this but do not validate.

## Success Criteria (Summary)

- All 8 template cards appear in the Custom SQL section of the rule form
- Applying any template fills the textarea with a valid SELECT that the existing validation pipeline accepts and the rule executor runs without error
- `python manage.py test monitor` passes with no regressions
