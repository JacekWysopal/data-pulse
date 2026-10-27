---
change_id: custom-sql-rule
title: Custom SQL rule — SQL returning true/false as a check condition
status: proposed
created: 2026-10-25
updated: 2026-10-25
archived_at: null
---

## Goal

User can define a rule as a raw SQL query that returns a single boolean-like value.
Result true = OK, false/0/null/empty = FAIL.

## Scope

- New Rule fields: rule_type (volume_freshness | custom_sql), custom_sql (TextField)
- Migration 0004
- services.py: _check_custom_sql() branch
- Form: rule_type toggle, conditional field validation
- SQL safety: only SELECT allowed (regex + psycopg2 read-only connection)
- statement_timeout: 30s to prevent runaway queries

## Out of scope

- SQL editor with syntax highlighting
- Query explain / execution plan view
- Parameterized SQL (user-supplied variables)

## Key files

- monitor/models.py — rule_type, custom_sql fields
- monitor/migrations/0004_rule_custom_sql.py
- monitor/services.py — _check_custom_sql
- monitor/forms.py — conditional validation
- templates/monitor/rule_form.html — toggle UI

## Blocking unknowns

BU-04: statement_timeout — psycopg2 connection options vs SET statement_timeout.
