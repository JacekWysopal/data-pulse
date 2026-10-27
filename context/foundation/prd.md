---
project: "DataPulse"
version: 1
status: draft
created: 2026-09-17
context_type: greenfield
product_type: web-app
target_scale:
  users: small
  qps: low
  data_volume: small
timeline_budget:
  mvp_weeks: 3
  hard_deadline: null
  after_hours_only: true
---

## Vision & Problem Statement

Osoby pracujące z danymi — BI developerzy, data engineerzy — nie mają prostego narzędzia do weryfikacji, czy dane w tabelach PostgreSQL są aktualne i kompletne. Odkrycie problemu z jakością danych następuje zbyt późno: po tym jak błędne lub nieświeże dane trafiają do raportów i dashboardów. Dziś sprawdzanie świeżości i wolumenu odbywa się ręcznie — przez `SELECT COUNT(*)`, `MAX(updated_at)` i podobne zapytania uruchamiane ad hoc, per tabela, bez historii wyników.

Brakującym ogniwem jest narzędzie, które zamienia te jednorazowe zapytania w trwałe, nazwane reguły i pozwala uruchomić je jednym kliknięciem, zobaczyć wynik per reguła i prześledzić historię w czasie. DataPulse wypełnia tę lukę bez schedulera, alertów ani złożonej konfiguracji.

## User & Persona

**Primary persona:** BI developer lub data engineer pracujący w organizacji używającej PostgreSQL jako źródła danych dla raportów i dashboardów. Zna SQL, rozumie strukturę swoich baz danych. Sprawdza jakość danych przed oddaniem pracy, po incydencie z błędnymi danymi lub w ramach rutynowego monitoringu. Nie potrzebuje narzędzia enterprise — potrzebuje czegoś, co działa szybko i nie wymaga konfigurowania infrastruktury.

## Success Criteria

### Primary
Użytkownik definiuje reguły dla tabel PostgreSQL, klika „Uruchom sprawdzenie" i widzi wynik per reguła (OK / FAIL / NEVER RUN) z wartością zmierzoną obok progu. Historia wyników jest zapisywana i dostępna do przeglądania.

### Secondary
Możliwość drill-down na historię konkretnej reguły — tabela lub wykres ostatnich N wyników w czasie z możliwością oceny trendu.

### Guardrails
- Connection string do PostgreSQL nie jest nigdy wyświetlany w UI, logowany ani zapisywany poza plikiem .env.
- Błąd połączenia z bazą lub błąd pojedynczego zapytania SQL nie crasha aplikacji — użytkownik widzi czytelny komunikat błędu dla danej reguły, pozostałe reguły są sprawdzane dalej.

## User Stories

### US-01: Pierwsze sprawdzenie

- **Given** użytkownik skonfigurował .env z connection stringiem do PostgreSQL i ma zdefiniowaną co najmniej jedną regułę
- **When** klika przycisk „Uruchom sprawdzenie"
- **Then** aplikacja wykonuje zapytania do PostgreSQL dla każdej reguły i wyświetla status (OK / FAIL / ERROR) z wartością zmierzoną obok progu

#### Acceptance Criteria
- Każda reguła wyświetla status (OK / FAIL / ERROR) i zmierzoną wartość (np. „12 340 wierszy, próg: 10 000" lub „3h temu, próg: 1h")
- Błąd połączenia z bazą wyświetla komunikat zamiast krachu aplikacji
- Błąd dla jednej reguły nie zatrzymuje sprawdzania pozostałych

### US-02: Diagnoza problemu przez historię reguły

- **Given** sprawdzenie zakończyło się i co najmniej jedna reguła ma status FAIL
- **When** użytkownik klika w tę regułę
- **Then** widzi historię jej wyników z ostatnich przebiegów — timestamp, status, wartość zmierzona

#### Acceptance Criteria
- Historia jest posortowana od najnowszego do najstarszego
- Każdy wpis zawiera: timestamp przebiegu, status (OK / FAIL / ERROR), zmierzoną wartość
- Brak historii (reguła NEVER RUN) wyświetla odpowiedni komunikat

## Functional Requirements

### Konfiguracja połączenia
- FR-001: Użytkownik może skonfigurować połączenie z PostgreSQL przez zmienne środowiskowe (plik .env). Priority: must-have.
  > Socratic: Counter-argument: "UI do konfiguracji connection stringu byłby wygodniejszy." Resolution: odrzucone — connection string to dane wrażliwe, .env jest standardem bezpieczeństwa. UI-based config post-MVP.

### Zarządzanie regułami
- FR-002: Użytkownik może dodać regułę monitoringu dla tabeli (schemat.tabela + opcjonalna kolumna timestampowa + opcjonalna minimalna liczba wierszy; co najmniej jeden z dwóch warunków wymagany). Priority: must-have.
  > Socratic: Counter-argument: "Co jeśli użytkownik nie zna nazwy kolumny timestampowej?" Resolution: pole opcjonalne — reguła tylko wolumenu jest w pełni poprawna.

- FR-003: Użytkownik może edytować istniejącą regułę. Priority: must-have.
  > Socratic: Counter-argument: "Edycja powinna tworzyć nową wersję reguły." Resolution: edycja in-place wystarczy w MVP — wersjonowanie reguł to post-MVP.

- FR-004: Użytkownik może usunąć regułę. Priority: must-have.
  > Socratic: Counter-argument: "Usunięcie reguły usuwa też jej historię?" Resolution: historia orphaned records pozostaje w SQLite — do decyzji implementacyjnej. Patrz Open Questions.

### Uruchamianie sprawdzeń
- FR-005: Użytkownik może uruchomić sprawdzenie wszystkich reguł naraz jednym kliknięciem. Priority: must-have.
  > Socratic: Counter-argument: "Sprawdzenie wszystkich tabel może być wolne." Resolution: akceptowalne w MVP — każda reguła to jedno zapytanie SQL; równoległość post-MVP.

### Widok statusu
- FR-006: Użytkownik widzi listę reguł ze statusem per reguła (OK / FAIL / NEVER RUN / ERROR) po ostatnim przebiegu. Priority: must-have.
  > Socratic: Counter-argument: "NEVER RUN to zbędny status — wystarczy brak daty." Resolution: explicit status jest czytelniejszy niż pusta data.

- FR-007: Użytkownik widzi dla każdej reguły zmierzoną wartość (liczba wierszy lub wiek ostatniego rekordu) obok zdefiniowanego progu. Priority: must-have.
  > Socratic: Counter-argument: "Samo OK/FAIL wystarczy." Resolution: odrzucone — wartość zmierzona jest krytyczna do diagnozy problemu.

### Historia wyników
- FR-008: Użytkownik widzi podsumowanie każdego przebiegu (timestamp + liczba OK / liczba FAIL / liczba ERROR). Priority: must-have.
  > Socratic: Counter-argument: "Historia jest zbędna przy ręcznym uruchamianiu." Resolution: historia pozwala wykryć wzorce i udokumentować jakość danych.

- FR-009: Użytkownik może kliknąć w regułę i zobaczyć historię jej wyników w czasie (tabela lub wykres ostatnich N przebiegów). Priority: must-have.
  > Socratic: Counter-argument: "Drill-down to nice-to-have." Resolution: uznane za must-have — bez drill-down historia przebiegów jest mało użyteczna diagnostycznie.

## Non-Functional Requirements

- Connection string do PostgreSQL nie opuszcza środowiska wykonania — nie jest wyświetlany w UI, logowany w plikach, wysyłany do zewnętrznych usług ani zapisywany poza plikiem .env.
- Błąd dla pojedynczej reguły (timeout zapytania, nieistniejąca tabela, brak uprawnień) nie przerywa przebiegu dla pozostałych reguł — każdy błąd jest rejestrowany osobno ze statusem ERROR.
- Aplikacja pozostaje użyteczna przy ~50 regułach bez zauważalnego spowolnienia UX (sekwencyjne zapytania, akceptowalny czas oczekiwania).
- Wielu użytkowników może korzystać z aplikacji jednocześnie przez Streamlit server mode bez wzajemnego zakłócania sesji.

## Business Logic

**Reguła domeny:** Aplikacja ocenia każdą tabelę PostgreSQL względem progów zdefiniowanych przez użytkownika i klasyfikuje wynik jako OK lub FAIL na podstawie aktualnego stanu danych.

Dla reguły wolumenu: aplikacja mierzy liczbę wierszy w tabeli i porównuje z progiem minimalnym — FAIL jeśli liczba wierszy jest niższa od progu. Dla reguły freshness: aplikacja mierzy wiek ostatniego rekordu w kolumnie timestampowej wskazanej przez użytkownika i porównuje z progiem maksymalnego wieku — FAIL jeśli ostatni rekord jest starszy niż próg. Gdy reguła definiuje oba warunki jednocześnie, wynik jest FAIL jeśli którykolwiek z warunków nie jest spełniony.

Wynik każdego przebiegu jest utrwalany w lokalnej bazie SQLite — wraz z timestampem, statusem i zmierzonymi wartościami — tworząc historię jakości danych dostępną do późniejszego przeglądania.

## Access Control

Brak uwierzytelniania w MVP — aplikacja działa w zaufanej sieci wewnętrznej. Wielu użytkowników może korzystać jednocześnie (Streamlit server mode). Brak ról — wszyscy użytkownicy mają identyczne uprawnienia do zarządzania regułami i przeglądania historii.

## Non-Goals

- **Scheduler / automatyczne uruchamianie sprawdzeń** — sprawdzanie jest wyłącznie ręczne w MVP.
- **Alerty email lub inne powiadomienia** — brak kanału powiadomień w MVP.
- **Obsługa wielu instancji PostgreSQL w MVP** — jeden connection string w MVP (S-01/S-02). Connection management przez UI wchodzi jako S-03 post-deploy (uzgodniono 2026-09-23: model Connection z zaszyfrowanym URL, granulacja per projekt/środowisko).
- **Status WARNING (próg ostrzegawczy)** — binarne OK/FAIL wystarczy w MVP; progi ostrzegawcze to post-MVP.
- **Wersjonowanie reguł** — edycja in-place bez historii zmian konfiguracji.
- **Uwierzytelnianie i autoryzacja użytkowników** — dostęp niekontrolowany w MVP (zaufana sieć).
- **Eksport wyników** — brak eksportu do CSV/Excel/API w MVP.
- **Równoległe wykonywanie zapytań** — zapytania sekwencyjne w MVP; równoległość post-MVP.

## Open Questions

1. **Co dzieje się z historią reguły po jej usunięciu?** — Czy rekordy historii w SQLite są usuwane razem z regułą (cascade delete), czy pozostają jako orphaned records? Owner: użytkownik / implementator. Block: nie (decyzja implementacyjna, nie blokuje MVP).
2. **Ile ostatnich przebiegów wyświetlać w drill-down per reguła (domyślna wartość N)?** — Propozycja: 20 ostatnich przebiegów lub ostatnie 30 dni, cokolwiek jest mniejsze. Owner: użytkownik. Block: nie (można domyślnie 20, zmienialne w konfiguracji).
