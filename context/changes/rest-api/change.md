---
change_id: rest-api
title: REST API + API keys — trigger rules from CI/CD and external tools
status: planned
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

User creates named API keys in UI. Endpoints: POST /api/v1/rules/{id}/run, POST /api/v1/rules/run-all, GET /api/v1/rules/{id}/results, GET /api/v1/rules. Auth: Bearer token header. Rate limiting: 60 req/min. Use cases: trigger after dbt run, after deploy, from GitHub Actions. Response: JSON with status, measured values, run_id.
