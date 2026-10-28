---
change_id: ci-cd-code-review
title: Agent code review in GitHub Actions CI — automated PR review on every pull request to master
status: implemented
created: 2026-10-28
updated: 2026-10-28
archived_at: null
---

## Notes

S-10 from roadmap M-03. Agent runs on every PR to master, reviews the diff against 6 criteria (correctness, idiom, complexity, test coverage, documentation, security), posts a comment with scores and verdict (pass/fail), and adds labels ai-cr:passed or ai-cr:failed.

Based on M5L3 from 10xDevs course. Uses 10x-impl-review-ci skill and composite action pattern.

Requirements source: .kiro/prompts/m5l3-requirements.md
