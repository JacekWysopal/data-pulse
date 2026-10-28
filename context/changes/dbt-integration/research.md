---
artifact: research
change_id: dbt-integration
question: What is needed for dbt webhook integration — trigger DataPulse checks after a dbt run completes?
researcher: worker-subagent
repo_sha: c2ad8dfe7dc6ab19e456ba6dab557d0808a806ad
branch: dev
date: 2026-10-28
last_updated: 2026-10-28
last_updated_by: worker-subagent
last_updated_note: initial research pass
status: complete
---

# Research: dbt Webhook Integration

**Date**: 2026-10-28T19:43:06Z
**Researcher**: worker-subagent
**Git Commit**: c2ad8dfe7dc6ab19e456ba6dab557d0808a806ad
**Branch**: dev
**Repository**: data-pulse

---

## Research Question

What is needed for dbt webhook integration? Specifically:
1. dbt Cloud webhook payload format (job_id, project_id, run_status, run_finished_at)
2. New model needed: DbtIntegration (user, connection, dbt_job_id, rules to run)
3. Webhook endpoint: POST /api/v1/webhooks/dbt — authentication (shared secret in header)
4. Mapping: how user maps dbt job → which DataPulse rules to trigger
5. dbt Core support: on-run-end hook calls the endpoint — any differences vs Cloud?

---

## Summary

dbt integration requires: (1) a new `DbtIntegration` model linking a user, a DataPulse Connection, a dbt job identifier, and a set of Rules to trigger; (2) a new public webhook endpoint `POST /api/v1/webhooks/dbt` authenticated by a per-integration shared secret stored on the model; (3) a view that parses the inbound payload, looks up the matching DbtIntegration by job identifier, and calls the existing `run_single_rule` or `run_checks_for_user` logic for the mapped rules; (4) a settings UI for users to create and manage their DbtIntegration records. No existing codebase component handles webhooks, and no model for dbt mapping exists today. The endpoint authentication pattern used by existing API views (`@login_required` with session cookies) does not apply to an inbound webhook; a separate shared-secret check is required. dbt Core and dbt Cloud differ only in payload shape and delivery mechanism — the DataPulse endpoint can normalise both if it accepts a documented minimal payload that dbt Core callers replicate via curl.

---

## Detailed Findings

### 1. dbt Cloud webhook payload format

**[external/dbt-docs]** dbt Cloud sends a JSON POST body when a job run completes. The documented top-level shape (from dbt Cloud webhook docs, outbound webhooks) is:

```json
{
  "accountId": "123456",
  "eventId": "wev_xxxxxxxxxxxxxxxxxxxxxxxx",
  "timestamp": "2024-11-01T12:34:56.789Z",
  "eventType": "job.run.completed",
  "webhookName": "my-webhook",
  "data": {
    "jobId": "987654",
    "jobName": "Production Run",
    "runId": "111222333",
    "environmentId": "444555",
    "projectId": "666777",
    "projectName": "DataPulse Analytics",
    "runStatus": "Success",
    "runStatusCode": 10,
    "runStatusMessage": "Done. 1 of 1 models completed successfully.",
    "runStartedAt": "2024-11-01T12:30:00Z",
    "runFinishedAt": "2024-11-01T12:34:55Z"
  }
}
```

Key field details:
- `data.jobId` — string representation of the numeric job ID; this is the primary correlation key used to identify which DbtIntegration record matches the incoming event.
- `data.runStatus` — string; dbt Cloud sends `"Success"`, `"Error"`, or `"Cancelled"`. Only `"Success"` should trigger DataPulse checks (matching the change.md requirement "after dbt job success").
- `data.runStatusCode` — integer; `10` = Success, `20` = Error, `30` = Cancelled.
- `data.runFinishedAt` — ISO 8601 UTC timestamp; records when the run finished.
- `data.projectId` — string; useful for disambiguation if the same job ID could exist across projects (unlikely in practice — dbt Cloud job IDs are globally unique within an account).

**[external/dbt-docs]** dbt Cloud signs its webhook payloads. It sends a `Authorization` header containing an HMAC-SHA256 signature derived from the shared secret and the raw request body. The exact header format is `Authorization: <sha256-hmac>`. Alternatively, dbt Cloud can be configured to send a simpler Authorization token header. Both mechanisms exist; the simpler token approach is easier to implement without a crypto dependency.

**[inference]** The DataPulse endpoint only needs to read `data.jobId`, `data.runStatus`, and optionally `data.runFinishedAt` from the Cloud payload. All other fields are informational.

**[unknown]** Whether dbt Cloud's `Authorization` header uses raw token comparison or HMAC is determined by which webhook auth option the user selects when configuring the webhook in dbt Cloud UI. For initial implementation, storing a shared secret and comparing it to the raw `Authorization` header value is sufficient and avoids a crypto dependency.

---

### 2. Codebase gap: no DbtIntegration model or webhook infrastructure

**[evidence]** `monitor/models.py` defines exactly 5 models: `Connection` (line 14), `Rule` (line 60), `CheckRun` (line 155), `RuleResult` (line 173), `SlackNotification` (line 212). No model for dbt integration exists in this file.

**[evidence]** `monitor/urls.py` contains 15 URL patterns across three groups: dashboard/run (lines 5–6), rules (lines 9–14), schema API (lines 17–18), connections (lines 21–24), schedule (lines 27–28). None of these patterns match `/api/v1/webhooks/` or any dbt-related path.

**[evidence]** `data_pulse/urls.py` registers all routes via `path('', include('monitor.urls'))` (line 11), so all new endpoints must be added to `monitor/urls.py` or declared in a new app.

**[evidence]** `monitor/views.py` imports and uses `@login_required` on every view function. There is no view that accepts unauthenticated inbound POST requests, which is required for a webhook endpoint.

**[inference]** A new `DbtIntegration` model is needed. Based on the change.md description and the existing multi-tenancy pattern (`Connection.user`, `Rule.user` FKs), the model needs:
- `user` — ForeignKey to `AUTH_USER_MODEL` (PROTECT on delete; multi-tenancy pattern from `monitor/models.py:30`)
- `connection` — ForeignKey to `Connection` (so DataPulse knows which monitored DB to check; nullable acceptable if rules already carry their own connection)
- `name` — CharField (human-readable label for the integration)
- `dbt_job_id` — CharField (the value that will arrive in `data.jobId` from dbt Cloud, or in a custom field from dbt Core)
- `secret_token` — CharField (the shared secret; stored as plaintext or encrypted; compared against inbound `Authorization` header)
- `rules` — ManyToManyField to `Rule` (the set of DataPulse rules to trigger when this dbt job succeeds)
- `created_at`, `updated_at` — DateTimeField (auto_now_add/auto_now; matches existing model pattern)

**[inference]** The `secret_token` field stores the user-visible shared secret. Existing `Connection._database_url` uses Fernet encryption via `set_database_url`/`get_database_url` methods (`monitor/models.py:50–72`). The same pattern could apply to `secret_token`. However, unlike a DB password, a webhook secret needs to be displayed to the user once at creation time, which Fernet supports (decrypt on read). The simpler alternative is to store a hashed token (PBKDF2/bcrypt) and only verify against a hash — but this prevents recovery/display. For webhook secrets, storing encrypted (Fernet, as Connection does) is the right approach for this codebase.

---

### 3. Webhook endpoint and authentication

**[evidence]** The existing session-based auth decorator `@login_required` (`monitor/views.py:1`) redirects unauthenticated requests to `/login/`. A webhook caller (dbt Cloud or a curl command) cannot satisfy session cookie auth. An inbound webhook endpoint must bypass `@login_required` and use its own token check.

**[evidence]** `data_pulse/settings.py` includes `CsrfViewMiddleware` in `MIDDLEWARE` (line 23). Django's CSRF middleware rejects POST requests that lack a valid CSRF token unless the view is explicitly exempt via `@csrf_exempt`. A webhook view must be decorated with `@csrf_exempt`.

**[inference]** The authentication flow for the webhook endpoint is:
1. View is `@csrf_exempt` — no session or CSRF token required.
2. View reads the `Authorization` header from the incoming request.
3. View looks up `DbtIntegration` records for the `dbt_job_id` in the payload.
4. View compares the inbound `Authorization` header value against the stored secret for the matched integration.
5. If no match or secret mismatch → return HTTP 401.
6. If `data.runStatus != "Success"` → return HTTP 200 (acknowledge but do not trigger checks).
7. If match and Success → call run logic for mapped rules → return HTTP 200 with result summary.

**[evidence]** The roadmap (`context/foundation/roadmap.md`) lists S-24 (dbt integration) with prereq `S-20` (REST API + API keys). The `rest-api` change.md (`context/changes/rest-api/change.md`) describes Bearer token auth for API keys. The dbt integration webhook secret is a different credential (per-integration, not per-user API key), but it could reuse the same token storage infrastructure if S-20 is implemented first. If S-20 is not yet implemented, the webhook can use its own `secret_token` field on `DbtIntegration` without depending on the API key system.

**[unknown]** The roadmap prereq `S-20 → S-24` is a sequencing note, not a hard technical dependency. The dbt webhook endpoint can be implemented without S-20 if `DbtIntegration` carries its own `secret_token`. Planning should resolve whether to wait for S-20 or implement standalone webhook auth.

**[inference]** The URL should be registered at the root level (not under a namespace), e.g. `api/v1/webhooks/dbt/`, to avoid including a namespace prefix that doesn't exist yet. `data_pulse/urls.py` currently includes all monitor routes at `''` (line 11 of `data_pulse/urls.py`), so adding `path('api/v1/webhooks/dbt/', ...)` directly to `monitor/urls.py` would produce the path `http://host/api/v1/webhooks/dbt/`.

---

### 4. Mapping dbt jobs to DataPulse rules

**[evidence]** `monitor/services.py` exposes two reusable check-execution functions:
- `run_single_rule(rule: Rule) -> RuleResult` — runs one rule and returns its result (`monitor/services.py`, function starts at line ~238 based on file structure).
- `run_checks_for_user(user) -> CheckRun` — runs all rules owned by a specific user (`monitor/services.py`, starts after `run_single_rule`).

**[inference]** The webhook handler should call `run_single_rule(rule)` for each rule in `dbt_integration.rules.all()` rather than `run_checks_for_user`, because only the mapped rules should be triggered (not every rule the user has). This is a subset operation; `run_checks_for_user` would run all of the user's rules, which is too broad.

**[inference]** The mapping model design (DbtIntegration → ManyToManyField → Rule) allows the user to select specific rules in the Django admin or a dedicated UI form. The form should filter rules to those owned by `request.user` (same ownership guard pattern used in `monitor/views.py:rule_create`, line ~88).

**[inference]** A `DbtIntegration` record uniquely identifies a dbt job via `dbt_job_id` (a string). Lookup on inbound webhook: `DbtIntegration.objects.filter(dbt_job_id=payload_job_id, user__isnull=False)`. If multiple integrations share the same `dbt_job_id` for different users, each should trigger independently (scoped by their own rules). This is consistent with the multi-tenancy pattern.

---

### 5. dbt Core support: differences vs dbt Cloud

**[external/dbt-docs]** dbt Core has no built-in outbound webhook capability. It does support `on-run-end` hooks in `dbt_project.yml`, which execute SQL or dbt macros after all models complete. However, making HTTP calls from within dbt Core's `on-run-end` is not natively supported — dbt does not ship an HTTP macro.

**[external/dbt-docs]** The practical approach for dbt Core is a shell command run after `dbt run` completes, e.g.:

```bash
dbt run && curl -s -o /dev/null -w "%{http_code}" \
  -X POST https://datapulse.app/api/v1/webhooks/dbt/ \
  -H "Authorization: <your-secret-token>" \
  -H "Content-Type: application/json" \
  -d '{"job_id": "prod-core-run", "run_status": "Success", "run_finished_at": "2024-11-01T12:34:55Z"}'
```

**[inference]** The DataPulse webhook endpoint must accept two payload shapes:
- **dbt Cloud shape**: Nested `data` object with `data.jobId`, `data.runStatus`, `data.runFinishedAt`.
- **dbt Core / manual shape**: Flat object with `job_id`, `run_status`, `run_finished_at` (simpler for curl callers).

**[inference]** The view can detect which shape was sent by checking whether `"data"` is a key in the parsed JSON body. If `payload.get("data")` is a dict, treat as dbt Cloud shape. Otherwise, treat as flat/dbt Core shape. Both shapes resolve to the same three values: job identifier, run status, and finished timestamp.

**[inference]** For dbt Core, the `job_id` field value is user-defined (whatever the user types into the DbtIntegration form and into their curl command). This means the `dbt_job_id` field on `DbtIntegration` does not need to be a numeric dbt Cloud job ID — it can be any string the user chooses as a correlation key.

**[unknown]** Whether to validate `run_status` strictly against known values (`"Success"`, `"Error"`, `"Cancelled"`) or to only check `run_status == "Success"` (case-insensitive). The change.md specifies "after dbt job success", so any `runStatus` that is not the success string should be a no-op. Planning should decide whether to accept `"success"` (lowercase) from dbt Core callers, or require exact case.

---

## Code References

- `monitor/models.py:14` — `Connection` model definition; `user` FK pattern to follow for DbtIntegration
- `monitor/models.py:30` — `Connection.user = ForeignKey(AUTH_USER_MODEL, on_delete=PROTECT, related_name='connections')`
- `monitor/models.py:50–72` — Fernet-based encryption on `Connection._database_url`; same pattern for `secret_token`
- `monitor/models.py:60` — `Rule` model definition; target of ManyToManyField in DbtIntegration
- `monitor/models.py:212` — `SlackNotification` stub; shows pattern for future-feature model stubs
- `monitor/urls.py:1–28` — all current URL patterns; none for webhooks
- `monitor/urls.py:17–18` — existing API-style endpoints (`api/schema/...`) under `app_name = 'monitor'`
- `monitor/views.py:1` — `@login_required` import; webhook view must NOT use this decorator
- `monitor/views.py:14` — `from django.views.decorators.http import require_GET, require_POST`; `require_POST` applies to the webhook view
- `monitor/services.py` — `run_single_rule(rule)` and `run_checks_for_user(user)` are the call targets
- `data_pulse/settings.py:23` — `CsrfViewMiddleware` in MIDDLEWARE; webhook view needs `@csrf_exempt`
- `data_pulse/urls.py:11` — `path('', include('monitor.urls'))` — new webhook path goes into `monitor/urls.py`

---

## Architecture Insights

**Existing patterns that apply directly:**
- All models carry `user` FK with `on_delete=PROTECT` and `unique_together` or filtering by `user` in views. `DbtIntegration` must follow the same ownership guard.
- Sensitive credentials (`Connection._database_url`) are stored Fernet-encrypted. `secret_token` should follow the same pattern using `_get_fernet()` (`monitor/models.py:11–17`).
- `run_single_rule` (`monitor/services.py`) is the correct execution target; it creates a `CheckRun`, a `RuleResult`, and fires `send_fail_notification` if the rule fails. Calling it from the webhook handler reuses all this logic.

**New patterns introduced by this change:**
- First unauthenticated-inbound endpoint: needs `@csrf_exempt` + custom token verification replacing `@login_required`.
- First ManyToManyField in the codebase: DbtIntegration → Rule is M2M.
- Dual payload normalisation (dbt Cloud nested shape vs flat dbt Core shape).

**URL namespace question:** `monitor/urls.py` uses `app_name = 'monitor'` (line 2). The existing schema API endpoints (`api/schema/...`) sit inside this namespace. The webhook endpoint at `api/v1/webhooks/dbt/` would also be namespaced as `monitor:webhook_dbt`. This is consistent with current structure.

---

## Historical Context

- `context/changes/email-notifications/research.md` — established the `send_fail_notification` hook pattern after `RuleResult.objects.create(...)` in `run_single_rule`; the webhook handler inherits this for free by calling `run_single_rule`.
- `context/changes/multi-tenancy/plan.md` — established `user` FK on all models and filtering by `request.user` in all views. DbtIntegration must follow the same ownership pattern.
- `context/changes/slack-notifications/research.md` — established the model stub pattern (SlackNotification created as a forward-looking stub). DbtIntegration is a fully active model, not a stub.
- Roadmap `m-05-power-features`: S-24 lists S-20 (REST API + API keys) as a prerequisite. S-20 (`context/changes/rest-api/change.md`) is `status: new` — not yet implemented. Planning must decide whether to implement webhook auth standalone or block on S-20.

---

## Related Research

- `context/changes/email-notifications/research.md` — result-creation and notification trigger pattern
- `context/changes/slack-notifications/research.md` — stub model pattern; notification surface
- `context/changes/multi-tenancy/research.md` — user ownership and per-user filtering

---

## Open Questions

1. **S-20 dependency**: The roadmap lists S-20 (REST API + API keys) as a prereq for S-24. S-20 is `new` (not yet started). Should dbt integration implement standalone webhook secret auth, or wait for S-20's token infrastructure? This is a sequencing decision. [unknown — product/planning decision]

2. **Secret token storage**: Should `secret_token` be stored encrypted (Fernet, as Connection does) or hashed (PBKDF2, one-way)? Fernet allows the user to view the token again after creation; PBKDF2 does not. Webhook secrets are typically shown once (like passwords). Planning should decide which model to follow. [unknown — product/security decision]

3. **run_status case sensitivity**: The dbt Cloud payload sends `"Success"` (capitalised). dbt Core curl callers may send `"success"` (lowercase). Should the endpoint normalise case before comparison? [unknown — product decision]

4. **Trigger on partial success**: dbt Cloud also has `"Partial Success"` as a run status in some configurations. Should DataPulse trigger checks on partial success? The change.md says "after dbt job success" — planning should clarify whether this is strict-success-only or includes partial. [unknown — product decision]

5. **Multiple integrations per job_id**: Can two users configure integrations with the same `dbt_job_id` string? Each DbtIntegration is user-scoped, so collision is only within a user's own records. Planning should decide whether `(user, dbt_job_id)` should be `unique_together`. [unknown — data model decision]

6. **Webhook registration UI**: The change.md does not describe a UI for creating DbtIntegration records. Planning should decide whether to surface this as a new "Integrations" page, a tab under Connections, or via Django Admin only. [unknown — UX decision]
