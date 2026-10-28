---
change_id: connection-badge
title: S-08 Connection badge on rule list — show source database per rule
status: implemented
created: 2026-10-25
updated: 2026-10-25
archived_at: null
---

## Goal

Every rule row in the dashboard table shows which connection (database) it belongs to.
"env" badge for rules using default MONITORED_DATABASE_URL.

## What was done

- New "Source" column in rules table (between Rule and Table columns)
- Two badge variants: conn-badge-named (blue, shows connection name) and conn-badge-env (muted, "env")
- Hover shows masked URL as tooltip via `title` attribute
- Click on badge triggers filterByConn() → sets connection filter
- data-conn attribute on each `<tr>` for JS filtering

## Key files changed

- templates/monitor/dashboard.html — Source column, badge HTML, data-conn attribute

## Progress

- [x] Source column in table header
- [x] Connection badge per row (named / env variants)
- [x] Click to filter by connection
- [x] data-conn attribute for JS filter
