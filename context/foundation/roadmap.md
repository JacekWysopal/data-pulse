---
project: DataPulse
prd_version: 1
updated: 2026-10-25
milestone_seq: 1
milestone_id: m-01-first-deploy
milestone_status: done
main_goal: speed
north_star: S-01
top_blocker: deploy-pipeline
---

## Milestone

**M-01 — Pierwsze wdrożenie na Render**

Status: done
Źródło: context/foundation/prd.md (v1) + codebase baseline (2026-09-23)

Zakres: aplikacja DataPulse działa na Render z Supabase jako bazą. Użytkownik może
dodać regułę, kliknąć „Uruchom sprawdzenie" i zobaczyć OK/FAIL z wartością zmierzoną
— wszystko na produkcyjnym URL.

---

## At a glance — M-01

| ID | Slice | Prereqs | Status |
|---|---|---|---|
| F-01 | Deploy pipeline — gunicorn, requirements.txt, render.yaml | — | done |
| F-02 | Statyczne pliki na Render — whitenoise | F-01 | done |
| F-03 | Supabase jako app DB — DATABASE_URL na Render | F-01 | done |
| F-04 | Pierwsze wdrożenie i smoke test US-01 | F-01, F-02, F-03 | done |
| S-01 | US-01 end-to-end na produkcji: dodaj regułę → uruchom → OK/FAIL | F-04 | done |
| S-02 | Historia wyników per reguła — US-02 drill-down | S-01 | done |
| S-03 | Connection management — użytkownik dodaje własny PostgreSQL przez UI | S-01 | done |
| H-01 | requirements.txt generowany z pyproject.toml — Render build step | — | done |

---

---
milestone_seq: 2
milestone_id: m-02-rule-builder
milestone_status: open
main_goal: usability
north_star: S-06
top_blocker: schema-introspection
---

## Milestone

**M-02 — Rule Builder & Multi-connection UX**

Status: open
Źródło: sesja robocza 2026-10-25 — rozbudowa post-MVP

Zakres: użytkownik może budować reguły bez znajomości schematu bazy — przegląda
tabele i kolumny z listy, wybiera je klikając. Może też pisać własny SQL z warunkiem
true/false. Dashboard ma filtry i widoczność źródła połączenia per reguła.

Scope anchors:
- MS-04: schema introspection — czytanie tabel i kolumn z podłączonego PostgreSQL
- MS-05: rule builder UI — wybór tabeli/kolumny z dropdown zamiast ręcznego wpisywania
- MS-06: custom SQL rule — nowy typ reguły: zapytanie SQL zwracające true/false
- MS-07: dashboard filtry — filtrowanie reguł po statusie, połączeniu, nazwie

---

## At a glance — M-02

| ID | Slice | Prereqs | Status |
|---|---|---|---|
| S-04 | Schema introspection — czytanie tabel i kolumn z połączonego PostgreSQL | S-03 | done |
| S-05 | Rule builder — wybór tabeli/kolumny z listy przy tworzeniu reguły | S-04 | done |
| S-06 | Custom SQL rule — reguła oparta o SQL zwracający true/false ⭐ | S-03 | done |
| S-07 | Dashboard filters — filtrowanie po statusie, połączeniu, nazwie | S-03 | done |
| S-08 | Connection badge na liście reguł — widoczność źródła per reguła | S-03 | done |

---

## Slices — M-02

### S-04 — Schema introspection

**Wynik:** Użytkownik otwiera formularz reguły, wybiera połączenie i widzi listę
dostępnych schematów → tabel → kolumn pobraną live z PostgreSQL przez
`information_schema`.

**Prerequisites:** S-03 (Connection model gotowy)

**Change ID:** DP-004

**Status:** proposed

**Decyzje architektoniczne:**
- Endpoint `/api/schema/<conn_id>/tables/` — zwraca JSON z listą `schema.table`
- Endpoint `/api/schema/<conn_id>/columns/<schema>/<table>/` — zwraca kolumny z typem
- Dane cachowane w sesji (5 min TTY) — nie ma sensu odpytywać przy każdym keystroke
- Połączenie read-only: `SELECT` na `information_schema.tables` i `information_schema.columns`
- Błąd połączenia → graceful fallback do ręcznego wpisywania (pola tekstowe)

**Implikacje dla kodu:**
- `monitor/views.py` — 2 nowe endpointy AJAX (login_required)
- `monitor/urls.py` — 2 nowe ścieżki `/api/schema/...`
- `templates/monitor/rule_form.html` — JS fetching schematów po wyborze Connection

**Success criteria:**
- Po wybraniu połączenia dropdown tabel ładuje się w < 2s
- Błąd połączenia nie crashuje formularza — widoczny komunikat, pola tekstowe aktywne
- Kolumny filtrowane do timestampowych przy polu `timestamp_column`

---

### S-05 — Rule builder UI

**Wynik:** Formularz tworzenia reguły ma dynamiczne dropdowny: po wyborze Connection
ładuje się lista schematów/tabel, po wyborze tabeli — lista kolumn timestampowych
do wyboru.

**Prerequisites:** S-04

**Change ID:** DP-005

**Status:** proposed

**Decyzje architektoniczne:**
- Pola `schema_name` i `table_name` zamieniają się na `<select>` po wyborze Connection
- Fallback: jeśli Connection = default (env) lub błąd → zwykłe `<input type="text">`
- `timestamp_column` filtruje kolumny po typach: `timestamp`, `timestamptz`, `date`
- UX: loading spinner w dropdown podczas fetcha

---

### S-06 — Custom SQL rule ⭐ (gwiazda przewodnia M-02)

**Wynik:** Użytkownik może zdefiniować regułę jako własne zapytanie SQL, które musi
zwrócić dokładnie jeden wiersz z jedną kolumną o wartości `true` (OK) lub `false`/`0` (FAIL).

**Prerequisites:** S-03

**Change ID:** DP-006

**Status:** proposed

**Decyzje architektoniczne:**
- Nowe pole `Rule.rule_type` — choices: `volume_freshness` (dotychczasowy), `custom_sql`
- Nowe pole `Rule.custom_sql` — TextField, nullable
- `services.py` — nowa gałąź `_check_rule`: jeśli `rule_type == custom_sql`, wykonaj SQL
  i sprawdź czy wynik to truthy value
- Walidacja SQL: musi być `SELECT` (nie `INSERT/UPDATE/DELETE/DROP`) — regex w `clean()`
- Formularz: radio "Rule type" przełącza między sekcją volume/freshness a polem SQL
- Wynik FAIL gdy zapytanie zwróci `false`, `0`, `f`, `no`, pusty zbiór lub NULL

**Implikacje dla kodu:**
- `monitor/models.py` — `rule_type`, `custom_sql`
- `monitor/migrations/` — 0004
- `monitor/services.py` — `_check_custom_sql(conn, rule)`
- `monitor/forms.py` — walidacja SQL + warunkowe wymaganie pól
- `templates/monitor/rule_form.html` — toggle sekcji

---

### S-07 — Dashboard filters

**Wynik:** Użytkownik może filtrować listę reguł na dashboardzie po: statusie
(OK/FAIL/ERROR/No data), połączeniu (dropdown), nazwie (szukajka tekstowa).
Filtry nie wymagają przeładowania strony — działają po stronie klienta (JS).

**Prerequisites:** S-03, S-08

**Change ID:** DP-007

**Status:** proposed

**Decyzje architektoniczne:**
- Filtrowanie client-side (nie server-side) — mała liczba reguł (< 200), brak sensu na osobne zapytania
- Stan filtrów w URL params — `?status=FAIL&conn=1` — shareable link
- Komponent: pasek filtrów nad tabelą, 3 kontrolki: status multi-select, connection select, text search
- Licznik aktywnych filtrów widoczny na pasku

---

### S-08 — Connection badge na liście reguł

**Wynik:** W tabeli reguł na dashboardzie widoczna jest nazwa połączenia (lub "default")
jako badge przy każdej regule. Jeden rzut oka pokazuje z której bazy pochodzi reguła.

**Prerequisites:** S-03

**Change ID:** DP-008

**Status:** proposed

**Decyzje architektoniczne:**
- Nowa kolumna "Source" w tabeli reguł
- Badge: ikona + nazwa Connection albo "env" jeśli default
- Kliknięcie w badge filtruje dashboard do tego połączenia (łączy z S-07)

---

## Blocking unknowns — M-02

- **BU-03:** Czy `information_schema` jest dostępne dla użytkownika Supabase pooler?
  Supabase ogranicza niektóre widoki systemowe dla połączeń przez pooler (port 6543).
  Może wymagać direct connection (port 5432) tylko do introspection.
- **BU-04:** Limit długości custom SQL — czy potrzeba walidacji długości i timeout zapytania?
  Zabezpieczenie przed bardzo wolnymi zapytaniami wymaga `statement_timeout` w psycopg2.

---

## Done — M-01

- F-01, F-02, F-03, F-04 — deploy pipeline, whitenoise, Supabase
- H-01 — requirements.txt
- S-01 — US-01 end-to-end na produkcji
- S-02 — historia wyników per reguła
- S-03 — connection management przez UI

---
---
milestone_seq: 3
milestone_id: m-03-large-scale
milestone_status: open
main_goal: quality
north_star: S-11
top_blocker: repo-map
---

## Milestone

**M-03 — Large Scale & Legacy + AI-Native Teamwork**

Status: open
Źródło: kurs 10xDevs M4 + M5 — nowe rozdziały

Zakres: zastosowanie wzorca Wide Scan → Deep Focus, mapa projektu,
agent code review w CI/CD, Shared AI Registry dla zespółu BIT.

---

## At a glance — M-03

| ID | Slice | Prereqs | Status |
|---|---|---|—|
| S-09 | Repo map — Wide Scan, context/map/repo-map.md (M4L2) | — | done |
| S-10 | Agent code review w CI — GitHub Actions Composite Action (M5L2) | S-09 | proposed |
| S-11 | Shared AI Registry — skille DataPulse jako paczka npm (M5L4) ⭐ | S-10 | proposed |

---

## Slices — M-03

### S-09 — Repo map (Wide Scan)

**Wynik:** Dokument `context/map/repo-map.md` z mapą projektu DataPulse:
aktywne obszary, punkty wejścia, zależności, ryzyka, niezwiadome.
Gotowy do użycia przez agenta w kolejnych sesjach.

**Change ID:** repo-map

**Metoda:** Wide Scan z M4L2 — 3 artefakty robocze → synteza.

**Status:** in-progress

---

### S-10 — Agent code review w CI

**Wynik:** GitHub Actions workflow uruchamia agenta na każdy PR.
Agent ocenia diff według kryteriów z M5L2 i zostawia komentarz.

**Change ID:** ci-code-review

**Prereqs:** S-09 (mapa projektu jako kontekst dla agenta)

**Status:** proposed

---

### S-11 — Shared AI Registry ⭐ (gwiazda M-03)

**Wynik:** Skille i reguły DataPulse spakowane jako paczka npm
w GitHub Packages. Zespół BIT instaluje przez `npm install`.

**Change ID:** shared-ai-registry

**Prereqs:** S-10

**Status:** proposed

---

## Milestone History

- **M-01** zamknięty 2026-10-25. Wszystkie slices done. Aplikacja live na Render.
  Post-MVP delivery: login/auth, side navbar, per-rule run, schedule, seed demo, dark UI.
