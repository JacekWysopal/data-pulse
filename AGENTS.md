# Repository Guidelines

DataPulse is a Django 6 web app (Python 3.12, uv) that monitors PostgreSQL table freshness and row counts. Rules and check history are stored in a PostgreSQL database (Supabase on production, SQLite locally). Checks run against a separate, externally-provided PostgreSQL instance configured via `.env`.

## Hard Rules

- **Never log or display `MONITORED_DATABASE_URL`** — the connection string to the monitored PostgreSQL must not appear in HTTP responses, log output, Django error pages, or template context. Read it only via `settings.MONITORED_DATABASE_URL`.
- **Never log or display `DATABASE_URL`** — the Supabase connection string is equally sensitive. Never expose it in UI or logs.
- **Never write raw SQL with f-strings in views or forms** — SQL with user input lives exclusively in `monitor/services.py`, where table/column identifiers come from the `Rule` model (saved by the admin, not HTTP input). If adding a new query, follow the pattern in `@monitor/services.py`.
- **`context/` is read-only for application code** — files under `context/foundation/` and `context/changes/` are workflow artifacts, not application config. Never read or import them from Django code.
- **Never edit a migration that has already been applied** — consequences are irreversible (corrupt migration state).

## Project Structure

```
data-pulse/
├── data_pulse/        # Django project package (settings, urls, wsgi)
├── monitor/           # Single Django app: models, views, forms, services
│   ├── models.py      # Rule, CheckRun, RuleResult
│   ├── services.py    # Monitored DB connection + check logic (domain layer)
│   ├── views.py       # HTTP handlers
│   └── migrations/    # Django migrations — always commit these
├── templates/
│   ├── base.html      # Bootstrap 5 shell
│   └── monitor/       # Per-view templates
├── .env               # Local secrets — never commit
└── db.sqlite3         # Local fallback SQLite — never commit
```

## Two-Database Architecture

```
DataPulse app
    ├── DATABASE_URL          → app database (Supabase on prod, SQLite locally)
    │                           stores: Rule, CheckRun, RuleResult
    └── MONITORED_DATABASE_URL → user's PostgreSQL (external, any provider)
                                 queried read-only by monitor/services.py
```

`settings.py` falls back to SQLite when `DATABASE_URL` is empty — safe for local development without Supabase credentials.

## Commands

```
uv run python manage.py runserver          # dev server → http://127.0.0.1:8000
uv run python manage.py migrate            # apply migrations
uv run python manage.py makemigrations monitor  # after model changes
uv run python manage.py createsuperuser    # create admin user
uv run python manage.py check              # validate config before running
uv run pip-audit                           # dependency vulnerability scan
```

## Coding Conventions

- **Python 3.12, no type annotations required** but use them for function signatures in `services.py`.
- **Django ORM only** — no raw SQL outside `monitor/services.py`. For new list views follow the `prefetch_related('results')` pattern in `views.py:dashboard`.
- **Templates:** all HTML lives in `templates/monitor/`. New views extend `templates/base.html`. Bootstrap 5 for layout; no custom CSS unless added to `base.html`.
- **Forms:** validation logic in `monitor/forms.py` `clean()` methods, not in views. Views only call `form.is_valid()` and redirect.
- **`services.py` is the only file that opens a `psycopg2` connection.** Views call `run_all_checks()`; they never import `psycopg2` directly.
- **`.env` keys:** `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASE_URL` (app DB), `MONITORED_DATABASE_URL` (user DB).

## Migrations

Always run `makemigrations monitor` after changing `monitor/models.py`. Commit the generated migration file alongside the model change.
<!-- BEGIN @przeprogramowani/10x-cli -->

## Zestaw narzędzi AI 10xDevs - Moduł 4, Lekcja 2 (Mapa Projektu)

Szybko zorientuj się w nieznanym lub starszym repozytorium na podstawie dowodów, a nie drzew katalogów: **najpierw szerokie skanowanie, później głęboka analiza.**

```
git history + dependency graph + contributors -> context/map/repo-map.md -> focused /10x-research
```

### Router zadań - od czego zacząć

| Umiejętność / prompt | Użyj, gdy |
| --- | --- |
| `/10x-repo-map` | Mapa Projektu w jednym uruchomieniu. Uszeregowuje możliwości biznesowe według krytyczności × rozgłosu, przechowuje dowody w `context/map/evidence/` i zapisuje `context/map/repo-map.md` ze strefami ryzyka, listą lektur na pierwszy dzień oraz jawnymi niewiadomymi. Użyj `--replace`, aby odświeżyć; poprzednie uruchomienie zostanie przeniesione do `context/archive/`. |
| `m4l2-1-territory-git-history` -> `m4l2-2-structure-dependency-cruiser` -> `m4l2-3-contributors-git` -> `m4l2-repo-map-synthesis` | Ta sama mapa tworzona krok po kroku, po jednym artefakcie naraz, aby można było zobaczyć, co wnosi każde źródło dowodów. |
| `/10x-research` | Pytanie dotyczące jednej funkcji lub obszaru. Mapa obejmuje szerokość i nie przyjmuje celu; głębokość należy do badań. |

### Twarde zasady

- **Niech narzędzia zbierają dowody poza oknem kontekstu.** Używaj git, forge i narzędzi grafowych do zbierania danych, a następnie interpretuj wyłącznie ich skondensowane wyniki. Nigdy nie czytaj repozytorium plik po pliku.
- **Wyklucz szum.** Pomijaj pliki lock, wygenerowany kod, commity masowego formatowania, commity botów i commity utworzone przez agentów podczas klasyfikowania aktywności.
- **Niewiadome są częścią mapy.** Oznaczaj jako niewiadome to, czego nie mogą pokazać dowody, zamiast wypełniać lukę domysłem.

<!-- END @przeprogramowani/10x-cli -->
