# Rule Live Preview — Plan Brief

> Full plan: `context/changes/rule-live-preview/plan.md`
> Research: `context/changes/rule-live-preview/research.md`

## What & Why

Add a "Test query" button to the rule creation/edit form so users can verify that a rule works against their connection before saving it. The button fires a stateless POST that runs the rule logic and returns the result inline — no `CheckRun` or `RuleResult` is persisted, and no notifications are sent.

## Starting Point

The services layer already has stateless check primitives (`_check_rule`, `_check_volume_freshness`, `_check_custom_sql`) that return a plain dict with `{status, row_count, last_record_age_hours, error_message, sample_rows}` and do no DB writes. No preview endpoint exists yet. The rule form already uses `fetch()` with session cookies for schema introspection calls.

## Desired End State

A "Test query" button appears below the conditions section in both rule-type modes. Clicking it POSTs form values to `POST /api/preview/`, and an inline result card renders with a coloured status badge, measured values, and (on FAIL) a compact table of up to 3 sample rows. No database rows are written.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| No DB writes on preview | Stateless — no CheckRun/RuleResult | Preview is a validation tool; persisting would pollute history and trigger notifications | Plan |
| Auth strategy | Session auth (`@login_required`) in `monitor/urls.py` | The form uses session cookies, not Bearer tokens; consistent with schema introspection endpoints | Research |
| Preview endpoint path | `POST /api/preview/` in `monitor/urls.py` | Matches the session-auth inline API namespace; Bearer-token `api_urls.py` is for external API clients | Research |
| Params via POST body | POST body (not rule_id lookup) | The Add Rule form fires before the rule is saved, so no rule_id exists yet | Research |
| Ownership guard | `Connection.objects.get(pk=..., user=user)` in service layer | Prevents SSRF via another user's connection; consistent with `api_schema_tables` pattern | Research |
| sample_rows limit | Slice to first 3 rows in endpoint | Sufficient for visual confirmation; keeps response payload small | Plan |
| Entry point | New `preview_rule(params, user)` in `services.py` | Calls existing `_check_rule` primitive; mirrors `run_single_rule` structure minus ORM writes | Research |

## Scope

**In scope:**
- `preview_rule(params, user)` function in `services.py` — stateless, ownership-checked
- `POST /api/preview/` view in `views.py` + URL registration in `urls.py`
- "Test query" button + JS + inline result card in `rule_form.html` (both Volume/Freshness and Custom SQL modes)
- Unit + view tests (service layer mocked; view layer uses test client)

**Out of scope:**
- Bearer-token API variant of the preview endpoint
- Storing preview history or linking previews to saved rules
- Changes to `api_urls.py` or any existing REST API surface
- No migrations (no model changes)

## Architecture / Approach

`preview_rule(params, user)` wraps the existing `_check_rule` primitive: resolve connection → verify ownership → build a transient `SimpleNamespace` rule object → open conn → `_check_rule(conn, ns, provider)` → close conn → slice `sample_rows[:3]` → return dict. The view parses JSON, calls the service, returns `JsonResponse`. The JS IIFE in `rule_form.html` reads the CSRF token from the cookie, POSTs with `X-CSRFToken` header, and renders the result card inline.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. preview_rule() in services.py | Stateless service function, tested in isolation | Edge case: rule namespace missing a field accessed by `_check_rule` |
| 2. POST /api/preview/ endpoint | Wired view + URL, ownership guard enforced | Input validation gaps (non-integer connection_id, malformed JSON) |
| 3. Test query button + JS + result card | User-visible button in both rule-type modes, inline result card | CSRF cookie absent in some browser contexts; sample_rows structure varies |
| 4. Tests | Full coverage of service + view; regression guard | Mock boundary — view tests must mock at `monitor.views.preview_rule` not `monitor.services` |

**Prerequisites:** No migrations or config changes needed. Requires a working `monitor/services.py` (already present).
**Estimated effort:** ~1 session across 4 short phases

## Open Risks & Assumptions

- `_check_rule` accesses `rule.rule_type`, `rule.schema_name`, `rule.table_name`, `rule.custom_sql`, `rule.min_row_count`, `rule.timestamp_column`, `rule.max_age_hours` — the `SimpleNamespace` must include all these fields with sensible defaults (empty string / None).
- The `sample_rows[:3]` slice assumes the helper returns a list or `None`; both cases must be handled.
- Browser CSRF cookie must be present; the form page always sets it via Django's middleware, so this is safe for normal browser use.

## Success Criteria (Summary)

- A user can click "Test query" on a new or edited rule and see status + measured values before saving.
- `python manage.py test monitor` passes with no regressions.
- No `CheckRun` or `RuleResult` rows are created by a preview call.
