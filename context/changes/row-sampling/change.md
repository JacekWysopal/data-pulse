---
change_id: row-sampling
title: Row-level sampling on failure — show example failing rows
status: planned
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

When a FAIL result occurs, run a follow-up query to fetch up to 5 sample rows that violate the condition. For volume check: show 5 most recent rows. For freshness: show the MAX(ts_col) row. For custom SQL: run the SQL and show the result rows. Store sample as JSON in RuleResult.sample_rows (JSONField). Display in history view as expandable "Sample rows" section.
