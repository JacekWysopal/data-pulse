---
change_id: ui-glass-command
topic: UI redesign — Glass Command theme with collapsible sidebar
researcher: worker-subagent
created: 2026-10-28
last_updated: 2026-10-28
last_updated_by: worker-subagent
last_updated_note: Initial research pass
---

# Research: ui-glass-command

## Summary

The Glass Command redesign replaces the current Steel Dark theme with glassmorphism cards, ambient orbs, and a collapsible sidebar. The change touches `base.html` (design system + sidebar), `dashboard.html` (KPI cards + table), and the standalone auth pages (`login.html`, `signup.html`). The 8 monitor child templates extend `base.html` and inherit token changes automatically. The proposal HTML (`proposal-ab-glass-command.html`) is the authoritative visual reference and is to be deleted after implementation.

---

## 1. CSS Tokens — What Must Change

### base.html `:root` — current vs. target

| Token | Current value | Target value | Source |
|---|---|---|---|
| `--ok` | `#34d399` | `#22c55e` | change.md explicit requirement |
| `--ok-dim` | `rgba(52,211,153,0.12)` | `rgba(34,197,94,0.12)` | derived from new `--ok` |
| `--ok-glow` | `rgba(52,211,153,0.3)` | `rgba(34,197,94,0.3)` | derived from new `--ok` |
| `--bg-base` | `#0a0a0f` | `#03050e` | proposal `:root --bg` |
| `--bg-surface` | `#111118` | `#07091a` | proposal `:root --surface` |
| `--bg-card` | `#16161f` (solid) | `rgba(255,255,255,0.025)` | proposal glassmorphism `--card` |
| `--bg-card-hover` | `#1c1c28` | `rgba(255,255,255,0.04)` | proposal hover behaviour |
| `--nav-width` | `220px` | `240px` | proposal `--nav-w` |
| `--nav-collapsed` | `64px` | `60px` | proposal `--nav-col` |
| `--transition` | (not defined) | `0.22s cubic-bezier(0.4,0,0.2,1)` | proposal `--transition` token |

New tokens to ADD:

| Token | Value | Purpose |
|---|---|---|
| `--card-solid` | `#0c0f1f` | Solid fallback for elements that cannot use transparent backgrounds (tooltip bg, etc.) |
| `--ok` updated | `#22c55e` | green-500, replaces cyan |

### login.html and signup.html (standalone — NOT extending base.html)

Both files duplicate `:root` CSS with `--ok` absent (only `--fail` is used), but both use `--accent`/`--bg-base` tokens that should be kept consistent. No `--ok` token update is strictly required for these files, but the ambient background should be upgraded to match the Glass Command aesthetic (stronger glow, richer radial gradients matching proposal).

---

## 2. Sidebar — Structural Changes

### Current sidebar structure (base.html)

```
<aside class="dp-sidebar" id="dp-sidebar">
  <a class="dp-logo">...</a>
  <nav class="dp-nav">...</nav>
  <div class="dp-sidebar-footer">...</div>
</aside>
```

Background: `var(--bg-surface)` (solid `#111118`).  
Width CSS classes: `.dp-sidebar` / `.dp-sidebar.collapsed` toggled by `body.nav-collapsed`.

### Required changes

- Sidebar background: `var(--bg-surface)` → `rgba(7,9,26,0.85)` with `backdrop-filter: blur(24px)` and `-webkit-backdrop-filter: blur(24px)`.
- Active nav indicator: current positions at `left: 0; top: 20%; bottom: 20%; width: 2px`. Proposal positions it at `left: -8px` (outside the item box, clipped by sidebar `overflow: hidden`). The sidebar already has `overflow: hidden`, so `left: -8px` works identically. Update coordinates.
- Sidebar width tokens: update `--nav-width` to `240px` and `--nav-collapsed` to `60px`.
- Tooltip positioning: current uses `left: calc(var(--nav-collapsed) - 4px)` = `60px` when updated; proposal uses `left: calc(var(--nav-col) + 4px)` = `64px`. After the width change the current formula evaluates to `56px`. Keep consistent with proposal intent: `left: calc(var(--nav-collapsed) + 4px)`.
- localStorage key: current key `'dp_nav_collapsed'` is kept (not changed to `'dp_collapsed'` from proposal) to avoid losing users' saved collapse state.

### No structural HTML changes to sidebar nav items

The proposal uses the same `data-tip` attribute pattern for tooltips. The existing markup is compatible.

---

## 3. Ambient Background Orbs

### Current implementation (base.html)

The ambient glow is a CSS `body::before` pseudo-element:
```css
body::before {
  radial-gradient(ellipse 60% 40% at 5% 10%, rgba(99,102,241,0.07) ...),
  radial-gradient(ellipse 40% 30% at 95% 90%, rgba(99,102,241,0.04) ...);
}
```

### Proposal implementation

Three `<div class="orb">` elements injected directly into `<body>`:
```html
<div class="orb o1"></div>  <!-- top-left, indigo/violet -->
<div class="orb o2"></div>  <!-- bottom-right, purple -->
<div class="orb o3"></div>  <!-- center, cyan/teal -->
```

### Change needed

Replace `body::before` with the three `.orb` div elements. The CSS `body::before` rule is removed; the orb divs go immediately after `<body id="dp-body">`, before the sidebar. The `body::before` rule must be explicitly deleted to avoid both rendering simultaneously.

---

## 4. JavaScript — Collapse Logic

### Current (base.html `<script>`)

```js
const STORAGE_KEY = 'dp_nav_collapsed';
function setCollapsed(v) {
  body.classList.toggle('nav-collapsed', v);
  sidebar.classList.toggle('collapsed', v);
  localStorage.setItem(STORAGE_KEY, v ? '1' : '');
}
if (localStorage.getItem(STORAGE_KEY)) setCollapsed(true);
btn.addEventListener('click', () => setCollapsed(!body.classList.contains('nav-collapsed')));
```

This is functionally identical to the proposal. No JS changes are required for the collapse logic. The only difference is the key name (`dp_nav_collapsed` vs `dp_collapsed`) — keeping current key.

---

## 5. KPI Cards — dashboard.html

### Current implementation

- Class: `.kpi-card` with solid `var(--bg-card)` background.
- Progress bar: `.kpi-bar-bg` / `.kpi-bar-fill` (horizontal bar beneath number).
- No glow orb, no trend badge.
- CSS lives in `{% block extra_head %}` of `dashboard.html`.

### Proposal implementation

- Class: `.kpi` with `var(--card)` (glassmorphism `rgba(255,255,255,0.025)`), `backdrop-filter: blur(12px)`.
- Inner glow: `.kpi-glow` — absolute-positioned `100×100px` blur circle (top-right).
- Bottom gradient line: `.kpi-bar` — `2px` absolute line at bottom, `background: linear-gradient(90deg, transparent, <color>, transparent)`.
- Trend badge: `.kpi-trend` pill showing delta (e.g., `↑ +2`). **No view context provides trend data** (`ok_trend`, etc. are absent from `monitor/views.py`). Trend badge will be omitted for OK/FAIL/ERROR cards. The TOTAL card will show the connection count using `{{ connections_count }}` if passed, or simply the database icon without a badge. This is a scoping decision kept in Phase 2.
- `::after` shimmer overlay: `linear-gradient(135deg, rgba(255,255,255,0.03) 0%, transparent 60%)`.

### OK card color correction

The proposal uses `rgba(34,211,238,...)` (cyan) for the OK card. Per `change.md`, OK = green `#22c55e`. All OK-related KPI card colours (glow, border, bar, icon stroke) must use `rgba(34,197,94,...)` derived from `#22c55e`.

---

## 6. Monitoring Table — dashboard.html

The current table already closely matches the proposal:
- `.rule-link-dot` with glow on row hover — present.
- `.actions-cell` with `opacity: 0 → 1` on hover — present.
- Status badges `.dp-badge-ok/fail/error` — present.

**Differences to reconcile:**
- Row hover background: current uses `var(--bg-card-hover)` = `#1c1c28` solid. After token update `--bg-card-hover` becomes `rgba(255,255,255,0.04)` (glassy). No template change needed — falls through from base token.
- `.conn-badge` styling: present in dashboard.html already. No change needed.

---

## 7. Templates Extending base.html

All 8 files listed below extend `base.html` and automatically inherit all token and layout changes:

| Template | Path | Own custom CSS? | Net impact |
|---|---|---|---|
| `dashboard.html` | `templates/monitor/dashboard.html` | Yes (KPI, table) | Phase 1 tokens + Phase 2 KPI rewrite |
| `connection_list.html` | `templates/monitor/connection_list.html` | Yes (provider-grid, conn-card) | Phase 1 tokens auto-applied; minor glass card touch-up in Phase 3 |
| `rule_form.html` | `templates/monitor/rule_form.html` | Yes (form-card, schema browser) | Phase 1 tokens auto-applied; `.form-card` gets glassmorphism in Phase 3 |
| `schedule_dashboard.html` | `templates/monitor/schedule_dashboard.html` | Yes (minimal) | Phase 1 tokens auto-applied; no additional work |
| `connection_form.html` | `templates/monitor/connection_form.html` | Unknown (not read) | Phase 1 tokens auto-applied |
| `rule_confirm_delete.html` | `templates/monitor/rule_confirm_delete.html` | Unknown (not read) | Phase 1 tokens auto-applied |
| `connection_confirm_delete.html` | `templates/monitor/connection_confirm_delete.html` | Unknown (not read) | Phase 1 tokens auto-applied |
| `rule_history.html` | `templates/monitor/rule_history.html` | Unknown (not read) | Phase 1 tokens auto-applied |

---

## 8. Standalone Auth Templates

| Template | Extends base? | Uses `--ok`? | Action |
|---|---|---|---|
| `login.html` | No — full standalone | No (uses `--fail` only) | Update ambient background to match Glass Command; no `--ok` change needed |
| `signup.html` | No — full standalone | No (uses `--fail` only) | Same as login.html |

Both templates duplicate the full CSS design system. They need the ambient background enhanced to richer radial gradients matching the Glass Command aesthetic.

---

## 9. Cleanup Scope

`ui-proposals/` folder contains one file confirmed: `proposal-ab-glass-command.html`. This folder is deleted in Phase 4. No other code references it (confirmed by grep: it's only referenced in `change.md` notes which will remain as-is after deletion as historical record).

---

## 10. Open Risks / Known Gaps

- `backdrop-filter` browser support: requires `-webkit-backdrop-filter` prefix for Safari. Both the current base.html and the proposal already include the `-webkit-` prefixed form. Risk: **low**.
- Glassmorphism on `--bg-card`: changing to `rgba(255,255,255,0.025)` means cards need a non-transparent ancestor. The `body` background (`#03050e` solid) provides this. Risk: **low**.
- `connection_form.html`, `rule_confirm_delete.html`, `connection_confirm_delete.html`, `rule_history.html` were not fully read. Their own block CSS uses base tokens which will inherit changes; no structural sidebar or KPI changes are needed in those files.
- Trend badge data: no backend changes planned. OK/FAIL/ERROR KPI cards will omit the trend pill. TOTAL card may show a DB count chip if `connection_count` context is available in views — verify at Phase 2 implementation time.
