---
date: 2026-10-29T11:34:08+00:00
researcher: worker-subagent
git_commit: 991d6ae9346728d5feecfd56d8cac6ddd7888da6
branch: dev
repository: data-pulse
topic: "Rule tags — CharField vs M2M, dashboard filter, form widget, pill display"
tags: [research, codebase, monitor, Rule, dashboard, forms]
status: complete
last_updated: 2026-10-29
last_updated_by: worker-subagent
---

# Research: Rule tags — CharField vs M2M, dashboard filter, form widget, pill display

**Date**: 2026-10-29T11:34:08+00:00
**Researcher**: worker-subagent
**Git Commit**: 991d6ae9346728d5feecfd56d8cac6ddd7888da6
**Branch**: dev
**Repository**: data-pulse

## Research Question

Four questions for the `rule-tags` change:

1. Simple `CharField` (comma-separated) versus a separate `Tag` M2M model — tradeoffs for this codebase.
2. Dashboard filter bar — how to add a tag filter alongside the existing name / status / connection filters.
3. Form widget for tag input: text input with JS chips versus alternatives.
4. Tags displayed as small pills on the rule row in the dashboard table.

---

## Summary

A comma-separated `CharField` is the lower-friction option for this codebase: no new
model, no migration join table, no `save_m2m()` ceremony, and it keeps `RuleForm`
consistent with every other field already there. Filtering in the dashboard can be
done client-side (already the established pattern for name/status/connection) by
adding a `data-tags` attribute to each `<tr>` and wiring a fourth `<select>` (or text
input) in the existing `.filter-bar`. Tag pills are rendered with the existing
`.cond-pill` CSS class — no new CSS needed. A plain text input in the form with
comma-separated entry requires the least new JavaScript; a lightweight chip widget
requires modest JS but improves UX. Both are viable; the chip approach is the nicer
finish.

---

## Detailed Findings

### 1. CharField comma-separated vs M2M Tag model

**Current `Rule` model** (`monitor/models.py:84–217`):

- `Rule` has 17 scalar fields (all `CharField`, `TextField`, `BooleanField`,
  `DateTimeField`, `PositiveIntegerField`, or FK). The only existing M2M on `Rule`
  comes from the *reverse* of `DbtIntegration.rules` (`monitor/models.py:335`).
- There is no `Tag` or tagging model anywhere in `monitor/models.py` (inspected full
  file, 0 matches for "Tag" or "tags").

**CharField option** — add `tags = models.CharField(max_length=500, blank=True, default='')` to `Rule`:
- Pro: one `ALTER TABLE` column; no join table; one migration.
- Pro: `RuleForm` field is a plain `TextInput` — consistent with existing `schema_name`, `timestamp_column`, etc.
- Pro: filtering is a Python `.split(',')` in the view or `data-tags` string-contains in JS.
- Con: querying is a `LIKE '%tag%'` scan (acceptable for per-user rule counts, which are typically small — each user sees only their own rules).
- Con: ordering / uniqueness / autocomplete require application logic.

**M2M Tag model** option:
- Pro: proper relational design; easy to enumerate all tags for a user; autocomplete is a queryset.
- Con: new `Tag` model + migration + join table migration = 2 new migrations.
- Con: `RuleForm` must add an M2M field; Django M2M in `ModelForm.save()` requires either `commit=False` + `save_m2m()` or `commit=True`. The `dbt_integration_create` view already handles this pattern (`monitor/views.py:364`) but `rule_create` and `rule_edit` currently use `commit=False` + manual `rule.user = request.user` + `rule.save()`, so `form.save_m2m()` would need to be appended in both views (`monitor/views.py:75–83` and `monitor/views.py:88–95`).
- Con: the dashboard `dashboard()` view (`monitor/views.py:31–56`) does not currently pass a tag list to the template, so the filter `<select>` would need a queryset of distinct tags from the user's rules.

**Verdict for this codebase**: CharField is the pragmatic fit. The expected per-user
rule count is small (no pagination exists), making LIKE-style filtering acceptable.
M2M is architecturally cleaner but adds meaningful plumbing. Either choice is
reversible.

---

### 2. Dashboard filter bar — adding a tag filter

**Existing filter bar** (`templates/monitor/dashboard.html:387–410`):

The filter bar has three active controls, all driven entirely by client-side JS
(`dashboard.html:550–615`):

| Control id | Type | Filters on |
|---|---|---|
| `#f-name` | `<input type="text">` | `tr[data-name]` (rule name, lowercased) |
| `#f-status` | `<select>` | `tr[data-status]` |
| `#f-conn` | `<select>` | `tr[data-conn]` |

The `applyFilters()` function at `dashboard.html:567` iterates all `tbody tr[data-name]`
rows and hides rows that do not match. URL-param persistence is handled via
`URLSearchParams` and `history.replaceState`.

**How to add a tag filter**:

Option A — client-side `<select>` for a single tag (consistent with `#f-conn`):
1. In `dashboard()` view (`views.py:31`): collect all distinct tags from the user's
   rules and pass them to the template (or derive them in JS from `data-tags`).
2. In the template `<tr>` (`dashboard.html:425–427`): add
   `data-tags="{{ item.rule.tags }}"` (comma-separated string or JSON list).
3. In the filter bar (`dashboard.html:400–403`): add a `<select id="f-tag">` populated
   from unique tag values.
4. In `applyFilters()` (`dashboard.html:567`): add `const tag = fTag.value;` and
   `const tagMatch = !tag || row.dataset.tags.split(',').map(s => s.trim()).includes(tag);`

Option B — client-side text input (consistent with `#f-name`):
- Simpler markup; filter on substring of `data-tags`.

Either option requires no new URL route and no server-side filtering logic — it
follows the fully-established client-side pattern. Server-side `?tag=` filtering is
possible but would break the current architecture where the view returns all the
user's rules and JS does the filtering.

Tag `<select>` options can be derived purely in JS by scanning existing `data-tags`
attributes on load, avoiding any view changes if the CharField approach is chosen.

---

### 3. Form widget for tag input

**Existing `RuleForm`** (`monitor/forms.py:56–145`):

- All text fields use `forms.TextInput` with `attrs={'class': 'form-control'}`.
- The form has 14 fields in `Meta.fields` (`forms.py:59`); all widgets are declared
  inline in `Meta.widgets`.
- There is no existing JS chip/token input widget in the codebase (0 matches for
  "chip", "token", "tagify", "choices.js" in all templates and static files).

**Option A — plain `TextInput`, comma-separated** (e.g. "production, finance, orders"):
- Zero new JS. User types a comma-separated string; server splits on `,` and strips
  whitespace to validate/normalise.
- Consistent with `timestamp_column`, `schema_name`, etc.
- UX: no visual chips, but clear with a help-text hint.

**Option B — JS chip widget built from scratch** (small, inline):
- The `rule_form.html` template already has substantial inline `<script>` blocks
  (`rule_form.html` from line ~350 onward for schema browser and template gallery).
  A self-contained chip widget fits the same pattern.
- Approach: a `<div class="tag-input-container">` renders existing tags as removable
  `<span>` chips and has an `<input>` for adding new ones. On submit a hidden
  `<input type="hidden" name="tags">` is populated with the comma-joined list.
- No third-party library required; ~40 lines of vanilla JS.
- CSS can reuse `.cond-pill` for the chip appearance.

**Option C — third-party library** (e.g. Tagify, Tom Select):
- Not present in the project; adding a CDN or bundled dependency would be the first
  external JS dependency in the project. Not recommended unless complexity warrants it.

**Recommendation**: Option B (inline chip widget) gives the best UX with no external
dependency and is consistent with the project's pattern of inline vanilla JS. Option A
is acceptable as a simpler first pass.

---

### 4. Tag pills display on the rule row

**Existing pill pattern** (`templates/monitor/dashboard.html:131–139`, `450–458`):

The `.cond-pill` CSS class is already defined and used for condition badges (min rows,
freshness). Its definition:

```css
.cond-pill {
  display: inline-flex; align-items: center; gap: 4px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 2px 8px;
  font-size: 0.71rem;
  color: var(--text-secondary);
  font-family: 'JetBrains Mono', monospace;
  margin: 1px 2px 1px 0;
}
```
(`dashboard.html:131–139`)

Tags as pills would fit into the same `<td>` that currently shows conditions, or a
dedicated new `<td>`. The minimal change is a new column — but adding a column
increases table width; alternatively tags can be added below the rule name in the
Rule cell.

**Rendering in template** — for a CharField, after splitting:
```django
{% for tag in item.rule.tags_list %}
  <span class="cond-pill" style="color:var(--accent-hover);border-color:rgba(99,102,241,0.25);background:var(--accent-dim)">{{ tag }}</span>
{% endfor %}
```
Where `tags_list` is a `@property` on `Rule` that returns `[t.strip() for t in self.tags.split(',') if t.strip()]`.

Using the existing accent variant of `.cond-pill` (same inline style used for the
schedule pill at `dashboard.html:463–467`) visually differentiates tags from
condition pills without new CSS.

The dashboard table currently has 8 columns (Rule, Source, Table, Conditions,
Schedule, Status, Measured values, actions). Adding a Tags column as column 5 or
appending tags below the rule name (inside the Rule `<td>`) avoids widening the table.

---

## Code References

- `monitor/models.py:84` — `class Rule(models.Model)` — all current fields; no tags field exists.
- `monitor/models.py:335` — `DbtIntegration.rules` — the only existing M2M on Rule (reverse side).
- `monitor/models.py:199` — `CheckConstraint` on `rule_has_at_least_one_condition` — must remain satisfied after adding tags (tags must not be counted as a condition; they are metadata).
- `monitor/forms.py:56–59` — `RuleForm` and its `Meta.fields` list — tags field to be appended.
- `monitor/forms.py:85–101` — `RuleForm.__init__` — where user-scoped querysets and JS attrs are injected.
- `monitor/views.py:63–83` — `rule_create` — uses `commit=False`; would need `form.save_m2m()` only if M2M is chosen.
- `monitor/views.py:86–95` — `rule_edit` — same pattern as `rule_create`.
- `monitor/views.py:31–56` — `dashboard()` — builds `rule_status` list; no tag data passed today.
- `templates/monitor/dashboard.html:387–410` — filter bar with 3 controls (`#f-name`, `#f-status`, `#f-conn`).
- `templates/monitor/dashboard.html:425–427` — `<tr>` data attributes (`data-name`, `data-status`, `data-conn`); `data-tags` to be added.
- `templates/monitor/dashboard.html:551–615` — `applyFilters()` JS function; tag filter logic to be added here.
- `templates/monitor/dashboard.html:131–139` — `.cond-pill` CSS — reusable for tag pills.
- `templates/monitor/dashboard.html:462–467` — schedule pill with accent color variant — visual model for tag pills.
- `templates/monitor/rule_form.html` — form template; tag input widget to be added, consistent with existing field pattern.

## Architecture Insights

- Client-side filtering is the established and exclusive pattern for dashboard row
  filtering. The three existing filters (`#f-name`, `#f-status`, `#f-conn`) all work
  on `data-*` attributes on `<tr>` rows and are wired together in a single
  `applyFilters()` closure. A tag filter must follow the same pattern to keep the
  architecture coherent.
- `RuleForm` is a `ModelForm` with inline JS for schema browsing and template
  gallery. The chip widget pattern is the natural extension.
- Inline vanilla JS is used everywhere; no bundler, no npm, no external JS libraries
  in the project. Any tag input widget must be self-contained.
- URL params (`?q=`, `?status=`, `?conn=`) are persisted by `history.replaceState`
  for shareable filtered URLs. A `?tag=` param should follow the same mechanism.
- The `Rule` model has a `CheckConstraint` (`rule_has_at_least_one_condition`) that
  enforces at least one condition. Tags are metadata, not conditions, so they must
  not affect this constraint.
- The last migration is `0017_apikey.py`; the next migration for tags will be `0018`.

## Historical Context (from prior changes)

No prior `context/changes/` or `context/archive/` artifacts relate to tagging.
The `DbtIntegration.rules` M2M (`monitor/models.py:335`) and its corresponding
`form.save_m2m()` call (`monitor/views.py:364`) demonstrate the project already
handles M2M in one location; that pattern is the reference if M2M is chosen.

## Related Research

No related research artifacts found under `context/changes/` or `context/archive/`.

## Open Questions

1. **New table column vs inline-in-Rule-cell**: A dedicated Tags column widens the table. Placing tags below the rule name in the Rule `<td>` is more compact but departs from the current table structure. This is a layout decision for planning.
2. **Tag validation/normalisation**: Should tags be lowercased and stripped on save (server-side `clean()` in `RuleForm`), or stored as entered? No prior precedent in this codebase.
3. **Max tag count / length**: No hard limit is defined. A reasonable constraint (e.g. max 10 tags, each ≤ 50 chars) should be defined in `clean()` to prevent abuse.
4. **Filter `<select>` vs free-text**: A `<select>` populated from all unique tags on the user's rules requires either a view change (queryset of distinct tags) or JS that scans `data-tags` on load. The JS-scan approach needs no view change and is consistent with the existing architecture.
