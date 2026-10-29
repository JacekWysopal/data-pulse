# Rule Tags — Plan Brief

> Full plan: `context/changes/rule-tags/plan.md`
> Research: `context/changes/rule-tags/research.md`

## What & Why

Add a `tags` field to the `Rule` model so users can label rules with short identifiers
(e.g. `production`, `finance`, `orders`). Tags make it faster to find related rules
in large dashboards and provide a lightweight grouping mechanism without requiring a
separate model or page.

## Starting Point

`Rule` (monitor/models.py:84) has 17 scalar fields and no tagging support today. The
dashboard has three client-side filters (name, status, connection) driven by
`data-*` attributes and a shared `applyFilters()` closure. No external JS libraries
are used anywhere in the project.

## Desired End State

Users can assign up to 5 tags per rule via a chip-style input on the rule form. Tags
appear as indigo accent pills below the rule name on every dashboard row. A fourth
dropdown in the filter bar lets users filter to rules carrying a specific tag, with
`?tag=` URL persistence consistent with existing filters.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Storage model | `CharField(max_length=200, blank=True)` — comma-separated | No new model, no join table, no `save_m2m()` plumbing; per-user rule counts are small so LIKE-style scanning is fine. | Research / Plan |
| Tag validation | max 5 tags, max 30 chars, `[a-z0-9-]` only, normalised lowercase | Prevents abuse and keeps the display compact; enforced in `clean_tags()`. | Plan (decisions) |
| Dashboard filter mechanism | Client-side `<select id="f-tag">`, options populated by JS scanning `data-tags` | Consistent with the three existing filters; no view change required. | Research / Plan |
| Tag display location | Below rule name in the existing Rule `<td>` (no new column) | Avoids widening the 8-column table. | Research / Plan |
| Form widget | Self-contained vanilla JS chip widget in `rule_form.html` | Matches the project pattern of inline vanilla JS; no external dependency. | Research / Plan |

## Scope

**In scope:**
- `Rule.tags` CharField + `tags_list` property
- Migration `0018_rule_tags.py`
- `RuleForm` field + `clean_tags()` validation
- Dashboard `data-tags` attribute, tag pills, `#f-tag` dropdown, extended `applyFilters()`
- Chip widget in `rule_form.html`
- Unit + integration tests

**Out of scope:**
- M2M Tag model
- Server-side tag filter route
- Tag autocomplete from existing tags
- Tag admin or management UI
- Per-tag analytics or grouping pages

## Architecture / Approach

One new column on `Rule` stores tags as a normalised comma-separated string. All
display and filtering happens client-side: the server renders `data-tags` on `<tr>` rows,
JS populates the dropdown and runs the filter. The chip widget intercepts the text
input and manages a hidden field that carries the comma-joined value to the server on
form submit.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Model + Migration | `Rule.tags` column + `tags_list` property + migration `0018` | Must not touch `rule_has_at_least_one_condition` constraint |
| 2. Form Field + Validation | `RuleForm.tags` widget + `clean_tags()` server validation | Regex must align with chip widget client-side check |
| 3. Dashboard Pills + Filter | Tag pills on row, `#f-tag` dropdown, extended `applyFilters()` | JS must handle rules with no tags gracefully |
| 4. Chip Widget | Vanilla JS chip input in `rule_form.html` | Backspace/blur edge cases; pre-population on edit |
| 5. Tests | Model, form, dashboard rendering tests | Full suite regression |

**Prerequisites:** None — purely additive change to an existing model and templates.
**Estimated effort:** ~2 focused sessions across 5 phases.

## Open Risks & Assumptions

- The `rule_has_at_least_one_condition` CheckConstraint expression does not reference
  `tags`; verified from models.py:199. If a future migration touches that constraint
  definition independently, it should be reviewed.
- Client-side tag population via JS scanning `data-tags` means a user who opens the
  filter bar before the page finishes rendering may see an empty dropdown momentarily
  (negligible at expected page sizes).

## Success Criteria (Summary)

- A rule with tags `production,finance` shows two indigo pills on the dashboard row and
  is correctly filtered when the user selects `production` from the `#f-tag` dropdown.
- The rule form chip widget round-trips tags correctly: chips pre-populate on edit and
  the normalised comma string is submitted and saved.
- All new tests pass and the existing `monitor` test suite has zero regressions.
