---
project: DataPulse
context_type: greenfield
checkpoint:
  current_phase: 6
  phases_completed: [1, 2, 3, 4, 5, 6]
  frs_drafted: 9
  quality_check_status: accepted
---

## Vision & Problem Statement

**Pain:** Osoby pracujące z danymi (BI developerzy, data engineerzy) nie mają szybkiego, prostego sposobu na weryfikację, czy dane w ich tabelach PostgreSQL są aktualne i kompletne. Odkrycie problemu z jakością danych następuje zbyt późno — po tym jak błędne dane trafią do raportów lub dashboardów.

**Person:** Osoba pracująca z danymi — BI developer, data engineer lub inna osoba odpowiedzialna za jakość danych w organizacji.

**Moment:** Przed uruchomieniem raportu lub dashboardu, albo po incydencie z błędnymi danymi — kiedy ktoś musi ręcznie sprawdzać `SELECT COUNT(*)`, `MAX(updated_at)` i podobne zapytania na wielu tabelach.

**Cost today:** Ręczne sprawdzanie wielu tabel jest czasochłonne, podatne na pominięcia i nieudokumentowane — każdy sprawdza po swojemu, brak historii wyników.

## User & Persona

**Primary persona:** Osoba pracująca z danymi (BI developer / data engineer) w organizacji korzystającej z PostgreSQL jako źródła danych dla raportów i dashboardów. Zna SQL, rozumie strukturę swoich baz danych, chce szybko zweryfikować stan danych przed oddaniem pracy lub w ramach rutynowego monitoringu.

## Access Control

Wielodostęp — wielu użytkowników jednocześnie (Streamlit multi-user). Brak uwierzytelniania w MVP — aplikacja działa w zaufanej sieci wewnętrznej.

> Decyzja: brak auth w MVP, wielu równoczesnych użytkowników obsługiwanych przez Streamlit server mode.

## Success Criteria

### Primary
Użytkownik definiuje reguły dla tabel PostgreSQL, klika „Uruchom sprawdzenie", widzi wynik per reguła (OK / FAIL / NEVER RUN) i historię poprzednich sprawdzeń.

### Secondary
Możliwość drill-down na historię konkretnej reguły — wykres/tabela ostatnich N wyników w czasie.

### Guardrails
- Connection string do PostgreSQL nie jest nigdy wyświetlany w UI ani logowany.
- Błąd połączenia z bazą nie crasha aplikacji — użytkownik widzi czytelny komunikat.

## Functional Requirements

### Konfiguracja połączenia
- FR-001: Użytkownik może skonfigurować połączenie z PostgreSQL przez zmienne środowiskowe (plik .env). Priority: must-have.
  > Socrates: Counter-argument: "UI do konfiguracji connection stringu byłby wygodniejszy." Resolution: odrzucone — connection string to dane wrażliwe, nie powinny być edytowane przez UI. .env jest standardem bezpieczeństwa.

### Zarządzanie regułami
- FR-002: Użytkownik może dodać regułę monitoringu dla tabeli (schemat.tabela + opcjonalna kolumna timestampowa + opcjonalna minimalna liczba wierszy). Priority: must-have.
  > Socrates: Counter-argument: "Co jeśli użytkownik nie zna nazwy kolumny timestampowej?" Resolution: pole opcjonalne — reguła tylko wolumenu jest w pełni poprawna. UI może w przyszłości podpowiadać kolumny.

- FR-003: Użytkownik może edytować istniejącą regułę. Priority: must-have.
  > Socrates: Counter-argument: "Czy edycja nie powinna tworzyć nowej wersji reguły?" Resolution: w MVP edycja in-place wystarczy — wersjonowanie reguł to funkcja post-MVP.

- FR-004: Użytkownik może usunąć regułę. Priority: must-have.
  > Socrates: Counter-argument: "Usunięcie reguły usuwa też jej historię?" Resolution: historia powiązana z usuniętą regułą pozostaje w SQLite (soft-delete lub orphaned records). Do decyzji na etapie implementacji.

### Uruchamianie sprawdzeń
- FR-005: Użytkownik może uruchomić sprawdzenie wszystkich reguł naraz (jeden przebieg). Priority: must-have.
  > Socrates: Counter-argument: "Sprawdzenie wszystkich tabel może być wolne przy dużej liczbie reguł." Resolution: akceptowalne w MVP — każda reguła to jedno zapytanie SQL, kolejkowanie/równoległość to post-MVP.

### Widok statusu
- FR-006: Użytkownik widzi listę reguł ze statusem per reguła (OK / FAIL / NEVER RUN) po ostatnim przebiegu. Priority: must-have.
  > Socrates: Counter-argument: "Czy NEVER RUN jest potrzebny — wystarczy brak daty?" Resolution: explicit status jest czytelniejszy niż pusta data — użytkownik od razu wie, że reguła nie była jeszcze sprawdzana.

- FR-007: Użytkownik widzi dla każdej reguły zmierzoną wartość (liczba wierszy, wiek ostatniego rekordu) obok progu. Priority: must-have.
  > Socrates: Counter-argument: "Samo OK/FAIL wystarczy." Resolution: odrzucone — wartość zmierzona (np. "3h ago vs próg 1h") jest krytyczna do diagnozy problemu.

### Historia wyników
- FR-008: Użytkownik widzi podsumowanie każdego przebiegu (timestamp + liczba OK / liczba FAIL). Priority: must-have.
  > Socrates: Counter-argument: "Historia jest zbędna jeśli sprawdzamy ręcznie." Resolution: odrzucone — historia pozwala wykryć wzorce (np. dane zawsze nie świeże w poniedziałek rano).

- FR-009: Użytkownik może kliknąć w regułę i zobaczyć historię jej wyników w czasie (tabela lub wykres). Priority: must-have.
  > Socrates: Counter-argument: "Drill-down to nice-to-have, nie must-have." Resolution: uznane za must-have — bez drill-down historia przebiegów jest mało użyteczna.

## User Stories

### US-01: Pierwsze sprawdzenie
**Given** użytkownik skonfigurował .env z connection stringiem do PostgreSQL i ma zdefiniowaną co najmniej jedną regułę,
**When** klika przycisk „Uruchom sprawdzenie",
**Then** aplikacja wykonuje zapytania do PostgreSQL dla każdej reguły i wyświetla status (OK / FAIL) z wartością zmierzoną obok progu.

### US-02: Diagnoza problemu
**Given** sprawdzenie zakończyło się i co najmniej jedna reguła ma status FAIL,
**When** użytkownik klika w tę regułę,
**Then** widzi historię jej wyników z ostatnich N przebiegów — timestamp, status, wartość zmierzona.

## Business Logic

**Reguła domeny (jednozdaniowa):** Aplikacja ocenia każdą tabelę PostgreSQL względem progów zdefiniowanych przez użytkownika i klasyfikuje ją jako OK lub FAIL na podstawie aktualnego stanu danych.

**Logika oceny reguły:**
1. Dla reguły wolumenu: wykonaj `SELECT COUNT(*) FROM schemat.tabela` i porównaj z `min_row_count`. FAIL jeśli `count < min_row_count`.
2. Dla reguły freshness: wykonaj `SELECT MAX(kolumna_timestamp) FROM schemat.tabela` i oblicz wiek w godzinach. FAIL jeśli `wiek > max_age_hours`.
3. Jeśli reguła ma oba warunki: FAIL jeśli **którykolwiek** warunek jest niespełniony.
4. Status NEVER RUN: reguła istnieje ale nie ma żadnego wpisu w historii.

**Przechowywanie:**
- Definicje reguł → schemat `datapulse.rules` w monitorowanym PostgreSQL
- Historia wyników → SQLite lokalnie (`datapulse.db` obok aplikacji)
- Connection string → zmienne środowiskowe / plik `.env`

## Non-Functional Requirements

- **Bezpieczeństwo:** Connection string nigdy nie jest wyświetlany w UI, logowany ani zapisywany poza plikiem .env.
- **Dostępność:** Aplikacja działa na lokalnym serwerze Streamlit dostępnym w sieci wewnętrznej; wielodostęp przez Streamlit server mode.
- **Odporność na błędy:** Błąd połączenia z bazą lub błąd zapytania SQL dla jednej reguły nie przerywa sprawdzania pozostałych reguł — błąd jest rejestrowany i wyświetlany jako osobny status (ERROR).
- **Wydajność:** Każda reguła to jedno zapytanie SQL — brak równoległości w MVP; akceptowalne dla ~50 reguł.

## Non-Goals (MVP)

- Scheduler / automatyczne uruchamianie sprawdzeń
- Alerty email lub inne powiadomienia
- Obsługa wielu instancji PostgreSQL
- Status WARNING (próg ostrzegawczy)
- Wersjonowanie reguł
- Uwierzytelnianie użytkowników
- Eksport wyników

## Open Questions

- Czy historia dla usuniętej reguły powinna być zachowana czy usunięta razem z regułą?
- Ile ostatnich przebiegów wyświetlać w drill-down per reguła (domyślnie N=?)?
