# Alert Digest — Plan Brief

> Full plan: `context/changes/alert-digest/plan.md`
> Research: `context/changes/alert-digest/research.md`

## What & Why

Instead of one email per failing rule, users can switch to **digest** mode and
receive a single grouped email per run listing every FAIL and ERROR in one table.
This eliminates alert fatigue when many rules fail simultaneously.

## Starting Point

`email_service.send_fail_notification(rule, result)` fires inside the rule loop in
both `run_checks_for_user` and `run_all_checks`. There is no per-user settings model;
Django's built-in `auth.User` is used directly. The latest migration is `0012`.

## Desired End State

A `UserProfile` (OneToOne with `User`) stores `notification_mode`. Users on
`immediate` see no change. Users on `digest` get exactly one email after each run,
showing a failure table (or a summary line for ≥ 10 failures). A settings page
at `/monitor/settings/` lets users toggle between modes.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| User preference storage | `UserProfile` OneToOne model | Standard Django pattern; no existing per-user settings model | Plan |
| Digest mode — per-run cooldown | None — one digest per run always | Cooldown complexity would suppress legitimate run-level notifications | Plan |
| Immediate mode — cooldown | Unchanged (`Rule.last_notified_at`, 1 h) | Backward compatible; no migration of existing behaviour | Plan |
| Digest threshold for summary | ≥ 10 failures → summary line only | Prevents oversized emails; confirmed from change notes | Plan |
| `run_single_rule` — mode check | Always immediate | Single-rule check is a manual action, digest doesn't apply | Plan |
| New function placement | `send_digest_notification` in `email_service.py` | Keeps all outbound email logic in one module | Research |
| `run_all_checks` grouping | `digest_pending` dict keyed by `user_id` | Accumulate in-loop, dispatch after loop — no extra query | Plan |
| UserProfile auto-creation | `post_save` signal on `User` | Ensures profile always exists; `get_or_create` in view as safety net | Plan |

## Scope

**In scope:**
- `UserProfile` model + `0013` migration
- `send_digest_notification()` + two new email templates
- `run_checks_for_user` and `run_all_checks` branching on mode
- Settings view (`GET /POST /monitor/settings/`), URL, template, sidebar link
- Unit and integration tests for all new paths

**Out of scope:**
- Slack digest (separate S-18 slice)
- Digest for `run_single_rule`
- Cooldown on the digest itself
- Back-fill of `last_notified_at` for existing users switching to digest

## Architecture / Approach

`UserProfile.notification_mode` drives a branch at the run level, not inside
`send_fail_notification`. For `immediate`, every failing result calls the existing
function unchanged. For `digest`, the loop accumulates failing results into a list
and `send_digest_notification` fires once after the loop completes, building
`{'run', 'failing_results', 'fail_count', 'error_count', 'is_summary'}` context for
two new templates that mirror the dark-theme style of `fail_notification.html`.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. UserProfile Model | `UserProfile` model, migration 0013, signal | Signal fires on all user types (admin, tests) |
| 2. Digest Email Function | `send_digest_notification()` + txt/html templates | Template rendering correct for summary vs. table |
| 3. Services Hook | Mode-branching in `run_checks_for_user` / `run_all_checks` | `run_all_checks` per-user grouping adds loop complexity |
| 4. Settings UI | `/monitor/settings/` page + sidebar link | Base template identification for sidebar link |
| 5. Tests | Full coverage of new paths, no regressions | Mocking psycopg2 + mail.outbox interaction |

**Prerequisites:** None — all development dependencies are already present.
**Estimated effort:** ~2 focused sessions across 5 phases.

## Open Risks & Assumptions

- `run_all_checks` uses `select_related('connection')` today; adding `'user'` prevents
  N+1 when reading `rule.user.profile` — confirmed needed.
- Existing users created before this change have no `UserProfile`; the `get_or_create`
  call in the settings view is the safety net. The signal will not retroactively create
  profiles, so the fallback in `_get_notification_mode` (returns `'immediate'`) ensures
  existing behaviour is preserved for all users until they visit settings.

## Success Criteria (Summary)

- A digest-mode user running checks with 3 failing rules receives **exactly 1 email**
  (not 3).
- A digest-mode user running checks with all rules passing receives **0 emails**.
- The settings page persists the mode toggle across sessions.
