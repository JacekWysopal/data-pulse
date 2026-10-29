# Rule Tags Implementation Plan

## Overview

Add a tags field to the `Rule` model that lets users label rules with short identifiers
(e.g. `production`, `finance`, `orders`). Tags appear as coloured pills on each rule row
in the dashboard and can be filtered via a tag dropdown in the filter bar. The rule form
gets a JS chip-input widget so tags are easy to add and remove.

## Current State Analysis

- `Rule` (models.py:84) has 17 scalar fields and no tags field or related tagging model.
- The only M2M on `Rule` is the reverse of `DbtIntegration.rules` (models.py:335).
- `RuleForm` (forms.py:56) has 14 fields in `Meta.fields`; all use `forms.TextInput` or
  similar inline widgets; no external JS dependency anywhere in the project.
- The dashboard filter bar (dashboard.html:387–410) has three client-side controls
  (`#f-name`, `#f-status`, `#f-conn`) driven by a single `applyFilters()` closure
  (dashboard.html:551–615) that reads `data-*` attributes on `<tr>` rows.
- `.cond-pill` CSS class (dashboard.html:131–139) is already defined and reusable;
  the schedule pill accent variant (dashboard.html:462–467) is the visual model for tag pills.
- Last migration is `0017_apikey.py`; next will be `0018_rule_tags.py`.
- The `CheckConstraint` `rule_has_at_least_one_condition` (models.py:199) must not be
  disturbed — tags are metadata, not conditions.
- Inline vanilla JS is the established pattern; no bundler, no npm, no external JS libs.
- `rule_create` (views.py:63–83) and `rule_edit` (views.py:86–95) both use `commit=False`
  plus manual `rule.user = request.user`; no `save_m2m()` needed for a CharField.

## Desired End State

After this change a user can:
1. Assign up to 5 tags (max 30 chars each, alphanumeric + hyphen, normalised lowercase)
  to any rule via the rule form.
2. See those tags as accent-coloured pills on the rule row in the dashboard table.
3. Filter the dashboard to rules that carry a specific tag using a new `#f-tag` dropdown
  in the filter bar; the dropdown is populated by JS scanning existing `data-tags`
  attributes — no view change required.
4. Create/edit rules via the form with a chip-style tag input (type + Enter adds a chip,
  ✕ removes it; a hidden field carries the comma-joined value on submit).

Verify end state by:
- Running `python manage.py migrate` cleanly.
- Saving a rule with tags and seeing the tags round-trip through the form.
- Viewing the dashboard and confirming pills and filter work as described.

### Key Discoveries

- `monitor/models.py:199` — `CheckConstraint` on at-least-one-condition; tags column
  must not touch the constraint expression.
- `templates/monitor/dashboard.html:131–139` — `.cond-pill` reusable as-is.
- `templates/monitor/dashboard.html:462–467` — accent variant (indigo) for schedule pill;
  tag pills will use the same inline style.
- `templates/monitor/dashboard.html:551–615` — `applyFilters()` closure to extend.
- `monitor/forms.py:85–101` — `RuleForm.__init__` where new widget attrs are injected.
- `monitor/tests.py` — single test file, 4010 lines; tests follow Django `TestCase`.

## What We're NOT Doing

- No M2M `Tag` model — CharField comma-separated is the chosen approach.
- No server-side tag filter route — client-side only, consistent with existing filters.
- No third-party JS library for the chip widget.
- No autocomplete from existing tags on the form (out of scope).
- No tag admin or management UI (create/delete tags outside the rule form).
- No per-tag analytics or grouping pages.
- No migration of existing rules to add default tags.

## Implementation Approach

A single `CharField(max_length=200, blank=True, default='')` column on `Rule` stores
tags as a lowercase comma-separated string. A `tags_list` property on `Rule` splits and
strips for template use. `RuleForm` adds the field with a custom `TextInput` widget that
is enhanced by a small inline JS chip widget in `rule_form.html`. Validation happens in
`clean_tags()` in `RuleForm`. The dashboard gets a `data-tags` attribute on each `<tr>`,
a fourth `<select id="f-tag">` in the filter bar (options populated by JS on load), and
extended `applyFilters()` logic.

---

## Phase 1: Model + Migration

### Overview

Add `tags` CharField and `tags_list` property to `Rule`; generate and verify migration
`0018_rule_tags.py`.

### Changes Required

#### 1. `Rule.tags` field

**File**: `monitor/models.py`

**Intent**: Add the `tags` column to `Rule` as a simple, nullable-free CharField so
existing rules get an empty string by default without requiring a data migration.

**Contract**: Insert after `updated_at` (line ~208, before `class Meta`):
```python
tags = models.CharField(
    max_length=200,
    blank=True,
    default='',
    verbose_name='Tags',
    help_text='Comma-separated labels, e.g. production, finance',
)
```

#### 2. `Rule.tags_list` property

**File**: `monitor/models.py`

**Intent**: Provide a template-friendly way to iterate tag strings without putting
split logic in the template.

**Contract**: Add as a `@property` on `Rule` (after `last_result`):
```python
@property
def tags_list(self):
    """Return list of normalised tag strings; empty list when no tags."""
    return [t.strip() for t in self.tags.split(',') if t.strip()]
```

#### 3. Migration

**File**: `monitor/migrations/0018_rule_tags.py`

**Intent**: Generate via `makemigrations`; verify it adds only the `tags` column and
does not alter `rule_has_at_least_one_condition`.

**Contract**: Run `python manage.py makemigrations monitor --name rule_tags`; inspect
the generated file to confirm it contains exactly one `AddField` for `Rule.tags` and no
`AlterConstraint` operations.

### Success Criteria

#### Automated Verification

- `python manage.py makemigrations --check` passes with 0 pending migrations after
  `0018_rule_tags.py` is committed.
- `python manage.py migrate --run-syncdb` applies cleanly on a fresh test database.
- `python manage.py test monitor.tests.RuleTagsModelTests` passes (tests added in Phase 5).
- `python manage.py check` passes with no system check errors.

#### Manual Verification

- `python manage.py shell -c "from monitor.models import Rule; r=Rule(); r.tags='a,b'; print(r.tags_list)"` → `['a', 'b']`
- Migration file contains only `AddField` for `tags`; `rule_has_at_least_one_condition` is unchanged.

**Implementation Note**: After completing this phase, pause for manual confirmation
before proceeding to Phase 2.

---

## Phase 2: Form Field + Validation

### Overview

Add `tags` to `RuleForm`: a `TextInput` backed by `clean_tags()` that enforces max-5
tags, max-30-chars each, alphanumeric-plus-hyphen, and normalises to lowercase.

### Changes Required

#### 1. `RuleForm.Meta.fields` — add `tags`

**File**: `monitor/forms.py`

**Intent**: Include `tags` in the form field list so it is bound, validated, and saved.

**Contract**: Append `'tags'` to the end of the `Meta.fields` list (currently ending
with `'notify_slack'`).

#### 2. `RuleForm.Meta.widgets` — add `tags` widget

**File**: `monitor/forms.py`

**Intent**: Render `tags` as a plain text input; the JS chip widget in the template will
enhance it. Using `id="id_tags"` (Django default) so the JS can target it by that id.

**Contract**: Add to `Meta.widgets`:
```python
'tags': forms.TextInput(attrs={
    'class': 'form-control',
    'placeholder': 'e.g. production, finance',
    'autocomplete': 'off',
}),
```

#### 3. `RuleForm.clean_tags()` validation method

**File**: `monitor/forms.py`

**Intent**: Normalise and validate tag values: lowercase, strip whitespace, reject
tags longer than 30 chars, reject tags with characters outside `[a-z0-9-]`, reject
more than 5 tags. Return a comma-separated normalised string.

**Contract**:
```python
def clean_tags(self):
    import re
    raw = (self.cleaned_data.get('tags') or '').strip()
    if not raw:
        return ''
    parts = [t.strip().lower() for t in raw.split(',') if t.strip()]
    if len(parts) > 5:
        raise forms.ValidationError('Maximum 5 tags allowed.')
    pattern = re.compile(r'^[a-z0-9][a-z0-9\-]{0,28}[a-z0-9]$|^[a-z0-9]$')
    for tag in parts:
        if len(tag) > 30:
            raise forms.ValidationError(
                f'Tag "{tag}" exceeds 30 characters.')
        if not re.match(r'^[a-z0-9][a-z0-9\-]*[a-z0-9]$|^[a-z0-9]$', tag):
            raise forms.ValidationError(
                f'Tag "{tag}" is invalid. Use lowercase letters, digits, and hyphens only; '
                'must start and end with a letter or digit.')
    return ','.join(parts)
```

### Success Criteria

#### Automated Verification

- `python manage.py test monitor.tests.RuleTagsFormTests` passes (tests added in Phase 5).
- `python manage.py check` passes.

#### Manual Verification

- Submit the rule form with `tags = "Production, Finance!, orders"` → validation error on `Finance!`.
- Submit with `tags = "a,b,c,d,e,f"` (6 tags) → validation error.
- Submit with valid `tags = "production, finance"` → saved as `production,finance`.

**Implementation Note**: After completing this phase, pause for manual confirmation
before proceeding to Phase 3.

---

## Phase 3: Dashboard Tag Pills + Filter

### Overview

Render tag pills inside the Rule `<td>` (below the rule name link), add `data-tags`
attribute to each `<tr>`, add `#f-tag` select to the filter bar, and extend
`applyFilters()` to filter on tags.

### Changes Required

#### 1. `<tr>` `data-tags` attribute

**File**: `templates/monitor/dashboard.html`

**Intent**: Make the comma-separated tags string available as a `data-*` attribute so
the JS filter can read it without a server round-trip.

**Contract**: In the `<tr>` that already has `data-name`, `data-status`, `data-conn`
(~line 427), add: `data-tags="{{ item.rule.tags }}"`.

#### 2. Tag pills inside the Rule `<td>`

**File**: `templates/monitor/dashboard.html`

**Intent**: Show tags as small accent-coloured pills below the rule name link, reusing
the existing `.cond-pill` with the same indigo accent style used for schedule pills.
Tags go inside the existing Rule `<td>` to avoid adding a new column.

**Contract**: After the `<a>` rule-link in the Rule `<td>` (~line 432), add:
```django
{% if item.rule.tags_list %}
<div style="margin-top:3px">
  {% for tag in item.rule.tags_list %}
  <span class="cond-pill" style="color:var(--accent-hover);border-color:rgba(99,102,241,0.25);background:var(--accent-dim)">{{ tag }}</span>
  {% endfor %}
</div>
{% endif %}
```

#### 3. `#f-tag` select in the filter bar

**File**: `templates/monitor/dashboard.html`

**Intent**: Add a fourth dropdown to the filter bar for tag selection. Options are
populated by JS on page load by scanning `data-tags` attributes — no view change
needed.

**Contract**: After the `#f-conn` `<select>` and before `#f-clear` in the filter bar
(~line 403), add:
```html
<select class="filter-select" id="f-tag">
  <option value="">All tags</option>
</select>
```

#### 4. `applyFilters()` — tag filter logic + `#f-tag` population

**File**: `templates/monitor/dashboard.html`

**Intent**: Populate `#f-tag` with unique tags from all rows on page load, restore tag
from URL param `?tag=`, include tag match in `applyFilters()`, persist `?tag=` in URL.

**Contract** — extend the existing JS closure (dashboard.html:548–615):

Add after `const fConn = …`:
```js
const fTag = document.getElementById('f-tag');
```

Add after URL-param restoration block (after `if (params.get('conn'))`):
```js
if (params.get('tag')) fTag.value = params.get('tag');
```

Populate tag options (add after fTag declaration, run once on load):
```js
// Populate #f-tag from data-tags attributes
(function() {
  const tagSet = new Set();
  rows.forEach(row => {
    (row.dataset.tags || '').split(',').forEach(t => {
      const trimmed = t.trim();
      if (trimmed) tagSet.add(trimmed);
    });
  });
  Array.from(tagSet).sort().forEach(tag => {
    const opt = document.createElement('option');
    opt.value = tag;
    opt.textContent = tag;
    fTag.appendChild(opt);
  });
  if (params.get('tag')) fTag.value = params.get('tag');
}());
```

In `applyFilters()` — add `tag` variable and `tagMatch`:
```js
const tag = fTag.value;
// inside rows.forEach:
const tagMatch = !tag || (row.dataset.tags || '').split(',').map(s => s.trim()).includes(tag);
const show = nameMatch && statusMatch && connMatch && tagMatch;
```

Active-count badge — add `tag` to the active array:
```js
const active = [q, status, conn, tag].filter(Boolean).length;
```

URL persistence — add:
```js
if (tag) p.set('tag', tag);
```

Wire event listener:
```js
fTag.addEventListener('change', applyFilters);
```

Wire clear button (existing `fClear` handler sets fields to `''`):
```js
// In fClear click handler: add fTag.value = '';
```

### Success Criteria

#### Automated Verification

- `python manage.py test monitor.tests.RuleTagsDashboardTests` passes (Phase 5).
- `python manage.py check` passes.

#### Manual Verification

- A rule with `tags = "production,finance"` shows two indigo pills below the rule name.
- A rule with no tags shows no pills and no empty space.
- The `#f-tag` dropdown lists all unique tags across all user rules.
- Selecting a tag hides rows that do not include it.
- Clicking ✕ Clear resets the tag filter.
- `?tag=production` URL parameter restores the tag filter on page load.

**Implementation Note**: After completing this phase, pause for manual confirmation
before proceeding to Phase 4.

---

## Phase 4: Rule Form Chip Widget

### Overview

Enhance the `tags` text input in `rule_form.html` with a self-contained vanilla JS
chip widget: existing tags render as removable chips; the user types a tag and presses
Enter to add it; a hidden `<input name="tags">` carries the comma-joined value on
submit.

### Changes Required

#### 1. Tag chip widget HTML + JS in `rule_form.html`

**File**: `templates/monitor/rule_form.html`

**Intent**: Replace the plain `{{ form.tags }}` render with a chip container that
provides a better UX while keeping the same `name="tags"` payload for the server.

**Contract**: Locate where `form.tags` is rendered (or add it near the `notify_on_fail`
block). Replace the default `{{ form.tags }}` with:

```html
<div class="mb-3" id="tags-field-group">
  <label class="form-label">Tags</label>
  <div id="tag-chip-container" style="
    display:flex; flex-wrap:wrap; gap:4px; align-items:center;
    border:1px solid var(--border); border-radius:6px;
    padding:6px 8px; background:var(--bg-elevated); min-height:38px;
    cursor:text;" onclick="document.getElementById('tag-input').focus()">
    <!-- chips inserted here by JS -->
    <input type="text" id="tag-input" placeholder="Add tag…" autocomplete="off"
      style="border:none;outline:none;background:transparent;
             font-size:0.85rem;color:var(--text-primary);flex:1;min-width:80px;">
  </div>
  <input type="hidden" name="tags" id="id_tags" value="{{ form.tags.value|default:'' }}">
  <div class="form-text">Up to 5 tags. Letters, digits, hyphens. Press Enter or comma to add.</div>
  {% if form.tags.errors %}
    <div class="invalid-feedback d-block">{{ form.tags.errors|join:", " }}</div>
  {% endif %}
</div>
```

Add inline script (consistent with existing inline scripts in the file):

```html
<script>
(function() {
  const container = document.getElementById('tag-chip-container');
  const input     = document.getElementById('tag-input');
  const hidden    = document.getElementById('id_tags');
  const MAX_TAGS  = 5;
  const MAX_LEN   = 30;
  const VALID     = /^[a-z0-9][a-z0-9\-]*[a-z0-9]$|^[a-z0-9]$/;

  let tags = hidden.value ? hidden.value.split(',').map(t => t.trim()).filter(Boolean) : [];

  function renderChips() {
    // Remove existing chips (not the input)
    container.querySelectorAll('.tag-chip').forEach(c => c.remove());
    tags.forEach((tag, i) => {
      const chip = document.createElement('span');
      chip.className = 'tag-chip cond-pill';
      chip.style.cssText = 'color:var(--accent-hover);border-color:rgba(99,102,241,0.25);background:var(--accent-dim);cursor:default';
      chip.innerHTML = tag + ' <span style="cursor:pointer;margin-left:2px" data-i="' + i + '">✕</span>';
      chip.querySelector('span').addEventListener('click', function() {
        tags.splice(parseInt(this.dataset.i), 1);
        renderChips();
        syncHidden();
      });
      container.insertBefore(chip, input);
    });
    input.placeholder = tags.length >= MAX_TAGS ? '' : 'Add tag…';
    input.disabled = tags.length >= MAX_TAGS;
  }

  function syncHidden() {
    hidden.value = tags.join(',');
  }

  function addTag(raw) {
    const tag = raw.trim().toLowerCase();
    if (!tag) return;
    if (tags.length >= MAX_TAGS) return;
    if (tag.length > MAX_LEN) { input.style.borderBottom = '2px solid var(--error)'; return; }
    if (!VALID.test(tag)) { input.style.borderBottom = '2px solid var(--error)'; return; }
    if (tags.includes(tag)) { input.value = ''; return; }
    input.style.borderBottom = '';
    tags.push(tag);
    input.value = '';
    renderChips();
    syncHidden();
  }

  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag(this.value);
    }
    if (e.key === 'Backspace' && this.value === '' && tags.length) {
      tags.pop();
      renderChips();
      syncHidden();
    }
  });

  input.addEventListener('blur', function() {
    if (this.value.trim()) addTag(this.value);
  });

  renderChips();
}());
</script>
```

### Success Criteria

#### Automated Verification

- `python manage.py test monitor.tests.RuleTagsFormTests` passes (Phase 5 adds these).
- `python manage.py check` passes.

#### Manual Verification

- Open a new rule form: tag input container renders with placeholder "Add tag…".
- Type `production` + Enter → chip appears, hidden input shows `production`.
- Type `finance` + Enter → second chip appears, hidden input shows `production,finance`.
- Click ✕ on `production` → chip removed, hidden input shows `finance`.
- Type 6th tag → input is disabled.
- Type invalid tag `Finance!` → input shows red border; chip not added.
- Submit the form → rule saved with correct tags; chips rerender on edit.
- Tags appear as pills on the dashboard rule row.

**Implementation Note**: After completing this phase, pause for manual confirmation
before proceeding to Phase 5.

---

## Phase 5: Tests

### Overview

Add `monitor/tests.py` test classes covering model, form validation, dashboard
rendering, and chip widget round-trip.

### Changes Required

#### 1. `RuleTagsModelTests`

**File**: `monitor/tests.py`

**Intent**: Cover `Rule.tags` field defaults, `tags_list` property, and the
constraint is unaffected.

**Contract**: Add `class RuleTagsModelTests(TestCase)` covering:
- `tags` defaults to empty string for a new Rule.
- `tags_list` returns `[]` when tags is `''`.
- `tags_list` returns normalised list for `'production,finance'`.
- `tags_list` ignores empty segments (e.g. `',production,'`).
- Setting `tags` does not violate `rule_has_at_least_one_condition` when a valid
  condition is present.

#### 2. `RuleTagsFormTests`

**File**: `monitor/tests.py`

**Intent**: Cover all `clean_tags()` validation branches.

**Contract**: Add `class RuleTagsFormTests(TestCase)` covering:
- Valid single tag `'production'` → cleaned to `'production'`.
- Valid multi-tag `'Production, Finance'` → cleaned to `'production,finance'`.
- 5 tags → valid.
- 6 tags → `ValidationError`.
- Tag with invalid char `'Finance!'` → `ValidationError`.
- Tag `'a-b'` (hyphen mid-tag) → valid.
- Tag starting with hyphen `'-tag'` → `ValidationError`.
- Tag of length 30 → valid.
- Tag of length 31 → `ValidationError`.
- Empty `tags` field → cleaned to `''`.

#### 3. `RuleTagsDashboardTests`

**File**: `monitor/tests.py`

**Intent**: Verify that the dashboard renders `data-tags` on `<tr>` rows and that
tag pills render for rules with tags.

**Contract**: Add `class RuleTagsDashboardTests(TestCase)` with a logged-in user and a
rule with `tags='production,finance'`; assert:
- Response contains `data-tags="production,finance"`.
- Response contains `>production<` inside a `cond-pill` span.
- Response contains `>finance<` inside a `cond-pill` span.
- A rule with `tags=''` does not produce a tags `<div>` in the Rule cell.

### Success Criteria

#### Automated Verification

- `python manage.py test monitor.tests.RuleTagsModelTests` passes.
- `python manage.py test monitor.tests.RuleTagsFormTests` passes.
- `python manage.py test monitor.tests.RuleTagsDashboardTests` passes.
- Full test suite `python manage.py test monitor` passes (no regressions).

#### Manual Verification

- `python manage.py test monitor` exits 0 with all existing tests still green.

---

## Testing Strategy

### Unit Tests

- `Rule.tags` field: default, `tags_list` property, empty/whitespace edge cases.
- `RuleForm.clean_tags()`: valid/invalid characters, max-5, max-30-chars, normalisation.

### Integration Tests

- Dashboard view: `data-tags` attribute present, pills rendered.

### Manual Testing Steps

1. Create a rule with tags `production, finance` — verify pills on dashboard.
2. Edit the rule — verify chips pre-populate in the form.
3. Filter by `production` — verify only tagged rules are visible; clear restores all.
4. Navigate to `?tag=production` directly — filter is restored.
5. Create a rule with no tags — confirm no pill space appears.
6. Try submitting 6 tags or an invalid tag — verify error messages.

## Performance Considerations

`Rule.tags` is a plain CharField scanned client-side. Per-user rule counts are small
(no pagination). No index is needed on the tags column for this use case.

## Migration Notes

The migration adds a single nullable-free `CharField` with `default=''`. All existing
rules get an empty string. No data migration is required. The `rule_has_at_least_one_condition`
`CheckConstraint` expression does not reference `tags` and is not altered.

## References

- Related research: `context/changes/rule-tags/research.md`
- Rule model: `monitor/models.py:84`
- Rule CheckConstraint: `monitor/models.py:199`
- RuleForm: `monitor/forms.py:56`
- Dashboard filter bar: `templates/monitor/dashboard.html:387`
- Dashboard applyFilters: `templates/monitor/dashboard.html:551`
- `.cond-pill` CSS: `templates/monitor/dashboard.html:131`
- Schedule pill accent variant: `templates/monitor/dashboard.html:462`
- Existing tests: `monitor/tests.py`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Model + Migration

#### Automated

- [ ] 1.1 makemigrations --check passes with 0 pending migrations
- [ ] 1.2 migrate applies cleanly on fresh test database
- [ ] 1.3 RuleTagsModelTests pass
- [ ] 1.4 manage.py check passes

#### Manual

- [ ] 1.5 Shell smoke-test: tags_list returns correct list
- [ ] 1.6 Migration file contains only AddField for tags; constraint unchanged

### Phase 2: Form Field + Validation

#### Automated

- [ ] 2.1 RuleTagsFormTests pass
- [ ] 2.2 manage.py check passes

#### Manual

- [ ] 2.3 Form rejects invalid tag characters
- [ ] 2.4 Form rejects more than 5 tags
- [ ] 2.5 Form saves normalised lowercase comma-separated string

### Phase 3: Dashboard Tag Pills + Filter

#### Automated

- [ ] 3.1 RuleTagsDashboardTests pass
- [ ] 3.2 manage.py check passes

#### Manual

- [ ] 3.3 Tag pills render on rule row
- [ ] 3.4 No pills for rules with no tags
- [ ] 3.5 f-tag dropdown lists unique tags
- [ ] 3.6 Tag filter hides non-matching rows
- [ ] 3.7 Clear button resets tag filter
- [ ] 3.8 ?tag= URL param restores filter on load

### Phase 4: Rule Form Chip Widget

#### Automated

- [ ] 4.1 RuleTagsFormTests pass (form round-trip)
- [ ] 4.2 manage.py check passes

#### Manual

- [ ] 4.3 Chip adds on Enter/comma
- [ ] 4.4 Chip removes on ✕ click
- [ ] 4.5 Backspace removes last chip when input empty
- [ ] 4.6 6th tag disables input
- [ ] 4.7 Invalid tag shows red border, not added
- [ ] 4.8 Edit form pre-populates chips from saved tags

### Phase 5: Tests

#### Automated

- [ ] 5.1 RuleTagsModelTests pass
- [ ] 5.2 RuleTagsFormTests pass
- [ ] 5.3 RuleTagsDashboardTests pass
- [ ] 5.4 Full test suite passes with no regressions
