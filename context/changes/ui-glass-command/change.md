---
change_id: ui-glass-command
title: UI redesign — Glass Command theme with collapsible sidebar
status: impl_reviewed
created: 2026-10-28
updated: 2026-10-29
archived_at: null
---

## Notes

Replace current Steel Dark theme with Glass Command — glassmorphism cards, ambient orbs,
collapsible sidebar (240px ↔ 60px), KPI cards with trend badges, gradient border lines.

Key changes from proposal-ab-glass-command.html:
- OK status badges: cyan (#22d3ee) → green (#22c55e / Tailwind green-500)
- Sidebar: collapsible with tooltip on icons when collapsed, localStorage state
- KPI cards: glassmorphism + glow + trend badge + gradient bottom line
- Table: hover-reveal actions, status dots with glow on row hover
- Ambient background orbs

Source: ui-proposals/proposal-ab-glass-command.html (to be deleted after implementation)
