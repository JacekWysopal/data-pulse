---
change_id: s02-rule-history
title: Rule history drill-down — US-02 on production
status: done
created: 2026-10-20
updated: 2026-10-20
archived_at: null
---

## Goal

User clicks a rule and sees last 20 check results with timestamp, status, measured value.

## What was done

- rule_history view and template already existed in codebase
- Verified on production with real data from Supabase
- Dark UI redesign applied: history table with progress bar for age, monospace timestamps
- Back-link navigation from history to dashboard

## Outcome

S-02 passed. History visible and functional on production.
