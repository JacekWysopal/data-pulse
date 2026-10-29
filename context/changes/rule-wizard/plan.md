# Rule Creation Wizard — 3-Step Form Implementation Plan

## Overview

Replace the single-page Add Rule form with a 3-step wizard implemented as pure client-side
JS multi-step UI inside the existing `rule_form.html`. No new views, URLs, or Python files.
The wizard applies only to `rule_create`; `rule_edit` keeps the current single-page layout.

## Current State Analysis

`rule_form.html` renders one `<form method="post">` with six logical sections in flat layout:
Rule identity → Rule type → Custom SQL section → VF section (target table + monitoring
conditions) → Schedule → Notifications. All 12 fields submit in one POST to `rule_create`.

Four JS IIFEs control dynamic behaviour: rule-type toggle (`setType()`), schema browser
(loadTables/selectTable/loadColumns), schedule toggle, and template gallery. Each IIFE
targets fixed DOM IDs (`#custom-sql-section`, `#vf-section`, `#id_connection`, etc.).

The `rule_create` view passes `{'form': form, 'action': 'Add rule'}` to the template.
`rule_edit` passes `{'form': form, 'action': 'Edit rule', 'rule': rule}`. A template
variable `wizard_mode` passed only from `rule_create` gates the wizard markup, keeping
the edit path unchanged.

**Key Discoveries:**

- `templates/monitor/rule_form.html` — single shared template for create + edit; all
  wizard markup is conditional on `{% if wizard_mode %}`
- `monitor/views.py:88–97` — `rule_create` — minimal change: add `'wizard_mode': True`
  to the render call context
- `#vf-section` currently wraps both Target table and Monitoring conditions. In wizard
  mode the Target table fields must live in Step 1 and monitoring conditions in Step 2,
  so the div boundary moves inside the `{% if wizard_mode %}` branch only. `#vf-section`
  still exists in Step 2 wizard mode (containing only monitoring conditions) so the
  rule-type toggle IIFE (`setType()`) continues to work without changes.
- Schema browser IIFE targets `#id_connection` change event; as long as connection and
  table browser remain in Step 1, the IIFE requires no changes.
- `monitor/models.py:84–243` — `Rule` model has no `description`, `severity`, or `tags`
  fields at current commit. Step 3 includes forward-compatible empty slot divs for
  those sections; they produce no form submissions until S-26/S-27/S-28 add the fields.
- `monitor/tests.py` — existing `RuleCRUDViewTest` (line 730) and `TemplateUITest` (line
  3342) test `rule_create` GET/POST responses; new wizard tests join the same file pattern.

## Desired End State

When a user visits `/rules/new/`, they see a 3-step wizard with a progress bar at the
top. Step 1 collects Rule name, connection, and target table. Step 2 collects rule type
and conditions (VF or custom SQL + templates). Step 3 collects schedule, notifications,
and forward-compatible slots for description/severity/tags. Each step has Next/Back
buttons; Submit appears only on Step 3. Field values persist across steps via
`sessionStorage`. Each step validates required fields before allowing Next. The final
POST to `/rules/new/` is unchanged; `rule_edit` is visually identical to today.

### Key Discoveries

- Wizard is gated by `wizard_mode` template variable — single template, zero route
  duplication
- `#vf-section` is split in wizard mode: table fields go to Step 1, monitoring
  conditions stay in Step 2 under a same-id `#vf-section`; rule-type toggle IIFE
  (`setType()`) is untouched
- sessionStorage key `dp_wiz_rule_create` is cleared on final submit and on fresh
  `rule_create` GET (no `?edit` param) to prevent stale state
- Step 1 validation: name non-empty + connection selected (table fields encouraged but
  not blocked here — server enforces for VF rules)
- Step 2 validation: for `volume_freshness`, at least one of (min_row_count) or
  (timestamp_column + max_age_hours) must be filled; for `custom_sql`, textarea non-empty
- Step 3 validation: no required fields — schedule and notifications are optional

## What We're NOT Doing

- Wizard on `rule_edit` — too complex; edit form keeps current single-page layout
- Server-side step storage / partial POST endpoints — pure client-side JS only
- `django-formtools` `SessionWizardView` — not a dependency; no new Python deps added
- Implementing S-26 (description), S-27 (severity), S-28 (tags) model fields — Step 3
  includes empty forward-compatible slot divs only; those fields are added by their
  own change IDs
- Live preview button (S-25) — if S-25 lands before this change, Step 2 gains the
  button; otherwise the slot is absent; no explicit placeholder needed
- Scroll-to-top polyfill for mobile — a `window.scrollTo(0,0)` call on each step
  transition is included in Phase 3 as a one-liner; no external lib required

## Implementation Approach

Gate all wizard UI with `{% if wizard_mode %}` in the template. In wizard mode, wrap
each logical section group into a `<div class="wizard-step" data-step="N">`. Add a
`.wizard-progress` bar above the form. Replace the single submit button with per-step
Next/Back buttons (Submit only on Step 3). Add one new JS IIFE (`dp-wizard`) for
step navigation, sessionStorage save/restore, and step validation. All four existing
IIFEs are untouched.

Non-wizard mode (`{% else %}` branch) renders exactly the current markup so `rule_edit`
continues to work with zero diff.

## Critical Implementation Details

**`#vf-section` boundary in wizard mode**: The existing rule-type toggle IIFE sets
`vfSec.style.display` to hide/show monitoring conditions when the user switches to
custom SQL. In wizard mode the Target table rows (schema, table, browser) must live in
Step 1, outside `#vf-section`. The IIFE still finds `#vf-section` in Step 2; it just
controls monitoring conditions rather than the full original div. The IIFE code is
unchanged; only the DOM position of `#vf-section` shifts (it still exists with the
same ID, just contains fewer children).

**sessionStorage clear on fresh load**: On `DOMContentLoaded`, if `wizard_mode` is
active and the current URL contains no `?restored` param, the wizard JS clears the
sessionStorage key before restoring. This prevents a stale half-complete wizard from
a previous session showing up on a fresh visit. After restoring from storage, the URL
gains no param; the clear happens only when there's nothing to restore (first visit).
Simpler: always write to sessionStorage on every Next/Back; always read on DOMContentLoaded.
On final submit, delete the key. Stale data from prior sessions is low-risk for a creation
form and the rule is: clear on submit, read on load.

**Step 2 rule-type toggle visibility**: When the wizard navigates to Step 2, the
rule-type toggle IIFE may have already run. The wizard JS dispatches a synthetic
`change` event on `#id_rule_type` after showing Step 2 if needed, or simply calls
`setType(currentType)` directly. Since `setType` is defined in a closure, the cleanest
approach is to expose it via a `window.dp_setRuleType` alias or fire `dp:setType`
custom event from the wizard IIFE.

---

## Phase 1: CSS Wizard Structure

### Overview

Wrap form sections into three `.wizard-step` containers inside a `{% if wizard_mode %}`
block. Steps 2 and 3 start hidden. Add step container CSS. Pass `wizard_mode=True` from
`rule_create`. Non-wizard edit path is an `{% else %}` branch preserving current markup.

### Changes Required:

#### 1. `rule_create` view — pass wizard_mode

**File**: `monitor/views.py`

**Intent**: Signal to the template that the create-only wizard UI should render.

**Contract**: Add `'wizard_mode': True` to the dict in the `render()` call inside
`rule_create`. `rule_edit` render call is unchanged (no key = falsy in template).

#### 2. Template — wizard step containers and CSS

**File**: `templates/monitor/rule_form.html`

**Intent**: Introduce `{% if wizard_mode %}` blocks that split the form into three
`.wizard-step` divs. The `{% else %}` branch is the current markup verbatim.

**Contract**:
- Three step containers: `<div class="wizard-step" data-step="1|2|3">`.
- Step 1 contains: Rule identity section (name, connection) + Target table section
  (schema_name, table_name, `#table-browser`, `#table-inputs`).
- Step 2 contains: Rule type tabs + `#custom-sql-section` + `#vf-section` (monitoring
  conditions only — no table rows here in wizard mode).
- Step 3 contains: Schedule section + Notifications section + three empty
  `<div id="wizard-slot-description">`, `<div id="wizard-slot-severity">`,
  `<div id="wizard-slot-tags">` forward-compat slots.
- CSS in `{% block extra_head %}`: `.wizard-step { display: none; }` and
  `.wizard-step.active { display: block; }`. Step 1 gets class `active` inline via
  `{% if wizard_mode %}` so it shows on load without JS.

### Success Criteria:

#### Automated Verification:

- `GET /rules/new/` returns HTTP 200
- `GET /rules/<rule_id>/edit/` returns HTTP 200 (existing edit test)
- Django `check` passes: `python manage.py check`

#### Manual Verification:

- `/rules/new/` shows only Step 1 content; Steps 2 and 3 are invisible
- `/rules/<id>/edit/` shows the full single-page form with no wizard markup

---

## Phase 2: Progress Bar + Step Indicators

### Overview

Add a `.wizard-progress` HTML block above the form (inside `{% if wizard_mode %}`)
showing three labeled step circles connected by lines. CSS-only styling; JS will
update active/complete classes in Phase 3.

### Changes Required:

#### 1. Template — progress bar HTML

**File**: `templates/monitor/rule_form.html`

**Intent**: Render a visual step indicator (circles + connecting lines) so the user
knows where they are in the 3-step flow.

**Contract**: Insert a `<div class="wizard-progress">` containing three
`<div class="wizard-step-ind" data-ind="1|2|3">` elements (each with a circle span
and a label: "Connection & table" / "Conditions" / "Schedule & notifications"). A
`<div class="wizard-progress-line">` span spans between circles. Step indicator 1
starts with class `active`.

#### 2. Template — progress bar CSS

**File**: `templates/monitor/rule_form.html`

**Intent**: Style the progress bar to match the existing DataPulse design tokens
(uses `var(--accent)`, `var(--bg-elevated)`, `var(--border)`, `var(--text-muted)`).

**Contract**: Add CSS rules for `.wizard-progress` (flex row, centered, margin-bottom),
`.wizard-step-ind` (circle + label column), `.wizard-step-ind .circle` (round,
border, transition), `.wizard-step-ind.active .circle` (accent background),
`.wizard-step-ind.complete .circle` (checkmark or filled accent), and
`.wizard-progress-line` (flex-1 thin border-top, aligned to circle center).

### Success Criteria:

#### Automated Verification:

- `GET /rules/new/` response body contains `wizard-progress`
- `GET /rules/new/` response body contains `wizard-step-ind`

#### Manual Verification:

- Step 1 indicator circle is highlighted; steps 2 and 3 are grey on page load
- Progress bar renders within the `form-card` at proper width

---

## Phase 3: Next/Back Navigation JS + sessionStorage

### Overview

Add a `dp-wizard` JS IIFE that manages step transitions, updates progress indicator
classes, persists field values to `sessionStorage` on each Next/Back, restores values
on page load, and clears storage on final submit. Add Next/Back/Submit buttons inside
each step container. The `window.scrollTo(0,0)` call fires on each transition.

### Changes Required:

#### 1. Template — per-step navigation buttons

**File**: `templates/monitor/rule_form.html`

**Intent**: Place navigation controls inside each step container so the user progresses
through the wizard without seeing a single-page form.

**Contract**:
- Step 1: `<div class="wizard-nav">` containing one `<button type="button"
  class="btn-dp btn-dp-primary wizard-next-btn" data-target="2">Next →</button>`.
- Step 2: Back button (`data-target="1"`, class `wizard-back-btn`) + Next button
  (`data-target="3"`).
- Step 3: Back button (`data-target="2"`) + Submit button (`type="submit"`,
  class `btn-dp btn-dp-primary`). The existing "Save rule" submit button and
  Cancel link move inside the Step 3 `wizard-nav` div (not duplicated; only one
  submit button in the form in wizard mode).
- The original `<div class="d-flex gap-2 pt-2" ...>` submit+cancel row is wrapped in
  `{% if not wizard_mode %}` so it only appears in the non-wizard edit path.

#### 2. Template — `dp-wizard` JS IIFE

**File**: `templates/monitor/rule_form.html`

**Intent**: Implement step transitions, progress indicator updates, and sessionStorage
persistence as a self-contained IIFE added to `{% block extra_scripts %}`.

**Contract**:
- The IIFE is guarded by an early return: `if (!document.querySelector('.wizard-step')) return;`
  so it does nothing on the edit page even if the script block loads.
- `showStep(n)`: removes `active` from all `.wizard-step` divs, adds `active` to
  `[data-step="n"]`; updates `.wizard-step-ind` active/complete classes; calls
  `window.scrollTo(0, 0)`.
- `saveToStorage()`: iterates `#rule-form` `elements`, saves `name → value` (for
  checkboxes: `name → checked`) to a JSON object under key `dp_wiz_rule_create` in
  `sessionStorage`.
- `restoreFromStorage()`: reads the JSON, sets field values; for radio/select fields
  dispatches a synthetic `change` event so dependent IIFEs (rule-type toggle, schedule
  toggle) pick up the restored value; calls `showStep(savedStep)`.
- On `DOMContentLoaded`: calls `restoreFromStorage()` if key exists, else `showStep(1)`.
- Each `.wizard-next-btn` click: calls `saveToStorage()`, then navigates (Step 2 restore
  re-fires the rule-type toggle via `document.dispatchEvent(new CustomEvent('dp:setType',
  {detail: {type: currentType}}))`).
- Each `.wizard-back-btn` click: calls `saveToStorage()`, navigates back.
- Form `submit` event: removes `dp_wiz_rule_create` from `sessionStorage`.

### Success Criteria:

#### Automated Verification:

- `GET /rules/new/` response body contains `wizard-next-btn`
- `GET /rules/new/` response body contains `sessionStorage`
- `GET /rules/new/` response body contains `dp_wiz_rule_create`

#### Manual Verification:

- Clicking Next on Step 1 shows Step 2 and hides Step 1
- Clicking Back on Step 2 returns to Step 1
- Refreshing the page within a wizard session restores the last-viewed step and values
- Completing the form and clicking Save clears sessionStorage (verify via devtools)
- Rule type toggle still works correctly inside Step 2

---

## Phase 4: Step Validation JS

### Overview

Extend the `dp-wizard` IIFE with a `validateStep(n)` function. Next button clicks call
`validateStep(current)` before advancing; errors display inline without a full-page
reload.

### Changes Required:

#### 1. Template — `validateStep` in dp-wizard IIFE

**File**: `templates/monitor/rule_form.html`

**Intent**: Prevent the user from advancing past a step when required fields for that
step are missing, surfacing a concise inline error without a server round-trip.

**Contract**:
- `validateStep(n)` returns `true` (valid) or `false` (blocked) and renders an error
  message inside `.wizard-step[data-step="n"] .wizard-step-error` span (created once,
  cleared on each validation call).
- Step 1 rules: `name` field non-empty (trimmed); `connection` select has a non-empty
  value. Error text: "Please enter a rule name and select a connection."
- Step 2 rules: active rule type is `volume_freshness` → at least one of (`min_row_count`
  non-empty) or (`timestamp_column` non-empty AND `max_age_hours` non-empty); active
  type is `custom_sql` → `custom_sql` textarea trimmed non-empty. Error text:
  "Please fill in at least one monitoring condition." or "Please enter a SQL query."
- Step 3: always returns `true` (schedule and notifications are optional).
- `.wizard-next-btn` click handler: `if (!validateStep(currentStep)) return;` before
  `saveToStorage()` and navigation.

### Success Criteria:

#### Automated Verification:

- `GET /rules/new/` response body contains `validateStep`

#### Manual Verification:

- Clicking Next on Step 1 without selecting a connection shows inline error
- Clicking Next on Step 2 with VF type but no conditions filled shows inline error
- Clicking Next on Step 2 with custom_sql type but empty textarea shows inline error
- Step 3 Next/Submit is never blocked by validation (schedule is optional)
- Error message disappears when the user fixes the field and clicks Next again

---

## Phase 5: Tests

### Overview

Add a `RuleWizardUITest` test class to `monitor/tests.py` that verifies the wizard
HTML structure on `rule_create` GET, the absence of wizard markup on `rule_edit` GET,
and that the existing single-POST flow still works from the wizard form.

### Changes Required:

#### 1. `monitor/tests.py` — `RuleWizardUITest` class

**File**: `monitor/tests.py`

**Intent**: Assert that the wizard markup is present on the create page and absent
on the edit page, and that a full POST through the wizard form still saves a rule.

**Contract**: New class `RuleWizardUITest(TestCase)` appended to `tests.py`, following
the pattern of `TemplateUITest` (line 3342). Setup creates a user + connection
(same pattern as `RuleCRUDViewTest` line 730). Tests:

- `test_rule_create_has_wizard_steps` — GET `/rules/new/`, assert `wizard-step` in
  content (×3 via `count`).
- `test_rule_create_has_wizard_progress` — GET `/rules/new/`, assert `wizard-progress`
  in content.
- `test_rule_create_has_next_button` — GET `/rules/new/`, assert `wizard-next-btn` in
  content.
- `test_rule_create_has_session_storage_js` — GET `/rules/new/`, assert `sessionStorage`
  in content.
- `test_rule_edit_has_no_wizard` — GET `/rules/<id>/edit/`, assert `wizard-step` NOT in
  content.
- `test_rule_create_post_still_works` — POST to `/rules/new/` with valid VF payload
  (same as existing `test_rule_create_post_volume`), assert redirect and rule saved.

### Success Criteria:

#### Automated Verification:

- `python manage.py test monitor.tests.RuleWizardUITest` — all 6 tests pass
- `python manage.py test monitor.tests.RuleCRUDViewTest` — existing tests unaffected

---

## Testing Strategy

### Unit Tests:

- All tests in `RuleWizardUITest` cover the six assertions above
- No new fixtures or mocks needed — standard `TestCase` with `self.client.force_login`

### Integration Tests:

- `test_rule_create_post_still_works` confirms the full POST→save flow is unbroken

### Manual Testing Steps:

1. Open `/rules/new/` — verify Step 1 is shown, Step 2/3 hidden, progress bar at top
2. Fill name + connection → Next → verify Step 2 appears, Step 1 hides
3. Leave all Step 2 conditions empty → Next → verify error message shown, no advance
4. Fill one condition → Next → verify Step 3 appears
5. Click Back on Step 3 → verify Step 2 re-shows with previously filled values
6. Refresh page on Step 2 → verify step and values restored from sessionStorage
7. Complete Step 3 → Save rule → verify redirect to dashboard, rule in list
8. Open `/rules/<id>/edit/` → verify full single-page form, no wizard markup
9. Verify rule-type toggle works in Step 2 (switch between VF and custom SQL)
10. Verify template gallery loads in Step 2 when custom SQL type is active

## Performance Considerations

No new network requests are introduced. The `dp-wizard` IIFE adds < 2 KB of JS to a
template that already has ~5 KB of IIFE JS. sessionStorage operations are synchronous
and negligible for the payload size (12 short field values).

## Migration Notes

No model migrations. No server-side state changes. `rule_edit` is unaffected.

## References

- Research: `context/changes/rule-wizard/research.md`
- Template under edit: `templates/monitor/rule_form.html`
- View under edit: `monitor/views.py:88–97` (`rule_create`)
- Tests to extend: `monitor/tests.py` (class `TemplateUITest` line 3342 as pattern)
- Related: `context/changes/check-templates/` (template gallery IIFE pattern)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: CSS Wizard Structure

#### Automated

- [ ] 1.1 GET /rules/new/ returns HTTP 200
- [ ] 1.2 GET /rules/<rule_id>/edit/ returns HTTP 200
- [ ] 1.3 Django check passes

#### Manual

- [ ] 1.4 /rules/new/ shows only Step 1 content on load
- [ ] 1.5 /rules/<id>/edit/ shows full single-page form with no wizard markup

### Phase 2: Progress Bar + Step Indicators

#### Automated

- [ ] 2.1 GET /rules/new/ response contains wizard-progress
- [ ] 2.2 GET /rules/new/ response contains wizard-step-ind

#### Manual

- [ ] 2.3 Step 1 indicator circle is highlighted on load
- [ ] 2.4 Progress bar renders within form-card at proper width

### Phase 3: Next/Back Navigation JS + sessionStorage

#### Automated

- [ ] 3.1 GET /rules/new/ response contains wizard-next-btn
- [ ] 3.2 GET /rules/new/ response contains sessionStorage
- [ ] 3.3 GET /rules/new/ response contains dp_wiz_rule_create

#### Manual

- [ ] 3.4 Clicking Next on Step 1 advances to Step 2
- [ ] 3.5 Clicking Back on Step 2 returns to Step 1
- [ ] 3.6 Refreshing page restores last step and values
- [ ] 3.7 Completing form and clicking Save clears sessionStorage

### Phase 4: Step Validation JS

#### Automated

- [ ] 4.1 GET /rules/new/ response contains validateStep

#### Manual

- [ ] 4.2 Step 1 Next blocked without connection selected
- [ ] 4.3 Step 2 Next blocked without any condition filled (VF type)
- [ ] 4.4 Step 2 Next blocked with empty SQL textarea (custom_sql type)
- [ ] 4.5 Step 3 Submit never blocked by validation

### Phase 5: Tests

#### Automated

- [ ] 5.1 RuleWizardUITest — all 6 tests pass
- [ ] 5.2 RuleCRUDViewTest — existing tests unaffected
