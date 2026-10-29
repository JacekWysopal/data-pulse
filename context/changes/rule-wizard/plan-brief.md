# Rule Creation Wizard — Plan Brief

> Full plan: `context/changes/rule-wizard/plan.md`
> Research: `context/changes/rule-wizard/research.md`

## What & Why

Replace the single-page Add Rule form with a 3-step guided wizard. The current form
shows all 12 fields at once, which overwhelms new users. A wizard sequences the
decisions logically — pick your data source first, then define conditions, then
configure schedule — and validates each step before advancing.

## Starting Point

`rule_form.html` is one flat `<form>` with six visual sections and four JS IIFEs
(rule-type toggle, schema browser, schedule toggle, template gallery). All 12 fields
POST to `rule_create`. The template is shared between create and edit views.

## Desired End State

`/rules/new/` shows a progress bar and three-step wizard: Step 1 (Rule name +
connection + target table), Step 2 (Rule type + conditions or custom SQL), Step 3
(Schedule, notifications, forward-compat slots for description/severity/tags). Each
step validates before Next; state persists in `sessionStorage`. `/rules/<id>/edit/`
is visually unchanged — full single-page form, no wizard markup.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Wizard scope | `rule_create` only, not `rule_edit` | Edit is too complex; existing single-page edit is correct for returning users | Plan |
| Implementation | Pure JS multi-step in existing template | Zero new Python files, URLs, or dependencies; consistent with existing IIFEs | Research |
| Step state | sessionStorage (client-side) | Survives refresh within tab, no server round-trips, cleared on submit | Research |
| Steps | 3: Connection+Table / Conditions / Schedule+Notifications | Maps cleanly to the six existing form sections | Plan |
| Wizard gate | `{% if wizard_mode %}` template variable from `rule_create` | Single template, zero route duplication, edit path is `{% else %}` verbatim | Plan |
| Step validation | Client-side required-field check before Next | Instant UX; server-side `RuleForm.clean()` remains the authoritative gate | Research |
| S-26/S-27/S-28 fields | Forward-compat slot divs in Step 3, no model fields | Those fields don't exist yet; slots are empty and produce no POST data | Research |

## Scope

**In scope:**
- Wizard UI on `/rules/new/` only
- CSS step containers (show/hide via `.active` class)
- Progress bar with step indicators
- Next/Back navigation + step transitions
- sessionStorage save/restore + clear on submit
- Per-step client-side validation with inline error
- `RuleWizardUITest` test class (6 tests)

**Out of scope:**
- `rule_edit` wizard
- S-26 (description), S-27 (severity), S-28 (tags) model fields
- S-25 (live preview) button — additive if that change lands first
- Server-side per-step validation endpoints
- `django-formtools` or any new Python dependency

## Architecture / Approach

One template variable (`wizard_mode=True`) from `rule_create` gates a `{% if wizard_mode %}`
block. Inside, the form sections are wrapped in three `<div class="wizard-step"
data-step="N">` containers. Steps 2 and 3 are hidden by CSS (`.wizard-step { display:none }`;
`.wizard-step.active { display:block }`). Step 1 has class `active` on initial render.
A new `dp-wizard` IIFE in `{% block extra_scripts %}` handles transitions, storage, and
validation. All four existing IIFEs (rule-type toggle, schema browser, schedule, template
gallery) are untouched. The `#vf-section` div shifts to Step 2 in wizard mode but retains
its ID so the rule-type toggle IIFE continues to work without changes.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. CSS Wizard Structure | step containers + `wizard_mode` var; steps 2/3 hidden | `#vf-section` split must preserve rule-type toggle IIFE |
| 2. Progress Bar | visual step indicator HTML + CSS | cosmetic only; no functional risk |
| 3. Next/Back + sessionStorage | navigation, storage, scroll-to-top | storage restore must re-fire rule-type toggle IIFE |
| 4. Step Validation | inline error on Next if required fields missing | Step 2 validation logic for both rule types |
| 5. Tests | 6-test `RuleWizardUITest`; existing tests unaffected | no risk beyond confirming edit page has no wizard markup |

**Prerequisites:** No model migrations; no new pip dependencies. Requires a running
Django dev server for manual verification.
**Estimated effort:** ~2 focused sessions across 5 phases (Phases 1–4 are template-only;
Phase 5 is Python test code).

## Open Risks & Assumptions

- `#vf-section` retains same ID in Step 2 — rule-type toggle IIFE finds it and works
  as before; validated by manual testing in Phase 3 manual criteria.
- sessionStorage shared across tabs: two simultaneous wizard sessions would collide.
  Acceptable for a creation wizard; noted in research.
- S-26/S-27/S-28 may add model fields before this wizard lands. If so, Step 3 slot
  divs simply need the actual form field widgets inserted — the structure is already
  there.

## Success Criteria (Summary)

- `/rules/new/` renders a 3-step wizard; the user can create a rule end-to-end
- `/rules/<id>/edit/` is visually identical to today (no wizard markup)
- All 6 `RuleWizardUITest` tests pass; all existing `RuleCRUDViewTest` tests pass
