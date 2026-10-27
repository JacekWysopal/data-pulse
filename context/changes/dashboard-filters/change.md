---
change_id: dashboard-filters
title: S-07 Dashboard filters — filter rules by status, connection, name
status: done
created: 2026-10-25
updated: 2026-10-25
archived_at: null
---

## Goal

User can filter the rules table without page reload. Filters persist in URL params.

## What was done

- Filter bar between run-info bar and table: text search, status select, connection select
- Client-side JS filtering (no server round-trip) — suitable for < 200 rules
- URL params: ?q=orders&status=FAIL&conn=1 — shareable, survives refresh
- Active filter count badge (purple circle with number)
- Clear all button (appears when any filter active)
- "No rules match" empty row when all filtered out
- filterByConn() global function called by S-08 connection badge clicks
- data-name / data-status / data-conn attributes on each `<tr>`

## Architecture decisions

- Client-side only — avoids extra server queries for small rule counts
- URL params via history.replaceState — no page reload, back button friendly
- Filter bar inside dp-panel (between header and table) — visually contained

## Key files changed

- templates/monitor/dashboard.html — filter bar HTML, JS block, tr data attributes

## Progress

- [x] Filter bar UI (text, status select, connection select)
- [x] Client-side JS filtering
- [x] URL param persistence
- [x] Active filter count badge
- [x] Clear button
- [x] No-results row
- [x] Integration with S-08 badge click
