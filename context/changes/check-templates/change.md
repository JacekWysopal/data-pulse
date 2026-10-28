---
change_id: check-templates
title: Built-in rule check templates — null, uniqueness, referential integrity
status: implemented
created: 2026-10-28
updated: 2026-10-29
archived_at: null
---

## Notes

Template gallery on rule creation: click a template and the SQL field pre-fills. Templates: null_check (no NULLs in column), uniqueness (no duplicate values), referential_integrity (FK exists in parent table), not_negative (numeric >= 0), future_date (date not in future), pattern_match (regex), row_count_equals, completeness_rate (% non-null >= threshold). Each template takes parameters filled in a simple form that generates the SQL.
