# Email Notifications on FAIL — Plan Brief

> Full plan: `context/changes/email-notifications/plan.md`
> Research: `context/changes/email-notifications/research.md`

## What & Why

When a rule check returns FAIL or ERROR, the rule owner currently has no automatic
alert — they only know if they check the dashboard. This feature sends an email to
the owner on failure so problems surface immediately without manual polling.

## Starting Point

`Rule` gains an `owner` FK to `User` via S-12 (multi-tenancy). Today there are no
`EMAIL_*` settings in `settings.py`, no notification fields on `Rule`, and no email
templates. Django's email framework is already available; it just needs wiring.

## Desired End State

A user editing a Rule sees a "Notify me on failure" checkbox. When checked, any FAIL
or ERROR result triggers a plain-text + HTML email to `rule.owner.email`. A 1-hour
cooldown suppresses repeat alerts for the same rule. Rules with the checkbox unchecked
(the default) generate no emails.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Email provider | SendGrid via SMTP | Free 100/day, no extra package — works with Django's built-in backend | Plan |
| Per-rule opt-in | `Rule.notify_on_fail` BooleanField, default False | Opt-out default means no unexpected emails for existing rules | Plan |
| Cooldown | `Rule.last_notified_at` DateTimeField, 1-hour window | Simplest approach — no extra model, single DB column | Research / Plan |
| Email format | Plain text + HTML via `EmailMultiAlternatives` | Best email client compatibility with one send call | Plan |
| Cooldown mechanism | Field on Rule (not cache, not separate model) | Zero extra models, survives restarts, visible in admin | Research / Plan |
| Send location | Synchronous call in `services.py` after each FAIL/ERROR create | Keeps all notification logic in one place; acceptable latency at current scale | Plan |
| Dev fallback | Console backend when `EMAIL_HOST` not set | Local dev works without credentials; no code change required | Plan |

## Scope

**In scope:**
- `Rule.notify_on_fail` + `Rule.last_notified_at` fields and migration `0005`
- `monitor/email_service.py` with `send_fail_notification(rule, result)`
- Email templates: plain text + HTML (in `templates/monitor/email/`)
- Hook into `run_single_rule` and `run_all_checks` in `services.py`
- `notify_on_fail` checkbox in `RuleForm` and `rule_form.html`
- `EMAIL_*` settings in `settings.py` + env var entries in `render.yaml` + `.env.example`

**Out of scope:**
- Slack / webhook notifications (S-16)
- Notification history / audit log model
- Per-user SMTP config
- Async task queue / retry logic
- Unsubscribe links or bounce handling
- Email verification for owner address

## Architecture / Approach

`services.py` already creates `RuleResult` records at two sites. A new thin module
`monitor/email_service.py` exposes `send_fail_notification(rule, result)`. This
function guards against four early-exit conditions (opt-out, blank email, cooldown,
send failure) then sends via Django's `EmailMultiAlternatives`. The function updates
`rule.last_notified_at` via a targeted `.update()` call — not `rule.save()` — to
avoid touching `Rule.updated_at`. `services.py` gains two import + call lines per
result-creation site; no other files in the services layer change.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Model Changes | `notify_on_fail` + `last_notified_at` on Rule, migration 0005 | None — additive, defaulted fields |
| 2. Email Service | `email_service.py` + email templates, fully unit-tested | Template rendering errors; guard against blank owner email |
| 3. Hook services.py | Notifications fire on every FAIL/ERROR result | Five create sites in run_single_rule must all be covered |
| 4. UI | notify_on_fail checkbox in rule form | Minor — form field + template change only |
| 5. Settings & Docs | EMAIL_* in settings.py, render.yaml, .env.example | SendGrid API key must be set as secret in Render dashboard |

**Prerequisites:** S-12 (multi-tenancy) merged — `Rule.owner` FK must exist before Phase 1.
**Estimated effort:** ~2 sessions across 5 phases. Phases 1–4 are 30–60 min each; Phase 5 is ~15 min.

## Open Risks & Assumptions

- `Rule.owner` FK from S-12 is assumed present. If S-12 is not merged, Phase 1
  must be deferred or the notification target must be a fallback (e.g., admin email
  from settings). This plan does not include that fallback — S-12 is a hard prerequisite.
- `User.email` is blank by default in Django. The email service guards against this,
  but users who forget to fill in their email will silently receive no notifications.
  Consider adding a note in the UI or a warning in the admin.
- Sending email synchronously inside `run_all_checks` adds latency proportional to
  the number of rules with `notify_on_fail=True`. At small scale (< 50 rules) this is
  fine; at larger scale, a task queue would be needed.

## Success Criteria (Summary)

- A rule with `notify_on_fail=True` and a valid `owner.email` delivers an email on FAIL/ERROR.
- A second FAIL within 1 hour produces no second email.
- A rule with `notify_on_fail=False` (default) never sends an email.
