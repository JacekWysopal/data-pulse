# Rule Live Preview — Implementation Plan

## Overview

Add a "Test query" button to the rule form that lets a user run the rule logic against their selected connection and see results inline — status (OK/FAIL/ERROR), measured values (row count, age), and up to 3 sample rows — before saving the rule. No `CheckRun` or `RuleResult` is persisted; the preview is purely stateless.

## Current State Analysis

The services layer already separates DB-writing orchestrators (`run_single_rule`, `run_checks_for_user`) from stateless primitives (`_check_rule`, `_check_volume_freshness`, `_check_custom_sql`). The primitives return a plain dict with `{status, row_count, last_record_age_hours, error_message, sample_rows}` and perform no ORM writes. A `preview_rule()` function can wrap them without touching the DB.

All existing inline API endpoints (`api_schema_tables`, `api_schema_columns`, `api_templates`) live in `monitor/views.py` with `@login_required` and follow Django session auth. The rule form already uses `fetch()` with session cookies for two AJAX calls. Preview must follow the same session-auth pattern, placing the endpoint in `monitor/urls.py`.

The form UI already has a `{% csrf_token %}` tag; the existing `fetch` calls are GET-only and do not send CSRF headers. The preview POST must include `X-CSRFToken`.

### Key Discoveries

- `monitor/services.py:193–249` — `run_single_rule` always creates `CheckRun` + `RuleResult` and fires notifications; cannot be used for preview.
- `monitor/services.py:~165` (`_check_rule`) — pure dispatcher, no ORM. `_check_volume_freshness` and `_check_custom_sql` each return the needed response dict.
- `monitor/urls.py:1–56` — no preview route exists; will be added as `api/preview/`.
- `monitor/views.py:api_schema_tables` — pattern to follow: `@login_required @require_GET` + `JsonResponse`; preview uses `@require_POST`.
- `templates/monitor/rule_form.html:~370` — `fetch('/api/schema/${connId}/tables/')` pattern to follow for the preview button JS.
- The preview endpoint receives rule parameters in the POST body (no `rule_id`), because the "Add Rule" form fires before the rule is saved. The "Edit Rule" form can send the same payload; no special handling needed.

## Desired End State

- `POST /api/preview/` (session auth, `@login_required`) accepts `{connection_id, rule_type, schema_name, table_name, custom_sql, min_row_count, timestamp_column, max_age_hours}` and returns `{status, row_count, last_record_age_hours, error_message, sample_rows}` (first 3 rows only).
- `preview_rule(params, user)` in `services.py` is a stateless function: resolves and ownership-checks the connection, builds a transient Rule-like object, calls `_check_rule`, returns the dict. No DB writes.
- The rule form displays a "Test query" button below the Monitoring conditions section (Volume/Freshness) and below the SQL editor section (Custom SQL). Clicking it fires the POST, then renders an inline result card with status badge, measured values, and sample row table.
- No `CheckRun`, no `RuleResult`, no email or Slack notification is triggered.

### Key Discoveries (Desired-End-State verification):

- `sample_rows` in the response must be limited to the first 3 rows — the `_check_rule` helpers return up to 5; the preview endpoint slices `[:3]` before serialising.
- The ownership guard uses `Connection.objects.get(pk=connection_id, user=user)` — consistent with `api_schema_tables` which uses `get_object_or_404(Connection, pk=conn_id, user=request.user)`.

## What We're NOT Doing

- No `CheckRun` or `RuleResult` written for the preview call.
- No email or Slack notification triggered by the preview.
- No `rule_id` lookup — the endpoint works purely from POST-body params.
- No Bearer-token (`@require_api_key`) variant of the preview endpoint.
- No dedicated preview model or history of previews.
- No changes to `api_urls.py` or the existing REST API surface.

## Implementation Approach

Four narrow phases, each independently deployable and verifiable:

1. Add a `preview_rule(params, user)` function in `services.py` — stateless, uses `_check_rule`, returns a plain dict.
2. Add `POST /api/preview/` view in `views.py` + register in `urls.py` — JSON in, JSON out, session auth, ownership check, slices `sample_rows` to 3.
3. Add "Test query" button + JS + result card to `rule_form.html` — fires the POST, renders inline result.
4. Add/update tests covering the service function, endpoint behaviour, and ownership guard.

---

## Phase 1: `preview_rule()` in services.py

### Overview

Add a stateless `preview_rule(params: dict, user) -> dict` public function to `monitor/services.py`. It resolves the connection, enforces ownership, constructs a transient Rule-like namespace, calls the existing `_check_rule` primitive, and returns the result dict. No ORM writes.

### Changes Required

#### 1. `preview_rule` function

**File**: `monitor/services.py`

**Intent**: Provide a public, side-effect-free entry point for the preview endpoint. It must resolve and own-check the connection, build a transient object that satisfies the interface expected by `_check_rule`, call that primitive, and return its dict unchanged. All error conditions (connection not found, wrong owner, missing URL, DB error) must be representable in the returned dict so the caller needs no try/except.

**Contract**:

```python
def preview_rule(params: dict, user) -> dict:
    """
    Run rule logic against the given connection without persisting anything.

    params keys (all optional except connection_id):
        connection_id   int
        rule_type       str  ('volume_freshness' | 'custom_sql')
        schema_name     str
        table_name      str
        custom_sql      str
        min_row_count   int | None
        timestamp_column str
        max_age_hours   int | None

    Returns a dict:
        status                  str  (RuleResult.Status value)
        row_count               int | None
        last_record_age_hours   float | None
        error_message           str
        sample_rows             list | None   (at most 3 entries)
    """
```

The function must:
- Look up `Connection` with `pk=connection_id, user=user` — return an ERROR dict if not found.
- Call `conn_obj.get_database_url()` — return an ERROR dict if empty.
- Build a `types.SimpleNamespace` (or equivalent) with the fields that `_check_rule` accesses on `rule`: `rule_type`, `schema_name`, `table_name`, `custom_sql`, `min_row_count`, `timestamp_column`, `max_age_hours`.
- Call `_open_conn`, `_check_rule(conn, rule_ns, provider)`, close the connection.
- Slice `result['sample_rows']` to `[:3]` before returning.
- Catch `MonitoredDbError` and return an ERROR dict.
- Import `types` (stdlib) at the top of the file.

### Success Criteria

#### Automated Verification

- `python manage.py test monitor.tests.PreviewRuleServiceTest` — all unit tests pass (mocked connection).
- `python manage.py check` — no system check errors.

#### Manual Verification

- Calling `preview_rule({'connection_id': <valid_id>, 'rule_type': 'volume_freshness', 'schema_name': 'public', 'table_name': 'orders', 'min_row_count': 1}, user)` in a Django shell against a real connection returns a dict with `status`, `row_count`, `error_message`.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding to Phase 2.

---

## Phase 2: POST /api/preview/ endpoint

### Overview

Add a `preview_rule_view` view to `monitor/views.py` and register it at `api/preview/` in `monitor/urls.py`. The view is `@login_required @require_POST`, parses a JSON body, calls `services.preview_rule(params, request.user)`, and returns `JsonResponse`. Input validation: `connection_id` is required and must be an integer; all other fields are optional.

### Changes Required

#### 1. Import `preview_rule` in views.py

**File**: `monitor/views.py`

**Intent**: Make the new service function available in the views module without altering any existing imports.

**Contract**: Add `preview_rule` to the existing import line from `.services`:

```python
from .services import get_schema_columns, get_schema_tables, preview_rule, run_all_checks, run_checks_for_user, run_single_rule
```

#### 2. `preview_rule_view` view

**File**: `monitor/views.py`

**Intent**: Accept POST JSON, call `services.preview_rule`, return JSON. Enforce session auth and reject missing/non-integer `connection_id` with a 400. Place the view near the other inline API views (`api_schema_tables`, `api_schema_columns`, `api_templates`).

**Contract**:

```python
@login_required
@require_POST
def preview_rule_view(request):
    """AJAX: preview a rule against a connection without saving anything.

    POST /api/preview/
    Body (JSON): {connection_id, rule_type?, schema_name?, table_name?,
                  custom_sql?, min_row_count?, timestamp_column?, max_age_hours?}
    Returns: {status, row_count, last_record_age_hours, error_message, sample_rows}
    """
```

- Parse `request.body` as JSON; return `JsonResponse({'error': 'Invalid JSON'}, status=400)` on failure.
- Validate `connection_id` is present and integer-castable; return `{'error': 'connection_id required'}` status 400 otherwise.
- Cast `min_row_count` and `max_age_hours` to int/None when present.
- Call `preview_rule(params, request.user)` and return `JsonResponse(result)`.

#### 3. URL registration

**File**: `monitor/urls.py`

**Intent**: Register the new view at `api/preview/` alongside the other session-auth inline API paths.

**Contract**: Add one line in the `# Schema introspection` block or immediately after it:

```python
path('api/preview/', views.preview_rule_view, name='api_preview_rule'),
```

### Success Criteria

#### Automated Verification

- `python manage.py test monitor.tests.PreviewRuleViewTest` — all view tests pass.
- `python manage.py check` — no system check errors.

#### Manual Verification

- `curl -X POST http://localhost:8000/api/preview/ -b session_cookie -H 'X-CSRFToken: ...' -H 'Content-Type: application/json' -d '{"connection_id": 1, "rule_type": "volume_freshness", "schema_name": "public", "table_name": "orders", "min_row_count": 1}'` returns a JSON response with `status`, `row_count`, `error_message`.
- POST without `connection_id` returns HTTP 400.
- POST with another user's `connection_id` returns `status: ERROR` (not HTTP 403) — ownership guard via service layer.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding to Phase 3.

---

## Phase 3: "Test query" button + JS + result card in rule_form.html

### Overview

Add a "Test query" button below the Monitoring conditions section (in `#vf-section`) and below the SQL editor (in `#custom-sql-section`). Clicking it collects form field values, POSTs to `/api/preview/`, and renders an inline result card. The result card shows: a coloured status badge, `row_count` and `last_record_age_hours` if present, `error_message` if any, and a compact table of `sample_rows` (max 3).

### Changes Required

#### 1. CSS for result card

**File**: `templates/monitor/rule_form.html`

**Intent**: Add minimal styles for the preview result card within `{% block extra_head %}`. Reuse existing CSS variables (`--ok`, `--fail`, `--error`, `--bg-elevated`, `--border`, `--text-muted`, `--radius`).

**Contract**: Add inside the existing `<style>` block:

```css
.preview-card {
  margin-top: 1rem;
  padding: 10px 14px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  font-size: 0.82rem;
}
.preview-badge {
  display: inline-block;
  font-size: 0.7rem; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase;
  padding: 2px 8px; border-radius: 4px;
  margin-bottom: 6px;
}
.preview-badge.ok   { background: rgba(34,197,94,0.15); color: var(--ok); }
.preview-badge.fail { background: rgba(239,68,68,0.15);  color: var(--fail); }
.preview-badge.error{ background: rgba(234,179,8,0.15);  color: var(--error, #eab308); }
.preview-rows-table {
  width: 100%; border-collapse: collapse;
  margin-top: 6px; font-size: 0.75rem;
  font-family: 'JetBrains Mono', monospace;
}
.preview-rows-table th, .preview-rows-table td {
  border: 1px solid var(--border); padding: 3px 8px;
  text-align: left; color: var(--text-secondary);
}
.preview-rows-table th { color: var(--text-muted); font-weight: 600; }
```

#### 2. "Test query" button HTML (in vf-section)

**File**: `templates/monitor/rule_form.html`

**Intent**: Place a "Test query" button below the Monitoring conditions section (`<!-- ── Monitoring conditions ──`) and its fields, before `</div><!-- /vf-section -->`. Add an empty `<div id="preview-result-vf">` for the result card to render into.

**Contract**: Insert before `</div><!-- /vf-section -->`:

```html
    <!-- Live preview -->
    <div class="mb-3 pt-2" style="border-top:1px solid var(--border)">
      <button type="button" id="btn-preview-vf" class="btn-dp btn-dp-ghost" style="font-size:0.8rem">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style="margin-right:4px"><path d="M2 6h8M6 2l4 4-4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
        Test query
      </button>
    </div>
    <div id="preview-result-vf"></div>
```

#### 3. "Test query" button HTML (in custom-sql-section)

**File**: `templates/monitor/rule_form.html`

**Intent**: Place an equivalent button below the SQL editor textarea and its hints, before `</div>` closing `#custom-sql-section`. Result renders into `<div id="preview-result-sql">`.

**Contract**: Insert inside `#custom-sql-section`, after the closing `</div>` of the `.mb-4` SQL editor wrapper:

```html
      <!-- Live preview -->
      <div class="mb-3 pt-2" style="border-top:1px solid var(--border)">
        <button type="button" id="btn-preview-sql" class="btn-dp btn-dp-ghost" style="font-size:0.8rem">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style="margin-right:4px"><path d="M2 6h8M6 2l4 4-4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
          Test query
        </button>
      </div>
      <div id="preview-result-sql"></div>
```

#### 4. Preview JS block

**File**: `templates/monitor/rule_form.html`

**Intent**: Add a self-contained IIFE in `{% block extra_scripts %}` that handles both "Test query" buttons. The IIFE must: read the CSRF token from the cookie, collect form values based on the active rule type, POST to `/api/preview/`, and render a result card into the appropriate result div.

**Contract**: The IIFE reads `getCookie('csrftoken')` using the Django-standard cookie-reading snippet. It calls `fetch('/api/preview/', {method:'POST', headers:{...}, body: JSON.stringify(params)})`. On network error it shows an error card. The result card logic:

- Always shows a status badge (OK/FAIL/ERROR).
- If `row_count !== null` → shows "Row count: N".
- If `last_record_age_hours !== null` → shows "Last record age: X.Xh".
- If `error_message` → shows error text in muted style.
- If `sample_rows` is a non-empty array → renders a table with column names as headers and up to 3 data rows.

The button shows a brief "Running…" disabled state during the fetch and restores after. The result div is cleared before each new call.

### Success Criteria

#### Automated Verification

- `python manage.py check` — no system check errors (template syntax not checked by this command; manual verification covers it).

#### Manual Verification

- Open the Add Rule form. Select a connection. Fill in schema/table/min_row_count. Click "Test query" → result card appears with correct status, row count.
- In Custom SQL mode: write a valid SELECT. Click "Test query" → result card shows OK or FAIL.
- Clicking "Test query" with no connection selected → result card shows an error (connection_id 400 or service ERROR).
- Sample rows table renders when the rule returns FAIL and rows exist.
- Button shows "Running…" during fetch and is re-enabled afterwards.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation before proceeding to Phase 4.

---

## Phase 4: Tests

### Overview

Add `PreviewRuleServiceTest` and `PreviewRuleViewTest` test classes in `monitor/tests.py`. The service tests mock `_open_conn` and `_check_rule`; the view tests use Django's test client with session auth. Cover the ownership guard, invalid input, and the `sample_rows[:3]` slicing.

### Changes Required

#### 1. `PreviewRuleServiceTest`

**File**: `monitor/tests.py`

**Intent**: Unit-test `preview_rule()` without a real DB connection. Cover: valid volume_freshness preview, valid custom_sql preview, unknown connection_id (ERROR dict), wrong owner (ERROR dict), empty URL (ERROR dict), `MonitoredDbError` (ERROR dict), `sample_rows` sliced to 3 (even when helper returns 5).

**Contract**: Use `@patch('monitor.services._open_conn')` and `@patch('monitor.services._check_rule')` to mock the DB layer. Assert `result['status']` and `result['sample_rows']` shapes.

#### 2. `PreviewRuleViewTest`

**File**: `monitor/tests.py`

**Intent**: Integration-test `POST /api/preview/` via Django's test client. Cover: unauthenticated request (302 redirect to login), missing `connection_id` (400), non-integer `connection_id` (400), invalid JSON body (400), valid request returns 200 with expected JSON keys, another user's `connection_id` returns 200 with `status: ERROR` (not 403).

**Contract**: Use `self.client.login(...)` for authenticated tests. Mock `preview_rule` at the view layer: `@patch('monitor.views.preview_rule', return_value={...})`. For the ownership test, use a real second-user connection and do NOT mock — let the service layer enforce the guard.

### Success Criteria

#### Automated Verification

- `python manage.py test monitor.tests.PreviewRuleServiceTest monitor.tests.PreviewRuleViewTest` — all tests pass, 0 errors.
- `python manage.py test monitor` — no regressions in the existing test suite.

#### Manual Verification

- Test output shows both new test classes with at least 7 test methods combined, all passing.

---

## Testing Strategy

### Unit Tests

- `preview_rule()` with mocked `_open_conn` and `_check_rule`: valid call → OK dict; connection not found → ERROR dict; wrong owner → ERROR dict; `MonitoredDbError` → ERROR dict.
- `preview_rule()` sample rows slicing: mock `_check_rule` returning 5-row list → assert returned dict has `len(sample_rows) == 3`.

### Integration Tests

- `POST /api/preview/` with no auth → 302.
- `POST /api/preview/` with invalid JSON → 400.
- `POST /api/preview/` without `connection_id` → 400.
- `POST /api/preview/` with valid payload + mocked service → 200, JSON keys present.
- `POST /api/preview/` with another user's connection → 200, `status == 'ERROR'` (ownership guard).

### Manual Testing Steps

1. Open the "Add Rule" form. Select a working connection. Fill in schema + table + min_row_count. Click "Test query". Verify the result card appears with a coloured status badge and row count.
2. Switch to Custom SQL mode. Enter `SELECT COUNT(*) > 0 FROM public.orders`. Click "Test query". Verify OK or FAIL response.
3. Leave connection blank. Click "Test query". Verify error card.
4. Enter a FAIL-producing rule (min_row_count higher than actual count). Verify sample rows table renders.
5. Verify no new `RuleResult` or `CheckRun` rows appear in the DB after any preview call.

## Performance Considerations

The preview endpoint opens and closes a DB connection per request, same as the existing schema introspection endpoints. No connection pooling change is needed. The `sample_rows[:3]` slice limits payload size.

## Migration Notes

No schema migrations required. The preview endpoint is purely in-memory; it does not touch any model.

## References

- Research doc: `context/changes/rule-live-preview/research.md`
- `monitor/services.py:193–249` — `run_single_rule` (do not use for preview)
- `monitor/services.py:~165` — `_check_rule` (stateless primitive used by `preview_rule`)
- `monitor/views.py:api_schema_tables` — session-auth view pattern to follow
- `templates/monitor/rule_form.html:~370` — existing `fetch` AJAX pattern to follow
- `monitor/urls.py:14–16` — schema introspection registration pattern

---

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: preview_rule() in services.py

#### Automated

- [ ] 1.1 preview_rule service unit tests pass
- [ ] 1.2 python manage.py check passes

#### Manual

- [ ] 1.3 preview_rule shell smoke test against real connection

### Phase 2: POST /api/preview/ endpoint

#### Automated

- [ ] 2.1 preview_rule_view tests pass
- [ ] 2.2 python manage.py check passes

#### Manual

- [ ] 2.3 curl smoke test — valid payload returns JSON
- [ ] 2.4 curl smoke test — missing connection_id returns 400
- [ ] 2.5 wrong-owner connection returns status ERROR

### Phase 3: Test query button + JS + result card

#### Automated

- [ ] 3.1 python manage.py check passes

#### Manual

- [ ] 3.2 VF mode — button triggers preview, result card renders
- [ ] 3.3 Custom SQL mode — button triggers preview, result card renders
- [ ] 3.4 No connection selected — error card shown
- [ ] 3.5 FAIL rule — sample rows table renders
- [ ] 3.6 Button shows Running... state during fetch

### Phase 4: Tests

#### Automated

- [ ] 4.1 PreviewRuleServiceTest all pass
- [ ] 4.2 PreviewRuleViewTest all pass
- [ ] 4.3 Full monitor test suite — no regressions
