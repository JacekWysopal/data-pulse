# artifact-1-territory — Historia zmian i aktywne obszary

> DataPulse — Wide Scan, 2026-10-27
> Dowód: `git log --format`, `git diff-tree`, `wc -l`

## Aktywność commitów

| Data | Commit | Obszar |
|---|---|---|
| 2026-10-27 | fix: _check_rule dispatcher | monitor/services.py |
| 2026-10-27 | S-06 custom SQL + 60 tests + CI | monitor/ wszystko |
| 2026-10-27 | S-04/S-05 schema introspection | monitor/services.py, views.py, rule_form.html |
| 2026-10-27 | S-08 badge + S-07 filters | templates/monitor/dashboard.html |
| 2026-10-27 | remove MONITORED_DATABASE_URL | services.py, settings.py, forms.py |
| 2026-10-26 | S-03 connection management | monitor/models.py, views.py, forms.py |
| 2026-10-26 | side navbar + animated logo | templates/base.html |
| 2026-10-25 | dark UI redesign | templates/* |
| 2026-10-20 | init on dev - render | deploy baseline |

**Czas trwania projektu:** 7 dni intensywnego developmentu (2026-10-20 → 2026-10-27)

## Najczęściej zmieniane pliki (commits touching file)

| Plik | Zmiany | Rola |
|---|---|---|
| `templates/monitor/dashboard.html` | 9 | Główny widok — KPI, tabela reguł, filtry |
| `templates/monitor/rule_form.html` | 8 | Formularz reguły — schema browser, SQL toggle |
| `templates/base.html` | 8 | Layout, navbar, design system |
| `monitor/views.py` | 8 | HTTP handlers — centralny punkt sterowania |
| `monitor/services.py` | 7 | Logika domenowa — najwrażliwszy plik |
| `monitor/models.py` | 5 | Modele — Connection, Rule, CheckRun, RuleResult |
| `monitor/forms.py` | 5 | Walidacja formularzy |
| `data_pulse/settings.py` | 5 | Konfiguracja Django |

## Aktywne obszary funkcjonalne

### 🔴 Gorące (najwięcej zmian)
- `monitor/services.py` — logika sprawdzania reguł, 2 bugfixy w jednym dniu
- `templates/monitor/dashboard.html` — UI dashboard z filtrami i KPI
- `monitor/views.py` — CRUD + AJAX endpointy

### 🟡 Aktywne
- `monitor/models.py` — 4 migracje w ciągu 7 dni (schemat ewoluuje)
- `templates/base.html` — design system, navbar

### 🟢 Stabilne
- `monitor/urls.py` — routing, małe zmiany
- `data_pulse/urls.py` — główny routing, 2 zmiany
- `monitor/management/commands/` — seed_demo, run_scheduled

## Rozmiar kodu

| Plik | Linie |
|---|---|
| `monitor/tests.py` | 973 |
| `monitor/services.py` | 329 |
| `monitor/models.py` | 210 |
| `monitor/views.py` | 191 |
| `monitor/forms.py` | 90 |
| `monitor/urls.py` | 26 |

## Sygnały ryzyka

- `services.py` miał bugfix (`_check_rule` rekurencja) — to najwrażliwszy plik
- 4 migracje w 7 dni = ewoluujący schemat, ryzyko przy fresh deploy
- Brak historii pre-deploy (`init: README` to 2 commity przed pierwszym deployem)

## Niewiadome z artifact-1

- Czy migracje 0002/0003/0004 są przetestowane na świeżej bazie?
- Czy `run_scheduled` jest testowany end-to-end (wymaga Render Cron)?
