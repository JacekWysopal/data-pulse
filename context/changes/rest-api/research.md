---
date: 2026-10-28T19:43:27Z
researcher: kiro-worker
git_commit: c2ad8dfe7dc6ab19e456ba6dab557d0808a806ad
branch: dev
repository: data-pulse
topic: "REST API + API keys — what's needed for external CI/CD access"
tags: [research, rest-api, api-keys, authentication, rate-limiting, django]
status: complete
last_updated: 2026-10-28
last_updated_by: kiro-worker
---

# Research: REST API + API Keys

**Date**: 2026-10-28T19:43:27Z
**Researcher**: kiro-worker
**Git Commit**: c2ad8dfe7dc6ab19e456ba6dab557d0808a806ad
**Branch**: dev
**Repository**: data-pulse

## Research Question

What is needed to add a REST API with API-key authentication to DataPulse?
Specifically: DRF vs vanilla Django, API key model fields, auth strategy,
required endpoints, and rate-limiting options without extra packages.

## Summary

Vanilla Django `JsonResponse` + custom middleware fits better than DRF for this
codebase. DRF is not installed (`ModuleNotFoundError: No module named 'rest_framework'`
confirmed at runtime) and is not listed in `pyproject.toml` or `requirements.txt`.
The project already uses `JsonResponse` for two internal AJAX endpoints
(`monitor/urls.py:9–10`, `monitor/views.py` imports `JsonResponse`).
Adding DRF would introduce a new dependency into an explicitly minimal stack
(`context/foundation/tech-stack.md` cites "no assembling extra libraries" as a
design goal).

The API key model requires 6 fields: `name`, `key_hash`, `user`, `created_at`,
`last_used_at`, `is_active`. The raw key is shown once on creation; only its
SHA-256 hex digest is stored, matching the pattern already used in the project
for sensitive data (Fernet encryption on `Connection._database_url`). The
`secrets` and `hashlib` modules are available in the stdlib and work correctly
in this environment (verified at runtime).

Custom middleware is the right authentication mechanism. `login_required` (used
on all existing views) relies on sessions and redirects to `/login/`, which breaks
stateless API clients. A custom `ApikeyMiddleware` or a `require_api_key` decorator
can extract the `Authorization: Bearer <key>` header, hash the value, look up the
matching active `ApiKey` row, and attach the owner to `request.api_user`. DRF
`TokenAuthentication` requires DRF installed and uses a different header convention
(`Token <key>` vs `Bearer <key>`); it is not applicable here.

The 4 endpoints in scope map cleanly to existing service functions:
- `POST /api/v1/rules/{id}/run` → `run_single_rule(rule)` in `services.py:L291`
- `POST /api/v1/rules/run-all` → `run_checks_for_user(user)` in `services.py:L330`
- `GET /api/v1/rules` → `Rule.objects.filter(user=...)` in `models.py`
- `GET /api/v1/runs/{id}` → `CheckRun.objects.get(pk=id)` + `results` FK

Rate limiting at 60 req/min without extra packages is achievable with Django's
built-in cache framework (`django.core.cache`). The current backend is
`LocMemCache` (`settings.py` shows no `CACHES` override, so Django's default
applies). `LocMemCache` is per-process; on Render's single-dyno deployment (as
configured in `render.yaml` with `gunicorn`) this works for a solo-user product.
A sliding-window counter keyed by `(api_key_id, minute_bucket)` fits inside a
single cache `incr` + `expire` pattern using only `cache.get`, `cache.set`, and
`cache.add`.

## Detailed Findings

### Q1: DRF vs vanilla Django JsonResponse

**Finding**: Vanilla Django `JsonResponse` fits better.

Evidence:
- `requirements.txt` (full pip-compiled file): DRF (`djangorestframework`) is
  absent from all 14 listed packages.
- `pyproject.toml:7-16`: `dependencies` list does not include `djangorestframework`.
- `uv run python -c "import rest_framework"` → `ModuleNotFoundError` (confirmed
  at runtime in this session).
- `monitor/views.py:6`: `from django.http import JsonResponse` — already imported.
- `monitor/views.py:L126-L147`: Two working JSON endpoints (`api_schema_tables`,
  `api_schema_columns`) use `JsonResponse` with `@login_required` + `@require_GET`
  decorators — this is the established pattern.
- `context/foundation/tech-stack.md` states "without assembling extra libraries"
  as an explicit design principle.

**Conclusion**: Installing DRF solely for this feature would contradict the stack
charter. The existing `JsonResponse` pattern handles all 4 endpoints without
additional dependencies.

### Q2: API key model — required fields

**Finding**: 6 fields are needed. All map to existing Django field types in `models.py`.

| Field | Type | Rationale |
|---|---|---|
| `name` | `CharField(max_length=100)` | Human label for UI list (e.g. "CI pipeline") |
| `key_hash` | `CharField(max_length=64, unique=True)` | SHA-256 hex digest (64 chars); raw key never stored |
| `user` | `ForeignKey(AUTH_USER_MODEL, on_delete=CASCADE)` | Ownership; scopes API calls to one user's rules |
| `created_at` | `DateTimeField(auto_now_add=True)` | Audit trail |
| `last_used_at` | `DateTimeField(null=True, blank=True)` | Detect stale keys; nullable until first use |
| `is_active` | `BooleanField(default=True)` | Revoke without delete |

Evidence:
- `models.py:L1-L9`: project imports `base64`, `os`, uses Fernet — convention for
  sensitive data is "store only the safe derivative, not the raw secret".
- `secrets.token_urlsafe(32)` produces a 43-character URL-safe base64 string;
  its `hashlib.sha256(...).hexdigest()` is always 64 chars. Both verified at
  runtime: `len(h) == 64`.
- `models.py:L28-L31`: `Connection.user` FK uses `on_delete=PROTECT` (keeps
  connection even if user is deleted). For `ApiKey`, `CASCADE` is appropriate —
  deleted user means their keys must also be deleted.
- `models.py:L178-L192`: `SlackNotification` model uses `null=True, blank=True`
  for optional FKs — same pattern applies to `last_used_at`.

The raw key (shown once on creation) should use the prefix `dp_` so users can
identify it in CI secrets: e.g. `dp_<43-char token>`. Only the SHA-256 hex of
the full string is stored in `key_hash`.

### Q3: Authentication — custom middleware vs DRF TokenAuthentication

**Finding**: A `require_api_key` function decorator is the right choice for this
codebase. Middleware is also viable but heavier.

Evidence:
- `settings.py:L24-L35`: `MIDDLEWARE` list has 8 entries. Adding a 9th middleware
  that fires on every request (including HTML views) would add overhead and
  complicate the UI's session-based auth.
- `monitor/views.py:L81-L102`: Existing `run_single` and `run_checks` views use
  `@login_required` + `@require_POST` decorators — this is the project's composition
  pattern.
- `monitor/urls.py:L1-L30`: All URL patterns are in one file with no namespace
  separation between HTML and API paths yet.
- A `require_api_key` decorator (analogous to `@login_required`) applied only to
  API view functions keeps the auth surface narrow and the decorator chain readable.
- DRF `TokenAuthentication` is not applicable: DRF is not installed and uses
  `Token <key>` header, whereas the change.md spec requires `Bearer <key>`
  (`change.md:L9`: "Auth: Bearer token header").

**Implementation pattern**:
```python
# monitor/api_auth.py (new file)
import hashlib, functools
from django.http import JsonResponse
from .models import ApiKey

def require_api_key(view_func):
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return JsonResponse({'error': 'missing or invalid Authorization header'}, status=401)
        raw = auth[7:]
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        try:
            api_key = ApiKey.objects.select_related('user').get(key_hash=key_hash, is_active=True)
        except ApiKey.DoesNotExist:
            return JsonResponse({'error': 'invalid API key'}, status=401)
        request.api_key = api_key
        request.api_user = api_key.user
        return view_func(request, *args, **kwargs)
    return wrapper
```

This pattern reuses `select_related` (already used in `services.py`) and returns
`JsonResponse` (already used in `views.py`).

### Q4: Endpoints needed

**Finding**: 4 endpoints. 3 map to existing service functions; 1 needs a new
query but no new service logic.

| Endpoint | Method | Service function | Notes |
|---|---|---|---|
| `POST /api/v1/rules/{id}/run` | POST | `run_single_rule(rule)` (`services.py:L291`) | Must scope rule to `request.api_user`; returns `RuleResult` |
| `POST /api/v1/rules/run-all` | POST | `run_checks_for_user(user)` (`services.py:L330`) | Returns `CheckRun` with counts |
| `GET /api/v1/rules` | GET | `Rule.objects.filter(user=request.api_user)` | No existing service function; simple ORM query |
| `GET /api/v1/runs/{id}` | GET | `CheckRun.objects.get(pk=id)` + `.results.all()` | Must verify run contains at least one rule owned by api_user |

Evidence (field coverage for JSON responses):
- `run_single_rule` returns `RuleResult` with fields: `id`, `status`, `row_count`,
  `last_record_age_hours`, `error_message`, `checked_at`, `run_id`
  (`models.py:L196-L215`, verified at runtime: `RuleResult._meta.get_fields()`).
- `run_checks_for_user` returns `CheckRun` with fields: `id`, `started_at`,
  `finished_at` + computed properties `ok_count`, `fail_count`, `error_count`
  (`models.py:L168-L188`).
- `Rule._meta.get_fields()` confirmed at runtime: 19 fields including `id`,
  `name`, `schema_name`, `table_name`, `rule_type`, `schedule_type`, `created_at`,
  `updated_at`.

The change.md spec (`change.md:L10`) requires the response to include
`status`, `measured values`, `run_id` — all present in `RuleResult`.

URL routing: New routes go under `/api/v1/` prefix, separate from the existing
`/api/schema/` AJAX prefix (`monitor/urls.py:L9-L10`). The cleanest place is a
new `urlpatterns` block registered in `data_pulse/urls.py` or as an additional
`include()` in `monitor/urls.py`.

### Q5: Rate limiting without extra packages

**Finding**: 60 req/min is achievable using Django's built-in `django.core.cache`
with a sliding-window counter. The current `LocMemCache` backend works for
single-process deployment.

Evidence:
- `settings.py` has no explicit `CACHES` setting → Django defaults to
  `LocMemCache` (verified at runtime: `settings.CACHES == {'default': {'BACKEND':
  'django.core.cache.backends.locmem.LocMemCache'}}`).
- `cache.set('test_key', 1, 60)` then `cache.get('test_key')` → `1` (verified
  at runtime in this session): Django's cache read/write works in the current env.
- `render.yaml` (inspected earlier) uses Gunicorn on Render. Render's free tier
  runs a single dyno by default; `LocMemCache` is per-process but sufficient for
  a single-worker deployment.
- `django.core.cache` exposes `cache.add(key, value, timeout)` which atomically
  sets only if the key doesn't exist — useful for initialising a counter.
  `cache.incr(key)` increments atomically within `LocMemCache`.

**Rate-limiting pattern** (no third-party packages):
```python
from django.core.cache import cache
import time

def _check_rate_limit(api_key_id: int, limit: int = 60) -> bool:
    """Return True if the request is allowed (under limit). False if exceeded."""
    bucket = int(time.time() // 60)  # 1-minute fixed window
    cache_key = f'rl:{api_key_id}:{bucket}'
    count = cache.get(cache_key, 0)
    if count >= limit:
        return False
    # Use add + incr to avoid race: add initialises to 0 if absent
    cache.add(cache_key, 0, timeout=120)  # TTL 2 min to clean up previous buckets
    cache.incr(cache_key)
    return True
```

This is a fixed-window counter (not sliding). At window boundaries a burst of
up to 2× the limit is theoretically possible. For a 60 req/min limit on a
solo-user product this is acceptable; a sliding window would require storing
a list of timestamps per key, which is more complex.

**Risk**: If Render scales to multiple workers in future, `LocMemCache` counters
won't be shared across processes. Switching to `DatabaseCache` (built into Django,
no extra package) or Redis (requires `django-redis`) would be needed. This is
a known deferred risk for the current change scope.

## Code References

- `monitor/views.py:6` — `from django.http import JsonResponse` (existing import)
- `monitor/views.py:126-147` — `api_schema_tables` and `api_schema_columns`: existing JSON endpoint pattern with `@login_required` + `@require_GET`
- `monitor/urls.py:9-10` — existing `/api/schema/` AJAX routes (pattern to follow)
- `monitor/models.py:1-9` — sensitive-data handling convention (Fernet for db URLs; SHA-256 for API keys follows the same philosophy)
- `monitor/models.py:168-215` — `CheckRun` and `RuleResult` field definitions (determines JSON response shape)
- `monitor/services.py:291` — `run_single_rule(rule) -> RuleResult`
- `monitor/services.py:330` — `run_checks_for_user(user) -> CheckRun`
- `data_pulse/settings.py:14-35` — `INSTALLED_APPS`, `MIDDLEWARE` (no DRF, no rate-limit middleware)
- `pyproject.toml:7-16` — `dependencies`: 8 runtime dependencies, no DRF
- `requirements.txt:1-19` — full compiled deps: 14 packages, no DRF

## Architecture Insights

1. **Decorator composition over middleware**: The project uses `@login_required` +
   `@require_POST`/`@require_GET` stacking. A `@require_api_key` decorator fits
   this pattern without modifying shared middleware.

2. **User scoping is mandatory**: Every existing query filters by `user=request.user`
   (`views.py` throughout). The API layer must do the same via `request.api_user`
   to prevent cross-user data access.

3. **CSRF exemption required**: Existing HTML views use Django's CSRF middleware
   (`settings.py:L29`). API endpoints called from CI/CD will not have CSRF tokens;
   they must be decorated with `@csrf_exempt`. This is safe because the API key
   in the `Authorization` header replaces the CSRF token as the request proof.

4. **Separate URL namespace**: The 4 API endpoints should live under `/api/v1/`
   in a dedicated include block. The existing `/api/schema/` prefix is internal
   (session-authenticated, AJAX-only); mixing them would obscure the boundary.

5. **`last_used_at` update**: When an API key authenticates successfully, update
   `ApiKey.last_used_at` via `ApiKey.objects.filter(pk=...).update(last_used_at=now())`
   (same pattern as `email_service.py:L68` which updates `Rule.last_notified_at`
   without triggering `auto_now`).

## Historical Context (from prior changes)

- `context/changes/schema-introspection/` — introduced the existing `/api/schema/`
  endpoints with `@login_required`. This confirms the project's JSON API pattern
  uses Django's native decorators, not DRF.
- `context/changes/mysql-support/` — added pymysql; connection management is
  via `Connection` model. API key model should follow `Connection`'s FK pattern
  (`user = ForeignKey(AUTH_USER_MODEL, on_delete=PROTECT/CASCADE)`).
- `context/changes/email-notifications/` — `email_service.py` uses
  `Model.objects.filter(pk=...).update(field=value)` to avoid triggering `auto_now`
  on adjacent fields — same technique needed for `ApiKey.last_used_at`.

## Related Research

No prior research artifact for `rest-api`. The schema-introspection change is the
closest related work (established JSON endpoint pattern).

## Open Questions

1. **UI for key management**: The change.md spec says "user creates named API keys
   in UI" but doesn't define the exact UI surface. The plan phase should decide
   whether this is a new page or a section in the existing connection/settings area.

2. **`run-all` scoping**: `run_checks_for_user` runs all rules owned by the user.
   Should `POST /api/v1/rules/run-all` also be limited to the key owner's rules?
   (Almost certainly yes — consistent with user-scoped design — but worth
   confirming in plan.)

3. **`GET /api/v1/runs/{id}` ownership check**: `CheckRun` has no `user` field
   (`models.py:L168-L188`). Ownership must be inferred from the run's results
   (all results must belong to `api_user`'s rules). The plan should define this
   check precisely.

4. **Rate limit response body**: The change.md spec states 60 req/min but does
   not specify the 429 response shape or `Retry-After` header behavior. Plan
   should decide whether to include `Retry-After` (easy to add with the fixed-window
   approach: `Retry-After = 60 - (now % 60)`).
