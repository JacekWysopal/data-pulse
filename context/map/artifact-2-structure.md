# artifact-2-structure — Zależności, entry pointy, cykle

> DataPulse — Wide Scan, 2026-10-27
> Dowód: analiza importów, urls.py, INSTALLED_APPS

## Architektura warstw

```
HTTP Request
    │
    ▼
data_pulse/urls.py          ← główny router
    ├── /admin/             ← Django Admin (wbudowany)
    ├── /login/, /logout/   ← Django Auth views
    └── /                   ← monitor.urls
            │
            ▼
    monitor/urls.py         ← 12 ścieżek
            │
            ▼
    monitor/views.py        ← 10 handlerów + 2 AJAX
            │
    ┌───────┼────────────┐
    ▼       ▼            ▼
forms.py  models.py   services.py
            │            │
            ▼            ▼
        Django ORM    psycopg2
            │            │
            ▼            ▼
    DATABASE_URL    Connection.database_url
    (app DB)        (monitored DB)
```

## Entry pointy aplikacji

| URL pattern | View | Opis |
|---|---|---|
| `/` | `dashboard` | Główny widok — lista reguł + KPI |
| `/run/` | `run_checks` | POST — uruchom wszystkie reguły |
| `/rules/new/` | `rule_create` | Formularz nowej reguły |
| `/rules/<id>/` | `rule_history` | Historia wyników |
| `/rules/<id>/run/` | `run_single` | POST — uruchom jedną regułę |
| `/rules/<id>/edit/` | `rule_edit` | Edycja reguły |
| `/rules/<id>/delete/` | `rule_delete` | Usunięcie reguły |
| `/connections/` | `connection_list` | Lista połączeń |
| `/connections/new/` | `connection_create` | Nowe połączenie |
| `/api/schema/<id>/tables/` | `api_schema_tables` | AJAX: tabele |
| `/api/schema/<id>/columns/<s>/<t>/` | `api_schema_columns` | AJAX: kolumny |

## Graf zależności modułów

```
monitor/views.py
    imports: forms, models, services
    
monitor/services.py
    imports: models, psycopg2, re
    NIE importuje: views, forms, settings
    
monitor/models.py
    imports: django.db, django.utils, settings, base64, os
    NIE importuje: views, services, forms
    
monitor/forms.py
    imports: django.forms, models
    NIE importuje: views, services
```

**Kierunek zależności (bezpieczny, brak cykli):**
```
views → forms → models
views → services → models
views → models
```

## Zależności zewnętrzne

| Pakiet | Użycie | Ryzyko |
|---|---|---|
| `psycopg2-binary` | services.py — połączenia do PostgreSQL | Jedyna droga do monitored DB |
| `django` | cały projekt | Core framework |
| `dj-database-url` | settings.py — parsowanie DATABASE_URL | Render/Supabase kompatybilność |
| `django-environ` | settings.py — .env handling | Konfiguracja |
| `whitenoise` | settings.py — static files | Render hosting |
| `gunicorn` | render — wsgi server | Production |
| `cryptography` | models.py — Fernet (opcjonalne) | Szyfrowanie URL w Connection |

**Uwaga:** `cryptography` jest używany ale NIE ma go w `requirements.txt` — szyfrowanie URL działa tylko z fallbackiem plaintext jeśli pakiet niedostępny.

## Cykle zależności

**Brak cykli** — sprawdzone przez analizę importów:
- models → NIE importuje views/services/forms ✓
- services → NIE importuje views/forms ✓  
- forms → NIE importuje views/services ✓

## Wrażliwe punkty

1. **`monitor/services.py`** — jedyny plik który otwiera psycopg2 do monitored DB. Dwa oddzielne code paths: `run_all_checks` (wiele reguł, connection cache) i `run_single_rule` (jedna reguła, nowe połączenie). Bugfix w tym pliku był ostatnim commitem.

2. **`monitor/models.py` — Connection._database_url** — pole z niekonwencjonalną nazwą (`_database_url` → `db_column='database_url'`). Migracja 0002 miała bug z tą nazwą.

3. **Dwie bazy danych** — `DATABASE_URL` (app DB przez Django ORM) i `Connection.get_database_url()` (monitored DB przez psycopg2). Kompletnie niezależne ścieżki, ryzyko pomylenia przy debugowaniu.

4. **`templates/monitor/rule_form.html`** — 295+ linii, zawiera JS dla schema browser (S-04/S-05) i rule type toggle (S-06). Najgęstszy szablon.

## Brakujące w strukturze

- Brak `monitor/serializers.py` — brak REST API (tylko AJAX JSON z views.py)
- Brak `monitor/signals.py` — brak Django signals
- Brak `monitor/tasks.py` — brak Celery (scheduler przez management command)
- Brak `monitor/permissions.py` — autoryzacja tylko przez `@login_required`
