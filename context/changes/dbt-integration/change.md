---
change_id: dbt-integration
title: dbt webhook integration — trigger checks after dbt run completes
status: implemented
created: 2026-10-28
updated: 2026-11-04
archived_at: null
---

## Notes

DataPulse exposes a webhook endpoint POST /api/v1/webhooks/dbt that accepts dbt Cloud job completion payload. User configures: which Connection maps to which dbt environment, which rules to run after dbt job success. Also support manual trigger: user selects "Run after dbt job ID X". dbt Cloud sends webhook on job completion → DataPulse runs mapped rules → results available in seconds after transform. Also support dbt Core: user calls the endpoint from their dbt on-run-end hook.
