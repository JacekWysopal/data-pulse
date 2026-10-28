# Advanced Scheduler — Plan Brief

> Full plan: `context/changes/advanced-scheduler/plan.md`
> Research: `context/changes/advanced-scheduler/research.md`

## What & Why

Replace `Rule.schedule_time` (a single UTC time-of-day) with a flexible scheduler that
supports multiple predefined daily frequencies and custom cron expressions. A rule can
now be disabled, run 1×/2×/3×/6× per day, every hour, or on a user-supplied 5-field
cron string. The change unblocks meaningful automated monitoring use cases that a
single-fire-per-day schedule cannot serve.

## Starting Point

`Rule` has one `schedule_time TimeField(null=True)`. `run_scheduled` filters
`schedule_time=now` to fire rules. The form exposes an `<input type="time">` widget.
`render.yaml` has no `type: cron` service — the cron caller is not yet configured on
Render. `croniter` is not installed.

## Desired End State

`Rule` has `schedule_type` (7 choices: disabled, 5 presets, custom_cron) and
`schedule_cron` (CharField for custom expressions); `schedule_time` is gone. The rule
form shows a dropdown with preset labels and reveals a cron text input when "Custom cron
expression" is selected. `run_scheduled` uses `croniter.match()` against a resolved cron
string per rule. `render.yaml` includes a `type: cron` service firing every minute.
Existing `schedule_time` values are preserved as `custom_cron` rows during migration.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Cron library | `croniter` (add dep) | Provides `is_valid()` + `match()` vs. weak regex-only path | Research |
| Model design | Extend Rule (2 new fields) | One schedule per rule; separate Schedule model adds join complexity without stated multi-schedule requirement | Research / Plan |
| Cron string storage | PREDEFINED dict in code, DB only for custom_cron | Keeps preset defaults changeable without a migration; debug info can be inferred from schedule_type label | Plan |
| Preset cron values | 1×=`0 8 * * *`, 2×=`0 8,20 * * *`, 3×=`0 6,14,22 * * *`, 6×=`0 */4 * * *`, hourly=`0 * * * *` | Sensible UTC business-hours defaults matching task spec | Plan |
| Migration strategy | Two-file (0005 add+data, 0006 remove) | Keeps rollback surface small; 0005 data-migrates `schedule_time` → `custom_cron` before 0006 drops column | Research / Plan |
| render.yaml cron job | Add `type: cron` every minute | Required for Render deployment; one per-minute caller is sufficient for all supported schedules | Research |
| schedule_time removal | Phase 3 (deferred, not same migration) | Safer rollback; tests and form updated first | Plan |

## Scope

**In scope:**
- `schedule_type` + `schedule_cron` fields on `Rule`
- Data migration: existing `schedule_time` values → `custom_cron` entries
- `schedule_time` removal (Phase 3)
- `run_scheduled` rewrite using `croniter.match()`
- Rule form schedule picker with JS show/hide for custom cron input
- Render Cron Job in `render.yaml`
- Test updates + new validation tests

**Out of scope:**
- Multiple schedules per rule
- Per-rule timezone (all UTC)
- Render pricing/tier verification
- Email/Slack notifications on schedule fire
- Non-Render deployment docs

## Architecture / Approach

`Rule.schedule_type` encodes the schedule intent; `run_scheduled` resolves preset types
through a `PREDEFINED` dict at runtime and reads `schedule_cron` for custom types. The
management command is called every minute by a Render Cron Job — it checks every
non-disabled rule against `croniter.match()` rather than a DB filter. Form validation
uses `croniter.is_valid()` to reject invalid custom expressions before save.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Model fields + data migration | `schedule_type`, `schedule_cron` on Rule; existing data preserved | Data migration must be atomic with AddField to avoid silent disable of running rules |
| 2. croniter + run_scheduled + render.yaml | Scheduler functional end-to-end; Render cron configured | `croniter.match()` requires timezone-aware datetime (not time object) |
| 3. Remove schedule_time | Clean model; old column gone | Must run after Phase 2 is verified |
| 4. UI — schedule picker | User-facing schedule selector in rule form | JS show/hide must handle page-load state for edit view |
| 5. Tests | Updated + new test coverage | Tests patching `timezone.now` must use UTC-aware datetime |

**Prerequisites:** None (S-15 is marked independent in roadmap).
**Estimated effort:** ~3–4 sessions across 5 phases.

## Open Risks & Assumptions

- `croniter.match()` behavior at exact minute boundaries — verify that `replace(second=0, microsecond=0)` gives consistent results (not off-by-one between cron spec and Python datetime).
- Render `type: cron` service may incur additional cost on paid tiers — check Render dashboard before enabling in production.
- `0005` data migration assumes `schedule_time.hour` is a sufficient proxy for the original intent (minute component is always 0 in existing `<input type="time">` entries).

## Success Criteria (Summary)

- A rule set to "2× / day" fires twice daily at 08:00 and 20:00 UTC without any manual intervention.
- A rule set to a custom cron expression fires at the correct times and rejects invalid expressions in the form.
- All existing monitor tests pass and no `schedule_time` references remain in non-migration source files.
