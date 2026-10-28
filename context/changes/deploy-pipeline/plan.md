# Deploy Pipeline — Implementation Plan

## Overview

Skonfigurowanie pelnego deploy pipeline dla DataPulse na Render. Obejmuje dodanie
gunicorn i whitenoise, generowanie requirements.txt, konfiguracje whitenoise
w settings.py, stworzenie render.yaml z automatycznymi migracjami oraz
GitHub Actions workflow do CI/CD.

## Current State Analysis

- `pyproject.toml` zarzadza zaleznoscia przez uv; brak gunicorn i whitenoise
- `settings.py` ma `STATIC_URL = "static/"` ale brak `STATIC_ROOT` i whitenoise
- Brak `requirements.txt` — Render uzywa pip, nie uv
- Brak `render.yaml`, `.github/workflows/`, `Procfile`
- Python 3.12 (`.python-version`)
- Django 6.1.1, SQLite lokalnie / Supabase na prod (dual-DB gotowe)

## Desired End State

`git push` do `main` wyzwala GitHub Actions, ktory deployuje na Render.
Render uruchamia build (pip install + collectstatic), release (migrate) i start
(gunicorn). Django Admin ma style. DataPulse dziala na `https://data-pulse.onrender.com`.

### Key Discoveries

- `data-pulse/data_pulse/settings.py:90` — `STATIC_URL = "static/"` bez STATIC_ROOT
- `data-pulse/data_pulse/settings.py:27-35` — MIDDLEWARE bez whitenoise
- `data-pulse/pyproject.toml` — brak gunicorn i whitenoise w dependencies
- `data-pulse/.python-version` — `3.12`

## What We Are NOT Doing

- Nie konfigurujemy custom domeny (.onrender.com wystarczy na MVP)
- Nie ustawiamy wildcard ALLOWED_HOSTS=*
- Nie uzywamy CDN do statycznych plikow (whitenoise wystarczy)
- Nie konfigurujemy Supabase DATABASE_URL — to F-03

## Implementation Approach

Trzy niezalezne warstwy, kolejnosc ma znaczenie:
1. Zaleznosci (gunicorn + whitenoise) — requirements.txt
2. settings.py (whitenoise w MIDDLEWARE + STATIC_ROOT)
3. render.yaml + GitHub Actions

## Phase 1: Zaleznosci i requirements.txt

### Overview

Dodanie gunicorn i whitenoise do projektu. Wygenerowanie requirements.txt
ktore Render uzyje podczas build.

### Changes Required

#### 1. Dodanie gunicorn i whitenoise do pyproject.toml

**File:** `data-pulse/pyproject.toml`

**Intent:** Dodac gunicorn jako serwer WSGI produkcyjny i whitenoise do serwowania statycznych plikow.

**Contract:** Po zmianie sekcja dependencies zawiera `"gunicorn>=23.0.0"` i `"whitenoise>=6.9.0"`

#### 2. Generowanie requirements.txt

**File:** `data-pulse/requirements.txt`

**Intent:** Wygenerowac plik requirements.txt ktory Render odczyta podczas build command.

**Contract:** `uv pip compile pyproject.toml -o requirements.txt` w katalogu `data-pulse/`. Plik musi zawierac gunicorn i whitenoise.

### Success Criteria

#### Automated Verification

- `uv run python -c "import gunicorn; import whitenoise; print(OK)"` — oba importy dzialaja
- `requirements.txt` istnieje i zawiera gunicorn i whitenoise

#### Manual Verification

- `uv run gunicorn data_pulse.wsgi:application` uruchamia serwer lokalnie

---

## Phase 2: Konfiguracja whitenoise w settings.py

### Overview

Skonfigurowanie Django do serwowania statycznych plikow przez whitenoise.

### Changes Required

#### 1. STATIC_ROOT i whitenoise storage

**File:** `data-pulse/data_pulse/settings.py`

**Intent:** Ustawic STATIC_ROOT i skonfigurowac whitenoise jako storage backend.

**Contract:** Dodac po `STATIC_URL`: `STATIC_ROOT = BASE_DIR / "staticfiles"` i STORAGES z whitenoise.storage.CompressedManifestStaticFilesStorage

#### 2. WhiteNoise middleware

**File:** `data-pulse/data_pulse/settings.py`

**Intent:** Dodac WhiteNoiseMiddleware zaraz po SecurityMiddleware (pozycja 2).

**Contract:** `whitenoise.middleware.WhiteNoiseMiddleware` po SecurityMiddleware, przed SessionMiddleware

#### 3. ALLOWED_HOSTS dla Render

**File:** `data-pulse/data_pulse/settings.py`

**Intent:** Dodac `.onrender.com` do domyslnej listy ALLOWED_HOSTS.

**Contract:** `ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1", ".onrender.com"])`

#### 4. .gitignore dla data-pulse/

**File:** `data-pulse/.gitignore`

**Intent:** Zapobiec commitowaniu staticfiles/, .venv/, db.sqlite3 i .env do repo.

**Contract:** Plik zawiera co najmniej: staticfiles/, .venv/, __pycache__/, *.pyc, db.sqlite3, .env

### Success Criteria

#### Automated Verification

- `uv run python manage.py check --deploy` — brak bledow
- `uv run python manage.py collectstatic --noinput` — tworzy staticfiles/ bez bledow

#### Manual Verification

- `staticfiles/admin/` istnieje z CSS/JS Django Admin
- `data-pulse/.gitignore` istnieje i pokrywa staticfiles/ i .venv/

---

## Phase 3: render.yaml + GitHub Actions

### Overview

render.yaml definiuje serwis na Render. GitHub Actions workflow deployuje przy push do main.

### Changes Required

#### 1. render.yaml

**File:** `data-pulse/render.yaml`

**Intent:** Zdefiniowac web service z build command (pip install + collectstatic),
release command (migrate) i start command (gunicorn).

**Contract:** type: web, runtime: python, buildCommand: pip install -r requirements.txt && python manage.py collectstatic --noinput,
startCommand: gunicorn data_pulse.wsgi:application, releaseCommand: python manage.py migrate,
envVars: DATABASE_URL i MONITORED_DATABASE_URL sync:false, SECRET_KEY generateValue:true, DEBUG=False, PYTHON_VERSION=3.12

#### 2. GitHub Actions workflow

**File:** `data-pulse/.github/workflows/deploy.yml`

**Intent:** Wyzwolic deploy przez Render API przy push do main.
Wymaga GitHub Secrets: RENDER_API_KEY i RENDER_SERVICE_ID.

**Contract:** POST do api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys przy kazdym push do main

### Success Criteria

#### Automated Verification

- `uv run python manage.py check` — 0 bledow

#### Manual Verification

- Render Dashboard wykrywa render.yaml po polaczeniu repo
- Pierwszy deploy OK — build + release + start
- `https://data-pulse.onrender.com` odpowiada
- Django Admin `/admin/` ma style (whitenoise dziala)

---

## References

- Roadmap slices: F-01, F-02, H-01 w M-01
- infrastructure.md - Getting Started
- change.md: `context/changes/deploy-pipeline/change.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done.

### Phase 1: Zaleznosci i requirements.txt

#### Automated

- [x] 1.1 import gunicorn i whitenoise — OK
- [x] 1.2 requirements.txt zawiera gunicorn i whitenoise

#### Manual

- [x] 1.3 gunicorn data_pulse.wsgi:application uruchamia sie lokalnie

### Phase 2: Konfiguracja whitenoise w settings.py

#### Automated

- [x] 2.1 manage.py check --deploy — brak bledow
- [x] 2.2 manage.py collectstatic --noinput — tworzy staticfiles/

#### Manual

- [x] 2.3 staticfiles/admin/ zawiera CSS/JS
- [x] 2.4 data-pulse/.gitignore istnieje i pokrywa staticfiles/ i .venv/

### Phase 3: render.yaml i GitHub Actions

#### Automated

- [x] 3.1 manage.py check — 0 bledow

#### Manual

- [x] 3.2 Render Dashboard wykrywa render.yaml
- [x] 3.3 Pierwszy deploy OK
- [x] 3.4 https://data-pulse.onrender.com odpowiada
- [x] 3.5 Django Admin ma style