---
date: 2026-10-29T11:34:20+00:00
researcher: worker-subagent
git_commit: 991d6ae9346728d5feecfd56d8cac6ddd7888da6
branch: dev
repository: data-pulse
topic: "Live preview — test rule query before saving"
tags: [research, codebase, services, api_views, rule_form, ajax]
status: complete
last_updated: 2026-10-29
last_updated_by: worker-subagent
---

# Research: Live preview — test rule query before saving

**Date**: 2026-10-29T11:34:20+00:00  
**Researcher**: worker-subagent  
**Git Commit**: 991d6ae9346728d5feecfd56d8cac6ddd7888da6  
**Branch**: dev  
**Repository**: data-pulse

## Research Question

Four questions for the `rule-live-preview` change (POST /api/v1/rules/preview):

1. How does `run_single_rule` work — can it run without saving a `RuleResult`?
2. What endpoint exists for preview (if any)?
3. What response format is needed?
4. How to show the result in the form without a page reload (AJAX)?

---

## Summary

`run_single_rule` always persists a `CheckRun` and a `RuleResult` to the database — it cannot run without saving. The core check logic that produces the raw dict is isolated in two private helpers (`_check_volume_freshness`, `_check_custom_sql`) called via `_check_rule`, which can each be called directly with an open `conn` and a `Rule`-like object and returns a plain dict without touching the DB. A preview endpoint does not yet exist anywhere in the project (neither in `monitor/api_urls.py` nor in `monitor/urls.py`). The response format required is a JSON dict with `status`, `row_count`, `last_record_age_hours`, `error_message`, and `sample_rows`. The form already uses `fetch()` for schema introspection, so the same AJAX+`JsonResponse` pattern can be applied for the preview button. The preview endpoint must be reachable from the browser with session auth (not Bearer token), because the rule form is a UI page, not an API client.

---

## Detailed Findings

### Q1 — `run_single_rule` always persists; `_check_rule` does not

`monitor/services.py:193–249` (`run_single_rule`):
- Opens by calling `CheckRun.objects.create()` (line ~193).
- Always calls `RuleResult.objects.create(...)` (multiple branches, lines ~197–247).
- Calls `notify_rule_result` on FAIL/ERROR (triggers email/Slack).
- Returns the `RuleResult` ORM instance.

**The function as written cannot be called for preview without side effects** (DB writes, notifications). A preview endpoint must NOT call `run_single_rule`.

The private helpers it delegates to produce a plain `dict` with no DB access:
- `monitor/services.py:_check_rule` (line ~165): dispatches to `_check_custom_sql` or `_check_volume_freshness` based on `rule.rule_type`.
- `monitor/services.py:_check_volume_freshness` (line ~201–260): takes `(conn, rule, provider)`, returns `{'row_count', 'last_record_age_hours', 'status', 'error_message', 'sample_rows'}`.
- `monitor/services.py:_check_custom_sql` (line ~155–200): same signature and return shape.

Both helpers only require an open DB connection and a rule-like object; they perform no ORM writes. They are already used directly in `run_checks_for_user` and `run_all_checks`.

A new `preview_rule(rule)` service function can open a connection, call `_check_rule`, and return the dict — no `CheckRun`, no `RuleResult`, no notification.

### Q2 — No preview endpoint exists

`monitor/api_urls.py` contains exactly 4 routes (inspected in full):
- `rules/run-all` → `api_run_all`
- `rules/<int:rule_id>/run` → `api_run_rule`
- `rules` → `api_list_rules`
- `rules/<int:rule_id>/results` → `api_get_results`

`monitor/urls.py` contains no preview route. The change.md spec says `POST /api/v1/rules/preview`, but that route does not exist yet; it must be added.

**Authentication note**: all routes in `monitor/api_urls.py` are guarded by `@require_api_key` (Bearer token, `monitor/api_auth.py`). A preview from the rule form uses Django session auth. Therefore the preview endpoint should be added to `monitor/urls.py` (session auth via `@login_required`), not to `monitor/api_urls.py`.

The change.md title "POST /api/v1/rules/preview" is the feature description, not necessarily the literal path. Given session-auth requirement, the path `api/rules/preview/` in `monitor/urls.py` (matching the existing schema introspection pattern at `api/schema/…`) is the natural fit. This is an open product decision — see Open Questions.

### Q3 — Required response format

Existing `api_run_rule` response (`monitor/api_views.py:27–35`) returns:
```json
{
  "run_id": "...",
  "rule_id": 123,
  "status": "OK|FAIL|ERROR",
  "row_count": 5,
  "last_record_age_hours": 2.5,
  "error_message": "",
  "checked_at": "2026-10-29T11:00:00+00:00"
}
```

The `RuleResult` model (`monitor/models.py:RuleResult`) stores `sample_rows` as a `JSONField` (null/blank). The change.md spec says preview should show sample rows, but `api_run_rule` does not include `sample_rows` in its response — the existing endpoint omits that field.

For preview, the required response is:
```json
{
  "status": "OK|FAIL|ERROR",
  "row_count": null_or_int,
  "last_record_age_hours": null_or_float,
  "error_message": "",
  "sample_rows": null_or_list_of_dicts
}
```

No `run_id` or `checked_at` is needed — preview does not persist. `sample_rows` must be included because the change.md spec explicitly lists it. The `_check_rule` helpers already populate `sample_rows` in their return dicts (inspected `_check_volume_freshness` lines ~250–270 and `_check_custom_sql` lines ~175–200).

### Q4 — AJAX pattern in the rule form

`templates/monitor/rule_form.html` already uses `fetch()` for two AJAX calls:
- Schema tables: `fetch('/api/schema/${connId}/tables/')` (line ~370).
- Schema columns: `fetch('/api/schema/${connId}/columns/${schema}/${table}/')` (line ~395).

Both calls use:
- No `Authorization` header (session cookie auth).
- `await r.json()` response handling.
- Inline DOM manipulation to display results.

The preview button can follow the same pattern:
1. Collect field values from the form.
2. POST to the preview endpoint with a CSRF token (`getCookie('csrftoken')` or read from `document.cookie`).
3. Render the result dict in a dedicated `<div id="preview-result">` injected below the form actions row.

CSRF: the form already has `{% csrf_token %}`. The `fetch` call needs `headers: {'X-CSRFToken': csrfToken, 'Content-Type': 'application/json'}`. The preview endpoint must be decorated with `@csrf_exempt` or — preferably — trust the session CSRF cookie via Django's default enforcement (`@login_required` already implies CSRF for standard views; `fetch` with the `X-CSRFToken` header is the documented AJAX pattern).

The existing schema-browser JS shows the precedent: the schema endpoints are `@login_required @require_GET` in `monitor/views.py`; the fetch calls do NOT send CSRF tokens because they are GET requests. The preview POST will need the CSRF token.

---

## Code References

- `monitor/services.py:193–249` — `run_single_rule`: always creates `CheckRun` + `RuleResult`, always notifies.
- `monitor/services.py:_check_rule` (approx line 165) — dispatches by `rule.rule_type`, returns plain dict.
- `monitor/services.py:_check_volume_freshness` (approx line 201) — returns `{status, row_count, last_record_age_hours, error_message, sample_rows}`.
- `monitor/services.py:_check_custom_sql` (approx line 155) — same return shape, validates and executes custom SQL.
- `monitor/api_urls.py:1–14` — all 4 existing API routes; none is `preview`.
- `monitor/urls.py:1–56` — all session-auth routes; no preview route.
- `monitor/api_views.py:21–36` — `api_run_rule` response shape (no `sample_rows`).
- `monitor/models.py:RuleResult` — `sample_rows` is `JSONField(null=True, blank=True)`.
- `templates/monitor/rule_form.html:~370` — existing `fetch('/api/schema/${connId}/tables/')` AJAX call pattern.
- `templates/monitor/rule_form.html:~395` — existing `fetch('/api/schema/${connId}/columns/…')` AJAX call pattern.
- `monitor/views.py:api_schema_tables` — session-auth `@require_GET` view as precedent for inline API endpoints.

---

## Architecture Insights

- The services layer cleanly separates DB-writing orchestrators (`run_single_rule`, `run_checks_for_user`, `run_all_checks`) from stateless check primitives (`_check_rule`, `_check_volume_freshness`, `_check_custom_sql`). The preview path should call only the primitives.
- A new `preview_rule(rule)` function in `services.py` mirrors `run_single_rule` minus the ORM writes: open conn → `_check_rule(conn, rule, provider)` → close conn → return dict.
- The split between `api_urls.py` (Bearer token) and `urls.py` (session auth) is consistent and load-bearing. Preview must land in `urls.py`.
- The rule form does not yet have a CSRF utility function for `fetch`; one must be added in the `{% block extra_scripts %}` JS or read from the cookie directly.

---

## Historical Context (from prior changes)

No prior `context/changes/` or `context/archive/` artifacts were found for preview or related endpoints in this repository.

---

## Related Research

No related research.md files found.

---

## Open Questions

1. **Preview endpoint path**: The change.md says `/api/v1/rules/preview`, which matches the Bearer-token `api_urls.py` namespace. But the form uses session auth. Should the endpoint live at `/api/v1/rules/preview` (requiring a session-aware auth variant) or at `/api/rules/preview/` in `monitor/urls.py` (consistent with schema introspection)? Recommend `/api/rules/preview/` in `monitor/urls.py` — a product decision is needed to confirm.

2. **Rule not yet saved**: The preview is triggered from the "Add Rule" form before the rule is saved, so no `rule_id` exists yet. The endpoint must accept rule parameters in the POST body (connection_id, rule_type, schema, table, etc.) rather than looking up a `Rule` by pk. The "Edit Rule" form can optionally send a `rule_id` for convenience, but the endpoint must work without one.

3. **Connection ownership**: The preview endpoint receives a `connection_id`. Ownership must be enforced (`Connection.objects.get(pk=..., user=request.user)`) to prevent SSRF via another user's connection URL.
