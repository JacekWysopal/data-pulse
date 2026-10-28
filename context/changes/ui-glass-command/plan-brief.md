# Plan Brief: ui-glass-command

**Full plan:** `context/changes/ui-glass-command/plan.md`  
**Change:** Replace Steel Dark theme with Glass Command — glassmorphism, ambient orbs, collapsible sidebar, OK = green.  
**Date:** 2026-10-28

---

## Problem

The current UI uses a Steel Dark theme with solid card backgrounds, a cyan `--ok` colour, and a fixed 220 px sidebar. The new Glass Command design calls for glassmorphism cards with `backdrop-filter`, ambient floating orb divs, a wider collapsible sidebar (240 px ↔ 60 px), and `--ok` = `#22c55e` (Tailwind green-500) throughout. A complete visual reference exists in `ui-proposals/proposal-ab-glass-command.html`.

---

## Starting Point

- `templates/base.html`: defines the full design system (`:root` tokens, sidebar, topbar, buttons, badges, table). 8 monitor templates extend it.
- `templates/monitor/dashboard.html`: overrides KPI cards and table in `{% block extra_head %}`.
- `templates/login.html` and `templates/signup.html`: standalone, duplicate their own `:root` CSS.
- `ui-proposals/proposal-ab-glass-command.html`: single-file HTML prototype — the authoritative reference for all visual decisions.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| OK colour | `#22c55e` (green-500) | Explicit requirement in change.md; proposal default cyan `#22d3ee` rejected |
| Sidebar width | `240px` expanded / `60px` collapsed | Matches proposal exactly |
| Ambient background | Three `.orb` divs replacing `body::before` pseudo | Proposal approach; divs stack correctly under sidebar+main in the flex layout |
| Trend badges | Omitted | No view context provides trend deltas; no backend changes in scope |
| localStorage key | Keep `dp_nav_collapsed` | Avoids resetting users' saved collapse state |
| Tooltip offset | `calc(var(--nav-collapsed) + 4px)` | Positions tooltip just outside sidebar edge after width token change |
| Auth pages (login/signup) | Ambient background upgrade only | Not extending base.html; structural glass card change is out of scope |
| Cleanup | Delete `ui-proposals/` in Phase 4 | No template or code references the folder at runtime |

---

## Phases

| # | Phase | Files | Estimated effort | Prerequisites |
|---|---|---|---|---|
| 1 | base.html — tokens, orbs, sidebar | `templates/base.html` | ~1 hr | none |
| 2 | dashboard.html — KPI cards, table | `templates/monitor/dashboard.html` | ~1 hr | Phase 1 (tokens must be set) |
| 3 | Secondary templates + auth pages | `connection_list.html`, `rule_form.html`, `schedule_dashboard.html`, `login.html`, `signup.html` | ~45 min | Phase 1 |
| 4 | Cleanup | `ui-proposals/` folder | ~5 min | Phase 2 + 3 complete |

---

## What We're NOT Doing

- No backend/view changes — no trend data wired up.
- No changes to `connection_form.html`, `rule_confirm_delete.html`, `connection_confirm_delete.html`, `rule_history.html` beyond inherited token updates.
- No changes to `registration/` password reset templates.
- No new JavaScript — collapse logic is unchanged.

---

## References

- Proposal: `ui-proposals/proposal-ab-glass-command.html`
- Research: `context/changes/ui-glass-command/research.md`
- Change: `context/changes/ui-glass-command/change.md`
