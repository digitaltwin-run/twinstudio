# Living Product Studio 0.3.0 — informacje o wydaniu

Data pakietu: 2026-08-11.

## Cel wydania

Wydanie rozszerza generator obudowy w kierunku event-sourced platformy „żywego produktu”: od materiałów źródłowych, przez drzewo obiektów, zaznaczenia 2D/3D i ograniczone zmiany naturalnym językiem, po xBOM, symulacje, testy, lifecycle, software i ofertę ecommerce.

## Najważniejsze funkcje

- wybór obiektu, podzespołu lub obszaru bryły kursorem, ołówkiem, lassem i prostokątem;
- zapis evidence zaznaczenia oraz rozwiązanie do `SelectionMap` i POA URI;
- NL → walidowany `ChangePlan` przez LiteLLM lub parser deterministyczny;
- ścisłe blokowanie operacji poza wybranym zakresem;
- parametryczne zmiany oraz kontrolowany adapter STEP/B-Rep: hole i local-box add/cut;
- widok drzewa obiektów, cech, parametrów, artefaktów i wariantów produkcji;
- unified project snapshot, xBOM i routing FDM/CNC/purchase/PCB/software/packaging/reference;
- współpraca mailowa, role reader/editor/admin/creator i HTTP Basic `email:PAT`;
- CQRS, Event Sourcing, Protobuf DSL, POA, REST, CLI, shell, MQTT i MCP;
- projekt przykładowy RPi5 + Camera Module 3 z STEP/STL/SVG, evidence, software i symulacjami;
- power/voltage-drop, thermal RC, camera sample replay, human-use, mechanical rules, FMEA i lifecycle;
- przenośny `.lps.zip` ze snapshotem, eventami, specification, artefaktami, manifestem i SHA-256.

## Zmiany 0.3.0

- dodano rdzeń MCP 2026-07-28: `server/discover`, wymagane metadane, nagłówki lustrzane, `resultType`, cache metadata i walidację `Origin`;
- pozostawiono jawny legacy `initialize` dla klientów 2025-11-25;
- dodano narzędzia MCP do human-use i mechanical rules;
- rozszerzono testy MCP i REST;
- dodano polski indeks startowy, plan lifecycle oraz macierz śledzenia wymagań.

## Zweryfikowano

- 26 testów automatycznych;
- kompilację źródeł Python;
- składnię JavaScript przez `node --check`;
- spójność 24 przykładowych artefaktów i ich hashy;
- działający wybrany-region → lokalny hole cut → poprawny STEP/STL/journal;
- strukturę Compose z 9 usługami;
- strukturę 8 plików Protobuf;
- integralność przykładowego `.lps.zip`.

Szczegóły: `docs/VERIFICATION.md` oraz `docs/verification-report.json`.

## Granice bieżącego wydania

- Nie ma ogólnego, swobodnego edytora dowolnej powierzchni B-Rep ani rekonstrukcji historii SolidWorks.
- Mapowanie fotografii/rzutu do 3D wymaga skalibrowanego `ProjectionMap`.
- PCB/SCH ma model danych i adapter KiCad CLI, ale nie autorouter ani pełny edytor semantyczny.
- Symulacje elektryczne, termiczne, mechaniczne i human-use są modelami redukowanymi/regułami; wymagają pomiarów, FEA/CFD/HIL i badań użytkowników przed decyzją produkcyjną.
- Docker, broker MQTT, rzeczywisty dostawca LiteLLM, Open WebUI, SMTP i KiCad nie zostały uruchomione end-to-end w środowisku budowy.
- Konfiguracja deweloperska nie jest konfiguracją produkcyjną; wymagane są TLS, IdP/OAuth, secure cookies, CSRF, rate limits, backup, audyt i rotacja sekretów.

## Start

```bash
cp .env.example .env
docker compose up --build
```

Aplikacja: `http://localhost:8000`  
OpenAPI: `http://localhost:8000/docs`  
Mailpit: `http://localhost:8025`

Pełny zakres i roadmap: `docs/16_MASTER_PRODUCT_LIFECYCLE_BLUEPRINT_PL.md`.  
Mapowanie wymagań: `docs/17_REQUIREMENTS_TRACEABILITY_PL.md`.
