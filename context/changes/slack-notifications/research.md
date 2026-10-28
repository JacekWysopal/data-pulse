---
change_id: slack-notifications
research_question: >
  What is the minimal implementation to show Slack as "Soon" in the
  notifications UI and prepare the model stub?
researcher: worker-subagent
date: 2026-10-28
commit_sha: 53d06be871068aad798577c0239e1cfaa94b3c43
---

## Summary

The minimal implementation requires two deliverables:

1. **UI: "Soon" badge for Slack** — add a Slack card in the
   `connection_list.html` provider grid, using the identical `.disabled` +
   `.badge-soon` pattern already applied to MySQL, Amazon S3, BigQuery, and
   Snowflake (4 existing disabled cards). No new URL, view, or context needed.

2. **Model stub** — add `SlackNotification` to `monitor/models.py` with
   `webhook_url (CharField, blank)`, `enabled (BooleanField, default=False)`,
   and a `user (ForeignKey → AUTH_USER_MODEL)`. Create the corresponding
   migration. No form, no view, no admin registration needed for this scope.

There is no dedicated notifications settings page today. The question of where
to place the Slack badge is answered by the existing precedent on the
Connections page (`/connections/`), which already hosts the provider selector
grid. Adding a sixth card there is the zero-friction path.

---

## Evidence

### 1. No notifications page or URL exists

Checked `monitor/urls.py` (9 URL patterns, all listed at file:1–22):
Dashboard, run_checks, rules CRUD (5 routes), schema API (2 routes),
connections CRUD (4 routes). No `/notifications/` URL is registered.

Checked `monitor/views.py` — 10 view functions, none named `notifications_*`
or `settings_*`. [evidence: monitor/views.py:1–200, monitor/urls.py:1–22]

Checked `templates/monitor/` — 9 templates total (find results). No
`notifications.html` file exists. [evidence: find output]

Checked `templates/base.html` sidebar nav — 3 nav items: Dashboard, Add rule,
Connections. No Notifications link. [evidence: base.html:~330–380]

**Conclusion (evidence):** There is no notifications settings page in the
current codebase. The first place to surface Slack as "Soon" is the
Connections page provider grid, which is the only UI section already showing
"Soon" badges for non-PostgreSQL providers.

---

### 2. "Soon" badge pattern — fully established in connection_list.html

The provider grid at `templates/monitor/connection_list.html` (lines ~85–190)
contains exactly 5 provider cards:

| Provider | CSS class | Badge class | element type |
|---|---|---|---|
| PostgreSQL | `provider-card available` | `badge-available` | `<a>` (links to add) |
| MySQL | `provider-card disabled` | `badge-soon` | `<div>` (non-interactive) |
| Amazon S3 | `provider-card disabled` | `badge-soon` | `<div>` |
| BigQuery | `provider-card disabled` | `badge-soon` | `<div>` |
| Snowflake | `provider-card disabled` | `badge-soon` | `<div>` |

CSS already defined inline in `connection_list.html` extra_head block:
- `.provider-card.disabled { opacity: 0.35; filter: grayscale(1); }` [connection_list.html:~42]
- `.badge-soon { background: var(--bg-elevated); border: 1px solid var(--border-strong); color: var(--text-muted); }` [connection_list.html:~62]

The grid is `grid-template-columns: repeat(5, 1fr)` [connection_list.html:~17].
Adding a sixth Slack card will require changing this to `repeat(6, 1fr)`, or
keeping 5 columns and allowing wrap. The Snowflake card is the last in the
grid today. **inference:** A layout change is needed (6 cards in a 5-column
grid). Options are `repeat(6, 1fr)` or `repeat(auto-fill, minmax(120px, 1fr))`.
This is a template-only change.

No view changes are required — `connection_list` already renders with
`connections` context; no additional context variable is needed for a purely
static "Soon" card.

[evidence: templates/monitor/connection_list.html — full read]

---

### 3. SlackNotification model fields

There is no existing `SlackNotification` model or any notification-related
model in `monitor/models.py`. The file defines exactly 4 models:
`Connection`, `Rule`, `CheckRun`, `RuleResult`. [evidence: monitor/models.py:1–185]

From the roadmap `S-16` spec:
> Model SlackNotification istnieje w bazie (gotowy do aktywacji).
[evidence: context/foundation/roadmap.md:416–417]

From `change.md`:
> Stub the backend: SlackNotification model with `webhook_url` field,
> `disabled=True` flag.
[evidence: context/changes/slack-notifications/change.md:13]

The `S-12 Multi-tenancy` story (prereq for S-13 email notifications) adds
`user ForeignKey` to `Rule` and `Connection`. S-16 has no S-12 prereq
(roadmap table row: `S-16 | — | new`). [evidence: roadmap.md:322–325]

**inference:** A `user` FK on `SlackNotification` is architecturally correct
for the notifications domain, but S-16 does not depend on S-12. Two stances:
(a) omit `user FK` now (simpler stub, no dependency on multi-tenancy schema);
(b) include nullable `user FK` (future-safe, one extra field). The change.md
scope says "webhook_url field, disabled=True flag" without mentioning `user`.
This research surfaces the ambiguity; the plan phase should decide.

Required fields for the stub based on change scope:
- `webhook_url: CharField(max_length=500, blank=True)` — stores URL once real
  Slack integration is enabled; blank now because feature is disabled
- `enabled: BooleanField(default=False)` — change.md says "disabled=True flag";
  field name `enabled` (False = disabled) or `disabled` (True = disabled) —
  either works; `enabled=False` is idiomatic Django

Optional field (ambiguous, not required by change.md):
- `user: ForeignKey(settings.AUTH_USER_MODEL, on_delete=CASCADE, null=True, blank=True)` — nullable FK allows stub without S-12 dependency

Encryption: `Connection._database_url` uses Fernet encryption
(`_get_fernet()` helper, `set_database_url`/`get_database_url` methods).
`webhook_url` on `SlackNotification` stores a Slack incoming webhook URL
(not a credential in the same sense as a DB password). The change scope
says "stub, no actual Slack API calls" — no encryption needed now.
[evidence: monitor/models.py:14–45]

Existing migration count: 4 migrations in `monitor/migrations/`.
A new migration `0005_slacknotification.py` would be the fifth.
[evidence: repo-map.md P2 section]

---

### 4. No settings page needed for this scope

The roadmap outcome for S-16:
> W ustawieniach powiadomień widoczna jest opcja Slack z badge „Soon".
[evidence: roadmap.md:416]

There is no "settings" section in the current nav or URL map. The phrase
"ustawieniach powiadomień" (notification settings) is aspirational roadmap
language — no such page exists. The Connections page provider grid is the
only place in the current UI that already shows provider availability/status
badges, making it the correct anchor point for this "Soon" badge.

**inference:** A dedicated notifications settings page is outside S-16 scope.
The Connections page is sufficient for this change.

---

### 5. No `user` FK dependency risk

`settings.AUTH_USER_MODEL` is not explicitly set in `data_pulse/settings.py`,
so it defaults to `auth.User` (Django built-in). [evidence: data_pulse/settings.py:1–60]
If a nullable `user` FK is added to `SlackNotification`, it introduces no
breaking migration — `null=True, blank=True` on a new model is safe.

---

## Gaps / Open questions for /10x-plan

1. **Layout of the provider grid:** Adding a 6th card breaks the
   `repeat(5, 1fr)` grid. The plan should specify whether to use `repeat(6, 1fr)`
   or switch to `repeat(auto-fill, minmax(130px, 1fr))`.

2. **`user` FK on `SlackNotification`:** Change.md scope does not require it.
   Including a nullable FK now avoids a future migration; omitting it keeps
   the stub minimal. Decision needed in the plan.

3. **Field name `enabled` vs `disabled`:** Either convention works.
   `enabled=False` (idiomatic Django) is recommended; plan should confirm.

---

## File surface for implementation

| File | Change |
|---|---|
| `templates/monitor/connection_list.html` | Add Slack `<div class="provider-card disabled">` card; adjust grid columns |
| `monitor/models.py` | Add `SlackNotification` model class |
| `monitor/migrations/0005_slacknotification.py` | New migration (auto-generated via `makemigrations`) |

No changes to: `monitor/views.py`, `monitor/urls.py`, `monitor/forms.py`,
`data_pulse/settings.py`, `templates/base.html`.
