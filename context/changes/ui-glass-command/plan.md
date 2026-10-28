# Plan: ui-glass-command — Glass Command UI Redesign

**Change ID:** ui-glass-command  
**Status:** planned  
**Created:** 2026-10-28  
**Source:** `context/changes/ui-glass-command/change.md`  
**Research:** `context/changes/ui-glass-command/research.md`  
**Proposal reference:** `ui-proposals/proposal-ab-glass-command.html` (deleted in Phase 4)

---

## Overview

Replace the current Steel Dark theme with the Glass Command design system: glassmorphism cards, ambient orbs, collapsible sidebar (240 px ↔ 60 px), KPI cards with glow lines, and consistent OK = green `#22c55e` across all templates. Four phases, each narrowly scoped to one concern and independently verifiable.

---

## What We're NOT Doing

- No backend changes — no new view context variables for trend badges; KPI trend pills are omitted from the build.
- No login/signup glass card redesign — only the ambient background is updated.
- No new pages, routes, or data model changes.
- No changes to `registration/` password-reset templates (they inherit no base.html tokens).

---

## Phase 1: base.html — Design System, Tokens, Orbs, Sidebar

### Goal

Establish the Glass Command design system foundation. All 8 child templates automatically inherit the updated tokens and sidebar chrome.

### Changes Required

#### 1.1 Update `:root` CSS tokens

**Intent:** Replace Steel Dark colour values with Glass Command palette. The `--ok` token is the most visible change (cyan → green); sidebar width tokens increase by 20 px expanded, decrease by 4 px collapsed.

**Contract:**

| Token | Old | New |
|---|---|---|
| `--bg-base` | `#0a0a0f` | `#03050e` |
| `--bg-surface` | `#111118` | `#07091a` |
| `--bg-card` | `#16161f` | `rgba(255,255,255,0.025)` |
| `--bg-card-hover` | `#1c1c28` | `rgba(255,255,255,0.04)` |
| `--ok` | `#34d399` | `#22c55e` |
| `--ok-dim` | `rgba(52,211,153,0.12)` | `rgba(34,197,94,0.12)` |
| `--ok-glow` | `rgba(52,211,153,0.3)` | `rgba(34,197,94,0.3)` |
| `--nav-width` | `220px` | `240px` |
| `--nav-collapsed` | `64px` | `60px` |
| Add `--card-solid` | — | `#0c0f1f` |
| Add `--transition` | — | `0.22s cubic-bezier(0.4,0,0.2,1)` |

#### 1.2 Replace `body::before` ambient glow with orb divs

**Intent:** The proposal uses three fixed-position blur divs (`.orb`) instead of a CSS pseudo-element. This allows the orbs to render in the stacking context correctly beneath all sidebar and main content.

**Contract:** Remove the `body::before` CSS rule. Add HTML immediately after `<body id="dp-body">`:
```html
<div class="orb o1"></div>
<div class="orb o2"></div>
<div class="orb o3"></div>
```
And add the corresponding CSS:
```css
.orb { position: fixed; border-radius: 50%; filter: blur(90px); pointer-events: none; z-index: 0; }
.o1 { width: 600px; height: 600px; background: rgba(129,140,248,0.07); top: -150px; left: -100px; }
.o2 { width: 500px; height: 500px; background: rgba(168,85,247,0.05); bottom: -100px; right: -100px; }
.o3 { width: 350px; height: 350px; background: rgba(34,211,238,0.04); top: 50%; left: 50%; transform: translate(-50%,-50%); }
```

#### 1.3 Glassmorphism sidebar

**Intent:** The sidebar must use a frosted-glass background so orbs bleed through it.

**Contract:** Change `.dp-sidebar` background from `var(--bg-surface)` to `rgba(7,9,26,0.85)` with `backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px);`.

#### 1.4 Fix sidebar active indicator position

**Intent:** The proposal positions the active indicator outside the nav-item's left edge, clipped by `overflow: hidden` on the sidebar. The current implementation uses `left: 0` which is visible inside the item.

**Contract:** Change `.dp-nav-item.active::before` from `left: 0; top: 20%; bottom: 20%; width: 2px` to `left: -8px; top: 50%; transform: translateY(-50%); width: 3px; height: 18px`.

#### 1.5 Fix tooltip left offset

**Intent:** After reducing `--nav-collapsed` to `60px`, the current tooltip formula `left: calc(var(--nav-collapsed) - 4px)` produces `56px`, clipping the tooltip into the sidebar. The proposal positions tooltips just past the sidebar edge.

**Contract:** Change `.dp-sidebar.collapsed .dp-nav-item[data-tip]:hover::after` left from `calc(var(--nav-collapsed) - 4px)` to `calc(var(--nav-collapsed) + 4px)`.

### Success Criteria

- Automated:
  - All 8 child templates render without missing token warnings in browser dev tools
  - `--ok` resolves to `#22c55e` in computed styles of `.dp-badge-ok`
  - Sidebar collapses to 60 px and expands to 240 px
  - Orb divs are present in DOM and have `filter: blur(90px)`
  - Tooltip appears at correct position when sidebar is collapsed (visual check)
- Manual:
  - Side-by-side comparison of proposal vs. implementation: sidebar chrome visually matches
  - `localStorage.getItem('dp_nav_collapsed')` persists across page reload

---

## Phase 2: dashboard.html — KPI Cards and Table

### Goal

Implement glassmorphism KPI cards with inner glow orbs, bottom gradient lines, and the updated table hover effects. The `--ok` token update from Phase 1 automatically corrects the OK badge in the table; Phase 2 adds the card-level glassmorphism and icon styling.

### Changes Required

#### 2.1 KPI card glassmorphism

**Intent:** Replace solid-background KPI cards with glassmorphism cards that match the proposal's inner glow and bottom border line.

**Contract:** In the `{% block extra_head %}` style block of `dashboard.html`:

- `.kpi-card`: add `backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);`
- Add `.kpi-glow` class: `position: absolute; width: 100px; height: 100px; border-radius: 50%; filter: blur(35px); top: -20px; right: -20px; opacity: 0.18;`
- Change `.kpi-card::after` to a shimmer overlay: `inset: 0; background: linear-gradient(135deg, rgba(255,255,255,0.03) 0%, transparent 60%); pointer-events: none; border-radius: inherit;` (replace the current gradient bottom line `::after`).
- Add `.kpi-bar` class (replaces `.kpi-bar-bg`/`.kpi-bar-fill`): `position: absolute; bottom: 0; left: 0; right: 0; height: 2px; border-radius: 0 0 16px 16px;`

#### 2.2 KPI card HTML — add glow div and bar, update OK colour references

**Intent:** Each KPI card needs the inner glow element and the gradient bottom line. The OK card uses `#22c55e` (green) not `#22d3ee` (cyan) from the proposal.

**Contract:** For each of the four KPI cards in the Django template:
- Add `<div class="kpi-glow" style="background:var(--ok|--fail|--error|--accent)"></div>` as first child inside `.kpi-card`.
- Replace the current `.kpi-bar-bg` + `.kpi-bar-fill` markup with a single `<div class="kpi-bar" style="background:linear-gradient(...)"></div>`.
- OK card icon SVG stroke: change `#34d399` → `#22c55e`.

#### 2.3 Table row hover glow — OK row uses green

**Intent:** `tr.row-ok:hover .rule-link-dot` should glow green not teal.

**Contract:** `tr.row-ok:hover .rule-link-dot` — `box-shadow` uses `var(--ok-glow)` which after Phase 1 resolves to `rgba(34,197,94,0.3)`. No template change needed if CSS still uses the token; verify it does. If any hardcoded `#34d399` or `rgba(52,211,153,...)` exists in `dashboard.html`, replace with the token reference.

### Success Criteria

- Automated:
  - OK KPI card has `.kpi-glow` div in DOM
  - OK KPI card computed `border-color` is `rgba(34,197,94,...)` derived from new `--ok`
  - Table status dot on `row-ok` hover glows in green, not teal (computed box-shadow)
- Manual:
  - KPI cards side-by-side with proposal: glow orbs and bottom gradient lines visible
  - Hover card lifts with `translateY(-2px)` and green/red/amber glow shadow

---

## Phase 3: Secondary Templates — Consistent Glass Style

### Goal

Apply the glassmorphism card style and OK-green corrections to `connection_list.html`, `rule_form.html`, `schedule_dashboard.html`, `login.html`, and `signup.html`. These templates already use base tokens and will inherit most of Phase 1's changes; Phase 3 adds card `backdrop-filter` and updates the standalone auth pages.

### Changes Required

#### 3.1 connection_list.html — glass cards

**Intent:** `.conn-card` and `.provider-card` already use `var(--bg-card)` which becomes glassmorphic after Phase 1. Add `backdrop-filter` to both so the frosted glass effect renders properly.

**Contract:** Add `backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);` to `.conn-card` and `.provider-card` CSS rules.

#### 3.2 rule_form.html — glass form card

**Intent:** `.form-card` uses `var(--bg-card)`. Add backdrop blur.

**Contract:** Add `backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);` to `.form-card`.

#### 3.3 schedule_dashboard.html — no structural changes needed

**Intent:** This template has minimal custom CSS (only `.next-run-soon`, `.sched-count-badge`, `.page-title-row`, `.empty-state`). All base tokens cascade from Phase 1. No additional changes required.

#### 3.4 login.html — Glass Command ambient background

**Intent:** The login page is standalone (does not extend base.html). Its ambient background should be upgraded to match the Glass Command aesthetic with a richer radial gradient, consistent with the proposal.

**Contract:** Replace the `body::before` radial gradient in `login.html`:
- Before: two indigo ellipses at 5%/10% and 95%/90%.
- After: three gradients — top-center indigo (stronger: 0.15), bottom-left purple (0.07), plus a subtle violet at bottom-right (matching proposal palette).

Also update the `--ok` token definition in login.html's `:root` to `#22c55e` for consistency (even though it's not currently used, it is a design system token).

#### 3.5 signup.html — same ambient background update as login.html

**Intent:** signup.html duplicates login.html's CSS. Apply the identical ambient background change.

### Success Criteria

- Automated:
  - `.conn-card` and `.form-card` have `backdrop-filter: blur(12px)` in computed styles
  - login.html and signup.html load without console errors
- Manual:
  - Connection list cards have visible frosted glass effect against orb background
  - Rule form card has visible frosted glass effect
  - Login and signup pages have richer ambient glow background

---

## Phase 4: Cleanup — Delete ui-proposals/

### Goal

Remove the `ui-proposals/` folder and its single file `proposal-ab-glass-command.html` now that implementation is complete.

### Changes Required

#### 4.1 Delete ui-proposals/ folder

**Intent:** The proposal HTML served as the visual reference during implementation. It is not a deployable asset and should not remain in the working tree post-implementation.

**Contract:** Delete `ui-proposals/proposal-ab-glass-command.html` and the now-empty `ui-proposals/` directory.

### Success Criteria

- Automated:
  - `ui-proposals/` directory no longer exists in the file tree
  - No Python/Django import or `{% static %}` reference points to `ui-proposals/`
- Manual:
  - Confirm no 404s from any template referencing `ui-proposals/`

---

## Progress

### Phase 1: base.html — Design system, tokens, orbs, sidebar
#### Automated
- [x] 1.1 `--ok` resolves to `#22c55e` in computed styles
- [x] 1.1 Sidebar width tokens: `--nav-width: 240px`, `--nav-collapsed: 60px`
- [x] 1.2 Three `.orb` divs present in DOM
- [x] 1.3 `.dp-sidebar` has `backdrop-filter: blur(24px)`
- [x] 1.5 Collapsed tooltip left position is `calc(var(--nav-collapsed) + 4px)`
#### Manual
- [x] 1.M1 Sidebar chrome matches proposal side-by-side
- [x] 1.M2 Collapse state persists across reload via `dp_nav_collapsed` key

### Phase 2: dashboard.html — KPI cards and table
#### Automated
- [x] 2.1 `.kpi-glow` div present inside each KPI card
- [x] 2.2 OK KPI card border-color derived from `rgba(34,197,94,...)`
- [x] 2.3 No hardcoded `#34d399` or `rgba(52,211,153,...)` in dashboard.html
#### Manual
- [x] 2.M1 KPI card glow orbs and bottom gradient lines visible
- [x] 2.M2 OK card shows green, not teal

### Phase 3: Secondary templates — consistent glass style
#### Automated
- [x] 3.1 `.conn-card` computed style has `backdrop-filter: blur(12px)`
- [x] 3.2 `.form-card` computed style has `backdrop-filter: blur(12px)`
- [x] 3.4 login.html loads without console errors after ambient update
#### Manual
- [x] 3.M1 Connection list and rule form cards show frosted glass effect
- [x] 3.M2 Login page ambient glow is richer/deeper

### Phase 4: Cleanup
#### Automated
- [x] 4.1 `ui-proposals/` directory does not exist
- [x] 4.1 No template references `ui-proposals/`
