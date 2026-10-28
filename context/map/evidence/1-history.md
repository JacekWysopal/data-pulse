# Evidence: history

**Window:** 2026-10-18..2026-10-28 (9 days, HEAD = 708cbc03)
**Buckets:** week — Week 1: Oct 18-24; Week 2: Oct 25-28
**Commits in window:** 19 total; **counted:** 17 (2 noise-filtered: "test" 5faf9aba, "init: README" 7f7c465d)
**Excluded noise:** ui-proposals/ (deleted), static/img/ (binary), .venv/, staticfiles/, uv.lock
**Author split:** all 17 counted commits attributed to Jacek Wysopal / Kiro AI agent (solo project — agent-authored share per contract)
**Counting rule applied:** file touching N capabilities adds 1 commit to each; co-change drops commits touching >5 of 10 caps

---

## Activity per capability

| Capability | Commits | Fix commits | Fix% | Top files (commit count) |
|---|---|---|---|---|
| C1 Rule management | 12 | 2 | 17% | rule_form.html(8), views.py(8), forms.py(5) |
| C2 Check execution | 11 | 3 | 27% | views.py(8), services.py(7), urls.py(4) |
| C3 Connection management | 11 | 2 | 18% | views.py(8), urls.py(4), connection_list.html(4) |
| C4 Schema introspection | 11 | 3 | 27% | views.py(8), services.py(7), urls.py(4) |
| C5 Dashboard & filters | 12 | 2 | 17% | dashboard.html(9), views.py(8) |
| C6 History & reporting | 10 | 2 | 20% | views.py(8), rule_history.html(5) |
| C7 Auth | 9 | 2 | 22% | views.py(8), login.html(5) |
| P1 Platform & infra | 7 | 0 | 0% | settings.py(5), render.yaml(4) |
| P2 Shared foundations | 11 | 2 | 18% | base.html(8), models.py(5) |
| P3 Docs & planning | 3 | 0 | 0% | roadmap.md(2) |

> **Tag: evidence** — commit counts derived directly from git-log.txt with noise/exclusion filters from scan contract.
>
> **Unmapped share:** 3 files not in capabilities.tsv (monitor/__init__.py, monitor/admin.py, monitor/apps.py), all from init commit e3bd6ea3; negligible (boilerplate). Tag: **evidence**
>
> **High apparent commit counts (C1–C5) are inflated by monitor/views.py** (Django monolith, 8 commits, maps to 7 capabilities). Any commit touching views.py counts toward C1–C7 simultaneously. Tag: **inference — mechanical signal** (see below)

---

## Top files by commit frequency

| Rank | File | Commits | Capabilities |
|---|---|---|---|
| 1 | templates/monitor/dashboard.html | 9 | C5 |
| 2 | monitor/views.py | 8 | C1, C2, C3, C4, C5, C6, C7 |
| 3 | templates/monitor/rule_form.html | 8 | C1 |
| 4 | templates/base.html | 8 | P2 |
| 5 | monitor/services.py | 7 | C2, C4 |

> **Freshness (git cat-file -e HEAD):** all 5 files exist at HEAD. Tag: **evidence**
>
> **monitor/views.py is a hub file** — single Django views module handling all 7 product capabilities. It is a fan-in by design (Django monolith pattern), not a fragile cross-cutting dependency. Applies false-signal rule 2 (config written as code) and rule 4 (shared cause). Tag: **inference**

---

## Trend (weekly buckets)

| Capability | Week 1 (Oct 18-24) | Week 2 (Oct 25-28) | Label |
|---|---|---|---|
| C1 | 1 | 11 | rising — active build |
| C2 | 1 | 10 | rising — active build |
| C3 | 1 | 10 | rising — active build |
| C4 | 1 | 10 | rising — active build |
| C5 | 1 | 11 | rising — active build |
| C6 | 1 | 9 | rising — active build |
| C7 | 1 | 8 | rising — active build |
| P1 | 1 | 6 | rising |
| P2 | 1 | 10 | rising — active build |
| P3 | 0 | 3 | rising (docs burst) |

Week 1 = 1 commit (init e3bd6ea3, added project skeleton to all caps).
Week 2 = 16 commits across 4 days: Oct 25 (4), Oct 26 (2), Oct 27 (9), Oct 28 (1).
Oct 27 spike (9 commits): S-03 through S-08 feature sprint + 3 fixes same day.

> All caps labelled **rising** — 9-day window is a single active build sprint; no fading or seasonal patterns observable. Tag: **evidence** (commit dates); **inference** (label — window too short for pattern analysis)

---

## Fix pressure

**Heuristic:** commit subject matches regex `\b(fix|bug|hotfix|revert|regression|broken|incident)\b`

3 commits match:

| SHA | Subject | Primary capability | Spillover |
|---|---|---|---|
| 719289cb | fix: _check_rule dispatcher — broken recursive call after refactor | C2 (services.py logic bug) | C4 same file |
| bb59e02e | fix: migration 0002 field name, seed schema update, remove run flash msg, tab title | P2 (migration) + C2 (seed) | C1–C7 via views.py + templates (cosmetic changes bundled in same commit) |
| 05554428 | fix: restore rule_history view, add favicon | C6 (rule_history view) | C1–C7 via views.py + C7/P2 via login/base (favicon cosmetic) |

**False-signal rule 12 (spillover from big commit):**
bb59e02e and 05554428 both inflate fix counts for C1–C7 because views.py is a monolith.
True primary failures: P2 migration schema (bb59e02e) and C6 view regression (05554428).
Attributing purely by file produces fix% of 17–27% across C1–C7; corrected primary fix% is: C2=1, C6=1, P2=1.

**No reverts in window.** Tag: **evidence** (subjects + files); **inference** (primary vs spillover attribution)

---

## Co-change between capabilities

**Drop rule applied:** commits touching >5 of 10 caps excluded (bb59e02e and 05554428 excluded — they each touch 8 caps).
14 commits remain eligible.

| Pair | Support | Confidence | Shared commits | Signal quality |
|---|---|---|---|---|
| (C1, C5) | 2 | 17% | 009ba369, 9516bfda | mechanical — both UI campaign commits |
| (C1, C6) | 2 | 20% | 009ba369, 9516bfda | mechanical — both UI campaign |
| (C5, C6) | 2 | 20% | 009ba369, 9516bfda | mechanical — both UI campaign |
| (C5, P2) | 2 | 18% | 009ba369, 9516bfda | mechanical — base.html in same UI campaign |
| (C1, P2) | 2 | 18% | 009ba369, 9516bfda | mechanical — same |
| (C6, P2) | 2 | 20% | 009ba369, 9516bfda | mechanical — same |
| (P1, P2) | 2 | 29% | 009ba369, 4ff92e20 | weak — settings+render updated on UI days |
| (C2, C4) | 1 | 9% | 719289cb | real — services.py handles both |

All support-2 pairs come from only 2 commits (009ba369 "Steel Dark theme", 9516bfda "navbar redesign") — a single UI campaign touching templates across caps. **False-signal rule 4 (shared cause):** demoted from coupling signal to campaign correlation.

**Strongest real signal:** C2 ↔ C4 (services.py shared file; check execution and schema introspection co-locate in the same module). Tag: **inference**

---

## Mechanical signals demoted

| Signal | Reason demoted | Rule |
|---|---|---|
| C1–C7 all show fix% 17–27% | Two of three fix commits are omnibus changes touching views.py (monolith); true fix targets are C2, C6, P2 | Rule 12 |
| All C1–C7 commit counts inflated | views.py maps to all 7 product caps; every commit touching it bumps all 7 | Rule 2, Rule 4 |
| C1/C5/C6/P2 co-change pairs | Driven by 2 UI campaign commits (theme + navbar); templates change together during visual sprints, not due to hidden coupling | Rule 4, Rule 8 |
| P3 (Docs) count = 3 | Two are docs commits (3b6d7fd6, 708cbc03) about context files, not code activity | Rule 8 |

---

## Unknowns

- **monitor/views.py granularity:** The TSV assigns views.py to all 7 caps, but the view functions inside may not be equally distributed; we do not know per-function commit attribution without blame analysis. Tag: **unknown**
- **C2 ↔ C4 coupling depth:** services.py holds both check execution and schema introspection; it is unknown whether these are cleanly separable modules or deeply intertwined. Tag: **unknown**
- **P1 fix% = 0%** despite CI/deploy config activity: either infra worked first-time or fixes were folded into feature commits. Cannot confirm from subjects alone. Tag: **unknown**
- **No frontend twin drift detectable:** single-file monolith views.py prevents detecting backend model changes without matching template updates (false-signal rule 3 inverse — guard absent). Tag: **unknown**

---

## Commands run

```
git -c core.quotepath=off log --no-merges --format=... --after="2026-10-17"   (verify commit list)
git -c core.quotepath=off cat-file -e HEAD:<path>                              (freshness check: 5 hot files)
python analyze_history.py                                                       (capability mapping, counts, co-change)
```
