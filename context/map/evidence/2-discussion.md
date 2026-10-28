# Evidence: discussion
<sources: git-only (gh not installed); window 2026-10-18..2026-10-27; 17 counted commits, 3 fix commits>

## Buzz per capability

| Cap | fix commits | reverts | multi-attempt | open plans | debt markers |
|-----|-------------|---------|---------------|------------|--------------|
| C2  | 1 (spillover, bb59e02) | 0 | 1 (C2 service broken after refactor → 719289c) | s01-smoke-test (done) | 0 |
| C3  | 1 (spillover, bb59e02) | 0 | 0 | s03-connection-management (done) | 0 |
| C4  | 1 direct (719289c) | 0 | 0 | schema-introspection (done), BU-03 resolved | 0 |
| P2  | 2 (bb59e02 + 0555442) | 0 | 1 (migration 0002 redone after S-03 feat) | — | 0 |
| C6  | 1 (0555442 — view accidentally dropped) | 0 | 1 | s02-rule-history (done) | 0 |
| C5  | 1 (spillover, bb59e02) | 0 | 0 | dashboard-filters (done) | 0 |
| C1  | 1 (spillover, bb59e02) | 0 | 0 | custom-sql-rule (proposed, BU-04 open) | 0 |
| C7  | 1 (0555442 — login.html touched alongside view restore) | 0 | 0 | — | 0 |
| P1  | 0 | 0 | 0 | deploy-pipeline (done, all gates passed) | 0 |
| P3  | 0 | 0 | 0 | repo-map (in-progress) | 0 |

## Friction

**C2 / services.py — post-refactor dispatcher break** [evidence]
- `a9bb540` refactored `services.py` (removed env fallback, touched `_check_rule` dispatch path).
- 34 minutes later: `719289c` `fix: _check_rule dispatcher — broken recursive call after refactor`.
- Single fix, resolved same session. Classified as trial-and-error (false-signal rule 5) but notable: the break was silent enough to survive the 60-test suite added in `e1f61e0`.

**P2 / migration 0002 — field-name error** [evidence]
- `165a14e` added `Connection` model and migration 0002.
- `35601b9` (9 min later) added `per-rule run` touching models again.
- `bb59e02` (9 min later) fixed `migration 0002 field name` — multi-step correction on the same artefact within 18 minutes.
- This is the clearest multi-attempt pattern in the window.

**C6 — rule_history view dropped and restored** [evidence]
- `35601b9` feat introduced a regression (view missing from views.py).
- `0555442` (2 min later) `fix: restore rule_history view`.
- Pattern: capability dropped as collateral during a broad views.py edit.

**No reverts found** [evidence]
- `git log --oneline` contains no "Revert" subject lines in the window.

## Planning attention

| Change folder | Status | Capability |
|---|---|---|
| custom-sql-rule | proposed (not yet in code) | C1/C2 |
| deploy-pipeline | done | P1 |
| s03-connection-management | done | C3 |
| schema-introspection | done | C4 |
| dashboard-filters | done | C5 |
| connection-badge | done | C5 |
| rule-builder-ui | done (merged into schema-introspection) | C1/C4 |
| post-mvp-ux | done | C5/C7/P2 |
| s01-smoke-test | done | C2/P1 |
| s02-rule-history | done | C6 |
| bootstrap-verification | done (scaffold audit) | P1/P2 |
| repo-map | in-progress | P3 |

Most-planned capabilities: C1 (rule management, 2 dedicated changes), C4/C5 (schema + dashboard, each with own change folder), P1 (deploy, most detailed plan.md).

## Debt markers

**Code (TODO/FIXME/HACK/XXX):** 0 markers found across all .py and .html files. [evidence]

**Documented blocking unknowns from change.md files:**
- BU-04 (custom-sql-rule): `statement_timeout` — psycopg2 connection options vs `SET statement_timeout` — open, capability C1/C2. [evidence]
- BU-03 (schema-introspection): `information_schema` via Supabase pooler — resolved in change.md. [evidence]
- bootstrap-verification: "GitHub recency check: unavailable (gh CLI not installed on this machine) — Severity: unknown". [evidence]

**Architectural debt signal — env fallback removal:** [inference]
- `a9bb540` `refactor: remove MONITORED_DATABASE_URL env fallback — connections UI-only` touched 6 files including tests and render.yaml. This was a deliberate clean-up of a transitional shortcut introduced during bootstrap. The fact it required a follow-up fix (719289c) suggests the fallback was load-bearing in the dispatch path.

## Mechanical signals (demoted, false-signal reasons)

- **fix bb59e02 spanning 7 capabilities** — one commit touching templates, migration, seed. Attributed to C3 origin (migration 0002 field name); spillover to C1/C2/C5/C6/C7/P2 is incidental (false-signal rule 12).
- **fix 0555442 touching C7** — login.html was in the same base.html edit adding favicon; C7 was not broken. Spillover (false-signal rule 12).
- **High fix ratio on P2 (migrations)** — iteration over migration field names is normal schema-driven work (false-signal rule 5).

## Unknowns

- No forge access (gh not installed): PR numbers, issue tracker, human review comments, closed-unmerged PRs, and bug labels are not available. [unknown]
- Production error tracker (Render/Sentry): no error-tracking integration found in settings.py; runtime errors from Render are not visible. [unknown]
- Test failure history in CI: `.github/workflows/ci.yml` added in `e1f61e0`; no CI run logs available locally. [unknown]

## Commands run

```
git log --oneline --no-merges
git log --oneline | grep -i "revert|hotfix|hack|workaround|temp"   # 0 results
python (inline): marker scan across .py + .html (TODO/FIXME/HACK/XXX) — 0 found
python (inline): fix commit → capability mapping via capabilities.tsv
ls context/changes/  + read all change.md files
```
