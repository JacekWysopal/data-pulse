---
change_id: email-notifications
title: Email notifications on FAIL — send alert when rule check fails
status: impl_reviewed
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

When a rule result is FAIL or ERROR, send an email to the rule owner.
Requires: email backend config (SMTP or SES), per-rule notification toggle, cooldown to avoid spam,
email template. Depends on multi-tenancy (need user email address).
