# CI/CD Agent Code Review — Plan Brief

> Full plan: `context/changes/ci-cd-code-review/plan.md`
> Research: `context/changes/ci-cd-code-review/research.md`

## What & Why

Add an automated agent-based code review to DataPulse's GitHub Actions CI. Every PR to `master` is evaluated against 6 quality criteria by a small LLM agent; the result is posted as a PR comment with scores and a verdict, and a label (`ai-cr:passed` / `ai-cr:failed`) is applied. This closes the gap between having tests in CI and having a lightweight code quality gate that catches idiom, complexity, and security issues before merge.

## Starting Point

DataPulse already has two GitHub Actions workflows: `ci.yml` (Django tests on push/PR) and `deploy.yml` (Render deploy on push to master). Neither manages labels or performs code review. The `.github/actions/` directory does not exist. Four M5L3 templates are available in `.kiro/config-templates/` and need only targeted changes to work with Anthropic instead of OpenRouter.

## Desired End State

Every PR to `master` automatically receives an AI review comment with 6 numeric scores (1–10) and a Markdown summary, plus a green `ai-cr:passed` or red `ai-cr:failed` label. The `AI Code Review` check fails on `fail` verdicts, and adding `ai-cr:review` to a PR triggers a fresh re-review on demand.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| LLM provider | Anthropic (`ANTHROPIC_API_KEY`) | Repo already uses Anthropic for other tooling; no extra provider secret needed | Plan |
| Model | `claude-3-5-haiku-20241022` | Cheapest + fastest Haiku; adequate for PR-size diffs | Plan |
| `dist/review.js` implementation | Vanilla Node.js, single file, native `fetch` | No bundler or build step keeps the action simple and fast; Node 24 is already installed by the composite action | Plan |
| Anthropic API method | Tool use with `tool_choice: {type:"tool",name:"submit_review"}` | Forced tool use is the only Anthropic path that enforces a JSON schema response | Research |
| Review criteria | All 6 from requirements.md | Full coverage of correctness, idiom, complexity, test coverage, docs, security | Requirements |
| Branch trigger | `pull_request` to `master` only | `master` is the merge target; `dev` runs tests via `ci.yml` | Research |
| promptfoo evaluation | Deferred | No fixture diffs exist; not required for the workflow to function | Plan |

## Scope

**In scope:**
- `.github/actions/ai-reviewer/dist/review.js` — single-file vanilla JS review agent
- `.github/actions/ai-reviewer/action.yml` — composite action (adapted from template)
- `.github/workflows/review.yml` — trigger workflow (adapted from template)
- Documentation of manual steps: repository secret + optional branch protection

**Out of scope:**
- TypeScript compilation or bundler (no `esbuild`, `ncc`, `tsup`)
- promptfoo evaluation config and fixture diffs
- Plan-adherence review (`10x-impl-review-ci` / Pattern B)
- Branch protection configuration (manual GitHub UI step)
- OpenRouter or any other LLM provider

## Architecture / Approach

```
PR opened/pushed to master
  └─ .github/workflows/review.yml  (trigger workflow)
        ├─ actions/checkout + git diff → $RUNNER_TEMP/pr.diff
        ├─ uses: ./.github/actions/ai-reviewer  (composite action)
        │     ├─ actions/setup-node@24
        │     └─ node dist/review.js  → $RUNNER_TEMP/ai-review.json
        │           reads: DIFF_FILE, PR_TITLE, PR_BODY, ANTHROPIC_API_KEY
        │           calls: Anthropic Messages API (tool use, forced schema)
        │           prints: JSON {scores×6, verdict, summary}
        ├─ Comment and label  (gh pr comment + gh pr edit)
        └─ Gate on verdict  (exit 1 if verdict != pass)
```

`dist/review.js` inlines `SYSTEM_PROMPT` and `REVIEW_JSON_SCHEMA` from the TypeScript schema template (translated to plain JS). No `npm install` step; no dependencies beyond Node built-ins and native `fetch`.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Review Agent | `dist/review.js` — Anthropic API call, JSON output | Anthropic tool-use response shape must be correctly parsed; smoke test with real key required |
| 2. Composite Action | `action.yml` — wires agent into GitHub Actions with correct env var name | Env var name mismatch (`ANTHROPIC_API_KEY` vs `LLM_PROVIDER_API_KEY`) would silently produce a 401 |
| 3. Trigger Workflow + Secrets | `review.yml` + manual secret setup | Workflow won't run until `ANTHROPIC_API_KEY` secret is added in repo settings |

**Prerequisites:** `ANTHROPIC_API_KEY` available for smoke-testing Phase 1 locally; repository admin access to add the secret in Phase 3.
**Estimated effort:** ~1 session across 3 sequential phases; each phase is a single file.

## Open Risks & Assumptions

- Anthropic's `claude-3-5-haiku-20241022` tool-use response format is assumed to match the contract shown in the plan's Phase 1 snippet; if the model is deprecated or the API changes, `dist/review.js` needs updating
- If the diff for a very large PR exceeds Anthropic's context window, the agent will return an API error — no truncation strategy is included in scope
- Adding `AI Code Review` as a required status check in branch protection is a manual step; until it's done, the failing check is visible but does not block merges

## Success Criteria (Summary)

- Every PR to `master` triggers the `AI Code Review` workflow and completes within ~60 seconds
- PR comment contains all 6 scores (numeric, 1–10) and a readable Markdown summary
- `ai-cr:passed` or `ai-cr:failed` label is applied; adding `ai-cr:review` re-triggers the review
