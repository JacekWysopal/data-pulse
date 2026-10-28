---
change_id: advanced-scheduler
title: Advanced scheduler — configurable schedule with multiple daily runs and cron-style options
status: preparing
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

Replace single schedule_time TimeField with flexible scheduler:
- Predefined options: 1x/day, 2x/day (every 12h), 3x/day (every 8h), 6x/day, hourly
- Custom cron expression (advanced mode)
- Per-rule enable/disable toggle
Requires: new Schedule model or extended Rule fields, updated run_scheduled command,
UI schedule picker, Render Cron setup docs.
