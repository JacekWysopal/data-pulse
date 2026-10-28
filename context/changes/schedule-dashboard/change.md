---
change_id: schedule-dashboard
title: Schedule dashboard — dedicated tab showing all scheduled rules and their next/last run
status: implemented
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

User wants a dedicated "Schedule" tab/page showing:
- All rules that have a schedule configured (schedule_type != disabled)
- Next scheduled run time for each rule
- Last run time and status for each rule
- Quick enable/disable toggle per rule
- Visual timeline or list view of upcoming runs

Depends on: advanced-scheduler (S-15) — already implemented (schedule_type, schedule_cron, croniter)
