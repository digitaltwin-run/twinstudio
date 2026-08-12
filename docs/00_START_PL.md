# Start projektu — skrócona instrukcja po polsku

## 1. Co pobierasz

Paczka źródłowa zawiera aplikację, model danych, interfejs webowy, usługę API, CQRS/Event Sourcing, konfigurację Docker, Protobuf, MQTT/MCP, przykład urządzenia Raspberry Pi 5 + Camera Module 3, modele STEP/STL, rzuty SVG, materiały referencyjne, scenariusze symulacji i kompletny plan lifecycle.

Projekt przykładowy można także przekazywać niezależnie jako `demo-rpi5.twinstudio.zip`. Ten format zachowuje snapshot, eventy, unified specification/xBOM, artefakty, manifest i sumy SHA-256.

## 2. Uruchomienie Docker

```bash
cp .env.example .env
docker compose up --build
```

Następnie otwórz:

```text
http://localhost:8000       aplikacja
http://localhost:8000/docs  REST/OpenAPI
http://localhost:8025       Mailpit — decyzje dostępu
```

Pełny zestaw usług:

```bash
docker compose \
  --profile cad \
  --profile integration \
  --profile simulation \
  --profile openwebui \
  --profile object-store \
  up --build
```

## 3. Typowa zmiana geometrii

1. Wybierz część lub podzespół w drzewie.
2. Wskaż fragment kursorem, ołówkiem, lassem albo prostokątem w 3D lub 2D.
3. Wpisz uwagę albo polecenie naturalne.
4. System tworzy `SelectionMap`, a następnie walidowany `ChangePlan` ograniczony do zaznaczonego POA URI.
5. Sprawdź plan 2D/parametry, skutki i pytania nierozstrzygnięte.
6. Zatwierdź bezpieczną część planu.
7. Operacje scalar są zapisywane jako eventy; allow-listed hole/local-box trafia do workera CAD; reszta pozostaje do review/adapera natywnego CAD.
8. Pobierz nową rewizję i artefakty.

System nie powinien automatycznie zmieniać obszaru, którego nie da się powiązać z trwałym obiektem/cechą/powierzchnią. Zaznaczenie fotografii bez kalibracji pozostaje adnotacją lub zadaniem do doprecyzowania.

## 4. Role

- `reader` — odczyt projektu i pobieranie zatwierdzonych artefaktów;
- `editor` — uwagi, zaznaczenia, plany i dozwolone zmiany;
- `admin` — użytkownicy, konfiguracja projektu i akceptacje operacyjne;
- `creator` — właściciel projektu i ostateczne decyzje.

Osoba zewnętrzna podaje email i rolę. Decydent dostaje email approve/reject. Po akceptacji użytkownik otrzymuje link jednorazowy, sesję oraz osobisty token do HTTP Basic `email:token`.

## 5. Najważniejsze ograniczenia

- Swobodna edycja dowolnej powierzchni CAD nie jest jeszcze ogólnym solverem; działają trzy kontrolowane operacje pochodne STEP.
- PCB/SCH to model danych i adapter KiCad CLI, nie autorouter ani synteza układu.
- Modele prądowe i termiczne są estymacją redukowaną, a nie certyfikowaną symulacją ani pomiarem.
- Kontener RPi/kamery testuje software i dane, ale nie emuluje fizycznego Raspberry Pi.
- Ocena człowieka to scenariusz i reguły, nie biomechaniczny avatar.
- GTIN/EAN wymaga legalnej alokacji właściciela w GS1; narzędzie oblicza tylko cyfrę kontrolną.

Pełny opis znajduje się w `docs/16_MASTER_PRODUCT_LIFECYCLE_BLUEPRINT_PL.md`, a stan implementacji w `docs/IMPLEMENTATION_STATUS.md`.
