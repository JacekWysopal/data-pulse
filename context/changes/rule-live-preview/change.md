---
change_id: rule-live-preview
title: Live preview — test rule query before saving
status: planned
created: 2026-10-28
updated: 2026-10-29
archived_at: null
---

## Notes

"Test query" button in Add Rule form runs the rule against the selected connection and shows result inline before saving. Shows: status (PASS/FAIL), measured values (row count, age), sample rows. No CheckRun/RuleResult stored — pure preview. Endpoint: POST /api/v1/rules/preview.
