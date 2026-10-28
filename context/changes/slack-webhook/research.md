---
date: 2026-10-28T00:00:00+00:00
researcher: worker-subagent
git_commit: c2ad8dfe7dc6ab19e456ba6dab557d0808a806ad
branch: dev
repository: data-pulse
topic: "What's needed for Slack/Teams webhook notifications?"
tags: [research, codebase, slack, teams, webhook, notifications, email_service, models, services]
status: complete
last_updated: 2026-10-28
last_updated_by: worker-subagent
---

# Research: What's needed for Slack/Teams webhook notifications?

**Date**: 2026-10-28  
**Researcher**: worker-subagent  
**Git Commit**: c2ad8dfe7dc6ab19e456ba6dab557d0808a806ad  
**Branch**: dev  
**Repository**: data-pulse

## Research Question

What is needed to implement Slack/Teams webhook notifications in DataPulse?
Specifically: current notification flow, Slack Block Kit vs simple JSON, model changes,
call site hooks, and Teams webhook format differences.

## Summary

The existing email notification path in `monitor/email_service.py` is a clean,
self-contained function (`send_fail_notification`) that checks a `notify_on_fail`
boolean and a 1-hour cooldown via `last_notified_at` on the `Rule` model before
dispatching email. This exact pattern — guard flag, cooldown timestamp, fire-and-forget
HTTP call — maps directly onto a Slack/Teams webhook sender. Three model changes are
required: `Rule.notify_slack` (BooleanField), `Rule.last_slack_notified_at`
(DateTimeField), and a `Connection`-level (or user-level) `slack_webhook_url`
CharField. A stub `SlackNotification` model (models.py:260–275) already exists with
`user`, `webhook_url`, and `enabled` fields; it was created in migration 0007 but is
not wired to any notification path. The webhook URL is most naturally stored on
`Connection` (one URL per monitored database) or on `SlackNotification` (one URL per
user); the change.md notes indicate per-connection *or* global (user-level). Slack
requires a JSON POST with a `blocks` array (Block Kit) or a plain `text` field;
Microsoft Teams Incoming Webhooks accept either an `O365ConnectorCard` JSON
(`@type: MessageCard`) or an Adaptive Card payload — the format differs meaningfully
from Slack's. No HTTP client (`requests`, `httpx`) is currently in `requirements.txt`
or `pyproject.toml`; one must be added. `urllib.request` from the standard library is
an alternative that avoids a new dependency.

## Detailed Findings

### 1. Current notification flow — email_service.py

`send_fail_notification(rule, result)` at `monitor/email_service.py:21` is the only
outbound notification function currently in the codebase (inspected path only).

Guard checks (in order, all at `email_service.py:33–42`):

1. `rule.notify_on_fail` — BooleanField on `Rule` (models.py:166); returns `False`
   immediately if the flag is `False`.
2. `rule.user` exists and `rule.user.email` is non-blank (email_service.py:36–37).
3. Cooldown: if `rule.last_notified_at` is not `None` and `timezone.now() -
   rule.last_notified_at < timedelta(hours=1)`, skip (email_service.py:40–42).

On pass: renders two templates (`monitor/email/fail_notification.txt` and `.html`),
sends via `django.core.mail.EmailMultiAlternatives`, then calls
`Rule.objects.filter(pk=rule.pk).update(last_notified_at=timezone.now())` at
email_service.py:62 to stamp the cooldown without touching `updated_at`.

The function returns `True` on success, `False` on skip, and logs at ERROR level
(never raises) on exception (email_service.py:67–70).

COOLDOWN_HOURS is the module-level constant `1` (email_service.py:18).

### 2. Call sites — where send_fail_notification is invoked

`send_fail_notification` is imported once in `monitor/services.py:16` and called at
these 8 locations within that file (all within status checks
`result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR)`):

- `services.py:300` — `run_single_rule`, no-connection ERROR branch
- `services.py:311` — `run_single_rule`, empty-URL ERROR branch
- `services.py:325` — `run_single_rule`, normal result branch
- `services.py:333` — `run_single_rule`, `MonitoredDbError` branch
- `services.py:341` — `run_single_rule`, outer catch-all
- `services.py:405` — `run_checks_for_user`, connection ERROR branch
- `services.py:443` — `run_checks_for_user`, conn-error branch
- `services.py:455` — `run_checks_for_user`, normal result branch
- `services.py:473` — `run_all_checks`, conn-error branch
- `services.py:484` — `run_all_checks`, normal result branch
- `services.py:493` — `run_all_checks`, outer catch-all

All 3 service functions (`run_single_rule`, `run_checks_for_user`, `run_all_checks`)
follow the same pattern: after creating a `RuleResult`, if status is FAIL or ERROR,
call `send_fail_notification`. A Slack sender placed at the same guard is a parallel
call to `send_slack_notification(rule, result)` at each of these 11 points — or,
preferably, a thin coordinator function that calls both, reducing site count from 11
to 1.

### 3. Existing SlackNotification stub model

`monitor/models.py:260–275` defines:

```python
class SlackNotification(models.Model):
    user = models.ForeignKey(AUTH_USER_MODEL, on_delete=CASCADE, null=True, blank=True,
                             related_name='slack_notifications')
    webhook_url = models.CharField(max_length=500, blank=True)
    enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

Migration: `monitor/migrations/0007_slacknotification.py`. This stub is registered in
`admin.py:25–26` but is not consumed anywhere in `services.py` or `email_service.py`.
It provides a user-level webhook URL and an `enabled` toggle, but does not carry a
per-rule cooldown timestamp.

### 4. Required model changes

Based on the email pattern and change.md notes, 3 additions are needed (2 on `Rule`,
1 on `Connection` or reuse of `SlackNotification`):

**Option A — webhook URL on Connection (per-monitored-db)**

- `Connection.slack_webhook_url` — `CharField(max_length=500, blank=True)` — URL set
  once per monitored connection, shared by all rules on that connection.
- `Rule.notify_slack` — `BooleanField(default=False)` — per-rule opt-in toggle,
  mirrors `notify_on_fail` pattern (models.py:166).
- `Rule.last_slack_notified_at` — `DateTimeField(null=True, blank=True)` — cooldown
  timestamp, mirrors `last_notified_at` (models.py:171).

**Option B — webhook URL on SlackNotification (per-user / global)**

Reuse the existing `SlackNotification.webhook_url` and `SlackNotification.enabled`
(models.py:260–275). Add only:
- `Rule.notify_slack` BooleanField
- `Rule.last_slack_notified_at` DateTimeField

Lookup in sender: `SlackNotification.objects.filter(user=rule.user, enabled=True).first()`.

The change.md note says "User adds webhook URL per connection or globally." Option A
(per-connection) and Option B (per-user/global) are both described. Option B reuses
the stub that already exists and avoids adding a field to the frequently-queried
`Connection` model. Option A is more granular.

**Minimum required regardless of option**: `Rule.notify_slack` (BooleanField) and
`Rule.last_slack_notified_at` (DateTimeField). These require one migration.

### 5. Slack Block Kit message format

Slack Incoming Webhooks accept a JSON POST body with either:

- Simple text: `{"text": "message"}` — rendered as plain notification
- Rich Block Kit: `{"blocks": [...], "text": "fallback"}` — rendered with formatted
  sections, inline code, buttons

A minimal FAIL/ERROR notification block:

```json
{
  "text": "[DataPulse] orders — FAIL",
  "blocks": [
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*[DataPulse] `orders` — FAIL*\nTable: `public.orders` · Row count: 0 (min: 100)"
      }
    },
    {
      "type": "section",
      "fields": [
        {"type": "mrkdwn", "text": "*Rule*\norders"},
        {"type": "mrkdwn", "text": "*Status*\nFAIL"},
        {"type": "mrkdwn", "text": "*Measured*\n0 rows"},
        {"type": "mrkdwn", "text": "*Threshold*\n≥ 100"}
      ]
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": {"type": "plain_text", "text": "View History"},
          "url": "https://datapulse.app/rules/42/"
        }
      ]
    }
  ]
}
```

The `text` field is mandatory as a notification fallback (required by Slack API for
accessibility and mobile push). The `blocks` array is optional but provides rich
formatting. For a first implementation, a simpler `{"text": "..."}` body suffices;
Block Kit can be added later with no API contract change.

### 6. Microsoft Teams webhook format differences

Teams Incoming Webhooks (legacy connector, available as of research date) expect a
different JSON schema. Two supported formats:

**MessageCard (legacy, widely supported)**:
```json
{
  "@type": "MessageCard",
  "@context": "https://schema.org/extensions",
  "summary": "[DataPulse] orders — FAIL",
  "themeColor": "FF0000",
  "title": "[DataPulse] orders — FAIL",
  "sections": [
    {
      "facts": [
        {"name": "Rule", "value": "orders"},
        {"name": "Status", "value": "FAIL"},
        {"name": "Table", "value": "public.orders"}
      ]
    }
  ],
  "potentialAction": [
    {
      "@type": "OpenUri",
      "name": "View History",
      "targets": [{"os": "default", "uri": "https://datapulse.app/rules/42/"}]
    }
  ]
}
```

**Adaptive Card (newer, Teams-only)**:
```json
{
  "type": "message",
  "attachments": [
    {
      "contentType": "application/vnd.microsoft.card.adaptive",
      "contentUrl": null,
      "content": {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [{"type": "TextBlock", "text": "[DataPulse] orders — FAIL"}]
      }
    }
  ]
}
```

Key differences from Slack:
- No `blocks` / `mrkdwn`; uses `sections.facts` (MessageCard) or AdaptiveCard schema.
- The `@type` root field is required for MessageCard; Slack has no equivalent.
- `themeColor` (hex without `#`) sets the left-edge stripe colour in Teams.
- Actions use `potentialAction` + `@type: OpenUri` instead of Slack's `actions`
  block with buttons.
- The same webhook URL endpoint does NOT accept Slack format and vice versa.
- Teams and Slack webhook URLs have distinct URL patterns
  (`outlook.office.com/webhook/...` for Teams; `hooks.slack.com/services/...` for Slack).

Practical implication: a single `send_webhook_notification(rule, result, webhook_url)`
function cannot blindly post the same body to both. The sender must either detect the
URL prefix to choose the payload format, or expose two separate functions
(`send_slack_notification`, `send_teams_notification`) with a shared payload builder.

### 7. HTTP client for outbound webhook POSTs

No HTTP client library (`requests`, `httpx`, `aiohttp`) is present in
`pyproject.toml` or `requirements.txt` (inspected as of commit
c2ad8dfe7dc6ab19e456ba6dab557d0808a806ad). Options:

- **`urllib.request`** (stdlib): zero dependencies, synchronous, adequate for fire-and-forget
  POST with JSON body. Pattern:
  ```python
  import json, urllib.request
  data = json.dumps(payload).encode()
  req = urllib.request.Request(url, data=data,
                                headers={'Content-Type': 'application/json'},
                                method='POST')
  urllib.request.urlopen(req, timeout=5)
  ```
- **`requests`**: simplest API; adds one dependency (`requests>=2.32`); widely used
  in Django projects.
- **`httpx`**: async-first but supports sync; adds one dependency.

Recommendation: use `urllib.request` for the initial implementation to stay dependency-free,
matching the project's minimal dependency philosophy (only 9 runtime deps in pyproject.toml).

### 8. Settings additions needed

No Slack or Teams webhook URL is currently read from settings (inspected
`data_pulse/settings.py`). If the URL is stored in the model (Option A or B), no
settings key is required. If a global fallback URL is desired, a settings key such as
`SLACK_WEBHOOK_URL = env('SLACK_WEBHOOK_URL', default='')` would follow the existing
`EMAIL_*` pattern (settings.py:115–122). No new settings are strictly required for the
model-stored approach.

## Code References

- `monitor/email_service.py:21` — `send_fail_notification` signature
- `monitor/email_service.py:33` — `notify_on_fail` guard
- `monitor/email_service.py:40–42` — 1-hour cooldown check
- `monitor/email_service.py:62–63` — cooldown stamp update via `.update()` (avoids auto_now)
- `monitor/email_service.py:18` — `COOLDOWN_HOURS = 1`
- `monitor/models.py:166–170` — `Rule.notify_on_fail` BooleanField
- `monitor/models.py:171–175` — `Rule.last_notified_at` DateTimeField
- `monitor/models.py:260–275` — `SlackNotification` stub model (user, webhook_url, enabled)
- `monitor/migrations/0007_slacknotification.py` — stub migration
- `monitor/migrations/0012_rule_notify_fields.py` — pattern for adding notify fields to Rule
- `monitor/services.py:16` — import of `send_fail_notification`
- `monitor/services.py:300–341` — call sites in `run_single_rule`
- `monitor/services.py:405–493` — call sites in `run_checks_for_user` and `run_all_checks`
- `monitor/forms.py:37` — `notify_on_fail` in `RuleForm.Meta.fields` list
- `monitor/forms.py:59` — `notify_on_fail` widget definition
- `data_pulse/settings.py:115–122` — email settings pattern for env-loaded config
- `pyproject.toml` — no `requests` or `httpx` present (9 runtime deps total)

## Architecture Insights

1. **Mirror the email pattern exactly.** `notify_on_fail` + `last_notified_at` on
   `Rule` is the established pattern; `notify_slack` + `last_slack_notified_at`
   follows the same shape.

2. **Coordinator function reduces duplication.** With 11 call sites in services.py,
   a single `send_notifications(rule, result)` that delegates to both email and Slack
   senders reduces the number of edits needed and makes future channels easier to add.

3. **SlackNotification stub is ready but unused.** The model, migration, and admin
   registration already exist. The implementation needs only to wire it into the
   sender: look up the user's `SlackNotification` record, check `enabled` and
   `webhook_url`, and POST.

4. **Teams requires a distinct payload builder.** The two formats (`@type: MessageCard`
   vs Slack `blocks`) are not interchangeable. URL-prefix detection (
   `hooks.slack.com` vs `outlook.office.com`) is a viable routing strategy.

5. **No async needed.** All existing services are synchronous Django views and
   management commands. `urllib.request.urlopen` with a 5-second timeout is safe here;
   failures should log at ERROR and not raise, matching the email pattern.

6. **cooldown stamp must use `.update()` not `.save()`.** The existing email code uses
   `Rule.objects.filter(pk=rule.pk).update(last_notified_at=...)` to avoid touching
   `updated_at` (auto_now). The Slack sender must do the same for
   `last_slack_notified_at`.

## Historical Context (from prior changes)

No prior research or plan documents found under `context/changes/` or
`context/archive/` specifically for Slack or webhook notifications.
`context/changes/slack-webhook/change.md` is the only artifact for this change as of
this research session.

## Related Research

- Not applicable — no other research.md files found referencing webhook or Slack in
  this repository.

## Open Questions

1. **Webhook URL storage**: Per-connection (`Connection.slack_webhook_url`) or
   per-user reusing the existing `SlackNotification` model? The stub model
   (`models.py:260`) already handles user-level; per-connection granularity requires
   a new field on `Connection`. Decision needed before writing the migration.

2. **Teams support in initial slice**: The change.md title says "Slack/Teams". Should
   the first implementation include Teams (requiring URL-prefix routing and a second
   payload builder), or ship Slack first and add Teams in a follow-up?

3. **Block Kit richness vs simple text**: A plain `{"text": "..."}` body works
   immediately; Block Kit with fields/buttons requires more rendering code. Is plain
   text acceptable for v1?

4. **Coordinator function vs 11-site patch**: Introduce `send_notifications(rule,
   result)` to consolidate the 11 call sites in services.py, or patch each site
   independently? The coordinator reduces future maintenance but touches more lines
   now.
