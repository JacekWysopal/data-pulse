

No write tool is available in this session. Per skill instructions, I'll return the complete artifacts in my response for runtime persistence.

---

## Review

```
═══════════════════════════════════════════════════════════
  PLAN REVIEW: dbt Webhook Integration
  Mode: Deep  |  Date: 2025-07-10
  Findings: 0 critical  3 warnings  2 observations
═══════════════════════════════════════════════════════════

  End-State Alignment    PASS    ✅
  Lean Execution         PASS    ✅
  Architectural Fitness  PASS    ✅
  Blind Spots            WARNING ⚠️   (2 findings)
  Plan Completeness      WARNING ⚠️   (3 findings)

  Grounding: 7/7 paths ✓, 5/5 symbols ✓, brief↔plan ✓
  ► Overall: REVISE

═══════════════════════════════════════════════════════════
  WARNING FINDINGS ⚠️
═══════════════════════════════════════════════════════════

  F1 — Phase 2 imports embedded in view stub, no module-level placement note
  ╌╌╌╌╌╌╌
    Severity:  ⚠️ WARNING
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Plan Completeness
    Location:  Phase 2 — dbt_webhook view contract

    Detail:
    The Phase 2 code block places `import hashlib`, `import hmac as _hmac`,
    `import secrets`, and `from django.views.decorators.csrf import csrf_exempt`
    inside the view stub. monitor/views.py puts all imports at lines 1–14;
    none of these four are currently present there. The comment
    "# (require_POST already imported at monitor/views.py:14)" hints at
    integration, but the contract never says "add these to the top-level
    imports block." An implementer following the code block literally may
    place the imports inside the function body, which is non-idiomatic and
    would trigger linter warnings.

    Fix: Add one sentence before the code block: "First add `import hashlib`,
    `import hmac as _hmac`, `import secrets`, and
    `from django.views.decorators.csrf import csrf_exempt` to the top of
    `monitor/views.py` alongside the existing imports (lines 1–14). The
    code block below shows them for clarity; do not place them inside the
    function body."

  ···

  F2 — Phase 4 create view uses render-on-POST; double-submit risk not noted
  ╌╌╌╌╌╌╌
    Severity:  ⚠️ WARNING
    Impact:    🔎 MEDIUM — real tradeoff; pause to reason through it
    Dimension: Blind Spots
    Location:  Phase 4 — dbt_integration_create view contract

    Detail:
    The plan says "simplest is render the create template on success with
    raw_key in context instead of redirect." This deliberately deviates
    from the POST-redirect-GET pattern used by connection_create
    (views.py:225–233) to avoid losing the raw secret across a redirect.
    The plan doesn't flag the consequence: refreshing the browser after
    a successful create re-submits the form. The unique_together(user,
    job_id) constraint on DbtIntegration will catch a true duplicate and
    surface a form error rather than a silent second row, so data integrity
    is safe — but the UX is confusing.

    Fix A ⭐ Recommended: Keep render-on-POST and add an explicit note to the
      contract: "Page refresh after create re-submits the form; the
      unique_together(user, job_id) constraint will produce a form
      validation error, not a silent duplicate. This is acceptable given
      the secret-display requirement."
      Strength:   No additional view or template needed; constraint is a
                  safety net; already planned.
      Tradeoff:   Slightly confusing UX on accidental refresh.
      Confidence: HIGH — unique_together confirmed in Phase 1 model contract.
      Blind spot: Whether the form error message clearly communicates
                  "this job_id already exists" vs. a generic error.

    Fix B: Redirect to a `_created` detail view; write raw_key to
      request.session before redirect, consume once in the detail view.
      POST-redirect-GET safe; no double-submit.
      Strength:   Correct PRG pattern; aligns with connection_create style.
      Tradeoff:   Adds a fifth UI view; increases Phase 4 scope.
      Confidence: HIGH — Django session write-then-consume is standard.
      Blind spot: Assumes Django session middleware is active; it is
                  (SessionMiddleware is in MIDDLEWARE by default).

  ···

  F3 — Phase 4 sidebar file reference is vague
  ╌╌╌╌╌╌╌
    Severity:  ⚠️ WARNING
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Plan Completeness
    Location:  Phase 4 — Sidebar navigation update

    Detail:
    Plan says "File: sidebar/base template (check templates/ for the nav
    partial)". There is no separate sidebar partial; the entire nav is in
    templates/base.html, confirmed at lines 636–649 (the Connections nav
    item). The plan's file reference will cause the implementer to search
    before they can start.

    Fix: Replace the file reference with "File: templates/base.html — add
    a new <a> block after the Connections item (around line 650) using the
    same dp-nav-item structure. Active-state: {% if 'dbt_integration' in
    request.resolver_match.url_name %}active{% endif %}."

═══════════════════════════════════════════════════════════
  OBSERVATION FINDINGS 🔍
═══════════════════════════════════════════════════════════

  F4 — No make_dbt_integration helper defined for HMAC test setup
  ╌╌╌╌╌╌╌
    Severity:  🔍 OBSERVATION
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Plan Completeness
    Location:  Phase 5 — DbtWebhookViewTest

    Detail:
    DbtWebhookViewTest needs a DbtIntegration with a known raw secret to
    compute the correct HMAC in every test. make_rule (tests.py:24) and
    make_connection (tests.py:43) exist as module-level helpers; the plan
    says "extend rather than replace" but provides no make_dbt_integration
    definition. The HMAC tests are the most setup-sensitive in the suite —
    they must call set_secret_key(raw) before save, mirror exactly what
    make_connection does for set_database_url. Without a defined helper,
    each test inlines the setup or drifts independently.

    Fix: Add to Phase 5 contract: "Add a module-level helper
    `make_dbt_integration(user, job_id='test-job', raw_secret='test-secret',
    rules=None)` that mirrors make_connection: create a DbtIntegration,
    call obj.set_secret_key(raw_secret), save, set rules if provided,
    return obj."

  ···

  F5 — HMAC test byte-encoding trap not documented
  ╌╌╌╌╌╌╌
    Severity:  🔍 OBSERVATION
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Blind Spots
    Location:  Phase 5 — DbtWebhookViewTest

    Detail:
    The view computes HMAC over request.body (raw bytes). When using
    Django's test Client, the byte sequence the view sees depends on
    how the POST is made. Calling client.post(url, data=dict, ...) uses
    form encoding, not JSON bytes, breaking the HMAC match. The test must
    post raw bytes: body = json.dumps(payload).encode(); then pass
    data=body, content_type='application/json'. This is a common
    HMAC-webhook test trap; the plan doesn't mention it.

    Fix: Add a note to the DbtWebhookViewTest contract: "Compute test
    HMAC over the exact bytes posted: body = json.dumps(payload).encode();
    sig = hmac.new(raw_secret.encode(), body, hashlib.sha256).hexdigest().
    Post via self.client.post(url, data=body,
    content_type='application/json',
    HTTP_AUTHORIZATION=f'sha256={sig}')."

═══════════════════════════════════════════════════════════
  Merge verdict: REVISE — 3 warnings, all fixable before Phase 2 begins.
  F1 and F3 are one-line plan edits. F2 needs a decision on render-vs-
  redirect. F4 and F5 can be resolved by adding two paragraphs to Phase 5.
  No architectural blockers; end state is clear and all paths verified.
═══════════════════════════════════════════════════════════
```

---

**Output artifacts for runtime persistence:**

**File 1 — `context/changes/dbt-integration/reviews/plan-review.md`**

```markdown
<!-- PLAN-REVIEW-REPORT -->
# Plan Review: dbt Webhook Integration

- **Plan**: context/changes/dbt-integration/plan.md
- **Mode**: Deep
- **Date**: 2025-07-10
- **Verdict**: REVISE
- **Findings**: 0 critical, 3 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding

7/7 paths ✓, 5/5 symbols ✓, brief↔plan ✓

Paths verified: `monitor/models.py`, `monitor/views.py`, `monitor/urls.py`, `monitor/services.py`, `monitor/forms.py`, `monitor/tests.py`, `data_pulse/settings.py` — all exist.
Symbols verified: `_get_fernet()` (models.py:14), `run_single_rule` (services.py:289 and imported at views.py:14), `make_rule` (tests.py:24), `make_connection` (tests.py:43), `require_POST` (views.py:9) — all confirmed.
Brief↔plan: phases, scope, key decisions consistent.
`docs/reference/contract-surfaces.md`: not present — check skipped (opt-in convention).

## Findings

### F1 — Phase 2 imports embedded in view stub, no module-level placement note

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 — dbt_webhook view contract
- **Detail**: The Phase 2 code block places `import hashlib`, `import hmac as _hmac`, `import secrets`, and `from django.views.decorators.csrf import csrf_exempt` inside the view stub. `monitor/views.py` has all imports at lines 1–14; none of these four are currently present there. The comment `# (require_POST already imported at monitor/views.py:14)` implies integration but the contract never says "add these to the top-level imports block." An implementer following the code block literally may place imports inside the function body, which is non-idiomatic.
- **Fix**: Add one sentence before the code block: "First add `import hashlib`, `import hmac as _hmac`, `import secrets`, and `from django.views.decorators.csrf import csrf_exempt` to the top of `monitor/views.py` alongside the existing imports (lines 1–14). The code block below shows them for reference; do not place them inside the function body."
- **Decision**: PENDING

---

### F2 — Phase 4 create view uses render-on-POST; double-submit risk not noted

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 4 — dbt_integration_create view contract
- **Detail**: The plan says "simplest is render the create template on success with `raw_key` in context instead of redirect." This deliberately deviates from the POST-redirect-GET pattern used by `connection_create` (views.py:225–233) to avoid losing the raw secret across a redirect. The plan does not flag the consequence: a browser page refresh after a successful create re-submits the form. The `unique_together(user, job_id)` constraint will catch a true duplicate and surface a form error (not a silent second row), so data integrity is preserved — but the UX is confusing.
- **Fix A ⭐ Recommended**: Keep render-on-POST and add an explicit note: "Rendering on POST (not redirecting) is intentional to pass `raw_key` in context. A page refresh after create will re-submit the form; the `unique_together(user, job_id)` constraint will produce a validation error, not a silent duplicate. This is acceptable given the secret-display requirement."
  - Strength: No additional view needed; unique constraint is the safety net; minimal scope change.
  - Tradeoff: Confusing UX if the user accidentally refreshes; form error message may not be intuitive.
  - Confidence: HIGH — `unique_together` confirmed in Phase 1 model contract.
  - Blind spot: Whether the form error message clearly communicates "this job_id already exists" vs. a generic constraint error.
- **Fix B**: Redirect to a `_created` detail view; write `raw_key` to `request.session` before redirect, consume once in the detail view. POST-redirect-GET safe; no double-submit.
  - Strength: Correct PRG pattern; aligns with `connection_create` style; no double-submit risk.
  - Tradeoff: Adds a fifth UI view and template; increases Phase 4 scope.
  - Confidence: HIGH — Django session write-then-consume is standard; session middleware is active by default.
  - Blind spot: None significant.
- **Decision**: PENDING

---

### F3 — Phase 4 sidebar file reference is vague

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 4 — Sidebar navigation update
- **Detail**: Plan says `File: sidebar/base template (check templates/ for the nav partial)`. There is no separate sidebar partial; the entire nav is inline in `templates/base.html`, confirmed at lines 636–649 (the Connections nav item block). No sidebar partial file exists. The vague reference forces the implementer to search before they can start.
- **Fix**: Replace the file reference with: "File: `templates/base.html` — add a new `<a class=\"dp-nav-item\">` block after the Connections item (around line 650) using the same `dp-nav-item` structure. Active-state condition: `{% if 'dbt_integration' in request.resolver_match.url_name %}active{% endif %}`."
- **Decision**: PENDING

---

### F4 — No make_dbt_integration helper defined for HMAC test setup

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 5 — DbtWebhookViewTest
- **Detail**: `DbtWebhookViewTest` needs a `DbtIntegration` with a known raw secret to compute the correct HMAC signature in every test. `make_rule` (tests.py:24) and `make_connection` (tests.py:43) exist as module-level helpers. The plan says "extend rather than replace" but provides no `make_dbt_integration` definition. HMAC tests are the most setup-sensitive — they must call `set_secret_key(raw)` before save, exactly as `make_connection` calls `set_database_url`. Without a defined helper, each test inlines setup differently or drifts.
- **Fix**: Add to Phase 5 contract: "Add module-level helper `make_dbt_integration(user, job_id='test-job', raw_secret='test-secret', rules=None)` that mirrors `make_connection`: create a `DbtIntegration`, call `obj.set_secret_key(raw_secret)`, save, call `obj.rules.set(rules)` if provided, return `obj`."
- **Decision**: PENDING

---

### F5 — HMAC test byte-encoding trap not documented

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 5 — DbtWebhookViewTest
- **Detail**: The view computes HMAC over `request.body` (raw bytes). When using Django's test `Client`, calling `client.post(url, data=dict)` sends form-encoded bytes — not JSON bytes — breaking the HMAC match. The test must post raw bytes: `body = json.dumps(payload).encode()` and pass `data=body, content_type='application/json'`. This is a common HMAC webhook test trap; the plan doesn't mention it.
- **Fix**: Add a note to the `DbtWebhookViewTest` contract: "Compute the test HMAC over the exact bytes posted: `body = json.dumps(payload).encode(); sig = hmac.new(raw_secret.encode(), body, hashlib.sha256).hexdigest()`. Post via `self.client.post(url, data=body, content_type='application/json', HTTP_AUTHORIZATION=f'sha256={sig}')` to match what the view computes over `request.body`."
- **Decision**: PENDING
```

---

**File 2 — `context/changes/dbt-integration/change.md`** (updated `status` field)

```markdown
---
change_id: dbt-integration
title: dbt webhook integration — trigger checks after dbt run completes
status: plan_reviewed
created: 2026-10-28
updated: 2025-07-10
archived_at: null
---

## Notes

DataPulse exposes a webhook endpoint POST /api/v1/webhooks/dbt that accepts dbt Cloud job completion payload. User configures: which Connection maps to which dbt environment, which rules to run after dbt job success. Also support manual trigger: user selects "Run after dbt job ID X". dbt Cloud sends webhook on job completion → DataPulse runs mapped rules → results available in seconds after transform. Also support dbt Core: user calls the endpoint from their dbt on-run-end hook.
```

---

**Summary of findings:**

The plan is well-grounded and architecturally sound — all 7 file paths verified, all 5 referenced symbols exist, and the brief matches the plan. The end state is clear and achievable across the 5 phases. Three items need fixing before implementation starts:

- **F1 (LOW)**: Phase 2 code block embeds stdlib imports that belong at the top of `views.py` — add one sentence clarifying placement.
- **F2 (MEDIUM)**: Phase 4 create view uses render-on-POST to preserve the raw secret; the double-submit/refresh behavior is unacknowledged. Either add a note accepting it (Fix A, minimal) or switch to session-based PRG (Fix B, clean but wider scope).
- **F3 (LOW)**: Phase 4 sidebar file reference is vague — the file is `templates/base.html`, confirmed at lines 636–649.

Two observations (F4, F5) for Phase 5: define a `make_dbt_integration` test helper and document the byte-encoding requirement for HMAC test setup.