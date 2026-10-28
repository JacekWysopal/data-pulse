---
change_id: slack-notifications
title: Slack notifications — Soon badge in UI, backend stub ready for activation
status: impl_reviewed
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

Show "Soon" badge on Slack notification option in UI (visible but not active).
Stub the backend: SlackNotification model with webhook_url field, disabled=True flag.
When a provider API key is available, activation is one flag flip.
Scope: UI badge only + model stub. No actual Slack API calls in this change.
