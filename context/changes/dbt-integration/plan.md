# dbt Webhook Integration — Implementation Plan

## Overview

Add a `DbtIntegration` model and a public `POST /api/v1/webhooks/dbt/` endpoint that accepts dbt Cloud job-completion events (or manual `curl` calls from dbt Core `on-run-end` hooks) authenticated by per-integration HMAC-SHA256 shared secret, then synchronously runs the mapped DataPulse rules. Users create and manage integrations through a new `/integrations/dbt/` UI page.

## Current State Analysis

- `monitor/models.py` defines five models — `Connection`, `Rule`, `CheckRun`, `RuleResult`, `SlackNotification`. No dbt-related model exists.
- `monitor/urls.py` has 15 URL patterns across dashboard/rules/connections/schedule/schema-API groups. No `/api/v1/webhooks/` path exists (`monitor/urls.py:1–28`).
- `data_pulse/urls.py:11` mounts the monitor app at `''`, so all new paths in `monitor/urls.py` resolve as expected.
- Every view in `monitor/views.py` is decorated with `@login_required`. No inbound-unauthenticated POST endpoint exists anywhere.
- `data_pulse/settings.py:23` enables `CsrfViewMiddleware`. Webhook views must use `@csrf_exempt`.
- `monitor/models.py:50–72` — Fernet encryption pattern on `Connection._database_url`. `DbtIntegration.secret_key` must follow the same pattern.
- `monitor/services.py` — `run_single_rule(rule: Rule) -> RuleResult` is the correct per-rule execution target; it creates `CheckRun`, `RuleResult`, and fires `send_fail_notification`. Calling it from the webhook reuses all existing logic.
- First `ManyToManyField` in the codebase: `DbtIntegration → Rule`.

### Key Discoveries

- `monitor/models.py:30` — `Connection.user` FK pattern: `ForeignKey(AUTH_USER_MODEL, on_delete=PROTECT, related_name='connections')`. Mirror for `DbtIntegration`.
- `monitor/models.py:50–72` — Fernet encrypt/decrypt accessor pattern for sensitive fields; reuse `_get_fernet()`.
- `monitor/services.py` — `run_single_rule` is synchronous and self-contained; no Celery or task queue needed.
- `monitor/tests.py:1–60` — test helpers `make_rule`, `make_connection` established; extend rather than replace.
- Roadmap note: S-24 listed S-20 as prereq; the approved plan direction resolves this with standalone HMAC auth, no dependency on S-20.

## Desired End State

After this change a user can:
1. Visit `/integrations/dbt/new/`, fill in name, a dbt job ID string, an optional Connection, and select rules to trigger.
2. On save, see the raw `secret_key` displayed once in the browser; copy it into dbt Cloud or into a `curl` command.
3. When dbt Cloud POSTs a job-completion event to `/api/v1/webhooks/dbt/`, DataPulse validates the HMAC-SHA256 signature, matches the `job_id`, checks that `runStatus` is `"Success"` (case-insensitive), and calls `run_single_rule()` for each mapped rule. Results appear in the rule history immediately.
4. dbt Core users replicate the same flow with a `curl` one-liner from `on-run-end`, using the flat payload shape.

### Verification

- `GET /integrations/dbt/` (logged in) returns HTTP 200 with the integration list.
- `POST /api/v1/webhooks/dbt/` with correct HMAC + success status returns HTTP 200 JSON with `triggered` count.
- `POST /api/v1/webhooks/dbt/` with wrong secret returns HTTP 401.
- `POST /api/v1/webhooks/dbt/` with `runStatus != success` returns HTTP 200 `{"status": "ignored"}`.

## What We're NOT Doing

- **No S-20 dependency** — webhook auth is standalone HMAC-SHA256; S-20 REST API / API keys are not required.
- **No async execution** — rules run synchronously in the webhook request. Celery/task queue is out of scope.
- **No dbt run metadata stored** — we do not persist dbt `run_id`, `project_id`, `run_finished_at`, etc.
- **No re-trigger UI** — there is no "manually replay last dbt run" button; that is future work.
- **No partial-success handling** — only `runStatus.lower() == "success"` triggers checks; `"Partial Success"` is treated as non-success and ignored.
- **No secret rotation UI** — to rotate the secret, delete and recreate the integration.

## Implementation Approach

1. **Model** — Add `DbtIntegration` to `monitor/models.py` following the `Connection` field-encryption pattern. Store the raw secret encrypted via Fernet. Generate a URL-safe random secret server-side at creation; expose it once in the create view.
2. **Webhook endpoint** — A single `@csrf_exempt @require_POST` view normalises both payload shapes (dbt Cloud nested under `"data"` vs. flat dbt Core), looks up integrations by `job_id`, validates HMAC-SHA256 with `hmac.compare_digest`, and calls `run_single_rule` for each mapped rule.
3. **UI** — Standard list/create/edit/delete views at `/integrations/dbt/` following the existing connection-management pattern. Secret shown once on create; not re-displayed on edit.
4. **Tests** — Unit and integration tests covering model encryption, HMAC validation edge cases, payload normalisation, UI ownership guards, and end-to-end webhook triggering.

## Critical Implementation Details

**HMAC validation** — The view must capture `request.body` (raw bytes) before any JSON parsing. Compute `hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()`. The incoming header is `Authorization: sha256=<hex>`. Strip the `sha256=` prefix before calling `hmac.compare_digest(computed, incoming)` to prevent timing attacks. Using `compare_digest` is mandatory.

**Secret displayed once** — `secrets.token_hex(32)` generates the raw key. Pass it to the template context under `raw_secret_key` only on the POST-success response of the create view, then store the Fernet-encrypted value. The raw key is never stored in plaintext and cannot be recovered; the template must display it with a copy-to-clipboard affordance and a "save this now" warning.

**Payload normalisation** — If `json_body.get("data")` is a `dict`, treat as dbt Cloud shape: extract `data["jobId"]` and `data["runStatus"]`. Otherwise treat as flat shape: extract `job_id` and `run_status`. Both resolve to the same two variables before any further logic runs.

---

## Phase 1: DbtIntegration Model + Migration

### Overview

Introduce `DbtIntegration` to `monitor/models.py` with Fernet-encrypted `secret_key`, user ownership, optional connection FK, M2M to `Rule`, and a `unique_together` constraint on `(user, job_id)`. Generate the corresponding migration.

### Changes Required

#### 1. DbtIntegration model

**File**: `monitor/models.py`

**Intent**: Add `DbtIntegration` below `SlackNotification`. The model links a user to a dbt job identifier and a set of DataPulse rules to trigger when that job succeeds. The secret key is Fernet-encrypted following the existing `Connection._database_url` pattern.

**Contract**: New class `DbtIntegration(models.Model)` with:
- `user` — `ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='dbt_integrations')`
- `name` — `CharField(max_length=200)`
- `connection` — `ForeignKey('Connection', on_delete=models.SET_NULL, null=True, blank=True, related_name='dbt_integrations')`
- `job_id` — `CharField(max_length=200)` — the correlation key supplied by the user (dbt Cloud job ID or any string for dbt Core)
- `_secret_key` — `TextField(db_column='secret_key')` — Fernet-encrypted raw secret
- `rules` — `ManyToManyField('Rule', blank=True, related_name='dbt_integrations')`
- `created_at`, `updated_at` — `auto_now_add` / `auto_now`
- `Meta.unique_together = [('user', 'job_id')]`
- `Meta.ordering = ['name']`
- `set_secret_key(raw: str)` / `get_secret_key() -> str` — mirror `Connection.set_database_url` / `get_database_url` using `_get_fernet()`
- `__str__` returning `f'{self.name} (job: {self.job_id})'`

#### 2. Migration

**File**: `monitor/migrations/` (next numbered file after the current last migration)

**Intent**: Generate the migration that creates the `monitor_dbtintegration` table and the M2M join table `monitor_dbtintegration_rules`.

**Contract**: Run `python manage.py makemigrations monitor` after adding the model. The migration name should be auto-generated. Verify it creates: `monitor_dbtintegration` (columns: id, user_id, name, job_id, secret_key, connection_id, created_at, updated_at) and `monitor_dbtintegration_rules` (dbtintegration_id, rule_id). The unique constraint on `(user_id, job_id)` must be present.

### Success Criteria

#### Automated Verification

- Migration applies cleanly: `python manage.py migrate --run-syncdb` (SQLite test DB)
- No pending migrations: `python manage.py migrate --check`
- Model unit test: `DbtIntegration` can be created, `set_secret_key` / `get_secret_key` round-trips correctly, unique constraint raises `IntegrityError` on duplicate `(user, job_id)`

#### Manual Verification

- `python manage.py shell` — import `DbtIntegration`, create an instance, verify encryption persists across save/reload

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Webhook Endpoint + HMAC Validation

### Overview

Add the `POST /api/v1/webhooks/dbt/` endpoint. The view is `@csrf_exempt` and `@require_POST`, normalises both dbt Cloud and dbt Core payload shapes, validates the HMAC-SHA256 signature, and returns 401 on failure or 200 on success/ignored.

### Changes Required

#### 1. dbt_webhook view

**File**: `monitor/views.py`

**Intent**: Add a new view `dbt_webhook` at the bottom of `monitor/views.py`. It handles all inbound dbt webhook calls: JSON parsing, payload normalisation, HMAC check, and status gating. Trigger logic is deferred to Phase 3.

**Contract**:

```python
import hashlib
import hmac as _hmac
import json
import secrets

from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
# (require_POST already imported at monitor/views.py:14)

@csrf_exempt
@require_POST
def dbt_webhook(request):
    try:
        body = request.body
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Normalise payload — dbt Cloud (nested) vs dbt Core (flat)
    data = payload.get('data')
    if isinstance(data, dict):
        job_id = str(data.get('jobId', ''))
        run_status = str(data.get('runStatus', ''))
    else:
        job_id = str(payload.get('job_id', ''))
        run_status = str(payload.get('run_status', ''))

    if not job_id:
        return JsonResponse({'error': 'Missing job_id'}, status=400)

    # HMAC-SHA256 validation
    auth_header = request.headers.get('Authorization', '')
    incoming_sig = auth_header.removeprefix('sha256=')

    integrations = DbtIntegration.objects.filter(job_id=job_id).prefetch_related('rules')
    valid_integrations = []
    for integration in integrations:
        secret = integration.get_secret_key()
        expected = _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if _hmac.compare_digest(expected, incoming_sig):
            valid_integrations.append(integration)

    if not valid_integrations:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    if run_status.lower() != 'success':
        return JsonResponse({'status': 'ignored', 'run_status': run_status}, status=200)

    # Phase 3 trigger logic goes here
    return JsonResponse({'status': 'ok', 'triggered': 0})
```

#### 2. URL registration

**File**: `monitor/urls.py`

**Intent**: Register the webhook endpoint at `api/v1/webhooks/dbt/` within the existing monitor URL file so it resolves as `/api/v1/webhooks/dbt/`.

**Contract**: Add `path('api/v1/webhooks/dbt/', views.dbt_webhook, name='dbt_webhook')` to `urlpatterns`. Place it after the existing `api/schema/` entries (lines 17–18) for readability.

### Success Criteria

#### Automated Verification

- `POST /api/v1/webhooks/dbt/` with correct HMAC + `run_status=Success` → HTTP 200, `{"status": "ok"}`
- `POST /api/v1/webhooks/dbt/` with wrong secret → HTTP 401
- `POST /api/v1/webhooks/dbt/` with no `Authorization` header → HTTP 401
- `POST /api/v1/webhooks/dbt/` with dbt Cloud nested payload → correct `job_id` extracted
- `POST /api/v1/webhooks/dbt/` with flat payload → correct `job_id` extracted
- `POST /api/v1/webhooks/dbt/` with `run_status=Error` → HTTP 200, `{"status": "ignored"}`
- `POST /api/v1/webhooks/dbt/` with malformed JSON → HTTP 400

#### Manual Verification

- `curl -X POST http://localhost:8000/api/v1/webhooks/dbt/ -H "Authorization: sha256=<computed>" -H "Content-Type: application/json" -d '{"job_id":"test","run_status":"Success"}'` — returns 200
- `curl` with wrong secret — returns 401

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Trigger Logic (Run Mapped Rules)

### Overview

Extend `dbt_webhook` to call `run_single_rule(rule)` for each rule mapped to the validated `DbtIntegration`, collect results, and return a JSON summary.

### Changes Required

#### 1. Rule-triggering block in dbt_webhook

**File**: `monitor/views.py`

**Intent**: Replace the Phase 2 placeholder `return JsonResponse({'status': 'ok', 'triggered': 0})` with the loop that runs each mapped rule and collects results. Import `run_single_rule` from `monitor.services` (already imported for existing views).

**Contract**: After the `if run_status.lower() != 'success'` block:
```python
results = []
for integration in valid_integrations:
    for rule in integration.rules.all():
        result = run_single_rule(rule)
        results.append({'rule': rule.name, 'status': result.status})

return JsonResponse({'status': 'ok', 'triggered': len(results), 'results': results})
```

### Success Criteria

#### Automated Verification

- Successful webhook call triggers `run_single_rule` once per mapped rule (verified with `unittest.mock.patch`)
- JSON response contains correct `triggered` count
- `results` list contains `{rule: name, status: status}` for each rule

#### Manual Verification

- End-to-end test with dev server: configure a `DbtIntegration`, POST a valid webhook, check rule result appears in `/rules/<id>/` history

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation that the manual testing was successful before proceeding to the next phase.

---

## Phase 4: UI — Integrations Page

### Overview

Add list / create / edit / delete views at `/integrations/dbt/`, following the `connection_list` / `connection_create` pattern from `monitor/views.py`. On create, display the raw secret once and never again. On edit, only name, job_id, connection, and rules are editable.

### Changes Required

#### 1. DbtIntegrationForm

**File**: `monitor/forms.py`

**Intent**: Add `DbtIntegrationForm(ModelForm)` with `fields = ['name', 'job_id', 'connection', 'rules']`. The `rules` queryset and `connection` queryset must be filtered to `request.user`'s own objects. Override `__init__` to accept `user` kwarg and apply filters.

**Contract**: `DbtIntegrationForm` with `Meta.model = DbtIntegration`, `Meta.fields = ['name', 'job_id', 'connection', 'rules']`. `__init__(self, *args, user=None, **kwargs)` filters `self.fields['rules'].queryset = Rule.objects.filter(user=user)` and `self.fields['connection'].queryset = Connection.objects.filter(user=user)`.

#### 2. UI views

**File**: `monitor/views.py`

**Intent**: Add four views — `dbt_integration_list`, `dbt_integration_create`, `dbt_integration_edit`, `dbt_integration_delete` — all `@login_required`, following the same ownership-guard pattern as `connection_list` etc.

**Contract**:
- `dbt_integration_list` — `GET` only; `DbtIntegration.objects.filter(user=request.user)`.
- `dbt_integration_create` — `GET/POST`; on valid POST: generate `raw_key = secrets.token_hex(32)`, call `obj.set_secret_key(raw_key)`, save, redirect to list with `raw_key` in one-time flash context (pass via redirect to a `_created` detail view that renders the secret once, or render directly with `raw_key` in context before redirect; simplest is render the create template on success with `raw_key` in context instead of redirect).
- `dbt_integration_edit` — `GET/POST`; `get_object_or_404(DbtIntegration, pk=pk, user=request.user)`; form excludes re-generating or showing secret.
- `dbt_integration_delete` — `POST`; `get_object_or_404(DbtIntegration, pk=pk, user=request.user)`; delete and redirect to list.

#### 3. URL registrations

**File**: `monitor/urls.py`

**Intent**: Register the four UI endpoints for the integrations page.

**Contract**: Add these four entries to `urlpatterns`:
```
path('integrations/dbt/', views.dbt_integration_list, name='dbt_integration_list'),
path('integrations/dbt/new/', views.dbt_integration_create, name='dbt_integration_create'),
path('integrations/dbt/<int:pk>/edit/', views.dbt_integration_edit, name='dbt_integration_edit'),
path('integrations/dbt/<int:pk>/delete/', views.dbt_integration_delete, name='dbt_integration_delete'),
```

#### 4. Templates

**Files**: `templates/monitor/dbt_integration_list.html`, `templates/monitor/dbt_integration_form.html`

**Intent**: List template shows a table of integrations (name, job ID, connection, rule count) with New / Edit / Delete actions. Create/edit form template renders `DbtIntegrationForm` fields and, when `raw_secret_key` is in context (create only), displays it in a highlighted code block with "Copy" and "I've saved this" note.

**Contract**: Match the look and feel of `templates/monitor/connection_list.html` and `templates/monitor/connection_form.html`. The secret display block must be conditionally rendered: `{% if raw_secret_key %}…{% endif %}`. Use the existing base template and sidebar nav.

#### 5. Sidebar navigation update

**File**: sidebar/base template (check `templates/` for the nav partial)

**Intent**: Add an "Integrations" link to the sidebar, pointing to `monitor:dbt_integration_list`, following the existing sidebar item pattern.

### Success Criteria

#### Automated Verification

- `GET /integrations/dbt/` (logged in) → HTTP 200
- `GET /integrations/dbt/` (anonymous) → redirect to login
- `POST /integrations/dbt/new/` with valid form → integration created, secret visible in response
- `GET /integrations/dbt/<pk>/edit/` for other user's integration → HTTP 404
- `POST /integrations/dbt/<pk>/delete/` → integration removed from DB

#### Manual Verification

- Full create → copy secret → edit name → delete flow in browser
- Secret appears only on create success page, not in edit form
- Sidebar "Integrations" link visible and functional

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation that the manual testing was successful before proceeding to the next phase.

---

## Phase 5: Tests

### Overview

Add unit and integration tests to `monitor/tests.py` covering the new model, webhook endpoint, and UI views.

### Changes Required

#### 1. Test cases

**File**: `monitor/tests.py`

**Intent**: Add three test classes: `DbtIntegrationModelTest`, `DbtWebhookViewTest`, `DbtIntegrationUITest`. Follow the existing helper patterns (`make_rule`, `make_connection`).

**Contract**:

`DbtIntegrationModelTest`:
- `test_set_and_get_secret_key` — round-trip encryption
- `test_unique_together_constraint` — creating two integrations with same `(user, job_id)` raises `IntegrityError`
- `test_str_representation`

`DbtWebhookViewTest` (uses `Client`, no login):
- `test_valid_hmac_success_triggers_rules` — mock `run_single_rule`, verify it is called once per mapped rule, response has `triggered: N`
- `test_wrong_secret_returns_401`
- `test_missing_authorization_header_returns_401`
- `test_non_success_run_status_ignored` — `run_status=Error`, verify `run_single_rule` not called, response `{"status": "ignored"}`
- `test_dbt_cloud_payload_shape` — nested `data.jobId` extracted correctly
- `test_dbt_core_flat_payload_shape` — flat `job_id` extracted correctly
- `test_invalid_json_returns_400`

`DbtIntegrationUITest` (uses `Client.login`):
- `test_list_view_requires_login`
- `test_list_view_shows_only_own_integrations`
- `test_create_view_displays_raw_secret_once`
- `test_edit_view_404_for_other_user`
- `test_delete_view_removes_integration`

### Success Criteria

#### Automated Verification

- All new tests pass: `python manage.py test monitor`
- No regressions in existing tests: full suite green
- HMAC edge cases covered: wrong secret, missing header, non-success status, both payload shapes

#### Manual Verification

- Review test output — confirm test names match the cases above; no tests skipped

**Implementation Note**: After completing this phase and all automated verification passes, this is the final phase — report completion.

---

## Testing Strategy

### Unit Tests

- `DbtIntegration` model: encryption round-trip, unique constraint, `__str__`
- HMAC computation: correct signature accepted, any modification to body or key produces a different digest
- Payload normalisation: dbt Cloud nested shape, dbt Core flat shape, missing fields

### Integration Tests

- Full webhook flow: `DbtIntegration` in DB → POST with correct HMAC + success → `run_single_rule` called → result in `RuleResult`
- UI CRUD: create integration (secret shown) → edit name → delete

### Manual Testing Steps

1. Create a `DbtIntegration` via `/integrations/dbt/new/`, note the secret key
2. POST to `http://localhost:8000/api/v1/webhooks/dbt/` with correct HMAC — confirm HTTP 200 and rule result in history
3. POST with wrong secret — confirm HTTP 401
4. POST with flat payload (dbt Core shape) — confirm HTTP 200 and rule triggered
5. Verify sidebar "Integrations" link navigates correctly
6. Verify edit form does not show or change the secret key

## Performance Considerations

Rules run synchronously in the webhook request. For the current scale (< 100 rules per integration), this is acceptable. If an integration maps more than a handful of rules, response time will grow linearly with rule count. Async execution via Celery is a future concern and explicitly out of scope here.

## Migration Notes

No existing data requires migration. The new migration adds only new tables. Running `python manage.py migrate` is safe at any time.

## References

- Research: `context/changes/dbt-integration/research.md`
- Change: `context/changes/dbt-integration/change.md`
- Connection model (encryption pattern): `monitor/models.py:14–72`
- run_single_rule: `monitor/services.py`
- Existing API-style views: `monitor/urls.py:17–18`, `monitor/views.py`
- Connection UI views (pattern to follow): `monitor/views.py` (connection_list, connection_create, etc.)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: DbtIntegration Model + Migration

#### Automated

- [x] 1.1 Migration applies cleanly (python manage.py migrate --run-syncdb)
- [x] 1.2 No pending migrations (python manage.py migrate --check)
- [x] 1.3 DbtIntegration model unit test: create, secret round-trip, unique constraint

#### Manual

- [ ] 1.4 Shell verification: DbtIntegration accessible, encryption persists across save/reload

### Phase 2: Webhook Endpoint + HMAC Validation

#### Automated

- [x] 2.1 Valid HMAC + success status → HTTP 200
- [x] 2.2 Wrong secret → HTTP 401
- [x] 2.3 Missing Authorization header → HTTP 401
- [x] 2.4 dbt Cloud nested payload → correct job_id extracted
- [x] 2.5 Flat dbt Core payload → correct job_id extracted
- [x] 2.6 Non-success run_status → HTTP 200 ignored
- [x] 2.7 Malformed JSON → HTTP 400

#### Manual

- [ ] 2.8 curl test against dev server: correct HMAC → 200, wrong secret → 401

### Phase 3: Trigger Logic

#### Automated

- [x] 3.1 Successful webhook triggers run_single_rule once per mapped rule
- [x] 3.2 Response JSON contains correct triggered count and results list

#### Manual

- [ ] 3.3 End-to-end: POST valid webhook, rule result appears in /rules/<id>/ history

### Phase 4: UI Integrations Page

#### Automated

- [x] 4.1 GET /integrations/dbt/ (logged in) → HTTP 200
- [x] 4.2 GET /integrations/dbt/ (anonymous) → redirect to login
- [x] 4.3 POST /integrations/dbt/new/ → integration created, secret in response
- [x] 4.4 GET /integrations/dbt/<pk>/edit/ for other user → HTTP 404
- [x] 4.5 POST /integrations/dbt/<pk>/delete/ → integration removed

#### Manual

- [ ] 4.6 Full create-edit-delete flow in browser
- [ ] 4.7 Secret visible only on create page, absent from edit form
- [ ] 4.8 Sidebar Integrations link functional

### Phase 5: Tests

#### Automated

- [x] 5.1 All new tests pass (python manage.py test monitor)
- [x] 5.2 No regressions in existing test suite

#### Manual

- [ ] 5.3 Test names and coverage reviewed: HMAC edge cases, payload shapes, ownership guards all present
