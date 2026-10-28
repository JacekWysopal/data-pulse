# artifact-3-contributors — Kontrybutorzy i wiedza domenowa

> DataPulse — Wide Scan, 2026-10-27
> Dowód: `git shortlog -sn`, historia commitów

## Kontrybutorzy

| Autor | Commity | Rola |
|---|---|---|
| Jacek Wysopal | 18 (100%) | Tech Lead, jedyny autor |

**Projekt solo** — brak ryzyka związanego z wiedzą rozproszoną między osobami.
Cała wiedza domenowa i architektoniczna siedzi w jednej głowie + dokumentacji.

## Wiedza domenowa zawarta w kodzie

### Reguły biznesowe (services.py)

1. **Volume check** — `COUNT(*) < min_row_count → FAIL`
2. **Freshness check** — `EXTRACT(EPOCH FROM (NOW() - MAX(ts_col))) / 3600 > max_age_hours → FAIL`
3. **Custom SQL** — query returns falsy value → FAIL; truthy → OK
4. **SQL safety** — regex whitelist (`^SELECT`) + blacklist (`INSERT/UPDATE/DROP/...`)
5. **statement_timeout = 30s** — zabezpieczenie przed wolnymi custom SQL queries
6. **Connection cache per run** — `run_all_checks` nie otwiera nowego połączenia dla reguł ze wspólnym URL

### Reguły walidacji (forms.py)

1. Reguła `volume_freshness` musi mieć co najmniej jeden warunek (freshness OR volume)
2. `timestamp_column` i `max_age_hours` muszą być podane razem
3. Custom SQL musi zaczynać się od SELECT
4. Connection jest wymagany — brak fallbacku na env

### Model danych (models.py)

- `Connection._database_url` z `db_column='database_url'` — niekonwencjonalne nazewnictwo, pułapka dla nowych
- `Rule.rule_type` — TextChoices z dwoma wariantami: `volume_freshness` / `custom_sql`
- `CheckRun` → `RuleResult` (1:N) — jeden przebieg, wiele wyników
- `Rule.connection` FK (nullable, SET_NULL) — usunięcie Connection nie usuwa reguł

## Decyzje architektoniczne (z context/)

| Decyzja | Uzasadnienie |
|---|---|
| Django ORM dla app DB | Standard, SQLite lokalnie / PostgreSQL prod |
| psycopg2 dla monitored DB | Bezpośredni dostęp, brak ORM pośredniego |
| Connection URL szyfrowany przez Fernet | Wrażliwe dane w bazie |
| Brak MONITORED_DATABASE_URL w env | Wszystko przez UI (S-03 decision) |
| SQLite lokalnie, PostgreSQL prod | Dual-DB pattern z settings.py |
| Client-side filtering (S-07) | Mała liczba reguł, brak sensu na server queries |
| Session cache dla schema introspection | 5 min, per Connection, unikanie przeładowań |

## Obszary z potencjalnym długiem technicznym

Z artifact-1 + artifact-2:

1. **`cryptography` nie w requirements.txt** — szyfrowanie Fernet działa tylko jeśli pakiet zainstalowany. Na Render jest tylko jeśli zainstalujesz ręcznie lub dodasz do requirements.
2. **Migracja 0002** — pole `_database_url` vs `database_url` — historia bugfixa w kodzie migracji może powodować problemy przy fresh deploy na czystej bazie.
3. **`run_single_rule` i `run_all_checks` powielają logikę** — obie funkcje otwierają połączenie i wywołują `_check_rule`. Różnią się tylko connection cachingiem.
4. **rule_form.html 295+ linii JS** — mieszany HTML + JS, trudny do testowania izolowanego.
5. **Brak rate limitingu na AJAX endpointach** (schema introspection) — użytkownik może wielokrotnie odpytywać monitored DB.

## Pierwszy dzień w projekcie

Gdzie zacząć rozumienie kodu:

1. `monitor/models.py` — 4 modele, zrozumieć schemat
2. `monitor/services.py` — logika sprawdzania reguł
3. `monitor/views.py` — przepływ HTTP
4. `templates/monitor/dashboard.html` — co widzi użytkownik
5. `context/foundation/prd.md` — po co to wszystko
