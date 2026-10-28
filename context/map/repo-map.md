# Mapa projektu — DataPulse

> Wygenerowano: 2026-10-27 metodą Wide Scan (M4L2)
> Źródła: artifact-1-territory.md, artifact-2-structure.md, artifact-3-contributors.md
> Projekt: Django 6, Python 3.12, PostgreSQL, Render

---

## Skrót dla agenta

DataPulse to aplikacja webowa do monitorowania jakości danych w PostgreSQL.
Użytkownik definiuje reguły (volume, freshness, custom SQL), uruchamia sprawdzenia
i widzi wyniki OK/FAIL/ERROR. Wszystko przez Django — jeden app `monitor`,
jedna zewnętrzna baza danych (`DATABASE_URL`), wiele monitorowanych baz przez `Connection`.

---

## Funkcje produktu i pliki

| Funkcja | Pliki odpowiedzialne |
|---|---|
| Dashboard + KPI | `views.py:dashboard`, `dashboard.html` |
| Tworzenie reguł | `views.py:rule_create/edit`, `forms.py:RuleForm`, `rule_form.html` |
| Sprawdzanie reguł | `services.py:run_all_checks`, `services.py:run_single_rule` |
| Custom SQL | `services.py:_check_custom_sql`, `models.py:Rule.custom_sql` |
| Historia wyników | `views.py:rule_history`, `rule_history.html` |
| Zarządzanie połączeniami | `views.py:connection_*`, `models.py:Connection`, `connection_*.html` |
| Schema introspection | `services.py:get_schema_tables/columns`, `views.py:api_schema_*` |
| Filtry dashboard | `dashboard.html` (client-side JS) |
| Schedule | `models.py:Rule.schedule_time`, `commands/run_scheduled.py` |
| Auth | `data_pulse/urls.py`, `templates/login.html` |

---

## Punkty wejścia

- **`/`** → `dashboard` — główna strona aplikacji
- **`/run/`** → `run_checks` — uruchamia wszystkie reguły (POST)
- **`/rules/<id>/run/`** → `run_single` — uruchamia jedną regułę (POST)
- **`/api/schema/<id>/tables/`** → `api_schema_tables` — AJAX lista tabel
- **`/api/schema/<id>/columns/<s>/<t>/`** → `api_schema_columns` — AJAX kolumny
- **`/admin/`** → Django Admin — zarządzanie danymi

---

## Dwie bazy danych (ważne)

```
settings.DATABASE_URL
  → Django ORM → Connection, Rule, CheckRun, RuleResult
  → Supabase / Render PostgreSQL / SQLite lokalnie

Connection.get_database_url()
  → psycopg2 (services.py) → monitored PostgreSQL
  → dowolna baza użytkownika
```

Nigdy nie mylić — to całkowicie oddzielne ścieżki.

---

## Wrażliwe obszary (uważaj przed zmianą)

### 🔴 Krytyczne
- **`monitor/services.py`** — jedyna logika sprawdzania reguł, bugfix w ostatnim commicie.
  Zmieniaj z testami. Dwa code paths: `run_all_checks` (connection cache) i `run_single_rule`.
- **`monitor/models.py:Connection._database_url`** — pole z `db_column='database_url'`.
  Niekonwencjonalne — `_database_url` to Python attr, `database_url` to kolumna DB.

### 🟡 Ryzykowne
- **Migracje 0002-0004** — ewoluujący schemat, 4 migracje w 7 dni.
  Na fresh deploy zawsze uruchom `migrate` — nie zakładaj że baza jest aktualna.
- **`templates/monitor/rule_form.html`** — 295+ linii, JS dla schema browser + SQL toggle.
  Zmiany w JS mogą zepsuć S-04/S-05/S-06 jednocześnie.

### 🟢 Bezpieczne
- `monitor/urls.py` — routing, czytelny
- `monitor/forms.py` — walidacja, dobrze pokryta testami
- `templates/base.html` — design system, zmiany CSS nie mają side effects

---

## Zależności zewnętrzne (kluczowe)

| Pakiet | Gdzie | Uwaga |
|---|---|---|
| `psycopg2-binary` | services.py | Jedyna droga do monitored DB |
| `cryptography` (Fernet) | models.py | **BRAKUJE w requirements.txt** — szyfrowanie URL nie działa na Render |
| `django 6.1` | wszędzie | Core |
| `dj-database-url` | settings.py | Parsowanie DATABASE_URL |

---

## Dług techniczny (z artifact-3)

1. **`cryptography` nie w requirements.txt** — Connection URL zapisywany plaintext na produkcji
2. **`run_single_rule` i `run_all_checks` powielają logikę** — connection cache różni obie
3. **Brak rate limitingu na `/api/schema/`** — wielokrotne odpytania monitored DB możliwe
4. **JS w rule_form.html** — 100+ linii inline JS, trudny do izolowanego testowania

---

## Niewiadome

- [ ] Czy migracja 0002 (`_database_url`) działa poprawnie na świeżej bazie?
- [ ] Czy `cryptography` jest zainstalowane na Render automatycznie?
- [ ] Czy `run_scheduled` jest kiedykolwiek wywoływany produkcyjnie (Render Cron wymaga planu płatnego)?

---

## Gdzie zacząć (nowa osoba)

1. `context/foundation/prd.md` — po co to wszystko
2. `monitor/models.py` — 4 modele, schemat danych
3. `monitor/services.py` — logika domenowa
4. `monitor/views.py` — przepływ HTTP
5. `python manage.py test monitor` — uruchom testy, sprawdź stan

---

## Następny krok (Deep Focus)

Kandydaci do S-10 (agent code review):
- **`monitor/services.py`** — najwrażliwszy plik, agent powinien znać go przed review
- **`monitor/tests.py`** — 973 linie, czy pokrycie jest wystarczające?
