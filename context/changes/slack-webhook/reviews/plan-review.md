No write tool is available in this session. Per the skill instructions: returning the complete artifacts for both output paths.

---

**OUTPUT PATH 1: `context/changes/slack-webhook/reviews/plan-review.md`**

```markdown
<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Slack Webhook Notifications

- **Plan**: `context/changes/slack-webhook/plan.md`
- **Mode**: Deep
- **Date**: 2026-10-28
- **Verdict**: REVISE
- **Findings**: 0 critical | 2 warnings | 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS ✅ |
| Lean Execution | PASS ✅ |
| Architectural Fitness | PASS ✅ |
| Blind Spots | WARNING ⚠️ |
| Plan Completeness | WARNING ⚠️ |

## Grounding

6/6 paths ✓, 5/5 symbols ✓, brief↔plan ✓

Verified:
- `monitor/models.py` — `Rule.notify_on_fail` at line 166, `Rule.last_notified_at` at line 171, `SlackNotification` stub at lines 260–275
- `monitor/email_service.py` — `send_fail_notification` at line 21, `COOLDOWN_HOURS = 1` at line 18, `.update()` cooldown stamp at lines 62–63
- `monitor/services.py` — `send_fail_notification` import at line 16, all 11 call sites confirmed (300, 311, 325, 333, 341, 405, 443, 455, 473, 484, 493)
- `monitor/forms.py` — `notify_on_fail` in `RuleForm.Meta.fields` at line 37, widget at line 59
- `monitor/views.py` — `connection_list/create/edit/delete` at lines 219–265
- `monitor/urls.py` — connection routes at lines 22–25, `rule_history` route at line 12
- `monitor/migrations/` — latest is `0012_rule_notify_fields.py` (matches plan assumption)
- `monitor/tests.py` — email test suite at line 1536; three integration tests patching `monitor.services.send_fail_notification` at lines 1675, 1699, 1719
- `data_pulse/settings.py` — no `BASE_URL` or `SITE_URL` key present
- `docs/reference/contract-surfaces.md` — does not exist; contract-surfaces check skipped
- `context/foundation/lessons.md` — does not exist; no prior lessons to cross-check

## Findings

### F1 — "View History" button URL requires a base URL not in settings

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 2 — Slack Sender Service (Block Kit payload)
- **Detail**: The plan specifies building the button URL with `django.urls.reverse('monitor:rule_history', args=[rule.pk])`. `reverse()` returns a relative path (e.g. `/rules/42/`); Slack requires an absolute URL for the button `url` field — a relative path causes Slack to silently drop the button or show a broken link. `settings.BASE_URL` / `SITE_URL` does not exist in `data_pulse/settings.py` (confirmed: no such key). The plan-brief flags this as an open risk but no phase resolves it.
- **Fix A ⭐ Recommended**: Add `SITE_URL = env('SITE_URL', default='')` to `data_pulse/settings.py` using the existing `env()` pattern (settings.py:9). In Phase 2, build the absolute URL as `f"{settings.SITE_URL.rstrip('/')}{reverse(...)}"`. If `SITE_URL` is blank, omit the `actions` block from the payload entirely (log at DEBUG). This matches the "log, don't raise" pattern and is testable with `SITE_URL=''` in unit tests.
  - Strength: Zero extra dependencies; env-driven; graceful fallback; pattern identical to `EMAIL_HOST` peers at settings.py:115–122.
  - Tradeoff: Requires `SITE_URL` env var in production; deploy notes must mention it.
  - Confidence: HIGH — identical env-key pattern exists for email settings.
  - Blind spot: Phase 5 "View History" button test must add an explicit `SITE_URL=''` case to cover the omit-block fallback.
- **Fix B**: Use Django's `Sites` framework to derive the absolute URL.
  - Strength: Centralises domain config in the DB rather than env.
  - Tradeoff: Adds `django.contrib.sites`; requires a DB row; more moving parts for a simple string prefix.
  - Confidence: MEDIUM — no evidence the project uses Sites framework.
  - Blind spot: Sites framework must be initialised in test fixtures.
- **Decision**: PENDING

### F2 — Three existing service integration tests mock `send_fail_notification`; Phase 5 scope only names one

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 5 — Tests, item 5 ("Update services integration test")
- **Detail**: Phase 5 item 5 says to update "test_run_single_rule_fail_calls_send_fail_notification (or equivalent)". The codebase has THREE tests patching `monitor.services.send_fail_notification` (tests.py:1675, 1699, 1719): `test_run_single_rule_fail_calls_send_notification`, `test_run_single_rule_ok_skips_notification`, and `test_run_all_checks_fail_calls_send_notification`. After Phase 3, all three will fail because `send_fail_notification` no longer exists at that import path. The "or equivalent" hedge leaves the implementer to discover this by watching tests break.
- **Fix**: Update Phase 5 item 5 to enumerate all three test methods explicitly and state that each mock target changes from `monitor.services.send_fail_notification` to `monitor.services.notify_rule_result`.
- **Decision**: PENDING

### F3 — `SlackWebhook.url` has `blank=True` but Phase 4 success criterion requires blank rejection

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 model contract vs. Phase 4 form success criteria
- **Detail**: Phase 1 defines `url = CharField(max_length=500, blank=True)`. Phase 4 success criterion says "Form validation rejects a SlackWebhook with a blank url". With `blank=True`, Django's `ModelForm` will accept an empty string; the Phase 4 criterion will silently fail without an explicit form override. The plan does not bridge this gap.
- **Fix**: Either change the Phase 1 model field to `blank=False` (simplest — blank webhook URLs are useless), or add a note to Phase 4 that `SlackWebhookForm.url` must be declared as a required `forms.CharField` or `forms.URLField` explicitly, overriding the model's `blank=True`.
- **Decision**: PENDING

### F4 — `url` field is a `CharField` with no URL format validation

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 model contract, Phase 4 form contract
- **Detail**: The model spec uses `CharField(max_length=500)`. Any string (including non-URLs) can be saved; the only failure path is a `urllib.error.URLError` logged silently at send time, giving the user no indication that the URL they entered is malformed. `URLField` validates the format at save time.
- **Fix**: Change Phase 1 model contract from `CharField` to `URLField` (Django normalises `blank` and validates format), or keep `CharField` on the model and specify `url = forms.URLField(...)` in `SlackWebhookForm` — the second option allows admin flexibility while giving the UI proper validation, consistent with the pattern used in `ConnectionForm` for database URLs.
- **Decision**: PENDING
```

---

**OUTPUT PATH 2: `context/changes/slack-webhook/change.md`** (updated field only)

```markdown
---
change_id: slack-webhook
title: Slack/Teams webhook notifications on FAIL/ERROR
status: plan_reviewed
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

User adds webhook URL per connection or globally. Every FAIL/ERROR result sends a Slack/Teams message with rule name, table, status, measured value, threshold, and link to history. Format: rich Slack block or simple JSON payload for Teams. Cooldown similar to email (1h per rule). Toggle per-rule: notify_slack BooleanField.
```

---

## Review

**Correct:**
- Plan structure is solid: current-state analysis is grounded in real file:line evidence, all 11 call sites confirmed, the email pattern mirror is accurate, Progress block is well-formed and phase-aligned, brief↔plan decisions match.
- Scope boundary is clean and self-consistent — Teams is explicitly deferred, fan-out deferred, no scope bleed into phases.
- Phase ordering is correct: model → sender → coordinator → UI → tests. Each phase leaves the test suite passable in isolation.
- `urllib.request` choice is correctly motivated; `.update()` cooldown stamp requirement is called out explicitly.

**Findings:**
- F1 (WARNING / MEDIUM): "View History" button in the Block Kit payload requires an absolute URL; `reverse()` returns a relative path and no `SITE_URL`/`BASE_URL` exists in settings. The plan-brief acknowledges the risk but no phase resolves it. Fix: add `SITE_URL` env key to settings, build absolute URL in Phase 2, gracefully omit the actions block if blank.
- F2 (WARNING / LOW): Phase 5 item 5 mentions updating one integration test but the codebase has three tests patching `monitor.services.send_fail_notification` (tests.py:1675, 1699, 1719). All three break after Phase 3. Fix: enumerate all three by name in Phase 5.
- F3 (OBSERVATION / LOW): `SlackWebhook.url` is `blank=True` on the model but Phase 4 success criterion requires blank rejection. The form must explicitly enforce required. Fix: set `blank=False` on model or call it out in Phase 4.
- F4 (OBSERVATION / LOW): `CharField` carries no URL format validation; a malformed URL only fails silently at send time. Fix: use `URLField` on model or form.

**Merge verdict:** REVISE — two targeted plan edits needed (F1 resolution in Phase 2, F2 enumeration in Phase 5) before implementation begins. F3/F4 are low-effort callouts worth a one-line note each.