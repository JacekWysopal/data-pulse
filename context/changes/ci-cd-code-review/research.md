---
date: 2026-10-28T09:18:54Z
researcher: kiro-worker
git_commit: c74492ceb06041478d36f11eee56ee553795e25c
branch: dev
repository: data-pulse
topic: "What is needed to implement an agent-based CI code review workflow for DataPulse on GitHub Actions, following M5L3 from the 10xDevs course?"
tags: [research, ci-cd, github-actions, code-review, m5l3, composite-action]
status: complete
last_updated: 2026-10-28
last_updated_by: kiro-worker
---

# Research: Agent-based CI Code Review Workflow for DataPulse (M5L3)

**Date**: 2026-10-28T09:18:54Z
**Researcher**: kiro-worker
**Git Commit**: c74492ceb06041478d36f11eee56ee553795e25c
**Branch**: dev
**Repository**: data-pulse

## Research Question

What is needed to implement an agent-based CI code review workflow for DataPulse on GitHub Actions, following M5L3 from the 10xDevs course?

## Summary

DataPulse has 2 existing GitHub Actions workflows (CI tests, Render deploy). No review workflow or `.github/actions/` directory exist yet. The M5L3 template set provides exactly 4 ready-to-adapt files in `.kiro/config-templates/`: a trigger workflow (`m5l3-review.yml.template`), a composite action (`m5l3-action.yml.template`), a TypeScript schema (`m5l2-review-schema.ts.template`), and a promptfoo eval config. The 6 review criteria in `requirements.md` are already expressed as a `zod` schema (`REVIEW_SCHEMA`) and a `SYSTEM_PROMPT` in the schema template. The primary missing artifact is `dist/review.js` — the compiled Node.js reviewer agent that the composite action invokes. This agent must read the diff from `DIFF_FILE`, call an LLM with the system prompt and schema, and print valid JSON to stdout. The M5L3 pattern differs from the `10x-impl-review-ci` skill (which reviews against a `plan.md`); the requirements.md aligns with M5L3 (quality review on every PR, not plan-adherence review).

## Detailed Findings

### Scope 1 — Existing CI Setup

Two workflows exist at the following inspected paths:

- `.github/workflows/ci.yml` — triggers on `push` and `pull_request` to `dev` and `master`. Runs `python manage.py test monitor --verbosity=2` with a stub environment (`SECRET_KEY`, `DEBUG=True`, `DATABASE_URL=''`). Uses `actions/setup-python@v5` (Python 3.12), installs from `data-pulse/requirements.txt`. No review step, no label management.
- `.github/workflows/deploy.yml` — triggers on `push` to `master` only. Calls Render Deploy Hook via `curl`. Has no test or review step.

Neither workflow manages labels. Neither workflow has a `pull-requests: write` or `issues: write` permission. The `.github/actions/` directory does not exist (`ls .github/` returns only `workflows/`).

**What already exists:** working tests-on-CI step covering Django test suite.  
**What must be added:** a third workflow (`review.yml`), a composite action directory (`.github/actions/ai-reviewer/`), a built reviewer script (`dist/review.js`), and a `LLM_PROVIDER_API_KEY` repository secret.

### Scope 2 — Repo Structure for PR Review

Based on `context/map/repo-map.md` (window: 2026-10-18..2026-10-27, 17 commits):

The active branch is `dev`; the target branch for PRs is `master`. The most recently changed commit (`c74492c`) was "ci: deploy from master, CI on dev+master", indicating the CI workflows themselves are part of ongoing work.

The 4 files that appeared in the highest number of distinct commits during the inspected window are (from the repo-map buzz analysis):

| File | Mapped capability | Buzz type |
|---|---|---|
| `monitor/views.py` | C1–C7 (monolith) | high change volume (cross-cutting) |
| `monitor/services.py` | C2 check execution | risk zone (silent bug history) |
| `monitor/models.py` | P2 shared foundations | risk zone (Ca=4) |
| `monitor/tests.py` | all capabilities | 973 lines, growing |

A PR to master typically includes changes to 1–4 files in `monitor/`. Diff size is expected to be small-to-medium (feature-level). The reviewer action receives `git diff origin/$BASE_REF...HEAD` — this merge-base diff excludes any master changes made after the branch forked.

### Scope 3 — 10x-impl-review-ci Skill vs. M5L3 Templates

Two distinct review patterns are available in this repo. They serve different purposes:

**Pattern A: M5L3 composite-action quality review** (`.kiro/config-templates/`)
- Trigger workflow: `m5l3-review.yml.template` — triggers on `pull_request` to `master` (types: opened, synchronize, reopened, labeled). Posts PR comment + labels `ai-cr:passed` / `ai-cr:failed`. Re-runs on `ai-cr:review` label.
- Composite action: `m5l3-action.yml.template` — Node 24, runs `node dist/review.js`, reads diff from `DIFF_FILE`, PR title/body from env vars, prints JSON to stdout.
- Schema: `m5l2-review-schema.ts.template` — zod schema with exactly the 6 criteria from `requirements.md` (implementationCorrectness, idiomaticity, complexity, testRiskCoverage, documentation, securitySafety), plus `verdict: pass|fail` and `summary: string`. Also defines `SYSTEM_PROMPT` in Polish, matching the rubric in requirements.md.
- Output contract: JSON printed to stdout, read by the `Comment and label` step via inline `node -e` parsing.
- Gate step: `test "$VERDICT" = pass || exit 1`

**Pattern B: 10x-impl-review-ci skill** (`.kiro/skills/10x-impl-review-ci/`)
- Invoked via `claude-code-action` (Anthropic's GitHub Action), not a Node.js agent.
- Reviews PR diff against a `context/changes/<change-id>/plan.md` (plan-adherence review — 7 dimensions including Plan Adherence, Scope Discipline, Architecture).
- Triggers on `impl-review` label, not on every PR.
- Writes report to `context/changes/<change-id>/reviews/impl-review.md`, commits it back with `[skip ci]`.
- Requires `ANTHROPIC_API_KEY` secret.
- Also provides its own workflow template: `.kiro/skills/10x-impl-review-ci/references/workflow-template.yml`.

**Alignment with requirements.md:** requirements.md specifies the 6 M5L3 quality criteria, `pass/fail` verdict, PR comment with summary, `ai-cr:passed` / `ai-cr:failed` labels, and re-run on `ai-cr:review` label. This exactly matches Pattern A (M5L3). Pattern B adds plan-adherence review on top of quality review and is intended for separate use.

The change.md note "Uses 10x-impl-review-ci skill and composite action pattern" appears to loosely describe the composite action approach; the review criteria and side-effects in requirements.md belong entirely to the M5L3 pattern.

### Scope 4 — Template Files

All 4 template files are in `.kiro/config-templates/`:

| Template | Path | Purpose |
|---|---|---|
| `m5l3-review.yml.template` | `.kiro/config-templates/m5l3-review.yml.template` | Trigger workflow — copy to `.github/workflows/review.yml` |
| `m5l3-action.yml.template` | `.kiro/config-templates/m5l3-action.yml.template` | Composite action — copy to `.github/actions/ai-reviewer/action.yml` |
| `m5l2-review-schema.ts.template` | `.kiro/config-templates/m5l2-review-schema.ts.template` | TypeScript zod schema + SYSTEM_PROMPT — source for the reviewer agent |
| `m5l3-promptfooconfig.yaml.template` | `.kiro/config-templates/m5l3-promptfooconfig.yaml.template` | promptfoo eval config — optional, for evaluating reviewer quality |

The action template references `$GITHUB_ACTION_PATH/dist/review.js`. This file is **not present in the repo** and must be built. It is the Node.js agent that:
1. Reads the diff file path from `DIFF_FILE` env var.
2. Reads `PR_TITLE`, `PR_BODY`, `REVIEW_MODEL`, `LLM_PROVIDER_API_KEY` from env.
3. Calls the LLM with `SYSTEM_PROMPT` from the schema template and the diff as the user message.
4. Parses the structured output with `REVIEW_SCHEMA` (zod).
5. Writes valid JSON to stdout, matching the `Review` type.

The action template uses `REVIEW_MODEL: z-ai/glm-5.3` as the default and `LLM_PROVIDER_API_KEY` pointing to an OpenRouter-compatible provider. Alternatively, the Anthropic API can be used directly if an `ANTHROPIC_API_KEY` secret is preferred.

The promptfoo template (`m5l3-promptfooconfig.yaml.template`) references fixture diff files (`fixtures/react19-migration.diff`, `fixtures/sql-injection.diff`) that do not exist in the repo yet. This template is for optional quality evaluation of the reviewer and is not required for the workflow to function.

## Code References

- `.github/workflows/ci.yml:1-25` — full existing CI workflow; no review, no label perms
- `.github/workflows/deploy.yml:1-15` — deploy-only, no review
- `.kiro/config-templates/m5l3-review.yml.template:1-62` — complete trigger workflow template
- `.kiro/config-templates/m5l3-action.yml.template:1-53` — complete composite action template
- `.kiro/config-templates/m5l2-review-schema.ts.template:1-71` — zod schema + SYSTEM_PROMPT + REVIEW_JSON_SCHEMA
- `.kiro/skills/10x-impl-review-ci/references/workflow-template.yml:1-end` — plan-adherence CI workflow (Pattern B, not required for M5L3 quality review)
- `context/map/repo-map.md` — buzz analysis and file-level risk zones

## Architecture Insights

**Composite action pattern (M5L3):** The composite action lives in `.github/actions/ai-reviewer/` and is referenced locally by the trigger workflow (`uses: ./.github/actions/ai-reviewer`). The trigger workflow handles all GitHub API calls (comment, label, gate check) using `gh` CLI; the composite action is a pure "call LLM → return verdict + review file path" step. This separation means the reviewer agent has no GitHub permissions and cannot accidentally manipulate the PR.

**Secret strategy:** The action template uses `LLM_PROVIDER_API_KEY` (OpenRouter) with model `z-ai/glm-5.3`. For the DataPulse repo, the owner must add `LLM_PROVIDER_API_KEY` as a repository secret. Alternatively the agent can use `ANTHROPIC_API_KEY` directly — the schema and prompt are provider-agnostic; only the client call in `dist/review.js` needs to match.

**Trigger conditions:** `pull_request` on `master` with `types: [opened, synchronize, reopened, labeled]`. The `if: github.event.action != 'labeled' || github.event.label.name == 'ai-cr:review'` guard prevents every label change from rerunning, while still supporting on-demand re-review.

**Label lifecycle:** The `Comment and label` step creates both labels idempotently (`gh label create --force`) before assigning. It removes the opposite label and clears the `ai-cr:review` trigger label. This means labels accumulate at most one `ai-cr:passed` or `ai-cr:failed` per PR at any time.

**Missing artifact — dist/review.js:** The composite action's `Run agent` step does `node "$GITHUB_ACTION_PATH/dist/review.js"`. The source for this script is the schema template (which supplies `REVIEW_SCHEMA` and `SYSTEM_PROMPT`) but the actual HTTP call to the LLM provider must be written. Two implementation choices exist: (a) a minimal single-file Node.js script that calls the LLM API directly, or (b) a TypeScript project compiled to `dist/review.js` with `esbuild` or `ncc`. The template uses Node 24 with no dependency on `pnpm` / `npm install` before the agent step — so `dist/review.js` must be a self-contained bundle or a script using only Node built-ins + fetch.

**Concurrency guard:** The trigger workflow uses `concurrency: group: ai-review-${{ github.event.pull_request.number }}, cancel-in-progress: true`. This means only one review runs per PR at a time; a new push during review cancels the in-flight run. No queuing side-effects.

## Historical Context (from prior changes)

No prior changes related to CI/CD code review exist in `context/changes/` or `context/archive/`. The existing CI workflow was introduced in commit `c74492c` ("ci: deploy from master, CI on dev+master") — the most recent commit in the repo. The repo-map (`context/map/repo-map.md`) notes that `P1 fix% = 0%` — CI/deploy infrastructure has not required fixes in the inspected 9-day window, suggesting the existing workflows are stable.

## Related Research

- `context/map/repo-map.md` — buzz analysis and file-level risk zones; informs what files a PR reviewer will most commonly encounter

## Open Questions

1. **LLM provider choice:** The template defaults to `z-ai/glm-5.3` via OpenRouter. DataPulse already uses Anthropic (via Kiro and `10x-impl-review-ci` skill). Should `dist/review.js` target OpenRouter (`LLM_PROVIDER_API_KEY`) or Anthropic (`ANTHROPIC_API_KEY`)? This determines which secret to add and which API client to use in the agent code.

2. **dist/review.js implementation path:** Build approach for `dist/review.js` — single-file vanilla Node.js using `fetch` (no bundler, no transpile), or TypeScript + `esbuild`/`ncc` (closer to production quality, more setup). The template installs Node 24 before the agent step; `fetch` is available natively, so a minimal single-file implementation is viable.

3. **promptfoo evaluation:** The `m5l3-promptfooconfig.yaml.template` is optional (no fixture diffs exist). Include it in scope for this change or defer?

4. **Branch protection:** The gate step (`test "$VERDICT" = pass || exit 1`) creates a failing check. For it to block merges, the `AI Code Review` check must be added as a required status check in branch protection settings for `master`. This is a manual GitHub UI step outside the workflow itself.
