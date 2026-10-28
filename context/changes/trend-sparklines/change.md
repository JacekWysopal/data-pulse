---
change_id: trend-sparklines
title: Trend sparklines — row count and age history charts in rule list
status: preparing
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

In the rules table and history view, show a tiny SVG sparkline of the last 20 check results for each rule. Row count over time, age over time. Color: green when OK, red when FAIL. Generated server-side as inline SVG from RuleResult history. No JS chart library needed. Shows trend at a glance without opening history.
