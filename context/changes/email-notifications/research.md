---
artifact: research
change_id: email-notifications
question: What is needed to send email notifications when a rule check returns FAIL or ERROR?
researcher: worker-subagent
repo_sha: 53d06be871068aad798577c0239e1cfaa94b3c43
date: 2026-10-28
last_updated: 2026-10-28
last_updated_by: worker-subagent
last_updated_note: initial research pass
---

## Summary

Sending email notifications when a rule check returns FAIL or ERROR requires: (1) an email backend configured in settings.py, (2) new fields on `Rule` for notification opt-in and cooldown tracking, (3) a post-result hook in `monitor/services.py` at the two result-creation sites, and (4) a user email address accessible via `request.user.email` (Django's built-in `User` model). No third-party notification library exists in requirements.txt; Django's built-in email framework is the only email infrastructure present.

---

## 1. Where results are created — monitor/services.py

**[evidence]** `monitor/services.py` contains two public functions that create `RuleResult` records:

- `run_single_rule(rule)` — `monitor/services.py:130–164`. Creates exactly one `RuleResult` via `RuleResult.objects.create(...)` in five branches (no connection, empty URL, connect error, check data, unhandled exception). The `result` object is returned to the caller (`monitor/views.py:run_single`, line ~45).
- `run_all_checks()` — `monitor/services.py:167–228`. Iterates over all `Rule` objects; creates one `RuleResult` per rule via `RuleResult.objects.create(...)` in four branches (no connection, empty URL, connect error, check data, unhandled exception). Returns the `CheckRun` object.

**[evidence]** Both functions set `status` to one of `RuleResult.Status.OK`, `RuleResult.Status.FAIL`, or `RuleResult.Status.ERROR` (defined in `monitor/models.py`, `RuleResult.Status` inner class, lines ~145–148).

**[inference]** The cleanest injection point for notification logic is immediately after `RuleResult.objects.create(...)` calls, or as a post-`RuleResult` creation function called from both sites. A `post_save` Django signal on `RuleResult` is an alternative that avoids touching both functions.

---

## 2. Django email backend — settings.py and env vars

**[evidence]** `data_pulse/settings.py` contains no `EMAIL_*` settings. The file uses `django-environ` for config loading (`environ.Env`, `environ.Env.read_env(BASE_DIR / '.env')`). No email backend, host, port, or credentials are present anywhere in the file.

**[evidence]** `render.yaml` declares four env vars: `DATABASE_URL`, `SECRET_KEY`, `DEBUG`, `PYTHON_VERSION`. No email-related env vars are declared.

**[inference]** Django's default email backend is `django.core.mail.backends.smtp.EmailBackend` when no `EMAIL_BACKEND` is set, but it requires SMTP credentials. For development/testing, `django.core.mail.backends.console.EmailBackend` or `django.core.mail.backends.locmem.EmailBackend` can be used without credentials.

**[inference]** To enable real email delivery on Render, the following env vars would need to be added to `render.yaml` (with `sync: false` for secrets):
- `EMAIL_BACKEND` — value `django.core.mail.backends.smtp.EmailBackend`
- `EMAIL_HOST` — SMTP server hostname
- `EMAIL_PORT` — typically 587 (TLS) or 465 (SSL)
- `EMAIL_USE_TLS` — `True` for port 587
- `EMAIL_HOST_USER` — sender address / API key username
- `EMAIL_HOST_PASSWORD` — SMTP password or API key
- `DEFAULT_FROM_EMAIL` — sender display address

**[inference]** settings.py would need to read these via `env()` calls using `django-environ`. The pattern already established in the file (e.g. `env('DATABASE_URL', default=None)`) applies directly.

---

## 3. Rule model — notification fields

**[evidence]** `monitor/models.py` `Rule` model (lines ~53–127) has these fields: `name`, `schema_name`, `table_name`, `connection` (FK), `rule_type`, `custom_sql`, `timestamp_column`, `max_age_hours`, `min_row_count`, `schedule_time`, `created_at`, `updated_at`. There are no notification-related fields.

**[evidence]** `Rule` has no `owner`, `user`, or `notify_*` fields. The model is not user-scoped; it is a single-tenant model with no FK to `django.contrib.auth.models.User`.

**[inference]** To support per-rule notification opt-in, a boolean field such as `notify_on_fail` (default `False`) would need to be added to `Rule`. This requires a new migration.

**[inference]** To support cooldown (avoid repeated notifications for the same rule in a short window), a `last_notified_at` DateTimeField (null=True, blank=True) on `Rule` would be needed, or alternatively a separate `Notification` model to track sent notifications with a timestamp.

**[unknown]** There is currently no user ownership on rules. To send email to the "rule owner", either: (a) a `ForeignKey` to `User` is added to `Rule`, (b) a single admin notification email is used (from settings), or (c) notifications always go to a configured address. The product decision is not resolved in change.md.

---

## 4. Render SMTP options — email providers

**[inference]** Render does not provide a built-in SMTP relay. Recommended options for Django apps on Render, ranked by ease of setup:

| Provider | Free tier | Setup complexity | Notes |
|---|---|---|---|
| SendGrid | 100 emails/day free | Low — API key only | Well-documented Django SMTP integration; uses `smtp.sendgrid.net:587` with API key as password |
| Mailgun | 100 emails/day (EU region) | Low | `smtp.mailgun.org:587`; requires domain verification |
| Brevo (ex-Sendinblue) | 300 emails/day free | Low | `smtp-relay.brevo.com:587` |
| Gmail SMTP | 500/day (workspace) | Medium | Requires App Password or OAuth; less suitable for production |
| Amazon SES | ~3000/month on free tier | Medium | Requires AWS account, DNS verification, Django `django-ses` package |

**[inference]** For a project at this stage (single developer, Render deploy, no existing AWS infrastructure), SendGrid or Brevo are the lowest-friction options — both work with Django's standard SMTP backend with no additional packages.

**[unknown]** No provider has been selected. This is a product/infrastructure decision not yet made.

---

## 5. User email field

**[evidence]** `monitor/views.py` uses `@login_required` decorator on all view functions and imports from `django.contrib.auth.decorators`. `django.contrib.auth` is in `INSTALLED_APPS` in `data_pulse/settings.py`.

**[evidence]** Django's built-in `User` model (`django.contrib.auth.models.User`) has an `email` field (CharField, blank=True by default). This field is available as `user.email` on any authenticated `User` instance.

**[evidence]** `monitor/tests.py` (line ~13) imports `User` from `django.contrib.auth.models` and creates users via `User.objects.create_user(...)`. No test checks that `user.email` is populated.

**[inference]** The `User.email` field is available but blank by default. The superuser / admin user created at setup may have no email set unless explicitly provided during `createsuperuser`. For notifications to reach the intended address, the user must have a populated `email` field.

**[unknown]** The app is currently single-tenant (one user). It is unclear whether the notification recipient is always the single logged-in user, or whether the design anticipates a future multi-user scenario where each rule has an assigned owner.

---

## 6. Cooldown mechanism options

**[inference]** Three viable cooldown approaches in Django, from simplest to most robust:

**Option A — `last_notified_at` field on `Rule`**
Add `notify_last_sent_at = DateTimeField(null=True, blank=True)` to `Rule`. Before sending, check `rule.notify_last_sent_at` against `timezone.now() - cooldown_delta`. Update the field after sending. Requires one migration. Simple, no extra models. Caveat: resets on rule edit if `updated_at` is the tracked field (it is not — `updated_at` is auto_now, not notification-related).

**Option B — Separate `NotificationLog` model**
A model with FK to `Rule`, `sent_at`, `status`, `recipient`. Enables audit trail. More complex but extensible. Requires one migration for new model.

**Option C — Django cache**
Use `django.core.cache.cache.set(f'notified_{rule.id}', True, timeout=cooldown_seconds)` to track cooldown in cache. Zero DB migrations. Downside: cache is volatile (lost on restart/deploy), no audit trail.

**[inference]** Option A is the minimum viable approach for this stage of the project. Option B is preferred if an audit trail of sent notifications is a requirement.

---

## 7. Implementation surface summary

| Area | Current state | What's needed |
|---|---|---|
| Result creation sites | `run_single_rule` (services.py:130) and `run_all_checks` (services.py:167) | Post-create hook or signal to trigger email |
| Email backend | Not configured in settings.py | `EMAIL_*` settings + env vars in render.yaml |
| Rule model | No notification fields | `notify_on_fail` (bool), `notify_last_sent_at` (DateTimeField) + migration |
| User email | Available via `User.email`, blank by default | Ensure admin user has email set |
| SMTP provider | None selected | Choose SendGrid/Brevo/Mailgun; add API key to Render env |
| Email template | None exists | New HTML/text template for FAIL/ERROR notification |
| Forms | `RuleForm` in forms.py | Add `notify_on_fail` field to `RuleForm.Meta.fields` |

---

## Open questions (unresolved before planning)

1. **Recipient model**: is the notification always sent to the single superuser's email, or to a configurable per-rule address? This determines whether a `User` FK is needed on `Rule`. [unknown]
2. **SMTP provider choice**: SendGrid, Brevo, or other? Affects which env vars and whether any extra package is needed. [unknown — product/infra decision]
3. **Cooldown duration**: what interval should suppress duplicate notifications? (e.g. 1 hour, 24 hours?) [unknown — product decision]
4. **ERROR vs FAIL distinction**: should ERROR status (infrastructure error, no DB connection) trigger notification separately from FAIL? Or both together? change.md says "FAIL or ERROR" — this is confirmed as a requirement, not a question.
5. **cryptography package**: `requirements.txt` now includes `cryptography==44.0.3` (added in commit 53d06be). `_FERNET_AVAILABLE` will be True on Render, so Connection URLs are encrypted. [evidence — resolved since repo-map was generated]
