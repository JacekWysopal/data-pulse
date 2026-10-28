---
change_id: slack-webhook
title: Slack/Teams webhook notifications on FAIL/ERROR
status: planned
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

User adds webhook URL per connection or globally. Every FAIL/ERROR result sends a Slack/Teams message with rule name, table, status, measured value, threshold, and link to history. Format: rich Slack block or simple JSON payload for Teams. Cooldown similar to email (1h per rule). Toggle per-rule: notify_slack BooleanField.
