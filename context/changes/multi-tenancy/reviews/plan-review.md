I have all the evidence I need. My tool set for this reviewer session does not include a write/edit tool — only `read`, `find`, `grep`, `ls`, `watchdog_diff`, and `contact_supervisor`. Per skill instructions: "If an output path is configured but no write-capable tool is available, return the complete artifact in your final response; the runtime will persist it."

---

## Review

**Grounding: 5/5 paths ✓, 3/3 symbols ✓, brief↔plan ✓**

Verified paths: `monitor/models.py` (Connection at :28-40, Rule at :47-80, no user FK confirmed), `monitor/views.py` (all 13 view functions confirmed, `run_checks` at :47-49 confirmed), `monitor/forms.py` (RuleForm.__init__ at :49+, no user filter confirmed), `data_pulse/urls.py` (LoginView/LogoutView only, no signup URL confirmed), `data_pulse/settings.py` (no HTTPS security settings confirmed).  
Verified symbols: `run_all_checks()` at `services.py:265` fetches `Rule.objects.select_related('connection').all()` (global, confirmed); `CACHE_KEY_TABLES = 'dp_schema_tables_{}'` (session-scoped per user, no cross-user bleed); migration last is `0004` (matches plan's "next is 0005").  
Brief↔plan: phases, scope, key decisions, and architecture all match.

---

```
═══════════════════════════════════════════════════════════
  PLAN REVIEW: Multi-tenancy Implementation Plan
  Mode: Deep  |  Date: 2026-10-28
  Findings: 1 critical, 1 warning, 1 observation
═══════════════════════════════════════════════════════════

  End-State Alignment    PASS    ✅
  Lean Execution         PASS    ✅
  Architectural Fitness  WARNING ⚠️   (1 finding)
  Blind Spots            FAIL    ❌   (1 finding)
  Plan Completeness      WARNING ⚠️   (1 finding)

  Grounding: 5/5 paths ✓, 3/3 symbols ✓, brief↔plan ✓
  ► Overall: REVISE

═══════════════════════════════════════════════════════════
  CRITICAL FINDINGS ❌
═══════════════════════════════════════════════════════════

  F1 — run_checks view executes all users' database connections on any button press
  ╌╌╌╌╌╌╌
    Severity:  ❌ CRITICAL
    Impact:    🔬 HIGH — architectural stakes; think carefully before deciding
    Dimension: Blind Spots
    Location:  Phase 3 — View Isolation & IDOR Fix (view contract list)

    Detail:
    The dashboard "Run Checks" button POSTs to the run_checks view (views.py:47-49),
    which calls run_all_checks() directly. run_all_checks() at services.py:265 fetches
    Rule.objects.select_related('connection').all() — every rule from every user.

    Phase 3's view contract lists 12 specific view changes but omits run_checks entirely.
    The plan says "no change needed in services.py for the cron use case" — correct for
    the cron path — but the run_checks view is UI-triggered, not cron. After Phase 3
    ships, any logged-in user pressing "Run Checks" causes DataPulse to open connections
    to other users' PostgreSQL databases. This is cross-tenant execution, not just a
    data-visibility leak: credentials from Connection records owned by other users are
    used to perform queries.

    Fix A ⭐ Recommended: Scope run_checks view to request.user's rules only
      Add a user parameter to run_all_checks() — or create a thin run_checks_for_user()
      wrapper in services.py — and pass request.user from the view. The cron management
      command (run_scheduled) continues calling the unscoped run_all_checks().
      Strength:   Minimal change; cron behavior unchanged; closes the cross-tenant
                  execution gap completely. Matches the pattern the plan already uses
                  for every other view (filter by request.user).
      Tradeoff:   One new function signature or an added parameter in services.py.
      Confidence: HIGH — the cron/view distinction is already identified in the research
                  (research.md section 4 table, run_checks row). Only the fix was
                  omitted from Phase 3.
      Blind spot: CheckRun has no user FK, so a user-scoped run still creates a global
                  CheckRun record — minor, noted in F3 below.

    Fix B: Remove the UI "Run All Checks" button; keep only run_single per rule
      Strength:   Eliminates the concept of a cross-tenant run entirely.
      Tradeoff:   Degrades UX; contradicts the existing dashboard design.
      Confidence: LOW — roadmap hasn't signalled removing bulk-run functionality.
      Blind spot: run_single is already ownership-checked, so this only affects bulk.

═══════════════════════════════════════════════════════════
  WARNING FINDINGS ⚠️
═══════════════════════════════════════════════════════════

  F2 — Phase 2 Progress has no automated verification step for /signup/
  ╌╌╌╌╌╌╌
    Severity:  ⚠️ WARNING
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Plan Completeness
    Location:  Phase 2 — Registration & Auth Flow / ## Progress Phase 2 Automated

    Detail:
    Phase 2 implements the signup view and template. Its success criteria section says
    "python manage.py test monitor.tests.SignupViewTest (added in Phase 4)" — explicitly
    deferring the automated test to Phase 4. The Phase 2 Progress Automated block has
    only two steps: 2.1 (existing tests pass) and 2.2 (/password-reset/ returns 200).
    There is no automated step for /signup/ returning 200, even a simple URL smoke test.

    Phase 3 then modifies views.py extensively. If signup breaks during Phase 3 changes,
    there is no automated gate — only the manual steps 2.3/2.4 were already passed.
    Phase 4 catches it, but that's after migration 0007 has already been applied.

    Fix: Add step 2.3a in Phase 2 Automated:
    - [ ] 2.3 /signup/ returns 200: python manage.py test monitor.tests.SignupViewTest
    Remove the "(added in Phase 4)" note from the Phase 2 success criteria; keep 4.3
    as the full SignupViewTest re-run after helper updates. The test class is written
    in Phase 4 — but a one-liner GET-200 check can be added there and run at Phase 2
    time by running only that test class early.
    Alternatively: add a curl/runserver smoke check as step 2.3 under Manual (already
    present as 2.3/2.4) and accept the gap — Manual coverage is already there.

═══════════════════════════════════════════════════════════
  OBSERVATIONS 📝
═══════════════════════════════════════════════════════════

  F3 — CheckRun has no user FK; dashboard last_run shows the global last run
  ╌╌╌╌╌╌╌
    Severity:  📝 OBSERVATION
    Impact:    🏃 LOW — quick decision; fix is obvious and narrowly scoped
    Dimension: Architectural Fitness
    Location:  Phase 3 — dashboard view / monitor/views.py:18

    Detail:
    dashboard view (views.py:18): last_run = CheckRun.objects.first()
    CheckRun has no user FK and the plan does not add one. After Phase 3, the "last run"
    timestamp shown on the dashboard will be the most recent run by anyone — not the
    current user's last run. This is a minor UX inconsistency, not an IDOR risk (no
    sensitive data in CheckRun itself). The plan acknowledges CheckRun is out of scope
    for user-scoping but doesn't note this dashboard side-effect.

    Note for implementer: acceptable for MVP. Track for post-MVP cleanup.

═══════════════════════════════════════════════════════════
  ► VERDICT: REVISE
═══════════════════════════════════════════════════════════
```

---

## Output artifacts to persist

**Save to:** `context/changes/multi-tenancy/reviews/plan-review.md`

```markdown
<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Multi-tenancy Implementation Plan

- **Plan**: context/changes/multi-tenancy/plan.md
- **Mode**: Deep
- **Date**: 2026-10-28
- **Verdict**: REVISE
- **Findings**: 1 critical, 1 warning, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | FAIL |
| Plan Completeness | WARNING |

## Grounding

5/5 paths ✓, 3/3 symbols ✓, brief↔plan ✓

Verified: `monitor/models.py` (Connection :28-40, Rule :47-80, no user FK), `monitor/views.py` (13 view functions, `run_checks` at :47-49), `monitor/forms.py` (RuleForm.__init__ at :49+, no user filter), `data_pulse/urls.py` (LoginView/LogoutView only), `data_pulse/settings.py` (no HTTPS security settings). Symbols: `run_all_checks()` at services.py:265 confirmed global `Rule.objects.all()`; `CACHE_KEY_TABLES = 'dp_schema_tables_{}'` confirmed session-scoped (no cross-user bleed); migration last is `0004` matches plan.

## Findings

### F1 — run_checks view executes all users' database connections on any button press

- **Severity**: ❌ CRITICAL
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Blind Spots
- **Location**: Phase 3 — View Isolation & IDOR Fix (view contract list)
- **Detail**: The dashboard "Run Checks" button POSTs to `run_checks` (views.py:47-49), which calls `run_all_checks()`. `run_all_checks()` at services.py:265 fetches `Rule.objects.select_related('connection').all()` — every rule from every user. Phase 3's view contract lists 12 specific view changes but omits `run_checks` entirely. The plan says "no change needed in services.py for the cron use case" — correct for cron — but the `run_checks` view is UI-triggered, not cron. After Phase 3, any logged-in user pressing "Run Checks" causes DataPulse to open connections to other users' PostgreSQL databases using their stored credentials. This is cross-tenant execution, not just a data-visibility leak.
- **Fix A ⭐ Recommended**: Scope `run_checks` view to `request.user`'s rules. Add a `user` parameter to `run_all_checks()` or create a thin `run_checks_for_user(user)` wrapper in services.py; call it from the view. The cron management command (`run_scheduled`) continues calling the unscoped version.
  - Strength: Minimal change; cron behavior unchanged; closes cross-tenant execution gap. Matches existing Phase 3 pattern.
  - Tradeoff: One new function signature or parameter in services.py.
  - Confidence: HIGH — the cron/view distinction is identified in research.md section 4; only the fix was omitted from the Phase 3 contract.
  - Blind spot: `CheckRun` has no `user` FK, so a user-scoped run still creates a global `CheckRun` record (minor, see F3).
- **Fix B**: Remove the UI "Run All Checks" button; keep only `run_single` per rule.
  - Strength: Eliminates cross-tenant run concept entirely.
  - Tradeoff: Degrades UX; contradicts existing dashboard design.
  - Confidence: LOW — roadmap has not signalled removing bulk-run functionality.
  - Blind spot: `run_single` is already ownership-checked, so this only affects the bulk path.
- **Decision**: PENDING

---

### F2 — Phase 2 Progress has no automated verification step for /signup/

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 — Registration & Auth Flow / ## Progress Phase 2 Automated
- **Detail**: Phase 2 implements the signup view and template. Its success criteria defers `SignupViewTest` to Phase 4 ("added in Phase 4"). The Phase 2 Progress Automated block has only steps 2.1 (existing tests) and 2.2 (/password-reset/ 200). There is no automated step for `/signup/` returning 200. Phase 3 then modifies views.py extensively; if signup breaks during Phase 3, there is no automated gate between Phases 2 and 3 — only already-passed manual steps. Phase 4 catches it after migration 0007 has been applied.
- **Fix**: Promote the `/signup/` 200 check to a Phase 2 automated step (step 2.3). Write `SignupViewTest` in Phase 4 as planned; but run a subset (GET-200 only) at Phase 2 close, or add a simple `python manage.py test monitor.tests.SignupViewTest.test_signup_get_200` once the class is created. If preferred: accept that manual steps 2.3/2.4 provide sufficient coverage and keep as-is — this is a design choice, not a structural defect.
- **Decision**: PENDING

---

### F3 — CheckRun has no user FK; dashboard last_run shows global last run

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architectural Fitness
- **Location**: Phase 3 — dashboard view / monitor/views.py:18
- **Detail**: `last_run = CheckRun.objects.first()` fetches the most recent run globally. After Phase 3, a user's dashboard shows a "last run" timestamp that may reflect another user's run. Not an IDOR risk (no sensitive data in `CheckRun`), but a minor UX inconsistency the plan doesn't note. Out of scope for this change; flag for post-MVP cleanup.
- **Fix**: Note in plan that `last_run` shows the global last run (acceptable for MVP). Track separately.
- **Decision**: PENDING
```

---

**Update `change.md`** — change `status: planned` → `status: plan_reviewed` and `updated: 2026-10-28`:

```yaml
---
change_id: multi-tenancy
title: Multi-tenancy — user accounts, per-user rules and connections
status: plan_reviewed
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

Full user registration and login. Each user sees only their own Rules and Connections.
Requires: user registration form, email verification or simple signup, Rule/Connection FK to User,
migration to reassign existing data, full auth flow (signup, login, logout, password reset).
This is the most impactful change — blocks per-user data isolation for all other features.
```

---

## Summary

**Verdict: REVISE**

Three findings, one blocking:

**F1 CRITICAL** — `run_checks` view is not in Phase 3's scope list but calls the global `run_all_checks()`. After isolation ships, any logged-in user pressing "Run Checks" will execute monitoring queries against every other user's PostgreSQL connection. Fix: add a `user` parameter to `run_all_checks()` and call `run_all_checks(user=request.user)` from the view; the cron path keeps calling it unscoped.

**F2 WARNING** — Phase 2 has no automated step verifying `/signup/` returns 200. Manual steps cover it, but the gap means a signup regression introduced in Phase 3 won't be caught until Phase 4, after migration 0007 has been applied.

**F3 OBSERVATION** — `last_run = CheckRun.objects.first()` on the dashboard will show any user's last run, not the current user's. Acceptable for MVP; plan should note it.