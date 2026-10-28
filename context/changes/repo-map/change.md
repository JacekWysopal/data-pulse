---
change_id: repo-map
title: Wide Scan — mapa projektu DataPulse
status: implemented
created: 2026-10-25
updated: 2026-10-27
archived_at: null
---

## Cel

Zbudowanie mapy projektu DataPulse metodą Wide Scan → Deep Focus zgodnie z M4L2.
Wynik: context/map/repo-map.md gotowy do użycia przez agenta w kolejnych sesjach.

## Proces (M4L2)

1. artifact-1-territory.md — historia zmian, aktywne obszary
2. artifact-2-structure.md — zależności, entry pointy, cykle
3. artifact-3-contributors.md — kontrybutorzy, wiedza domenowa
4. repo-map.md — synteza

## Narzędzia

- git log, git shortlog, git diff --stat
- find, rg (ripgrep)
- python -m modulefinder / pipdeptree (graf zależności Python)

## Scope

Tylko data-pulse/ — aplikacja Django.
Brak dependency-cruiser (projekt Python, nie Node).
