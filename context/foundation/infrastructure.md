---
project: DataPulse
researched_at: 2026-09-18
recommended_platform: Render
runner_up: Railway
context_type: mvp
tech_stack:
  language: python
  framework: django
  runtime: python3.12
---

## Recommendation

**Deploy on Render.**

DataPulse is a low-traffic, internal Django app with SQLite as its results store. Render's free tier supports Python/Django natively with git-push deploys, managed TLS, and a stable deploy API — all without requiring persistent volume configuration (unlike Railway, where the default filesystem is ephemeral and would destroy the SQLite history on every redeploy). The free tier's 15-minute spin-down is acceptable for a tool used sporadically by a small internal team. Cost priority from the interview breaks the tie with Railway ($5/mo Hobby).

## Platform Comparison

| Platform | CLI-first | Managed | Agent docs | Stable deploy API | MCP | Score |
|---|---|---|---|---|---|---|
| **Render** | Pass | Pass | Partial | Pass | Fail | 3.5/5 |
| **Railway** | Pass | Pass | Pass | Pass | Pass | 5/5 |
| **Fly.io** | Pass | Pass | Partial | Pass | Fail | 3.5/5 |

### Shortlisted Platforms

#### 1. Render (Recommended)

Free tier with git-push deploys, Django guide in official docs, Render CLI v2 with agent skills. Spin-down after 15 min inactivity — cold start ~30-60s. SQLite persists across deploys on the default filesystem (no persistent volume needed). No MCP server, but CLI supports non-interactive scripting and GitHub Actions integration. Agent skills installable via `render agent-skills install`.

#### 2. Railway

Best agent-story of the three: GA MCP server (`railway mcp`, `mcp.railway.com`), `railway setup agents` one-command setup. Hobby plan $5/mo. Django officially documented. **Critical caveat for DataPulse:** Railway's default filesystem is ephemeral — SQLite is deleted on every redeploy unless a persistent volume is attached. This requires manual configuration and adds operational overhead for an MVP.

#### 3. Fly.io

Excellent `flyctl` CLI, multi-region by default, usage-based pricing (no seat fee). No free tier proper — only free resource allowances. No MCP server. Django supported via Dockerfile. More configuration overhead than Render for a simple Django app.

## Anti-Bias Cross-Check: Render

### Devil's Advocate — Weaknesses

1. **Spin-down on free tier**: 15 min inactivity triggers sleep; cold start takes 30-60s. For an internal team opening the app once a day, the first request will always be slow.
2. **750 free hours/month**: one always-on service eats the entire free budget. If any other service is added to the workspace, hours run out mid-month.
3. **No MCP server**: Render has agent skills for the CLI but no MCP server. Railway is ahead on agent-native operations.
4. **Render CLI is newer**: CLI v2 is solid but younger than `flyctl`. Some operations still require the dashboard (billing, team management).
5. **Free tier limitations**: no SLA, no priority support, no custom health checks on free tier.

### Pre-Mortem — How This Could Fail

The team deploys DataPulse on Render free tier. For the first month it works fine — the app spins up on the first daily check. After 6 weeks, the team adds a second service to the workspace (e.g., a staging environment). The combined free hours run out on the 20th of the month. Both services stop. The team doesn't notice for two days because DataPulse is only checked sporadically. The fix requires upgrading to Render's Starter plan ($7/mo per service). The real cost was not anticipated because the free tier limit was not visible in the dashboard during setup.

### Unknown Unknowns

- **750h/month is per workspace, not per service**: adding a second service (e.g. a staging environment) halves the effective free runtime. Monitor usage from day one.
- **Free tier has no custom health checks**: Render uses a default HTTP health check. If the Django app takes >30s to start (e.g. running migrations at boot), the health check fails and Render marks the deploy as failed.
- **`render.yaml` Blueprint is required for reproducible deploys**: manual dashboard deploys are fine for the first deploy, but a `render.yaml` in the repo is needed for CI/CD (`render deploy` command) and for the agent to trigger deploys programmatically.
- **SQLite is safe on Render but not recommended for concurrent writes**: DataPulse has multiple concurrent users (per PRD). SQLite handles read concurrency well but write-heavy workloads (running checks simultaneously) may hit locking. At ~50 rules and manual triggering, this is acceptable for MVP.

## Operational Story

- **Preview deploys**: Render creates a preview URL per pull request when connected to GitHub. Preview services share the free hour budget — disable if budget is tight, or use a separate `staging` branch strategy.
- **Secrets**: env vars set in the Render Dashboard under "Environment" or via `render env set KEY=VALUE`. `DATABASE_URL` (the monitored PostgreSQL connection string) goes here — never in `render.yaml` or the repo.
- **Rollback**: `render deploys rollback --service-id <id>` or one click in the dashboard. Time to revert: ~2 minutes. SQLite data is not affected by app rollbacks (it persists on the filesystem).
- **Approval**: human approval required for: first deploy setup, env var changes for `DATABASE_URL`/`SECRET_KEY`, plan upgrades. Agent may perform unattended: redeploys (`render deploys create`), log tailing (`render logs`), service restarts.
- **Logs**: `render logs --service-id <id> --tail` — real-time log streaming from CLI. Pipe to file for offline review. No MCP; parse CLI output.

## Risk Register

| Risk | Source | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Free hours exhausted mid-month | Unknown unknowns | Medium | High | Monitor via `render billing`; keep workspace to one service in MVP |
| Cold start 30-60s on first daily request | Devil's advocate | High | Low | Acceptable for internal tool; document in AGENTS.md |
| Health check fails on slow boot | Unknown unknowns | Low | High | Add `RENDER_START_TIMEOUT` or run migrations before binding port |
| SQLite write contention with concurrent check runs | Unknown unknowns | Low | Medium | Acceptable at MVP scale (~50 rules, manual trigger); switch to PostgreSQL if concurrency grows |
| No MCP — agent must parse CLI output | Devil's advocate | High | Low | Use Render CLI non-interactive mode; document commands in AGENTS.md |

## Getting Started

1. **Install Render CLI**: `winget install Render.Render` (Windows) or download from [render.com/docs/cli](https://render.com/docs/cli)
2. **Create `render.yaml`** in repo root:
   ```yaml
   services:
     - type: web
       name: data-pulse
       runtime: python
       buildCommand: "pip install -r requirements.txt && python manage.py migrate"
       startCommand: "gunicorn data_pulse.wsgi:application"
       envVars:
         - key: DATABASE_URL
           sync: false
         - key: SECRET_KEY
           generateValue: true
         - key: DEBUG
           value: "False"
   ```
3. **Add `gunicorn` dependency**: `uv add gunicorn` and export `requirements.txt` via `uv pip compile pyproject.toml -o requirements.txt`
4. **Connect repo** in Render Dashboard → New Web Service → connect GitHub repo
5. **Set `DATABASE_URL`** in Render Dashboard → Environment — the connection string to the monitored PostgreSQL instance

## Out of Scope

The following were not evaluated in this research:
- Docker image configuration
- CI/CD pipeline setup beyond git-push auto-deploy
- Production-scale architecture (multi-region, HA, DR)
- Railway persistent volume configuration (relevant if Railway is reconsidered post-MVP)