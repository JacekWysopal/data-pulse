# REST API + API Keys — Plan Brief

> Full plan: `context/changes/rest-api/plan.md`
> Research: `context/changes/rest-api/research.md`

## What & Why

Add a REST API with API-key authentication so DataPulse rules can be triggered from CI/CD pipelines, GitHub Actions, and external tooling (e.g. after a dbt run). Users generate named API keys through a settings UI; the keys authenticate stateless API calls that the existing session-based auth cannot handle.

## Starting Point

The codebase already has two `JsonResponse` AJAX endpoints (`/api/schema/...`) using Django's native decorator pattern (`@login_required` + `@require_GET`). Service functions `run_single_rule()` and `run_checks_for_user()` exist in `services.py`. DRF is not installed; `pyproject.toml` lists 8 runtime dependencies with no `djangorestframework`.

## Desired End State

Users can create named API keys at `/settings/api-keys/`, copy the one-time raw key (prefixed `dp_`), and use it as a Bearer token to call four endpoints under `/api/v1/`. Existing HTML views and session-based auth are completely unaffected. A 60 req/min rate limit per key is enforced using Django's built-in cache.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| HTTP API library | Vanilla Django `JsonResponse` | DRF not installed, tech-stack charter prohibits extra libs, existing pattern works | Research |
| API key storage | SHA-256 hex of raw key only (`key_hash` field, 64 chars) | Matches existing convention of storing only the safe derivative (Fernet for DB URLs) | Research |
| Raw key prefix | `dp_` + `secrets.token_urlsafe(32)` | Recognisable in CI secret lists; `secrets` is stdlib | Research |
| Authentication mechanism | `@require_api_key` decorator (not middleware) | Project uses decorator stacking; middleware fires on every request including HTML views | Research |
| Rate limiting | Fixed-window counter via `django.core.cache` (60 req/min per key) | No extra packages; `LocMemCache` sufficient for single-process Render deployment | Research |
| `CheckRun` ownership | Infer via `results__rule__user` (no `user` FK on `CheckRun`) | `CheckRun` model has no direct user FK; results link back to rules which have a user | Plan |
| 429 response | JSON body with `retry_after_seconds`; no `Retry-After` header | Simpler; fixed-window bucket end time is trivially computable | Plan |
| URL namespace | New `monitor/api_urls.py` + `path('api/v1/', include('monitor.api_urls'))` in `data_pulse/urls.py` | Keeps API and HTML route files separate; explicit boundary | Plan |
| Key management UI location | `/settings/api-keys/` (new settings page) | Consistent with Connections and Schedule settings; avoids cluttering the dashboard | Plan |

## Scope

**In scope:**
- `ApiKey` model + migration `0013`
- `@require_api_key` decorator with rate limiting in `monitor/api_auth.py`
- `POST /api/v1/rules/{id}/run` — trigger one rule
- `POST /api/v1/runs/` — trigger all rules for the key owner
- `GET /api/v1/rules` — list all rules for the key owner
- `GET /api/v1/results/{run_id}` — fetch results of a run
- `/settings/api-keys/` settings page (create, list, revoke)
- Unit + integration tests for decorator, rate limiter, all four endpoints

**Out of scope:**
- DRF installation
- Sliding-window rate limiting
- Per-endpoint rate limits
- API key rotation/versioning
- OAuth / JWT
- `Retry-After` HTTP header
- `run-all` scoping to a subset of rules

## Architecture / Approach

```
Browser / CI tool
      │
      │ Authorization: Bearer dp_<token>
      ▼
data_pulse/urls.py
  └─ api/v1/ → monitor/api_urls.py
                  └─ @csrf_exempt + @require_api_key + @require_POST/GET
                          │
                          ├─ hash token → ApiKey lookup (key_hash UNIQUE index)
                          ├─ rate-limit check (django.core.cache, fixed window)
                          ├─ last_used_at update (.filter().update(), no auto_now)
                          └─ delegate to existing services.py functions
                                  │
                                  └─ JsonResponse({'run_id': ..., 'status': ..., ...})
```

HTML views at `monitor/urls.py` remain untouched; session auth is unaffected.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. ApiKey Model + Migration | `ApiKey` model + `0013` migration; SHA-256 storage pattern | None — additive only |
| 2. Auth Decorator + Mgmt Views | `@require_api_key`, rate limiter, create/revoke views + URLs | `last_used_at` race condition if `.update()` pattern not followed |
| 3. API Endpoints | 4 endpoints at `/api/v1/`; `@csrf_exempt` required | Cross-user ownership check on `CheckRun` (no direct FK) |
| 4. Settings UI Page | `/settings/api-keys/` template + nav link | Raw key one-time display (session-based); must clear from session after render |
| 5. Tests | Full test coverage for decorator, rate limiter, endpoints | Rate-limit tests need cache isolation (`override_settings`) |

**Prerequisites:** No external dependencies. `python manage.py migrate` must run cleanly after Phase 1 before Phase 2 work begins.

**Estimated effort:** ~2-3 sessions across 5 phases (Phases 1–3 are the core; 4–5 are polish and safety net).

## Open Risks & Assumptions

- **Multi-process rate limiting**: `LocMemCache` is per-process. If Render scales beyond one gunicorn worker, rate-limit counters won't be shared. Switching to `DatabaseCache` (built-in Django, no extra package) is the documented upgrade path.
- **Fixed-window burst**: At minute boundaries, up to 2× the limit (120 requests) is theoretically possible. Acceptable for a solo-user product at 60 req/min.
- **`CheckRun` ownership**: The plan infers ownership via `results__rule__user`. A run that contains zero results (edge case: all rules errored before results were written) would return 404. Acceptable — such a run has no useful data.

## Success Criteria (Summary)

- `curl -H "Authorization: Bearer dp_<key>" http://localhost:8000/api/v1/rules` returns the user's rules as JSON
- Creating a key at `/settings/api-keys/` shows the raw `dp_...` key once; revoking it causes the API to return HTTP 401
- All `python manage.py test monitor` tests pass with no regressions
