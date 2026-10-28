---
change_id: rule-builder-ui
title: S-05 Rule builder UI — table/column selection from dropdowns
status: implemented
created: 2026-10-25
updated: 2026-10-25
archived_at: null
---

## Goal

Rule form uses schema browser from S-04 to let user pick table and column by clicking
instead of typing. Implemented together with S-04.

## What was done

Implemented as part of rule_form.html rewrite in S-04. See schema-introspection/change.md.

## Key files changed

- templates/monitor/rule_form.html
