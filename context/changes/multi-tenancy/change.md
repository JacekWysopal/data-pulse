---
change_id: multi-tenancy
title: Multi-tenancy — user accounts, per-user rules and connections
status: planned
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

Full user registration and login. Each user sees only their own Rules and Connections.
Requires: user registration form, email verification or simple signup, Rule/Connection FK to User,
migration to reassign existing data, full auth flow (signup, login, logout, password reset).
This is the most impactful change — blocks per-user data isolation for all other features.
