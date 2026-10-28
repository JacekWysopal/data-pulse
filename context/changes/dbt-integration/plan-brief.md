# dbt Webhook Integration — Plan Brief

> Full plan: `context/changes/dbt-integration/plan.md`
> Research: `context/changes/dbt-integration/research.md`

## What & Why

Add a `DbtIntegration` model and a public `POST /api/v1/webhooks/dbt/` webhook endpoint so DataPulse can automatically run monitoring rules immediately after a dbt run completes. Users connect their dbt Cloud jobs (or dbt Core pipelines via `curl`) to a set of DataPulse rules; when the job succeeds, DataPulse fires the checks without any manual action.

## Starting Point

DataPulse has no webhook infrastructure today. Every check is triggered manually via the UI or on a cron schedule. `monitor/models.py` defines five models — none for dbt integration. All existing views use `@login_required` session auth; no inbound-unauthenticated endpoint exists.

## Desired End State

A user creates a `DbtIntegration` record through `/integrations/dbt/new/`, copies the displayed HMAC secret into dbt Cloud (or a `curl` one-liner), and DataPulse automatically runs the mapped rules whenever dbt reports job success. Rule results appear in the existing history view within seconds of the dbt run completing.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| S-20 dependency | Standalone HMAC auth (no S-20 required) | Avoids blocking on unbuilt REST API; per-integration secret is the right granularity for webhook auth | Plan |
| Auth mechanism | HMAC-SHA256 shared secret, `Authorization: sha256=<hex>` header | Matches dbt Cloud's signing scheme; `hmac.compare_digest` prevents timing attacks | Plan / Research |
| Secret storage | Fernet-encrypted (same as `Connection._database_url`) | Encrypted storage with recovery on read; consistent with existing sensitive-field pattern | Research |
| Secret display | Shown once on create, not recoverable afterwards | Standard webhook-secret UX; prevents accidental re-exposure | Plan |
| Execution model | Synchronous in-request via `run_single_rule()` | Reuses all existing logic (CheckRun, RuleResult, notifications); no Celery needed at current scale | Research |
| Payload support | dbt Cloud (nested `data.jobId`) + dbt Core (flat `job_id`) | Broadens support to on-prem dbt users with minimal added complexity | Research |
| Success gating | `run_status.lower() == "success"` only; partial success ignored | Change spec says "after dbt job success"; avoids triggering on failed/cancelled runs | Plan |
| Unique constraint | `(user, job_id)` unique_together | Prevents duplicate integrations for the same job within one user's account | Plan |
| UI location | `/integrations/dbt/` — new top-level integrations page | Clean separation from Connections and Rules; extensible to future integration types | Plan |
| Trigger scope | `run_single_rule(rule)` per mapped rule (not `run_checks_for_user`) | Runs only the rules the user explicitly mapped, not all rules | Research |

## Scope

**In scope:**
- `DbtIntegration` model with Fernet-encrypted `secret_key`, `job_id`, M2M to `Rule`, FK to `Connection`
- `POST /api/v1/webhooks/dbt/` — HMAC validation, payload normalisation, rule triggering
- List / create / edit / delete UI at `/integrations/dbt/`
- Sidebar navigation entry for Integrations
- Unit + integration tests for model, webhook, and UI

**Out of scope:**
- S-20 REST API / API keys — not required
- Async execution / Celery
- dbt run metadata persistence (run_id, project_id, etc.)
- Manual replay / re-trigger UI
- Partial success handling
- Secret rotation UI

## Architecture / Approach

```
dbt Cloud job completes
    → POST /api/v1/webhooks/dbt/ (no CSRF, no session)
        → parse JSON body (normalise Cloud nested vs Core flat shape)
        → look up DbtIntegration by job_id
        → HMAC-SHA256 verify: hmac(secret, raw_body) vs Authorization header
        → gate on run_status == "success"
        → for each mapped rule: run_single_rule(rule) → RuleResult persisted
    → return JSON {triggered: N, results: [...]}
```

User manages integrations via `/integrations/dbt/` (standard Django CRUD views, `@login_required`, ownership-guarded by `user` FK on `DbtIntegration`).

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. DbtIntegration Model + Migration | New DB table with encrypted secret, M2M to Rule | Migration conflicts if last migration number collides |
| 2. Webhook Endpoint + HMAC Validation | Public POST endpoint with auth; returns 401/200/ignored | CSRF exempt + raw body capture must happen before JSON parse |
| 3. Trigger Logic | Webhook calls run_single_rule for each mapped rule | Synchronous execution blocks request for slow connections |
| 4. UI Integrations Page | List/create/edit/delete at /integrations/dbt/; secret shown once | Secret must only appear in create-success context, never edit |
| 5. Tests | Full coverage of model, webhook, and UI | Webhook tests need raw body + computed HMAC in test setup |

**Prerequisites:** No external dependencies. Requires existing `Connection`, `Rule`, `run_single_rule`, Fernet config (`FIELD_ENCRYPTION_KEY` in settings) to be present — all are already implemented.

**Estimated effort:** ~3–4 focused sessions across 5 phases.

## Open Risks & Assumptions

- `FIELD_ENCRYPTION_KEY` is configured in the deployment environment; if absent, `_get_fernet()` returns `None` and `secret_key` is stored in plaintext (same fallback as `Connection._database_url`).
- Synchronous execution means webhook response time grows linearly with rule count. Acceptable at current scale; becomes a problem if integrations map many slow rules.
- dbt Cloud HMAC signing uses the exact header format `Authorization: sha256=<hex>`. If dbt Cloud changes this format, the `removeprefix('sha256=')` parse step breaks silently — treat incoming sig as an empty string and return 401.

## Success Criteria (Summary)

- `POST /api/v1/webhooks/dbt/` with a valid HMAC and `runStatus: Success` triggers all mapped rules and returns `{"status": "ok", "triggered": N}`.
- The same endpoint returns HTTP 401 for any request with a missing or incorrect `Authorization` header.
- A user can create, view, edit, and delete integrations at `/integrations/dbt/` without seeing or modifying another user's data.
