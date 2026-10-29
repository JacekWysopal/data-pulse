---
change_id: rule-severity
title: Rule severity — critical/warning/info levels affecting badge color and notifications
status: planned
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

Add Rule.severity CharField choices: critical/warning/info (default: critical). CRITICAL = red badge, immediate notification. WARNING = amber badge, notification after 3 consecutive failures. INFO = blue badge, no notification. Affects dashboard badge colors and notification routing.
