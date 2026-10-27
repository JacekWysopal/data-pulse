---
change_id: s03-connection-management
title: S-03 Connection management — UI for named PostgreSQL connections
status: done
created: 2026-10-25
updated: 2026-10-25
archived_at: null
---

## Goal

User adds named connections (e.g. "production", "staging") via UI with encrypted
database URL. Rules are assigned to a Connection instead of global MONITORED_DATABASE_URL.

## Architecture decisions

- Model Connection: name, description, _database_url (encrypted via Fernet if key set)
- Rule.connection FK → Connection (nullable, fallback to env MONITORED_DATABASE_URL)
- services.py caches connections per URL to avoid duplicate open connections per run
- ConnectionForm: password input for URL, masked display in list (set_database_url / masked_url)
- Provider grid in connection_list: PostgreSQL available, MySQL/S3/BigQuery/Snowflake grayed out

## Key files changed

- monitor/models.py — Connection model, Rule.connection FK
- monitor/migrations/0002_connection_rule_connection.py
- monitor/services.py — run_single_rule, connection URL resolution
- monitor/views.py — connection CRUD views
- monitor/forms.py — ConnectionForm, RuleForm with connection dropdown
- templates/monitor/connection_list.html — provider grid
- templates/monitor/connection_form.html — add/edit form
- templates/monitor/connection_confirm_delete.html

## Outcome

S-03 done. User can add multiple PostgreSQL connections and assign rules to them.
