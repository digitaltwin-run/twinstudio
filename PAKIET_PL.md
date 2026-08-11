# Pakiet Living Product Studio — indeks odbiorczy

## Najważniejsze elementy

- `README.md` — instalacja, uruchomienie i przegląd funkcji.
- `RELEASE_NOTES_PL.md` — zakres wydania 0.3.0, testy i granice.
- `docs/00_START_PL.md` — szybkie uruchomienie i podstawowy workflow po polsku.
- `docs/16_MASTER_PRODUCT_LIFECYCLE_BLUEPRINT_PL.md` — kompletny plan platformy i cyklu życia produktu.
- `docs/17_REQUIREMENTS_TRACEABILITY_PL.md` — macierz każdego wymagania, modułu, statusu i kryterium odbioru.
- `docs/IMPLEMENTATION_STATUS.md` — macierz: zaimplementowane / scaffold / roadmap.
- `docs/VERIFICATION.md` oraz `docs/verification-report.json` — wykonane testy i jawne ograniczenia.
- `compose.yaml` — środowisko Docker z profilami CAD, integracji, symulacji, Open WebUI i storage.
- `src/living_product_studio/` — API, CQRS/ES, auth, POA, planner LiteLLM, symulacje, MCP i UI.
- `proto/lps/v1/` — kontrakty Protobuf DSL.
- `services/cad-worker/` — generator obudowy oraz ograniczony adapter zaznaczonego regionu STEP/B-Rep.
- `services/mqtt-gateway/` — most MQTT → REST.
- `services/device-sim/` — symulator telemetrii urządzenia.
- `examples/rpi5-camera3/` — żywy projekt przykładowego urządzenia.
- `examples/rpi5-camera3/demo-rpi5.lps.zip` — przenośny eksport projektu.
- `examples/rpi5-camera3/scoped-edit-demo/` — działający przykład zaznaczenie → lokalny otwór → STEP/STL/journal.

## Uruchomienie

```bash
cp .env.example .env
docker compose up --build
```

Aplikacja: `http://localhost:8000`  
OpenAPI: `http://localhost:8000/docs`  
Mailpit: `http://localhost:8025`

Profil CAD:

```bash
docker compose --profile cad up --build
```

Wszystkie opcjonalne warstwy:

```bash
docker compose \
  --profile cad \
  --profile integration \
  --profile simulation \
  --profile openwebui \
  --profile object-store \
  up --build
```

## Co jest działającym MVP

- drzewo obiektów i xBOM;
- zaznaczenia pointer/pencil/lasso/rectangle w 3D oraz adnotacje 2D;
- rozwiązywanie zaznaczeń do obiektów/cech/powierzchni semantycznych;
- prompt naturalny → walidowany `ChangePlan` przez LiteLLM lub parser lokalny;
- blokada modyfikacji poza zaznaczonym zakresem POA;
- event-sourced zmiany parametrów;
- ograniczony lokalny adapter STEP: otwór oraz axis-aligned local-box add/cut;
- role reader/editor/admin/creator i email approval onboarding;
- REST, CLI, shell, MQTT, WebSocket i MCP 2026-07-28 core (`server/discover`, tools/resources, wymagane metadane i nagłówki) z legacy initialize;
- specyfikacja wielotechnologiczna, test plans, lifecycle, FMEA, power/thermal i human-use;
- eksport `.lps.zip` ze snapshotem, eventami, artefaktami i hashami.

## Najważniejsze granice

Nie są gotowe: dowolna swobodna edycja każdego fragmentu B-Rep, rekonstrukcja natywnej historii SolidWorks, automatyczna dokładna geometria ze zdjęcia bez kalibracji, produkcyjny PCB/SCH autorouter, CFD/FEA, emulacja Raspberry Pi i pełny digital-human. Ograniczenia są opisane w macierzy implementacji i raporcie weryfikacji. MCP nie obejmuje jeszcze SSE/MRTR/OAuth server, a połączenie z konkretną wersją Open WebUI pozostaje testem wdrożeniowym.
