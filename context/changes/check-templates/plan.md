# Built-in Rule Check Templates Implementation Plan

## Overview

Add a template gallery to the Custom SQL rule form that lets a user pick one of 8 pre-built SQL patterns, fill in a small parameter form, and apply the generated SELECT statement into the custom_sql textarea — switching rule_type to `custom_sql` automatically. No database changes are required.

## Current State Analysis

The form already has a `#custom-sql-section` that appears when the user picks the "Custom SQL" tab (rule_form.html:181–194). The textarea is at `id_custom_sql`. The JS `setType()` function (rule_form.html:338–352) controls visibility.

`Rule.custom_sql` accepts any SELECT that:
- starts with `SELECT` (enforced by `SQL_ALLOWED`, services.py:179)
- contains no DML/DDL keywords (enforced by `SQL_FORBIDDEN`, services.py:182–185)
- returns a single truthy/falsy value (executor: services.py:184–225)

All 8 templates satisfy these constraints without changes to `services.py` or `forms.py`.

### Key Discoveries:

- `templates/monitor/rule_form.html:181` — `#custom-sql-section` is the insertion point; gallery goes before the `<label>SQL query</label>` line (rule_form.html:183)
- `monitor/models.py:115–123` — `Rule.custom_sql` TextField, receives generated SELECT unchanged
- `monitor/services.py:177–185` — SQL_ALLOWED / SQL_FORBIDDEN regexes are the only hard constraints; all 8 templates satisfy them
- `monitor/views.py:145–177` — existing `api_schema_tables` / `api_schema_columns` AJAX views show the pattern for a new `api_templates` view
- `monitor/urls.py:18–19` — schema API URL pattern to replicate at `api/templates/`
- The `Connection` model has a `provider` field (`postgresql` or `mysql`); `<select id="id_connection">` option elements do not currently carry `data-provider`; adding it enables client-side provider detection for `pattern_match`

## Desired End State

A "Templates" section appears at the top of `#custom-sql-section`. Eight template cards are shown in a horizontally scrollable strip. Clicking a card reveals a compact parameter sub-form. Clicking "Apply" renders the SQL into the `custom_sql` textarea and ensures the rule type is set to `custom_sql`. The user can edit the SQL freely before saving.

A GET `/api/templates/` endpoint returns the full template catalog as JSON (list of objects with `id`, `label`, `description`, `params`, and `sql_template` fields per provider). The templates are stored in `monitor/check_templates.py` as a plain Python dict.

### Key Discoveries:

- Provider-specific SQL only affects `pattern_match` (PostgreSQL: `SIMILAR TO` / `~`; MySQL: `REGEXP`). The `Connection.provider` field value is available server-side and can be embedded as `data-provider` on each `<option>` in the rendered widget.
- `completeness_rate` threshold is a plain number input (0–100), consistent with existing `min_row_count` / `max_age_hours` inputs.
- `referential_integrity` uses 4 text inputs (child_schema.child_table, child_column, parent_schema.parent_table, parent_column).
- The inline panel pattern avoids modals; it follows the progressive-disclosure pattern already used by the schema browser and cron presets.

## What We're NOT Doing

- No Django model or migration for templates — they are static product config
- No user-created or user-edited templates
- No modal overlay — gallery is an inline panel inside `#custom-sql-section`
- No reuse of the table/column browser dropdowns in the template parameter form — plain text inputs for now
- No server-side SQL generation — rendering is pure client-side JS
- No change to `services.py`, `forms.py`, or any model
- No Slack / email notification changes
- No change to the AJAX endpoint for the decision to embed templates as inline JSON (see Phase 1, item 3)

## Implementation Approach

Three phases, strictly additive:
1. Create `monitor/check_templates.py` with the catalog dict and `api_templates` view + URL. The view is the authoritative source for the client.
2. Extend `rule_form.html`: add `data-provider` to connection `<option>` elements; insert the template gallery panel inside `#custom-sql-section`; add the client-side JS that fetches templates, renders cards, builds parameter sub-forms, and writes into the textarea.
3. Add tests: unit tests for `check_templates.py` SQL generation and the `api_templates` endpoint.

---

## Phase 1: check_templates.py + AJAX endpoint

### Overview

Create the template catalog module and expose it as a GET endpoint. This phase produces no visible UI change but is the data contract that Phase 2 depends on.

### Changes Required:

#### 1. monitor/check_templates.py — new file

**File**: `monitor/check_templates.py`

**Intent**: Define the 8 template entries and a `generate_sql(template_id, params, provider)` function that returns the rendered SELECT string. This is the single source of truth for template data; views and tests both import from here.

**Contract**:
- Module-level constant `TEMPLATES`: list of dicts, one per template.
- Each dict has: `id` (str, slug), `label` (str, display name), `description` (str, one-line), `params` (list of dicts with `name`, `label`, `placeholder`), and `sql` (dict keyed `postgresql` / `mysql`, each a Python format string with named placeholders matching `params[*].name`).
- `generate_sql(template_id: str, params: dict[str, str], provider: str) -> str` renders the format string for the given provider, raising `KeyError` on unknown template or provider.
- SQL template strings per entry (provider=postgresql shown; mysql variant noted where different):

| id | SQL (postgresql) | MySQL difference |
|---|---|---|
| `null_check` | `SELECT COUNT(*) = 0 FROM {table} WHERE {column} IS NULL` | identical |
| `uniqueness` | `SELECT COUNT(*) = COUNT(DISTINCT {column}) FROM {table}` | identical |
| `not_negative` | `SELECT MIN({column}) >= 0 FROM {table}` | identical |
| `future_date` | `SELECT MAX({column}) <= NOW() FROM {table}` | identical |
| `referential_integrity` | `SELECT COUNT(*) = 0 FROM {child_table} WHERE {child_column} NOT IN (SELECT {parent_column} FROM {parent_table})` | identical |
| `completeness_rate` | `SELECT ROUND(100.0 * COUNT({column}) / NULLIF(COUNT(*), 0), 2) >= {threshold} FROM {table}` | identical |
| `row_count_equals` | `SELECT COUNT(*) = {expected_count} FROM {table}` | identical |
| `pattern_match` | `SELECT COUNT(*) = 0 FROM {table} WHERE {column} !~ '{pattern}'` | `SELECT COUNT(*) = 0 FROM {table} WHERE {column} NOT REGEXP '{pattern}'` |

All generated strings start with `SELECT` and contain no forbidden DML/DDL keywords.

#### 2. monitor/views.py — add api_templates view

**File**: `monitor/views.py`

**Intent**: Expose the template catalog as a JSON array so the client-side gallery can fetch it once per page load.

**Contract**:
- New view `api_templates(request)`, decorated `@login_required` and `@require_GET`.
- Returns `JsonResponse({'templates': TEMPLATES})` where `TEMPLATES` is imported from `monitor.check_templates`.
- The `sql` field per entry is the dict with both provider keys; the client picks the right one using `data-provider` on the selected connection `<option>`.

#### 3. monitor/urls.py — register api/templates/ route

**File**: `monitor/urls.py`

**Intent**: Make the template catalog reachable at a consistent path alongside the existing schema API URLs.

**Contract**: Add `path('api/templates/', views.api_templates, name='api_templates')` in the `# Schema introspection` block (after line 19).

### Success Criteria:

#### Automated Verification:

- `python manage.py check` passes with no errors
- `python manage.py test monitor.tests.CheckTemplatesTests` passes (unit tests for all 8 `generate_sql` outputs and the view — added in Phase 3, but the module and view must exist)
- Endpoint responds: `curl -s http://localhost:8000/api/templates/` returns HTTP 302 (redirect to login) when unauthenticated, confirming `@login_required` is applied
- `python -c "from monitor.check_templates import TEMPLATES, generate_sql; assert len(TEMPLATES) == 8"` exits 0

#### Manual Verification:

- Log in, navigate to `/api/templates/` — JSON response with `templates` array of 8 objects is returned
- Each object has `id`, `label`, `description`, `params`, `sql` keys

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: rule_form.html template gallery UI

### Overview

Inject the template gallery panel into `#custom-sql-section` and write the client-side JS that fetches templates, renders cards, handles parameter input, and applies the generated SQL.

### Changes Required:

#### 1. monitor/forms.py — add data-provider to connection option elements

**File**: `monitor/forms.py`

**Intent**: Let client-side JS read the provider of the selected connection without an extra AJAX call.

**Contract**: In `RuleForm.__init__`, after the `connection` queryset is set, iterate the connection queryset and build a `{pk: provider}` mapping. Override the `connection` widget's `attrs` to pass this mapping as a JSON string in a `data-providers` attribute on the `<select>` element:
```python
providers = {str(c.pk): c.provider for c in self.fields['connection'].queryset}
self.fields['connection'].widget.attrs['data-providers'] = json.dumps(providers)
```
`import json` at the top of `forms.py`. The client reads `data-providers` from `#id_connection` to resolve provider without needing a separate `<option data-provider>` attribute per option.

#### 2. templates/monitor/rule_form.html — template gallery panel + CSS

**File**: `templates/monitor/rule_form.html`

**Intent**: Show a horizontally scrollable card strip inside `#custom-sql-section`, above the SQL label. Clicking a card opens a parameter sub-form; clicking Apply writes the rendered SQL into the textarea and ensures `custom_sql` rule type is active.

**Contract** (structure only; implementer writes the markup):

CSS additions inside `{% block extra_head %}`:
- `.tpl-gallery` — flex row, `overflow-x: auto`, `gap: 8px`, `padding-bottom: 8px`, `margin-bottom: 12px`
- `.tpl-card` — ~140px wide, `cursor: pointer`, border/background using existing design tokens (`var(--bg-elevated)`, `var(--border)`, `var(--radius)`)
- `.tpl-card.selected` — accent border (`var(--accent)`) and background (`var(--accent-dim)`)
- `.tpl-params` — container for parameter inputs, hidden by default, shown on card select, `margin-bottom: 12px`
- `.tpl-apply-btn` — reuses `btn-dp btn-dp-primary` classes at small size

HTML insertion point: immediately before `<label for="{{ form.custom_sql.id_for_label }}"` (rule_form.html:183), inside `#custom-sql-section`:
```html
<!-- Template gallery — check-templates -->
<div id="tpl-gallery-section" class="mb-3">
  <div class="form-section-label">Templates <span class="optional-tag">optional</span></div>
  <div id="tpl-gallery" class="tpl-gallery"><!-- cards injected by JS --></div>
  <div id="tpl-params" class="tpl-params" style="display:none">
    <!-- param inputs injected by JS -->
    <button type="button" id="tpl-apply-btn" class="btn-dp btn-dp-primary" style="font-size:0.78rem;padding:5px 14px;margin-top:8px">Apply template</button>
  </div>
</div>
```

#### 3. templates/monitor/rule_form.html — client-side JS for template gallery

**File**: `templates/monitor/rule_form.html`

**Intent**: Fetch the template catalog once on page load, render cards, handle card selection, build the parameter sub-form, render the SQL string on Apply, and fill the textarea.

**Contract**: New IIFE inside `{% block extra_scripts %}`, after the existing `setType` IIFE:

```
(function() {
  // 1. Fetch /api/templates/ once; cache in module variable
  // 2. renderGallery(templates): create .tpl-card for each, attach click → selectCard
  // 3. selectCard(tpl): mark card .selected, build param inputs in #tpl-params, show Apply btn
  //    - Each tpl.params entry becomes a labeled <input type="text"> with placeholder
  // 4. getProvider(): read #id_connection dataset.providers JSON, resolve current value
  // 5. #tpl-apply-btn click:
  //    a. collect param values from #tpl-params inputs
  //    b. pick sql = selectedTpl.sql[provider] (fallback: .sql.postgresql)
  //    c. replace {placeholder} in sql string with param values
  //    d. set #id_custom_sql.value = rendered sql
  //    e. call setType('custom_sql') so the tab switches if not already active
  //    f. hide #tpl-params, deselect cards
  // 6. expose setType so it can be called from this IIFE (move setType to module scope or use
  //    a custom event: dispatch 'dp:setType' and handle in the setType IIFE)
})();
```

The `setType` function is currently inside an IIFE (rule_form.html:338–348). To call it from the new gallery IIFE, dispatch a custom event `dp:setType` with `detail.type` from the gallery, and add a `document.addEventListener('dp:setType', ...)` listener inside the existing setType IIFE. This preserves the existing encapsulation.

### Success Criteria:

#### Automated Verification:

- `python manage.py check` passes
- `python -m py_compile templates/monitor/rule_form.html` is not applicable (HTML); manual check suffices

#### Manual Verification:

- Navigate to Add rule → click "Custom SQL" tab → template gallery strip with 8 cards appears
- Clicking a card (e.g. "Null check") shows 2 param inputs (table, column)
- Filling in `public.orders` / `customer_id` and clicking Apply puts `SELECT COUNT(*) = 0 FROM public.orders WHERE customer_id IS NULL` in the SQL textarea
- Rule type tab switches to Custom SQL if it wasn't already active
- Clicking Apply with a PostgreSQL connection produces `!~` pattern for `pattern_match`; switching to a MySQL connection and re-applying produces `NOT REGEXP`
- Editing the generated SQL manually before saving works as before
- Edit-rule page loads without JS errors; gallery appears when Custom SQL tab is selected

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 3: Tests

### Overview

Add automated tests covering template SQL generation correctness and the `api_templates` endpoint.

### Changes Required:

#### 1. monitor/tests.py — CheckTemplatesTests and ApiTemplatesTests

**File**: `monitor/tests.py`

**Intent**: Cover all 8 `generate_sql` outputs for both providers and verify the endpoint shape and auth guard.

**Contract**:
- `class CheckTemplatesTests(TestCase)` with one test method per template; each asserts:
  - generated SQL starts with `SELECT` (enforced by services.py constraint)
  - generated SQL does not contain any forbidden keyword (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`) — case-insensitive
  - For `pattern_match`: postgresql variant contains `!~`, mysql variant contains `REGEXP`
  - Returned string contains the supplied parameter values
- `class ApiTemplatesTests(TestCase)` with:
  - `test_unauthenticated_redirects` — GET `/api/templates/` without login returns 302
  - `test_authenticated_returns_8_templates` — login, GET returns 200 with JSON `templates` list of length 8
  - `test_each_template_has_required_keys` — each object has `id`, `label`, `description`, `params`, `sql` keys

### Success Criteria:

#### Automated Verification:

- `python manage.py test monitor.tests.CheckTemplatesTests` — all template SQL tests pass
- `python manage.py test monitor.tests.ApiTemplatesTests` — all endpoint tests pass
- `python manage.py test monitor` — full monitor test suite passes (no regressions)

#### Manual Verification:

- Test output shows no failures or errors
- No previously passing tests are broken

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Testing Strategy

### Unit Tests:

- All 8 templates × 2 providers = 16 SQL generation cases in `CheckTemplatesTests`
- Forbidden keyword check on every generated SQL string
- `generate_sql` raises `KeyError` for unknown `template_id` and unknown `provider`

### Integration Tests:

- `api_templates` endpoint: auth guard, response shape, template count

### Manual Testing Steps:

1. Add rule → Custom SQL tab → verify gallery renders 8 cards
2. Select `null_check` → fill `public.users` / `email` → Apply → verify SQL in textarea
3. Select `pattern_match` with PostgreSQL connection → Apply → verify `!~` in SQL
4. Select `pattern_match` with MySQL connection → Apply → verify `REGEXP` in SQL
5. Select `referential_integrity` → fill all 4 params → Apply → verify 4 values present in SQL
6. Save a rule using template-generated SQL → run check → verify OK/FAIL response
7. Edit existing rule: Custom SQL section opens, gallery is present, existing SQL is not overwritten on load

## Performance Considerations

The template catalog is fetched once per page load via `/api/templates/` and cached in the JS module variable. No repeated requests. The catalog is ~2 KB JSON; no caching header or server-side session cache is needed.

## Migration Notes

No database migration required. No changes to existing model fields or constraints.

## References

- Research: `context/changes/check-templates/research.md`
- Insertion point: `templates/monitor/rule_form.html:181–194`
- setType toggle: `templates/monitor/rule_form.html:338–352`
- SQL constraints: `monitor/services.py:177–185`
- Existing AJAX pattern: `monitor/views.py:145–177`
- ScheduleType static config precedent: `monitor/models.py:143–154`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: check_templates.py + AJAX endpoint

#### Automated

- [ ] 1.1 `python manage.py check` passes with no errors
- [ ] 1.2 `python -c "from monitor.check_templates import TEMPLATES, generate_sql; assert len(TEMPLATES) == 8"` exits 0
- [ ] 1.3 GET `/api/templates/` unauthenticated returns HTTP 302

#### Manual

- [ ] 1.4 Authenticated GET `/api/templates/` returns JSON with `templates` array of 8 objects, each with `id`, `label`, `description`, `params`, `sql` keys

### Phase 2: rule_form.html template gallery UI

#### Automated

- [ ] 2.1 `python manage.py check` passes

#### Manual

- [ ] 2.2 Gallery with 8 cards appears when Custom SQL tab is active
- [ ] 2.3 Selecting a card shows parameter inputs and Apply button
- [ ] 2.4 Applying `null_check` with table/column fills correct SELECT into textarea
- [ ] 2.5 `pattern_match` generates `!~` for PostgreSQL and `REGEXP` for MySQL
- [ ] 2.6 Applying a template switches rule type tab to Custom SQL
- [ ] 2.7 Edit-rule page loads without JS errors; gallery present on Custom SQL tab

### Phase 3: Tests

#### Automated

- [ ] 3.1 `python manage.py test monitor.tests.CheckTemplatesTests` passes
- [ ] 3.2 `python manage.py test monitor.tests.ApiTemplatesTests` passes
- [ ] 3.3 `python manage.py test monitor` passes with no regressions

#### Manual

- [ ] 3.4 No previously passing tests broken
