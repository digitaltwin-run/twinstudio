# TwinStudio 0.5.0 — indeks paczki

## Najważniejsze pliki

- `README.md` — architektura, instalacja, DSL i interfejsy.
- `RELEASE_NOTES_PL.md` — zakres wydania, testy i ograniczenia.
- `docs/18_PROJECT_EVOLUTION_DSL_PL.md` — metody ewolucji projektu i przeciwdziałanie fiksacji.
- `docs/19_TWINSCRIPT_API_REFERENCE.md` — składnia DSL, schema, REST, CLI i MCP.
- `docs/IMPLEMENTATION_STATUS.md` — macierz stanu funkcji.
- `docs/VERIFICATION.md` — zapis wykonanych kontroli.
- `schemas/` — JSON Schema Draft 2020-12, indeks oraz EBNF TwinScript.
- `examples/evolution/` — równoważne przykłady `.twin`, YAML i JSON oraz wygenerowany raport demonstracyjny.
- `src/twinstudio/` — API, CQRS/ES, auth, POA, LiteLLM, feature lenses, evolution engine, DSL, lifecycle, MCP i web UI.
- `components/housing-studio/` — parametryczny generator obudowy 2D/3D.
- `services/cad-worker/` — ograniczony adapter zaznaczonego obszaru STEP/B-Rep.
- `examples/rpi5-camera3/` — demonstracyjny projekt urządzenia oraz zweryfikowany `demo-rpi5.twinstudio.zip`.
- `proto/lps/v1/` — zachowana przestrzeń kontraktów przewodowych dla kompatybilności.

## Uruchomienie

```bash
cp .env.example .env
docker compose up --build
```

Aplikacja: `http://localhost:8000`  
OpenAPI: `http://localhost:8000/docs`  
Mailpit: `http://localhost:8025`

Lokalnie:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[llm,dev]"
twinstudio seed
twinstudio serve
```

## Najkrótszy workflow ewolucji

```bash
twinstudio dsl-preview examples/evolution/rpi5-hinge-evolution.twin \
  --project-id demo-rpi5
```

Po przeglądzie kandydatów:

```bash
twinstudio dsl-apply examples/evolution/rpi5-hinge-evolution.twin \
  --project-id demo-rpi5 --execute
```

Domyślny tryb jest bezpieczny: podgląd nie zapisuje zdarzeń. Wykonanie zapisuje `EvolutionRun`, blueprint lifecycle, typowane `ChangePlan` oraz artefakty raportowe; nie oznacza automatycznego dowodu poprawności konstrukcji.

## Zakres działającego MVP

- drzewo produktu, xBOM, artefakty i POA;
- zaznaczenia 2D/3D i kontrolowany NL → `ChangePlan`;
- 49 aktywnych soczewek źródłowych oraz jawna luka pięćdziesiątej pozycji;
- katalog czasowników, graf celu i zasobów, adjacent possible, mutacje, rekombinacja i eksperymenty;
- 34 rozszerzone wymiary inżynierskie i 17 operatorów ewolucji;
- TwinScript/YAML/JSON, JSON Schema, EBNF, REST, CLI, MCP i edytor webowy;
- lifecycle sprzętowy, cyfrowy i ciągłej ewolucji;
- CQRS/Event Sourcing, role i optimistic concurrency;
- eksport `.twinstudio.zip` z manifestem SHA-256;
- redukowane modele power/thermal, human-use, reguły mechaniczne i FMEA.

## Jawne granice

Brak dowolnej edycji każdej powierzchni B-Rep, rekonstrukcji historii SolidWorks, automatycznej geometrii ze zdjęcia bez kalibracji, kompletnego edytora/autoroutera PCB, CFD/FEA, pełnej emulacji Raspberry Pi i biomechanicznego digital-human. Kandydaci ewolucji wymagają prototypów i evidence przed akceptacją.
