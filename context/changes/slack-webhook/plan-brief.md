# Slack Webhook Notifications — Plan Brief

> Full plan: `context/changes/slack-webhook/plan.md`
> Research: `context/changes/slack-webhook/research.md`

## What & Why

Add Slack Incoming Webhook support to DataPulse so rule owners receive rich Block Kit notifications when a monitored rule returns FAIL or ERROR. Currently only email is supported; Slack is the highest-priority notification channel for teams using DataPulse in a monitoring workflow (Milestone 5, north-star S-18).

## Starting Point

`email_service.py` provides a complete `send_fail_notification(rule, result)` pattern (flag guard → cooldown check → dispatch → cooldown stamp). A `SlackNotification` stub model (migration 0007) exists but is not wired to any notification path. `services.py` calls `send_fail_notification` at 11 separate sites across three functions.

## Desired End State

Users create named Slack webhook URLs in a new "Slack Webhooks" section. Each rule gains a "Notify via Slack" checkbox. When a rule fails, DataPulse POSTs a Block Kit message (rule name, status, measured value, threshold, "View History" button) to the user's first enabled webhook. Both email and Slack fire from a single `notify_rule_result(rule, result)` call — `services.py` no longer calls individual channel senders.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Platforms in v1 | Slack only | Teams requires a distinct payload format (MessageCard vs Block Kit); ship one channel cleanly first | Plan |
| Webhook URL storage | New `SlackWebhook` model (user FK, name, url, enabled) | Existing `SlackNotification` stub lacks a `name` field; `SlackWebhook` is additive and does not require Connection-level granularity | Plan |
| Message format | Slack Block Kit (rich fields + action button) | Block Kit is the Slack-standard rich format; section + fields + actions buttons deliver rule name, status, measured/threshold, and a deep-link in one message | Plan |
| HTTP client | `urllib.request` (stdlib) | No new dependency; project has only 9 runtime deps and explicitly avoids adding libraries when stdlib suffices | Research |
| Call-site consolidation | Coordinator `notify_rule_result` in `email_service.py` | 11 scattered call sites in `services.py` become 11 identical one-line calls; future channels extend only the coordinator | Plan |
| Cooldown | 1 hour per rule, per channel, independent timestamps | Mirrors `last_notified_at` pattern exactly; separate `last_slack_notified_at` prevents email and Slack from blocking each other | Research |

## Scope

**In scope:**
- `SlackWebhook` model + migration (user FK, name, url, enabled)
- `Rule.notify_slack` BooleanField + `Rule.last_slack_notified_at` DateTimeField
- `monitor/slack_service.py` — `send_slack_notification(rule, result)` sender
- `notify_rule_result(rule, result)` coordinator in `email_service.py`
- `services.py` rewired to call `notify_rule_result` at all 11 sites
- CRUD views + templates for `SlackWebhook` management
- `notify_slack` checkbox on rule create/edit form
- Full unit and integration test coverage

**Out of scope:**
- Microsoft Teams support
- Per-connection webhook URL
- Global settings-level fallback webhook URL
- Multi-webhook fan-out per result
- Async/Celery dispatch
- Shared email+Slack cooldown

## Architecture / Approach

`slack_service.py` is a self-contained module with no coupling to `email_service.py`. The coordinator in `email_service.py` calls both senders and returns a `{'email': bool, 'slack': bool}` dict. `services.py` imports and calls only `notify_rule_result` — it has no knowledge of individual channels. The `SlackWebhook` lookup is: `SlackWebhook.objects.filter(user=rule.user, enabled=True).first()`.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. SlackWebhook Model + Migration | DB schema: `SlackWebhook` + two `Rule` fields + migration 0013 + admin | Migration conflicts if 0012 is not the current head |
| 2. Slack Sender Service | `slack_service.py` with full guard/cooldown/Block Kit/dispatch logic | `urllib.request` error handling must match email pattern (log, don't raise) |
| 3. Coordinator + Wire-up | `notify_rule_result` coordinator; all 11 services.py call sites updated | Missed call site would leave Slack notifications silently unfired |
| 4. UI — CRUD + Rule Toggle | SlackWebhook list/create/edit/delete views + `notify_slack` in rule form | Template markup must follow existing patterns for design consistency |
| 5. Tests | Full unit + integration test coverage for new code; update mocked import in existing service tests | Existing service test mocks `send_fail_notification` directly — must be updated to `notify_rule_result` |

**Prerequisites:** Migration 0012 is the current head; Django project runs locally with `python manage.py runserver`
**Estimated effort:** ~2–3 sessions across 5 phases

## Open Risks & Assumptions

- The `"View History"` button URL is built with `django.urls.reverse` — this requires the app to know its public base URL. In the current codebase `settings.BASE_URL` may not exist; the Phase 2 implementation must handle a missing base URL gracefully (e.g., fallback to relative path or omit the button).
- Slack Incoming Webhook responses a `200 OK` with body `"ok"` on success; any non-200 response should be treated as an error and logged.
- The first enabled `SlackWebhook` for the user is used in v1; if a user has multiple enabled webhooks, only the first (ordered by name) fires — this is a known limitation, not a bug.

## Success Criteria (Summary)

- A rule with `notify_slack=True` and an enabled `SlackWebhook` sends a Block Kit message to Slack on FAIL/ERROR, with correct rule name, status, measured/threshold values, and a "View History" link
- A second FAIL result within 1 hour does not send a duplicate Slack message
- All 254+ existing tests continue to pass after Phase 3 rewires `services.py`
