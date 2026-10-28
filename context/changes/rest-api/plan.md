# REST API + API Keys — Implementation Plan

## Overview

Add a REST API with API-key authentication so users can trigger monitoring rules from CI/CD pipelines, GitHub Actions, and external tools. Users manage named API keys through a new settings page at `/settings/api-keys/`. The API exposes four endpoints under `/api/v1/` protected by a `@require_api_key` decorator. Rate limiting uses Django's built-in cache (60 req/min per key).

## Current State Analysis

DataPulse uses vanilla Django `JsonResponse` for its two existing AJAX endpoints (`api_schema_tables`, `api_schema_columns` at `monitor/urls.py:9–10`). These are protected by `@login_required` + `@require_GET` — the established decorator-composition pattern. DRF is not installed and not in `pyproject.toml`. The project's design charter (`context/foundation/tech-stack.md`) prohibits adding extra libraries without justification.

The two core service functions that the API will delegate to already exist:
- `services.py:291` — `run_single_rule(rule) -> RuleResult`
- `services.py:330` — `run_checks_for_user(user) -> CheckRun`

`CheckRun` (`models.py:168`) has no `user` field; ownership must be inferred by checking that at least one result in the run belongs to `request.api_user`'s rules. The latest migration is `0012_rule_notify_fields.py`; the `ApiKey` model will go in `0013`.

### Key Discoveries:

- `monitor/views.py:6` — `JsonResponse` already imported; follow its `@csrf_exempt` + decorator pattern for API views
- `monitor/models.py:1-9` — Fernet used for sensitive data; SHA-256 for API key hash follows the same "store only the safe derivative" convention
- `monitor/models.py:178-192` — `SlackNotification` uses `null=True, blank=True` FK — same pattern for `ApiKey.last_used_at`
- `monitor/models.py:168-188` — `CheckRun` has no `user` FK; ownership check via `results__rule__user`
- `monitor/views.py:81-102` — decorator stacking: `@login_required` + `@require_POST` is the project pattern
- `data_pulse/urls.py:14` — `path('', include('monitor.urls'))` — API routes can be added as a separate `include()` block in `data_pulse/urls.py`
- `email_service.py:68` — uses `.filter(pk=...).update(field=value)` to avoid triggering `auto_now` — same technique for `ApiKey.last_used_at`

## Desired End State

After this plan is complete:
- `ApiKey` model exists with migration; users can create/revoke named keys from a settings page at `/settings/api-keys/`
- Raw key shown once at creation, stored as SHA-256 only
- `POST /api/v1/rules/{id}/run`, `POST /api/v1/runs/`, `GET /api/v1/rules`, `GET /api/v1/results/{run_id}` all respond with JSON
- Bearer token in `Authorization` header authenticates the caller; 60 req/min rate limit enforced per key
- All existing HTML views and session auth are unaffected

## What We're NOT Doing

- **DRF** — not installing `djangorestframework`; the `JsonResponse` pattern is sufficient
- **Sliding-window rate limiting** — fixed-window counter is acceptable; acknowledged risk for multi-process deployment noted below
- **Per-endpoint rate limits** — single 60 req/min limit shared across all API endpoints per key
- **API key rotation / versioning** — users revoke the old key and create a new one
- **OAuth / JWT** — Bearer + SHA-256 API key is the full auth story for this slice
- **Admin UI for API keys** — management is the `/settings/api-keys/` user-facing page only
- **`run-all` scoping to subset of rules** — `POST /api/v1/runs/` triggers all rules owned by the key owner; no rule filter parameter
- **`Retry-After` header** — 429 response includes `retry_after_seconds` field in JSON body (not an HTTP header)

## Implementation Approach

Five phases follow natural dependency order:

1. **ApiKey model** — blocked on nothing; enables all other phases
2. **Auth decorator + key management views** — blocked on Phase 1 model
3. **API endpoints** — blocked on Phase 2 decorator
4. **Settings UI page** — blocked on Phase 2 management views
5. **Tests** — can be written once all production code exists

The `@require_api_key` decorator (analogous to `@login_required`) is placed only on API view functions; no new middleware is added to avoid affecting HTML views. The decorator sets `request.api_key` and `request.api_user` on the request object. Rate limiting runs inside the decorator after authentication, using `django.core.cache` with a fixed-window counter keyed by `(api_key_id, minute_bucket)`.

---

## Phase 1: ApiKey Model + Migration

### Overview

Add the `ApiKey` model to `monitor/models.py` and generate migration `0013`. The model stores the SHA-256 hash of the raw key, never the raw key itself.

### Changes Required:

#### 1. ApiKey model

**File**: `monitor/models.py`

**Intent**: Add `ApiKey` after the `SlackNotification` class. The model belongs to a user, has a human-readable name (e.g. "CI pipeline"), stores only the SHA-256 hex digest of the raw key, and supports soft-revocation via `is_active`.

**Contract**:

```
class ApiKey(models.Model):
    user         = ForeignKey(AUTH_USER_MODEL, on_delete=CASCADE, related_name='api_keys')
    name         = CharField(max_length=100)
    key_hash     = CharField(max_length=64, unique=True)   # SHA-256 hex, 64 chars
    created_at   = DateTimeField(auto_now_add=True)
    last_used_at = DateTimeField(null=True, blank=True)    # updated on each auth
    is_active    = BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('user', 'name')]

    def __str__(self):
        return f'{self.name} ({self.user})'
```

`key_hash` is `max_length=64` because `hashlib.sha256(...).hexdigest()` always produces 64 hex characters.

#### 2. Migration 0013

**File**: `monitor/migrations/0013_apikey.py`

**Intent**: Auto-generate via `python manage.py makemigrations monitor`. The migration creates the `monitor_apikey` table with a `UNIQUE` constraint on `key_hash`.

**Contract**: Run `python manage.py makemigrations monitor --name apikey` after adding the model. Verify the migration file references `settings.AUTH_USER_MODEL` (not a hard-coded user model path).

### Success Criteria:

#### Automated Verification:

- Migration applies cleanly: `python manage.py migrate --run-syncdb`
- Model imports without error: `python manage.py shell -c "from monitor.models import ApiKey; print(ApiKey._meta.get_fields())"`
- `key_hash` uniqueness enforced: attempt to insert two rows with the same hash raises `IntegrityError`

#### Manual Verification:

- `python manage.py showmigrations monitor` shows `0013_apikey` as applied

**Implementation Note**: Pause here for manual confirmation before proceeding to Phase 2.

---

## Phase 2: API Key Auth Decorator + Key Management Views

### Overview

Create `monitor/api_auth.py` with the `@require_api_key` decorator and rate-limit helper. Add management views for creating and revoking API keys.

### Changes Required:

#### 1. `monitor/api_auth.py` (new file)

**File**: `monitor/api_auth.py`

**Intent**: `require_api_key` is a function decorator (analogous to `@login_required`) that validates the `Authorization: Bearer <key>` header, looks up the active `ApiKey` row, updates `last_used_at`, checks rate limit, and attaches `request.api_key` and `request.api_user` before passing control to the wrapped view. Returns `JsonResponse` errors for 401 and 429.

**Contract**:

```python
# monitor/api_auth.py
import hashlib, functools, time
from django.http import JsonResponse
from django.core.cache import cache
from django.utils import timezone
from .models import ApiKey

_RATE_LIMIT = 60  # requests per minute

def _check_rate_limit(api_key_id: int) -> bool:
    """Return True if under limit, False if exceeded."""
    bucket = int(time.time() // 60)
    cache_key = f'rl:{api_key_id}:{bucket}'
    cache.add(cache_key, 0, timeout=120)
    count = cache.incr(cache_key)
    return count <= _RATE_LIMIT

def require_api_key(view_func):
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return JsonResponse({'error': 'missing or invalid Authorization header'}, status=401)
        raw = auth[7:]
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        try:
            api_key = ApiKey.objects.select_related('user').get(
                key_hash=key_hash, is_active=True
            )
        except ApiKey.DoesNotExist:
            return JsonResponse({'error': 'invalid API key'}, status=401)
        if not _check_rate_limit(api_key.pk):
            bucket_end = (int(time.time() // 60) + 1) * 60
            retry_after = int(bucket_end - time.time())
            return JsonResponse(
                {'error': 'rate limit exceeded', 'retry_after_seconds': retry_after},
                status=429
            )
        ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())
        request.api_key = api_key
        request.api_user = api_key.user
        return view_func(request, *args, **kwargs)
    return wrapper
```

The `cache.add` + `cache.incr` pattern is non-obvious (atomic init then increment); keeping it here prevents a race condition where two concurrent requests both read `count=0` and both pass the limit check.

#### 2. Key creation and revocation views

**File**: `monitor/views.py`

**Intent**: Add three views below the existing `toggle_schedule` view:
- `api_key_list` (`GET /settings/api-keys/`) — lists all `ApiKey` rows for `request.user`; if a `new_key` session variable is set, passes it to the template once then deletes it from the session (raw key shown once)
- `api_key_create` (`POST /settings/api-keys/new/`) — generates `secrets.token_urlsafe(32)`, prefixes with `dp_`, computes SHA-256, saves `ApiKey`, stores raw key in session, redirects to list
- `api_key_revoke` (`POST /settings/api-keys/{key_id}/revoke/`) — sets `is_active=False` on the key owned by `request.user`; 404 if not found

**Contract**: All three views require `@login_required`. Create and revoke require `@require_POST`. Revoke must filter by `user=request.user` before updating to prevent cross-user revocation.

#### 3. URL registration for management views

**File**: `monitor/urls.py`

**Intent**: Add three URL patterns to the existing `urlpatterns` list, under a `# API key management` comment, between the schedule block and the end of the file.

**Contract**:
```python
# API key management
path('settings/api-keys/', views.api_key_list, name='api_key_list'),
path('settings/api-keys/new/', views.api_key_create, name='api_key_create'),
path('settings/api-keys/<int:key_id>/revoke/', views.api_key_revoke, name='api_key_revoke'),
```

### Success Criteria:

#### Automated Verification:

- Import check: `python manage.py shell -c "from monitor.api_auth import require_api_key"`
- `GET /settings/api-keys/` returns 302 redirect to login when unauthenticated
- `POST /settings/api-keys/new/` with a logged-in session creates a new `ApiKey` row with `is_active=True`

#### Manual Verification:

- Navigate to `/settings/api-keys/` while logged in — page loads without error (template may be stub)
- Create a key — raw key starting with `dp_` displayed on page; `ApiKey` row visible in Django admin
- Revoke a key — `is_active` flips to `False` in the database

**Implementation Note**: Pause here for manual confirmation before proceeding to Phase 3.

---

## Phase 3: API Endpoints

### Overview

Add four API endpoint views to `monitor/views.py` (or a new `monitor/api_views.py`) protected by `@require_api_key` + `@csrf_exempt`, and register them at `/api/v1/` in `data_pulse/urls.py`.

### Changes Required:

#### 1. API endpoint views

**File**: `monitor/views.py` (append after management views, or extract to `monitor/api_views.py` for clarity — either is acceptable; keep consistent with the import in `data_pulse/urls.py`)

**Intent**: Four views — one per endpoint. All return `JsonResponse`. All scope data to `request.api_user`.

**Contract per endpoint**:

- **`POST /api/v1/rules/{id}/run`** — `api_run_rule(request, rule_id)`
  - Decorator stack: `@csrf_exempt`, `@require_api_key`, `@require_POST`
  - Fetch `Rule.objects.get(pk=rule_id, user=request.api_user)` — 404 if not owned by api_user
  - Call `run_single_rule(rule)` → returns a `RuleResult` instance
  - Response: `{"run_id": result.run_id, "rule_id": rule_id, "status": result.status, "row_count": result.row_count, "last_record_age_hours": result.last_record_age_hours, "error_message": result.error_message, "checked_at": result.checked_at.isoformat()}`

- **`POST /api/v1/runs/`** — `api_create_run(request)`
  - Decorator stack: `@csrf_exempt`, `@require_api_key`, `@require_POST`
  - Call `run_checks_for_user(request.api_user)` → returns a `CheckRun` instance
  - Response: `{"run_id": run.pk, "started_at": run.started_at.isoformat(), "finished_at": run.finished_at.isoformat() if run.finished_at else None, "ok_count": run.ok_count, "fail_count": run.fail_count, "error_count": run.error_count}`

- **`GET /api/v1/rules`** — `api_list_rules(request)`
  - Decorator stack: `@csrf_exempt`, `@require_api_key`, `@require_GET`
  - `Rule.objects.filter(user=request.api_user).values('id', 'name', 'schema_name', 'table_name', 'rule_type', 'schedule_type', 'created_at', 'updated_at')`
  - Response: `{"rules": [...list of rule dicts with isoformat dates...]}`

- **`GET /api/v1/results/{run_id}`** — `api_get_results(request, run_id)`
  - Decorator stack: `@csrf_exempt`, `@require_api_key`, `@require_GET`
  - Fetch `CheckRun.objects.prefetch_related('results__rule').get(pk=run_id)`; verify ownership by checking `run.results.filter(rule__user=request.api_user).exists()` — if empty, return 404
  - Response: `{"run_id": run_id, "started_at": ..., "finished_at": ..., "results": [{"rule_id": r.rule_id, "rule_name": r.rule.name, "status": r.status, "row_count": r.row_count, "last_record_age_hours": r.last_record_age_hours, "error_message": r.error_message, "checked_at": r.checked_at.isoformat()} for r in run.results.all()]}`

#### 2. URL registration in `data_pulse/urls.py`

**File**: `data_pulse/urls.py`

**Intent**: Add a new `path('api/v1/', include('monitor.api_urls'))` entry so API routes live at `/api/v1/` and are clearly separated from the existing `monitor.urls` HTML routes. Create a new `monitor/api_urls.py` file (rather than adding to `monitor/urls.py`) to keep the boundary explicit.

**Contract**:

`monitor/api_urls.py` (new file):
```python
from django.urls import path
from . import views  # or api_views if extracted

urlpatterns = [
    path('rules/<int:rule_id>/run', views.api_run_rule, name='api_run_rule'),
    path('runs/', views.api_create_run, name='api_create_run'),
    path('rules', views.api_list_rules, name='api_list_rules'),
    path('results/<int:run_id>', views.api_get_results, name='api_get_results'),
]
```

`data_pulse/urls.py` — add before `path('', include('monitor.urls'))`:
```python
path('api/v1/', include('monitor.api_urls')),
```

### Success Criteria:

#### Automated Verification:

- `GET /api/v1/rules` without `Authorization` header returns `{"error": "missing or invalid Authorization header"}` with HTTP 401
- `GET /api/v1/rules` with a valid Bearer token returns `{"rules": [...]}` with HTTP 200
- `POST /api/v1/rules/{id}/run` with a valid Bearer token returns `run_id` and `status` fields
- `GET /api/v1/results/{nonexistent_run_id}` returns HTTP 404
- `GET /api/v1/results/{run_id_owned_by_other_user}` returns HTTP 404 (ownership enforced)

#### Manual Verification:

- `curl -H "Authorization: Bearer dp_<key>" http://localhost:8000/api/v1/rules` returns your rules
- `curl -X POST -H "Authorization: Bearer dp_<key>" http://localhost:8000/api/v1/runs/` triggers a run and returns `run_id`
- Rate limit: 61 rapid requests to any endpoint with the same key; 61st request returns HTTP 429 with `retry_after_seconds`

**Implementation Note**: Pause here for manual confirmation before proceeding to Phase 4.

---

## Phase 4: Settings UI Page

### Overview

Create the `/settings/api-keys/` template with a form to create named keys, a table of existing keys with revoke buttons, and a one-time display of the raw key after creation.

### Changes Required:

#### 1. Template `api_key_list.html`

**File**: `templates/monitor/api_key_list.html`

**Intent**: Extend `base.html`. Show a form (one text input: key name) that POSTs to `api_key_create`. Show a table of the user's existing keys: name, created_at, last_used_at, is_active status, and a "Revoke" button (POST form to `api_key_revoke`). If `new_key` is in context (passed once after creation), show it in a highlighted, copyable block with a warning that it will not be shown again.

**Contract**: Form fields: `name` (text, required, max 100 chars). Revoke button must be inside a `<form method="post">` with `{% csrf_token %}`. New key display block must be visually distinct (e.g. `<code>` in a warning card). Follow the dark-theme CSS patterns from `base.html` (use `--bg-card`, `--accent`, `--fail` tokens).

#### 2. Navigation link

**File**: `templates/base.html`

**Intent**: Add a nav link to `/settings/api-keys/` in the sidebar navigation, alongside the existing Connections and Schedule links. Label: "API Keys".

**Contract**: Follow the existing `<a href="{% url 'monitor:...' %}">` pattern in the sidebar. Place it in the "Settings"-equivalent nav section.

### Success Criteria:

#### Automated Verification:

- `GET /settings/api-keys/` with a logged-in session returns HTTP 200
- Submitting the creation form with `name="test"` creates an `ApiKey` row and redirects back to the list

#### Manual Verification:

- Create a key named "test" — raw key displayed in the UI once, starts with `dp_`
- Reload the page — raw key is gone, key appears in the table as active
- Click "Revoke" — key disappears from active list (or is shown as inactive)
- New key can be pasted into `curl -H "Authorization: Bearer <key>"` and the API responds

**Implementation Note**: Pause here for manual confirmation before proceeding to Phase 5.

---

## Phase 5: Tests

### Overview

Add unit tests for the auth decorator, rate limiter, and API endpoints. Tests run against the existing SQLite test database; no external services required.

### Changes Required:

#### 1. Test file

**File**: `monitor/tests/test_api.py` (new file; create `monitor/tests/__init__.py` if the `tests/` directory doesn't exist, or add to `monitor/tests.py` if that's the current pattern)

**Intent**: Cover:
1. `require_api_key` — missing header → 401, invalid key → 401, revoked key → 401, valid key → 200
2. Rate limiting — under limit passes, 61st request in same minute → 429 with `retry_after_seconds`
3. `GET /api/v1/rules` — returns only the authenticated user's rules (not another user's)
4. `POST /api/v1/rules/{id}/run` — 404 when rule belongs to another user
5. `GET /api/v1/results/{run_id}` — 404 when run belongs to another user's rules
6. `POST /api/v1/runs/` — returns `run_id` and count fields
7. Key creation view — POST creates `ApiKey`, redirects, session contains `new_key`
8. Key revocation view — POST sets `is_active=False` only for the owner

**Contract**: Use Django's `TestCase` and `Client`. Override `cache` with `django.test.override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})` for rate-limit tests to avoid cross-test pollution. For key generation, call `hashlib.sha256(b"testkey").hexdigest()` directly in test setup rather than going through the creation view.

### Success Criteria:

#### Automated Verification:

- All tests pass: `python manage.py test monitor.tests.test_api`
- No existing tests broken: `python manage.py test monitor`

#### Manual Verification:

- Test output shows at least 8 test methods passing

---

## Testing Strategy

### Unit Tests:

- `require_api_key` decorator: missing header, wrong scheme (`Token` vs `Bearer`), invalid hash, revoked key, valid key
- Rate limiter: first request passes, 60th passes, 61st fails, next-minute bucket resets
- Cross-user isolation: each of the 4 endpoints returns 404 when the authenticated user doesn't own the resource

### Integration Tests:

- Full round-trip: create key via UI → use key to trigger `POST /api/v1/runs/` → fetch results via `GET /api/v1/results/{run_id}`
- `last_used_at` updated after successful auth

### Manual Testing Steps:

1. Create a key at `/settings/api-keys/` — note the `dp_...` value
2. `curl -H "Authorization: Bearer <key>" http://localhost:8000/api/v1/rules` — expect JSON list
3. `curl -X POST -H "Authorization: Bearer <key>" http://localhost:8000/api/v1/runs/` — expect `run_id`
4. `curl -H "Authorization: Bearer <key>" http://localhost:8000/api/v1/results/<run_id>` — expect results array
5. Revoke the key at `/settings/api-keys/` — repeat step 2 — expect HTTP 401
6. Rapid-fire 61 requests with the same key within one minute — 61st returns HTTP 429

## Performance Considerations

- `require_api_key` does one `SELECT` (with `select_related('user')`) per request — single indexed lookup on `key_hash` (UNIQUE). Acceptable at the expected request volume.
- `_check_rate_limit` does two cache operations (`add` + `incr`) — sub-millisecond with `LocMemCache`.
- `last_used_at` update uses `.filter().update()` — one `UPDATE` with no model instantiation, following the `email_service.py:68` pattern.
- **Known risk**: `LocMemCache` is per-process. If Render scales to multiple gunicorn workers or dynos in future, rate-limit counters won't be shared. Switching to `DatabaseCache` (Django built-in, no extra package) would fix this without adding dependencies.

## Migration Notes

No existing data needs to be migrated. Migration `0013_apikey` creates a new table; it does not alter existing tables. Apply with `python manage.py migrate`.

## References

- Related research: `context/changes/rest-api/research.md`
- Existing JSON endpoint pattern: `monitor/views.py:126-147`
- Existing service functions: `monitor/services.py:291`, `monitor/services.py:330`
- Existing URL structure: `monitor/urls.py`, `data_pulse/urls.py`
- Sensitive-data convention (store hash, not raw): `monitor/models.py:1-9`
- `last_used_at` update pattern: `email_service.py:68`

---

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: ApiKey Model + Migration

#### Automated

- [x] 1.1 Migration applies cleanly
- [x] 1.2 Model imports without error
- [x] 1.3 key_hash uniqueness enforced

#### Manual

- [ ] 1.4 showmigrations shows 0017_apikey applied

### Phase 2: API Key Auth Decorator + Key Management Views

#### Automated

- [x] 2.1 require_api_key imports without error
- [x] 2.2 GET /settings/api-keys/ returns 302 when unauthenticated
- [x] 2.3 POST /settings/api-keys/new/ creates ApiKey row

#### Manual

- [ ] 2.4 /settings/api-keys/ page loads while logged in
- [ ] 2.5 Create key — raw dp_ key displayed once
- [ ] 2.6 Revoke key — is_active flips to False

### Phase 3: API Endpoints

#### Automated

- [x] 3.1 GET /api/v1/rules without auth returns 401
- [x] 3.2 GET /api/v1/rules with valid key returns 200
- [x] 3.3 POST /api/v1/rules/{id}/run returns run_id and status
- [x] 3.4 GET /api/v1/rules/{nonexistent_id}/results returns 404
- [x] 3.5 GET /api/v1/rules/{other_user_rule_id}/results returns 404

#### Manual

- [ ] 3.6 curl GET /api/v1/rules returns rules JSON
- [ ] 3.7 curl POST /api/v1/rules/run-all returns run_id
- [ ] 3.8 Rate limit: 61st request returns 429 with retry_after_seconds

### Phase 4: Settings UI Page

#### Automated

- [x] 4.1 GET /settings/api-keys/ returns 200 when logged in
- [x] 4.2 Key creation form creates ApiKey and redirects

#### Manual

- [ ] 4.3 Raw key shown once after creation starting with dp_
- [ ] 4.4 Reload — raw key gone, key in active table
- [ ] 4.5 Revoke — key removed from active list
- [ ] 4.6 Created key works in curl API call

### Phase 5: Tests

#### Automated

- [x] 5.1 python manage.py test ... ApiKeyModelTest ApiAuthTest RateLimitTest ApiEndpointsTest ApiKeyViewTest passes (28/28)
- [x] 5.2 python manage.py test monitor (core views pass, no regressions)

#### Manual

- [ ] 5.3 Test output shows at least 8 test methods passing
