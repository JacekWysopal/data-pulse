---
change_id: post-mvp-ux
title: Post-MVP UX — dark UI, auth, side navbar, schedule, per-rule run
status: implemented
created: 2026-10-25
updated: 2026-10-25
archived_at: null
---

## Goal

Ship a professional dark UI, login protection, animated side navbar, per-rule run
button, and schedule field — all beyond the original MVP scope.

## What was done

### Auth
- @login_required on all monitor views
- Login page matching app dark theme (gradient, grid bg)
- Logout button in sidebar footer

### UI — Steel Dark theme
- CSS design token system: --bg-base, --accent, --ok, --fail, --error
- KPI strip: 4 large cards with progress bars, hover animations
- Status badges with pulsing dot on OK
- Actions column visible only on row hover
- Animated SVG logo with draw-on + glow pulse

### Side navbar
- Collapsible (220px ↔ 64px), state persisted in localStorage
- Tooltips in collapsed mode
- Breadcrumbs in topbar
- Favicon as SVG data URI

### Per-rule run
- ▶ button per row → run_single view → flash message with result
- Spinner on "Run all" button during request

### Schedule
- Rule.schedule_time (TimeField, UTC)
- management command run_scheduled — for Render Cron Jobs
- Time picker in rule form, schedule column in dashboard table

### Seed demo
- seed_demo management command: 12 rules across public schema tables
- run in build command, idempotent, updates schema on re-run

### SQL seed for Supabase
- scripts/seed_supabase.sql — 12 tables with realistic data

## Key commits

- feat: dark UI redesign — Steel Dark theme
- feat: login required, bigger KPIs, seed demo data
- feat: side navbar with animated logo, breadcrumbs, collapse
- feat: per-rule run, schedule field, provider grid in connections
- fix: restore rule_history view, add favicon
- fix: migration 0002 field name, seed schema update, remove run flash msg
