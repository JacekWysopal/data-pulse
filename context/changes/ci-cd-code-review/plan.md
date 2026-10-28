# CI/CD Agent Code Review Implementation Plan

## Overview

Add an agent-based code review workflow to DataPulse's GitHub Actions CI that runs automatically on every pull request to `master`. The review agent calls the Anthropic API (claude-3-5-haiku) to evaluate the PR diff against 6 quality criteria, posts a PR comment with scores and a Markdown summary, and assigns `ai-cr:passed` or `ai-cr:failed` labels. A failing verdict blocks the merge via a failing check.

The implementation follows the M5L3 composite action pattern: a trigger workflow (`.github/workflows/review.yml`) invokes a local composite action (`.github/actions/ai-reviewer/action.yml`), which runs a single-file vanilla Node.js agent (`dist/review.js`).

## Current State Analysis

Two workflows exist in `.github/workflows/`: `ci.yml` (tests on push/PR to dev+master) and `deploy.yml` (Render deploy on push to master). Neither manages labels or has review logic. The `.github/actions/` directory does not exist.

Four M5L3 templates are ready in `.kiro/config-templates/`: trigger workflow, composite action, TypeScript zod schema (with `SYSTEM_PROMPT` and `REVIEW_JSON_SCHEMA`), and a promptfoo eval config. The templates default to OpenRouter (`LLM_PROVIDER_API_KEY`, model `z-ai/glm-5.3`); this plan replaces those with `ANTHROPIC_API_KEY` and `claude-3-5-haiku-20241022`.

### Key Discoveries

- `.kiro/config-templates/m5l3-review.yml.template:1-62` — complete trigger workflow; only `secrets.LLM_PROVIDER_API_KEY` → `secrets.ANTHROPIC_API_KEY` needs changing
- `.kiro/config-templates/m5l3-action.yml.template:1-53` — composite action; `LLM_PROVIDER_API_KEY` env var and `z-ai/glm-5.3` default model need changing
- `.kiro/config-templates/m5l2-review-schema.ts.template` — defines `SYSTEM_PROMPT` (Polish) and `REVIEW_JSON_SCHEMA` (draft-07 JSON Schema); the vanilla JS agent must inline both as plain JS objects — no TypeScript or bundler
- Node 24 is installed by the composite action before running `dist/review.js`; native `fetch` is available, no `npm install` step exists in the composite action
- The Anthropic structured output mechanism to use is **tool use with forced tool choice** (`tool_choice: {type: "tool", name: "submit_review"}`), which is the only Anthropic API path that enforces a JSON schema contract matching `REVIEW_JSON_SCHEMA`
- `.github/workflows/ci.yml:1` — uses `actions/checkout@v4` (unpinned); the review workflow templates use pinned SHAs — follow the template's pinned style for new files

## Desired End State

After this plan is complete:
1. Every PR opened, synchronized, or reopened against `master` triggers the `AI Code Review` workflow.
2. The workflow posts a PR comment with 6 criterion scores and a Markdown summary.
3. The PR receives either `ai-cr:passed` (green) or `ai-cr:failed` (red).
4. The `Gate on verdict` step exits non-zero on `fail`, creating a failing check.
5. When `ai-cr:review` is added to a PR, the workflow re-runs.
6. Adding `AI Code Review` to branch protection required checks (manual GitHub UI step) turns the verdict into a hard merge gate.

**Verify end state:** Open a PR to master; within ~60 seconds a PR comment appears with 6 scores and verdict, labels are applied, and the check is visible in the PR status bar.

### Key Discoveries

- Composite action lives at `.github/actions/ai-reviewer/action.yml`; trigger workflow references it via `uses: ./.github/actions/ai-reviewer`
- `dist/review.js` path is relative to the composite action directory: `.github/actions/ai-reviewer/dist/review.js`
- Label creation (`gh label create --force`) is idempotent; the workflow creates both labels before assigning
- `concurrency: cancel-in-progress: true` ensures only one review runs per PR at a time

## What We're NOT Doing

- **No TypeScript compilation or bundler** — `dist/review.js` is a plain `.js` file committed directly; no `esbuild`, `ncc`, or `tsup` involved
- **No promptfoo evaluation** — `m5l3-promptfooconfig.yaml.template` and fixture diffs are deferred to a follow-up change
- **No plan-adherence review** — the `10x-impl-review-ci` skill (Pattern B) is a separate concern; this plan implements Pattern A (quality review) only
- **No branch protection configuration** — adding `AI Code Review` as a required status check is a manual GitHub UI step documented in Phase 3's manual criteria
- **No OpenRouter or other LLM provider** — only `ANTHROPIC_API_KEY` is needed

## Implementation Approach

Three sequential phases matching the dependency order:
1. Build `dist/review.js` (the agent that the composite action invokes — must exist before the action can be tested)
2. Create the composite action `action.yml` (wires the agent into GitHub Actions — must exist before the trigger workflow can use it)
3. Create the trigger workflow `review.yml` and document the secret + branch protection setup

All three new files are adaptations of existing templates with targeted changes. No existing workflow files are modified.

## Phase 1: Review Agent

### Overview

Create `.github/actions/ai-reviewer/dist/review.js` — a single-file vanilla Node.js script that reads the PR diff from `DIFF_FILE`, calls the Anthropic Messages API with forced tool use to obtain a structured 6-criterion review, and prints valid JSON to stdout.

### Changes Required:

#### 1. Review agent script

**File**: `.github/actions/ai-reviewer/dist/review.js`

**Intent**: Implement the agent that the composite action's `node "$GITHUB_ACTION_PATH/dist/review.js"` step runs. The script calls `POST https://api.anthropic.com/v1/messages` using native `fetch`, forces a structured response via tool use, validates that `verdict` is `pass` or `fail`, then writes the full JSON object to stdout. The composite action captures stdout to `$RUNNER_TEMP/ai-review.json`.

**Contract**:

Environment variables read (all provided by the composite action's `env:` block):
- `ANTHROPIC_API_KEY` — Anthropic API key
- `REVIEW_MODEL` — model ID (default: `claude-3-5-haiku-20241022`)
- `DIFF_FILE` — absolute path to the diff file on the runner
- `PR_TITLE` — PR title string
- `PR_BODY` — PR description string (may be empty)

Output (stdout): a single JSON object matching this shape (keys from the TypeScript schema at `.kiro/config-templates/m5l2-review-schema.ts.template`):
```json
{
  "implementationCorrectness": 7,
  "idiomaticity": 8,
  "complexity": 9,
  "testRiskCoverage": 6,
  "documentation": 7,
  "securitySafety": 9,
  "verdict": "pass",
  "summary": "..."
}
```

The Anthropic tool-use pattern that enforces this schema (non-obvious: must use `tool_choice` to force the model to call the tool rather than produce free text):

```js
const response = await fetch("https://api.anthropic.com/v1/messages", {
  method: "POST",
  headers: {
    "x-api-key": process.env.ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
  },
  body: JSON.stringify({
    model: process.env.REVIEW_MODEL || "claude-3-5-haiku-20241022",
    max_tokens: 1024,
    system: SYSTEM_PROMPT,
    messages: [{ role: "user", content: userMessage }],
    tools: [{ name: "submit_review", description: "Submit the structured code review", input_schema: REVIEW_JSON_SCHEMA }],
    tool_choice: { type: "tool", name: "submit_review" },
  }),
});
// Extract result from response.content[0].input (tool_use block)
```

The `SYSTEM_PROMPT` and `REVIEW_JSON_SCHEMA` constants must be inlined verbatim from `.kiro/config-templates/m5l2-review-schema.ts.template` (translated to plain JS — no `import`, no `z.toJSONSchema`; write out the JSON schema object directly).

The concrete draft-07 JSON Schema object to inline as `REVIEW_JSON_SCHEMA` (compiled from `z.toJSONSchema(REVIEW_SCHEMA, { target: "draft-07" })`):

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "implementationCorrectness": {
      "type": "number",
      "description": "Poprawność implementacji (skala 1-10). 1: logika jest błędna, pomija oczywiste przypadki brzegowe lub po cichu psuje istniejące zachowania. 10: poprawny na ścieżce głównej, w przypadkach brzegowych i w obsłudze błędów, bez regresji."
    },
    "idiomaticity": {
      "type": "number",
      "description": "Idiomatyczność (skala 1-10). 1: walczy z idiomami stacku i wzorcami repozytorium. 10: nie do odróżnienia od dobrze napisanego kodu wokół."
    },
    "complexity": {
      "type": "number",
      "description": "Złożoność (skala 1-10). 1: przekombinowane lub splątane, przypadkowa złożoność zasłania intencję. 10: najprostszy projekt, który w pełni rozwiązuje problem."
    },
    "testRiskCoverage": {
      "type": "number",
      "description": "Pokrycie testami proporcjonalne do ryzyka (skala 1-10). 1: ryzykowna logika bez testów albo testy, które nic nie sprawdzają. 10: najbardziej ryzykowne ścieżki są przetestowane celowo i dobrze."
    },
    "documentation": {
      "type": "number",
      "description": "Dokumentacja (skala 1-10). 1: brak komentarzy i dokumentacji tam, gdzie są potrzebne; intencję trzeba odtwarzać. 10: tyle dokumentacji, ile trzeba, by wyjaśnić \"dlaczego\", bez powtarzania oczywistości."
    },
    "securitySafety": {
      "type": "number",
      "description": "Bezpieczeństwo (skala 1-10). 1: podatność, wyciek sekretów lub niebezpieczne zaufanie do danych z zewnątrz. 10: wejście walidowane, sekrety obsłużone poprawnie, brak nowej powierzchni ataku."
    },
    "verdict": {
      "type": "string",
      "enum": ["pass", "fail"],
      "description": "Wiążący werdykt dla całej zmiany; czyta go bramka w CI"
    },
    "summary": {
      "type": "string",
      "description": "Podsumowanie w Markdown, gotowe jako komentarz do PR-a"
    }
  },
  "required": ["implementationCorrectness", "idiomaticity", "complexity", "testRiskCoverage", "documentation", "securitySafety", "verdict", "summary"],
  "additionalProperties": false
}
```

Exit codes: `0` on success, `1` on API error, invalid HTTP status, missing `ANTHROPIC_API_KEY`, or verdict not in `["pass", "fail"]`.

### Success Criteria:

#### Automated Verification:

- Script parses without error: `node --check .github/actions/ai-reviewer/dist/review.js`
- Live smoke test: set `ANTHROPIC_API_KEY`, `DIFF_FILE` (point at any small `.diff` file), `PR_TITLE="test"`, `PR_BODY=""` → `node .github/actions/ai-reviewer/dist/review.js` exits 0 and stdout is valid JSON with `verdict` in `["pass","fail"]`

#### Manual Verification:

- Inspect printed JSON: all 6 score fields present and numeric, `summary` is a non-empty string, `verdict` is `pass` or `fail`

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Composite Action

### Overview

Create `.github/actions/ai-reviewer/action.yml` by adapting `m5l3-action.yml.template` to use `ANTHROPIC_API_KEY` and `claude-3-5-haiku-20241022`. The composite action sets up Node 24, then invokes `dist/review.js`, extracts `verdict` and `review-file` as step outputs.

### Changes Required:

#### 1. Composite action YAML

**File**: `.github/actions/ai-reviewer/action.yml`

**Intent**: Adapt the template so that the `api-key` input description refers to Anthropic, the default model is `claude-3-5-haiku-20241022`, and the `Run agent` step passes `ANTHROPIC_API_KEY` (not `LLM_PROVIDER_API_KEY`) to the script.

**Contract**: All differences from `m5l3-action.yml.template`:

| Template value | Plan value |
|---|---|
| `description: LLM provider API key (e.g. OpenRouter)` | `description: Anthropic API key` |
| `default: z-ai/glm-5.3` | `default: claude-3-5-haiku-20241022` |
| `LLM_PROVIDER_API_KEY: ${{ inputs.api-key }}` | `ANTHROPIC_API_KEY: ${{ inputs.api-key }}` |

All other structure (inputs, outputs, Node 24 setup, `node "$GITHUB_ACTION_PATH/dist/review.js"`, stdout capture, verdict extraction) is copied verbatim from the template.

### Success Criteria:

#### Automated Verification:

- YAML syntax valid: `python3 -c "import yaml, sys; yaml.safe_load(open(sys.argv[1]))" .github/actions/ai-reviewer/action.yml`
- File exists at `.github/actions/ai-reviewer/action.yml`

#### Manual Verification:

- Confirm `action.yml` contains `ANTHROPIC_API_KEY` (not `LLM_PROVIDER_API_KEY`) and model default `claude-3-5-haiku-20241022`

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Trigger Workflow, Labels, and Secrets

### Overview

Create `.github/workflows/review.yml` by adapting `m5l3-review.yml.template` to use `secrets.ANTHROPIC_API_KEY`. Document the manual steps: adding the repository secret and (optionally) configuring branch protection. Verify the workflow file is syntactically valid and that GitHub Actions picks it up.

### Changes Required:

#### 1. Trigger workflow YAML

**File**: `.github/workflows/review.yml`

**Intent**: Adapt the template so the secret reference matches the repository secret name `ANTHROPIC_API_KEY`. All triggering logic, concurrency guard, comment/label/gate steps, and permissions are copied verbatim.

**Contract**: Differences from `m5l3-review.yml.template`:

| Template value | Plan value |
|---|---|
| `api-key: ${{ secrets.LLM_PROVIDER_API_KEY }}` | `api-key: ${{ secrets.ANTHROPIC_API_KEY }}` |
| Comment node command: emits only `r.verdict` + `r.summary` | Extend to render a Markdown table of all 6 criterion scores above the summary: `\| Criterion \| Score \|` with rows for implementationCorrectness, idiomaticity, complexity, testRiskCoverage, documentation, securitySafety |

All other structure preserved: `on.pull_request.branches: [master]`, `types: [opened, synchronize, reopened, labeled]`, concurrency group, `if: github.event.action != 'labeled' || github.event.label.name == 'ai-cr:review'` guard, the `Compute diff`, `Comment and label`, and `Gate on verdict` steps.

#### 2. Repository secret (manual)

**Intent**: The `ANTHROPIC_API_KEY` secret must exist in the GitHub repository settings before the workflow can call the Anthropic API.

**Contract**: Navigate to `Settings → Secrets and variables → Actions → New repository secret`. Name: `ANTHROPIC_API_KEY`. Value: your Anthropic API key. This is a one-time manual step not automatable from a workflow file.

### Success Criteria:

#### Automated Verification:

- YAML syntax valid: `python3 -c "import yaml, sys; yaml.safe_load(open(sys.argv[1]))" .github/workflows/review.yml`
- File exists at `.github/workflows/review.yml`

#### Manual Verification:

- `ANTHROPIC_API_KEY` repository secret added in GitHub Settings
- Open a PR to `master` (or push to an existing PR branch) → GitHub Actions tab shows `AI Code Review` workflow triggered within ~30 seconds
- Workflow run completes: PR comment appears with 6 scores and summary, `ai-cr:passed` or `ai-cr:failed` label is applied
- (Optional) Add `AI Code Review` as a required status check under `Settings → Branches → Branch protection rules` for `master` to enforce the merge gate

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful.

---

## Testing Strategy

### Automated Tests:

- `node --check` syntax check on `dist/review.js`
- YAML `yaml.safe_load` syntax checks on both `action.yml` and `review.yml`
- Live smoke test of `dist/review.js` with a real `ANTHROPIC_API_KEY` and a sample diff

### Manual Testing Steps:

1. Run `dist/review.js` locally with env vars set; inspect stdout JSON for all required fields
2. Push a branch and open a PR to `master`; verify workflow triggers and completes
3. Inspect the PR comment; verify scores are numeric and summary is readable
4. Verify `ai-cr:passed` or `ai-cr:failed` label applied; verify `ai-cr:review` re-triggers

## Performance Considerations

`claude-3-5-haiku-20241022` is the fastest and cheapest Haiku model on Anthropic's API. Typical review latency for a small-to-medium diff is 5–15 seconds. The `max_tokens: 1024` cap in `dist/review.js` constrains cost per run. The concurrency guard (`cancel-in-progress: true`) prevents stacking runs on rapid pushes.

## Migration Notes

No existing workflows are modified. The three new files are additive. The `ANTHROPIC_API_KEY` secret is already likely used by other tooling in this repo (Kiro, `10x-impl-review-ci`); check with the repo owner before creating it to avoid duplication.

## References

- Research: `context/changes/ci-cd-code-review/research.md`
- Requirements: `context/changes/ci-cd-code-review/requirements.md`
- Trigger workflow template: `.kiro/config-templates/m5l3-review.yml.template`
- Composite action template: `.kiro/config-templates/m5l3-action.yml.template`
- Schema + SYSTEM_PROMPT: `.kiro/config-templates/m5l2-review-schema.ts.template`
- Existing CI workflow: `.github/workflows/ci.yml:1-25`
- Existing deploy workflow: `.github/workflows/deploy.yml:1-15`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Review Agent

#### Automated

- [x] 1.1 Script parses without error: `node --check .github/actions/ai-reviewer/dist/review.js`
- [x] 1.2 Live smoke test: exits 0 and stdout is valid JSON with verdict in ["pass","fail"]

#### Manual

- [x] 1.3 Inspect printed JSON: all 6 score fields present and numeric, summary non-empty, verdict valid

### Phase 2: Composite Action

#### Automated

- [x] 2.1 YAML syntax valid: `python3 -c "import yaml, sys; yaml.safe_load(open(sys.argv[1]))" .github/actions/ai-reviewer/action.yml`
- [x] 2.2 File exists at `.github/actions/ai-reviewer/action.yml`

#### Manual

- [x] 2.3 Confirm `action.yml` contains `ANTHROPIC_API_KEY` and model default `claude-3-5-haiku-20241022`

### Phase 3: Trigger Workflow, Labels, and Secrets

#### Automated

- [x] 3.1 YAML syntax valid: `python3 -c "import yaml, sys; yaml.safe_load(open(sys.argv[1]))" .github/workflows/review.yml`
- [x] 3.2 File exists at `.github/workflows/review.yml`

#### Manual

- [ ] 3.3 `ANTHROPIC_API_KEY` repository secret added in GitHub Settings — **MANUAL STEP REQUIRED**: Navigate to `Settings → Secrets and variables → Actions → New repository secret`, Name: `ANTHROPIC_API_KEY`, Value: your Anthropic API key. This cannot be automated from a workflow file.
- [ ] 3.4 Open a PR to master — workflow triggers, comment posted with 6 criterion scores table, label applied
- [ ] 3.5 (Optional) `AI Code Review` added as required status check in branch protection for master
