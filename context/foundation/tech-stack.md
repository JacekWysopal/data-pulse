---
starter_id: django
package_manager: uv
project_name: data-pulse
hints:
  language_family: python
  team_size: solo
  deployment_target: render
  ci_provider: github-actions
  ci_default_flow: auto-deploy-on-merge
  bootstrapper_confidence: verified
  path_taken: standard
  quality_override: false
  self_check_answers: null
  has_auth: false
  has_payments: false
  has_realtime: false
  has_ai: false
  has_background_jobs: false
---

## Why this stack

DataPulse is a small, internal web app (3-week after-hours MVP) for a Python-native BI/data team monitoring PostgreSQL table freshness and volume. Django is the recommended default for `(web-app, python)` and clears all four agent-friendly gates: convention-based ORM and URL routing give an AI agent predictable file structure, the training corpus is enormous, and documentation is current. Django's built-in admin and form system map directly onto DataPulse's core loop — define rules, run checks, display results — without assembling extra libraries. SQLite as Django's test database mirrors the local results-store choice in the PRD, and Django's `psycopg2` integration handles the monitored PostgreSQL connection cleanly. No auth, payments, realtime, AI, or background-job features are in scope for MVP. Deployment targets Render (PaaS, git-push deploy); CI runs on GitHub Actions with auto-deploy-on-merge.
