---
date: 2026-10-28T19:43:05+00:00
researcher: kiro (worker subagent)
git_commit: c2ad8dfe7dc6ab19e456ba6dab557d0808a806ad
branch: dev
repository: data-pulse
topic: "What is needed to implement built-in check templates for custom SQL rules?"
tags: [research, codebase, check-templates, rule_form, custom_sql, templates]
status: complete
last_updated: 2026-10-28
last_updated_by: kiro (worker subagent)
---

# Research: Check Templates for Custom SQL Rules

**Date**: 2026-10-28T19:43:05+00:00
**Researcher**: kiro (worker subagent)
**Git Commit**: c2ad8dfe7dc6ab19e456ba6dab557d0808a806ad
**Branch**: dev
**Repository**: data-pulse

## Research Question

What is needed to implement a built-in template gallery on rule creation, where clicking
a template pre-fills the Custom SQL field? Templates targeted: null_check, uniqueness,
referential_integrity, not_negative, future_date, pattern_match, row_count_equals,
completeness_rate.

Five sub-questions were investigated:
1. Where in `rule_form.html` does the template picker go?
2. How do templates target `Rule.custom_sql`?
3. Which templates need user-supplied parameters, and what are they?
4. Should templates be stored as a hardcoded dict in `views.py` or a separate model?
5. What UX pattern — modal/gallery or inline dropdown with preview?

---

## Summary

All five questions have code-backed answers. No external unknowns block planning.

- **Insertion point**: inside `#custom-sql-section` in `rule_form.html:181–194`, above the existing `<textarea>` for `custom_sql`.
- **Target field**: `Rule.custom_sql` (`monitor/models.py:87`), a `TextField` that receives the generated SELECT statement. The existing custom SQL validation pipeline in `services.py` (`_check_custom_sql`, lines 179–225) and `forms.py` (`clean()`, lines 79–97) will accept template-generated SQL without any changes.
- **Parameter requirements**: 7 of 8 templates need user parameters (table/column/threshold); only `row_count_equals` needs table + expected count. Full parameter map in Detailed Findings.
- **Storage decision**: hardcoded dict in a new `monitor/templates_catalog.py` module (not a DB model). No new migrations needed; no admin overhead; parameters are structural, not user-configurable data.
- **UX pattern**: inline panel that appears when the user switches to Custom SQL tab. A horizontally scrollable card row (gallery strip) is feasible within the `max-width: 580px` form card. Clicking a card opens a small parameter form beneath the gallery; "Apply" renders the SQL into the `<textarea>`. This avoids a modal overlay and keeps the flow within the existing form layout.

---

## Detailed Findings

### 1. Insertion point in rule_form.html

`templates/monitor/rule_form.html:181` begins `#custom-sql-section`, which is toggled visible when the user selects the Custom SQL tab:

```html
<!-- rule_form.html:181 -->
<div id="custom-sql-section" style="display:{% if form.rule_type.value == 'custom_sql' %}block{% else %}none{% endif %}">
  <div class="mb-4">
    <label ...>SQL query</label>
    <textarea id="id_custom_sql" name="custom_sql" ...></textarea>
    ...
  </div>
</div>
```

The template picker panel should be inserted **before** `<label ...>SQL query</label>` (rule_form.html:183), inside `#custom-sql-section`. This placement shows the gallery only when Custom SQL is active and naturally leads the user from "pick a template" → "see the generated SQL" → "edit if needed" → "save".

The existing JS toggle at `rule_form.html:338–352` already controls `#custom-sql-section` visibility via the `setType()` function; no change to that logic is needed.

### 2. Rule.custom_sql — the target field

`monitor/models.py:115–123`:
```python
custom_sql = models.TextField(
    blank=True,
    verbose_name='Custom SQL',
    help_text=(
        'SELECT query returning a single boolean-like value. '
        'true / 1 = OK, false / 0 / NULL / empty = FAIL. '
        'Must start with SELECT.'
    ),
)
```

Templates must generate SQL that:
- Starts with `SELECT` (enforced by `SQL_ALLOWED` regex, `services.py:179`)
- Does not contain INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER/CREATE/GRANT/REVOKE (enforced by `SQL_FORBIDDEN`, `services.py:182–185`)
- Returns a single boolean-like value: truthy = OK, falsy/NULL/empty = FAIL

The executor (`_check_custom_sql`, `services.py:184–225`) interprets the first column of the first row. It applies a `statement_timeout` of 30 s on PostgreSQL and `max_execution_time=30000` on MySQL (`services.py:212–214`).

All 8 planned templates can be expressed as `SELECT … AS result` queries that return a boolean or 0/1 integer satisfying these constraints. No changes to `services.py` or `forms.py` are required.

### 3. Template parameters

Each template name is from `change.md`. Parameters that are required from the user before SQL can be generated are listed per template:

| Template | Required user params | Optional params | Notes |
|---|---|---|---|
| `null_check` | `table` (schema.table), `column` | — | `SELECT COUNT(*) = 0 FROM {table} WHERE {col} IS NULL` |
| `uniqueness` | `table`, `column` | — | `SELECT COUNT(*) = COUNT(DISTINCT {col}) FROM {table}` |
| `referential_integrity` | `child_table`, `child_column`, `parent_table`, `parent_column` | — | 4 params; checks FK exists |
| `not_negative` | `table`, `column` | — | `SELECT MIN({col}) >= 0 FROM {table}` |
| `future_date` | `table`, `column` | — | `SELECT MAX({col}) <= NOW() FROM {table}` |
| `pattern_match` | `table`, `column`, `pattern` | — | `SELECT COUNT(*) = 0 FROM {table} WHERE {col} NOT SIMILAR TO '{pattern}'` |
| `row_count_equals` | `table`, `expected_count` | — | `SELECT COUNT(*) = {n} FROM {table}` |
| `completeness_rate` | `table`, `column`, `threshold` | — | threshold = minimum % non-null (0–100); `SELECT ROUND(100.0 * COUNT({col}) / NULLIF(COUNT(*),0),2) >= {threshold} FROM {table}` |

Notes on portability: `SIMILAR TO` is PostgreSQL-specific; MySQL uses `REGEXP`. Pattern_match SQL will need a provider-conditional generation or a note to the user. The current form has a `Connection` selector; the provider could be read client-side from a `data-provider` attribute on the connection `<option>` elements. However, this is a planning decision rather than a research blocker.

`referential_integrity` is the most complex (4 params). Keeping it as one template is feasible; the parameter form simply shows 4 fields.

### 4. Storage: hardcoded dict vs. DB model

**Hardcoded dict (recommended):**
- Templates are structural product features, not user data. There is no requirement to add/remove them at runtime.
- No new migration needed.
- Easy to keep in a new `monitor/templates_catalog.py` module: each entry holds `name`, `label`, `description`, `params` list, and a `generate_sql(params, provider) -> str` callable.
- Consistent with the project pattern of keeping static configuration outside the DB (e.g., `ScheduleType` choices in `models.py:102–110`, SQL validation regexes in `services.py:177–185`).

**DB model (not recommended for this feature):**
- Would require a new migration, admin registration, and either seeded fixtures or manual entry.
- No user-facing benefit (users cannot create their own templates per the change spec).
- Adds operational complexity without value at this scope.

Conclusion: hardcoded dict in `monitor/templates_catalog.py`. The dict is passed to the template context in `rule_create` and `rule_edit` views or rendered as inline JSON in `rule_form.html`.

### 5. UX: modal/gallery vs. inline panel

**Inline panel (recommended):**

The `form-card` is `max-width: 580px` (`rule_form.html:7`). A horizontal scrollable card strip fits comfortably at this width with cards ~140px wide (4 cards visible, scrollable).

Flow:
1. User clicks "Custom SQL" tab → `#custom-sql-section` reveals.
2. Template gallery strip appears at the top of the section: 8 small cards with icon + name + one-line description.
3. Clicking a card shows a compact parameter sub-form (1–4 inputs) immediately below the strip.
4. "Apply" button calls a JS `renderSQL(template, params)` function that replaces the textarea content.
5. User can edit the generated SQL freely before saving.

This avoids a modal overlay (no `z-index`/focus-trap complexity) and follows the existing pattern of in-page progressive disclosure already used for the schema browser (`rule_form.html:200–268`) and the cron preset buttons (`rule_form.html:275–284`).

**Modal/gallery (viable alternative):**
- Would allow a richer preview of each template.
- The project has no existing modal component (`grep` across all templates returns no modal pattern), so a modal would introduce new CSS/JS infrastructure.
- At 8 templates the extra complexity is not justified.

**Inline dropdown with preview (not recommended):**
- A `<select>` hides all template names from view simultaneously; discovery is poor for a first-time user.
- Preview would require dynamic injection, which is the same JS work as the panel but with a worse layout.

---

## Code References

- `templates/monitor/rule_form.html:7` — `.form-card { max-width: 580px }` — layout constraint
- `templates/monitor/rule_form.html:181–194` — `#custom-sql-section` — insertion point
- `templates/monitor/rule_form.html:338–352` — `setType()` JS toggle — no changes needed
- `monitor/models.py:115–123` — `Rule.custom_sql` field definition
- `monitor/models.py:143–154` — `ScheduleType` choices — pattern for hardcoded config
- `monitor/services.py:177–183` — `SQL_ALLOWED` / `SQL_FORBIDDEN` regexes — validation constraints templates must satisfy
- `monitor/services.py:184–225` — `_check_custom_sql()` — runtime executor; accepts template-generated SQL unchanged
- `monitor/services.py:212–214` — 30 s statement timeout applied per execution
- `monitor/forms.py:92–137` — `clean()` on `RuleForm` — SQL validation on form submit
- `monitor/views.py:98–125` — `rule_create` / `rule_edit` — context dict origin for template data
- `monitor/urls.py:11,14` — `rules/new/` and `rules/<id>/edit/` — no new URL endpoints needed

---

## Architecture Insights

- **No new URL endpoints needed.** Template SQL generation is pure client-side JS. The `apply` action writes into the existing `<textarea name="custom_sql">` and the form submits normally.
- **No new model or migration needed.** Templates are static config; a Python module suffices.
- **Provider awareness is the one open question.** The `Connection` model has a `provider` field (`postgresql` or `mysql`), and some templates (`pattern_match`) need different SQL syntax per provider. The form already renders `<select id="id_connection">` but the option elements do not carry `data-provider`. Adding `data-provider="postgresql|mysql"` to each `<option>` (rendered server-side in the form widget) would let client-side JS select the correct SQL variant. This is a small, additive change to `RuleForm`'s `connection` widget or a template filter.
- **Parameter sub-form can be rendered server-side as a JSON literal.** Encoding the templates catalog as a `<script>const TEMPLATES = {...}</script>` block in `rule_form.html` (injected from context) keeps the JS self-contained and avoids a second AJAX call.

---

## Historical Context (from prior changes)

- `context/changes/custom-sql-rule/change.md` — established `Rule.rule_type` toggle and `custom_sql` field (S-06). The tab UI and `#custom-sql-section` are already in place; templates extend this, not replace it.
- `context/changes/schema-introspection/change.md` — introduced the schema browser inside `rule_form.html` using a similar progressive-disclosure pattern (connection → table list → column list). The same JS fetch+render pattern can be reused for template parameter field rendering.
- `context/changes/advanced-scheduler/research.md` — used `croniter` for cron validation; shows precedent for adding a small utility module to `monitor/` for a focused concern.
- `context/changes/mysql-support/research.md` — documents the two-provider (`postgresql` / `mysql`) split in `services.py`. Provider-conditional SQL in templates follows the same branching already established there.

## Related Research

- `context/changes/schema-introspection/` — JS schema browser pattern reused for template panel
- `context/changes/advanced-scheduler/research.md` — utility module precedent
- `context/changes/mysql-support/research.md` — two-provider SQL branching pattern

---

## Open Questions

1. **Provider-conditional SQL for `pattern_match`**: PostgreSQL uses `SIMILAR TO` or `~`; MySQL uses `REGEXP`. Decision needed: (a) generate provider-specific SQL using a `data-provider` attribute on `<option>` elements, or (b) use a lowest-common-denominator approach (REGEXP works on both if MySQL 8+). Recommend option (a) for correctness.
2. **`referential_integrity` cross-schema support**: The template needs `child_schema.child_table` and `parent_schema.parent_table`. Should the parameter form reuse the existing table browser dropdowns, or use plain text inputs? Text inputs are simpler to ship first.
3. **`completeness_rate` threshold UX**: A percentage slider (0–100) or a plain number input? Number input is consistent with existing `min_row_count` and `max_age_hours` inputs in the form.
