# Evidence: people

**Humans in window:** 1 — Jacek Wysopal (jacekwysopal123@gmail.com), all 19 commits.  
**Agents:** Kiro AI (co-author on commits; counted as activity, not a person — per scan contract).  
**Baseline rule (false-signals §6):** with ≤3 humans, 100% concentration per capability is the baseline, not a finding. Bus-factor language is replaced with an ownership list.

---

## People per capability

| Capability | Human author | Topic groups from commits | Active period |
|---|---|---|---|
| C1 Rule management | Jacek Wysopal | rule forms, custom SQL rule, form validation, schedule field | Oct 18 – Oct 27 |
| C2 Check execution | Jacek Wysopal | check dispatcher, run_scheduled command, per-rule run, fix recursive call | Oct 18 – Oct 27 |
| C3 Connection management | Jacek Wysopal | Connection model, CRUD views, per-rule assignment, migration 0002 | Oct 26 – Oct 27 |
| C4 Schema introspection | Jacek Wysopal | AJAX schema API, rule builder table/column browser | Oct 27 |
| C5 Dashboard & filters | Jacek Wysopal | KPI counts, dashboard filters with URL persistence, dark UI redesign | Oct 18 – Oct 27 |
| C6 History & reporting | Jacek Wysopal | rule_history view restore, history template | Oct 27 |
| C7 Auth | Jacek Wysopal | login_required decorator, login/logout views, favicon | Oct 25 – Oct 27 |
| P1 Platform & infra | Jacek Wysopal | CI workflow, deploy pipeline, render.yaml, Render deploy | Oct 18 – Oct 27 |
| P2 Shared foundations | Jacek Wysopal | initial models, all 4 migrations, settings, base template | Oct 18 – Oct 27 |
| P3 Docs & planning | Jacek Wysopal | PRD, roadmap, change folders, AGENTS.md | Oct 27 |

*[evidence — derived from git log --format with paths mapped to capabilities.tsv]*

---

## Concentration

Solo project: Jacek Wysopal is the sole human author of all commits across all capabilities.  
Concentration is the baseline, not a risk signal — per false-signals §6.  
No capability has ever been touched by a second human.

*[evidence — `git log --format="%ae" | sort -u` returned exactly one email]*

---

## Agent co-authorship

The scan contract notes all 17 non-init commits are "agent-authored (Kiro AI)" with jwysopal@novomatic-tech.com as the co-author identity; the human (jacekwysopal123@gmail.com) steered every change.  
Agent share per capability: 100% (all commits in window are Kiro-assisted).  
This is context only — it does not change ownership; Jacek Wysopal directed every change.

*[inference — scan contract states "agent-authored: all 17 commits (Kiro AI agent)" and distinguishes human steering]*

---

## Documentation coverage per capability

| Capability | context/changes entry | context/foundation coverage | Test classes in tests.py | Assessment |
|---|---|---|---|---|
| C1 Rule management | custom-sql-rule, rule-builder-ui, s01-smoke-test | prd.md, roadmap.md | RuleModelTest, RuleFormTest, RuleCRUDViewTest | good — PRD + change docs + tests |
| C2 Check execution | s01-smoke-test, custom-sql-rule | prd.md | CheckVolumeFreshnessTest, CheckCustomSQLTest, RunAllChecksTest, RunSingleRuleTest, RunScheduledCommandTest | good — domain logic heavily tested |
| C3 Connection management | s03-connection-management, connection-badge | prd.md | ConnectionModelTest, ConnectionFormTest, ConnectionCRUDViewTest | good — change doc + tests |
| C4 Schema introspection | schema-introspection | prd.md | SchemaAPITest | adequate — one change doc + tests |
| C5 Dashboard & filters | dashboard-filters, post-mvp-ux | prd.md, shape-notes.md | DashboardViewTest | adequate — tests cover view; no UI spec |
| C6 History & reporting | s02-rule-history | prd.md | no dedicated history test class (partial in DashboardViewTest) | sparse — no standalone test class |
| C7 Auth | (no dedicated change doc) | AGENTS.md (hard rules), prd.md | AuthRedirectTest | sparse — only redirect tests; no dedicated change doc |
| P1 Platform & infra | deploy-pipeline | infrastructure.md, tech-stack.md | (no infra tests) | adequate for docs; zero automated tests |
| P2 Shared foundations | bootstrap-verification | tech-stack.md, AGENTS.md | CheckRunModelTest | partial — migration docs only in code |
| P3 Docs & planning | repo-map | roadmap.md, prd.md | n/a | covered — it is itself the docs layer |

*[evidence for test classes — grep on monitor/tests.py; evidence for context/ — ls on context/changes/ and context/foundation/; inference for coverage gaps]*

---

## Unknowns

- **[unknown]** Whether Jacek Wysopal remains the active maintainer post-Oct 27 (no commits after the git window).
- **[unknown]** C6 (rule history): only partially tested via DashboardViewTest; no standalone history test class exists. Intended coverage level unknown.
- **[unknown]** C7 (auth): no dedicated change doc; the auth flow was added implicitly with the seed/login commits. Full intended auth behaviour (password policy, session timeout) undocumented.
- **[unknown]** P1 (infra): no automated infra tests; deploy pipeline health relies on Render logs, not code.
- **[unknown]** Whether any external stakeholder or second developer is planned (roadmap does not mention team expansion).

---

## Implications

- **Before changing C2 (check execution):** read monitor/services.py change history; the recursive-call fix (commit 719289c) is a trap — the dispatcher was already broken once after a refactor.
- **Before changing C3 (connections):** review s03-connection-management change.md; the encrypted URL pattern is the only secure path — AGENTS.md hard rule.
- **Before changing C1 (rules) or C4 (schema):** read schema-introspection and rule-builder-ui change folders; C4 feeds C1's form UX.
- **Before touching auth (C7):** no change doc exists; rely on AGENTS.md hard rules and AuthRedirectTest as the only spec.
- **Before deploy/infra changes (P1):** read deploy-pipeline plan.md and reviews/; it has the most complete planning artefact in the repo.

*[inference — from commit subjects and change folder inventory]*

---

## Commands run

```
read  context/map/.work/git-log.txt
read  context/map/.work/capabilities.tsv
read  context/map/.work/scan-contract.md
read  .kiro/skills/10x-repo-map/references/agent-people.md
read  .kiro/skills/10x-repo-map/references/false-signals.md
read  AGENTS.md
ls    context/foundation/
ls    context/changes/
grep  "class.*Test" monitor/tests.py
grep  "def test.*schema|connection|view|dashboard|history|auth|login" monitor/tests.py
git log --format="%ae" | sort -u
```
