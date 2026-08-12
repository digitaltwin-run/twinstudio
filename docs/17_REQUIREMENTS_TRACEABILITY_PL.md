# 17 — Macierz śledzenia wymagań użytkownika

Dokument mapuje wymagania produktu na elementy paczki, status realizacji i kryterium odbioru. Statusy: **Implemented**, **Working scaffold**, **Roadmap**.

| ID | Wymaganie | Realizacja w paczce | Status | Kryterium odbioru / następny krok |
|---|---|---|---|---|
| SEL-001 | Zaznaczanie fragmentu bryły kursorem | `static/app.js`, `RegionSelection`, ray hits i zakres POA | Implemented | Kliknięcie zapisuje obiekt, trafienia promieni, kamerę, hash siatki i geometrię ekranu |
| SEL-002 | Ołówek, lasso i prostokąt w 3D | Narzędzia wejściowe w viewerze oraz schema `region-selection` | Implemented | Każdy tryb tworzy walidowalne evidence zaznaczenia |
| SEL-003 | Ołówek/lasso/prostokąt na rzucie 2D | Nakładka SVG/Canvas i powiązanie z artefaktem źródłowym | Implemented | Adnotacja zachowuje widok, ścieżkę, bbox i identyfikator artefaktu |
| SEL-004 | Zmiana wyłącznie zaznaczonego fragmentu | `SelectionMap`, resolver i scope guard POA | Implemented | Plan zawierający cel poza zaznaczonym poddrzewem jest odrzucany |
| SEL-005 | Stabilne wskazanie powierzchni po regeneracji | Semantic face tags i opcjonalne B-Rep IDs | Working scaffold | Adapter CAD musi dostarczyć trwałą mapę feature/face dla każdej operacji natywnej |
| SEL-006 | Fotografia lub skan 2D → wskazanie 3D | `ProjectionMap` schema i przykład kalibracji | Roadmap | Wymagana kalibracja kamery, punkty kontrolne i solver projekcji; bez tego system zachowuje uwagę, nie zgaduje geometrii |
| NL-001 | Opis naturalny → konfiguracja/plan | `ChangePlanner`, LiteLLM structured output i parser lokalny | Implemented | Wynik musi przejść JSON Schema/Pydantic oraz kontrolę zakresu |
| NL-002 | Przepływ NL → 2D preview → 3D | `ChangePlan`, review w UI, event i worker CAD | Working scaffold | Parametry i trzy allow-listed operacje działają; dowolne operacje topologiczne wymagają rozbudowy adaptera |
| CAD-001 | Parametryczna obudowa 2D/3D | Vendored generator CadQuery i worker obudowy | Working scaffold | Regeneruje przykładową podstawę/klapę i eksportuje STEP/STL/SVG |
| CAD-002 | Lokalny otwór w wybranym regionie | `scoped_brep_adapter.py`, directional cylinder cut | Implemented | Derived STEP/STL jest poprawnym pojedynczym solidem, a journal zawiera wejście, zakres i zmianę objętości |
| CAD-003 | Lokalny add/cut box | Axis-aligned local-box boolean add/cut | Implemented | Cel musi należeć do zaznaczenia; wynik i hash są audytowalne |
| CAD-004 | Dowolna edycja fragmentu B-Rep | Granica adaptera i kolejka review | Roadmap | Wymaga natywnego kernela/adaptera z persistent naming, retry i testami regresji topologii |
| TREE-001 | Lista obiektów i podzespołów w drzewie | Project graph, REST tree projection i panel UI | Implemented | Wybór w drzewie synchronizuje viewer, parametry i artefakty |
| TREE-002 | Edycja całego obiektu, podzespołu lub fragmentu | POA URI na każdym poziomie | Implemented | Polecenie może wskazać project/assembly/part/feature/face i podlega uprawnieniom |
| SPEC-001 | Lista cech, rozmiarów i zależności | Unified Project Snapshot + generowana specification | Implemented | Eksport zawiera obiekty, parametry, features, wymagania, evidence i weryfikację |
| XBOM-001 | Rozdział elementów drukowanych i niedrukowanych | Inclusion flags i widoki xBOM | Implemented | Print BOM nie zawiera elementów purchase/software/reference |
| XBOM-002 | Różne technologie: FDM, CNC, purchase, PCB, software | `manufacturing_route`, route views i przykładowe dane | Implemented | Każdy obiekt ma route, make/buy, pliki wejściowe i kryteria odbioru |
| XBOM-003 | Gotowe podzespoły RPi5 i Camera 3 ze specyfikacją | Przykładowe obiekty purchase/reference | Implemented | Są częścią urządzenia i BOM, lecz nie trafiają do jobu wydruku |
| COL-001 | Współdzielenie online | API, sesje, membership i event stream | Implemented | Uprawniony użytkownik widzi projekt, historię i zatwierdzone artefakty |
| COL-002 | Zaproszenie tylko przez email obu stron | Access request + decision-maker workflow | Implemented | Requestor podaje email; decydent dostaje approve/reject; akceptacja tworzy konto/membership |
| COL-003 | Role reader/editor/admin/creator | Permission matrix | Implemented | Testy sprawdzają ograniczenia komend i danych dla każdej roli |
| COL-004 | HTTP Basic | `email:PAT` dla API/CLI | Implemented | Działa w referencyjnym wdrożeniu; produkcja wymaga TLS, rotacji i revocation UI |
| COL-005 | Wspólne zmiany bez nadpisywania | CQRS/ES i optimistic concurrency | Implemented | Komenda z nieaktualną wersją strumienia jest odrzucana |
| CQRS-001 | Rozdzielenie command/query | `CommandBus`, `QueryService`, projector | Implemented | REST/CLI/MQTT/MCP używają wspólnych kontraktów domenowych |
| ES-001 | Pełna historia zmian | Append-only event store i portable event stream | Implemented | Snapshot można odtworzyć z eventów; eksport zawiera NDJSON |
| DSL-001 | Protobuf dla DSL | `proto/lps/v1/*.proto` | Implemented as source contract | Źródła przechodzą kontrolę statyczną; CI powinno wykonywać `buf lint` i generację klientów |
| POA-001 | URI procesu/obiektu oparte o POA | `poa://tenant/project@revision/kind/id/...` | Implemented | Ten sam identyfikator działa w API, eventach, selekcjach, MQTT i MCP |
| API-001 | REST | FastAPI + OpenAPI | Implemented | Główne ścieżki są objęte testem subprocess API |
| API-002 | CLI i shell | Typer `twinstudio` oraz interaktywny shell | Implemented | Seed/tree/plan/power/export działają na tych samych serwisach |
| API-003 | WebSocket | Kanał eventów UI | Implemented | Klient może odświeżać read model po zdarzeniach |
| INT-001 | MQTT | Publisher i opcjonalny command gateway | Working scaffold | Wymaga live testu z brokerem i polityk ACL na docelowym środowisku |
| INT-002 | MCP | MCP 2026-07-28 core subset + legacy initialize | Working scaffold | Discovery/tools/resources i walidacja są testowane; pozostają SSE, MRTR, subscriptions i produkcyjny OAuth |
| INT-003 | Open WebUI | Profil Compose i REST/MCP endpoints | Working scaffold | Wymaga uruchomienia docelowej wersji Open WebUI, konfiguracji admin integration i testu end-to-end |
| INT-004 | MinIO/object storage | Opcjonalny profil i granica backendu | Working scaffold | Należy zaimplementować produkcyjny adapter artefaktów, signed URLs i retencję |
| EVID-001 | Fotografie, PDF, wymiary, wycinki jako evidence | Artifact/evidence/claim model z hashami i provenance | Implemented | Każda teza może wskazać źródło, confidence i rewizję |
| EVID-002 | „Żywy projekt” aktualizowany przez LLM | Event-sourced snapshot + plan/apply/review | Implemented for scoped changes | LLM nie wykonuje kodu bezpośrednio; generuje walidowany plan |
| PCB-001 | PCB/SCH jako elementy projektu | Schema, object kinds i KiCad adapter boundary | Implemented in schema | PCB/SCH uczestniczą w xBOM, requirements i artifact graph |
| PCB-002 | Edycja natywna PCB/SCH | KiCad CLI check/export scaffold | Roadmap | Potrzebny parser/AST, reguły DRC/ERC, diff semantyczny, footprint identity i bezpieczny writer |
| PCB-003 | Autorouting/synteza schematu | Brak ukrytej implementacji | Roadmap | Osobny silnik ze ścisłymi ograniczeniami i walidacją elektryczną |
| SW-001 | Oprogramowanie jako część urządzenia | Software object, container source, release route | Implemented | Software ma wersję, obraz, konfigurację, testy i powiązanie z hardware |
| SW-002 | Symulacja uruchomienia RPi w Docker | Kontener aplikacji i sample replay | Implemented as software/data-flow simulation | Nie emuluje CPU, kernela ani timingów fizycznego RPi |
| CAM-001 | Symulacja kamery na przykładowych obrazach | Synthetic images, scenario i deterministic analysis | Implemented | Wynik JSON jest powtarzalny i dołączony do projektu |
| PWR-001 | Parametry zasilania i spadki napięcia | Lumped DC power model | Implemented | Raportuje prąd, moc, rezystancję toru, spadek i napięcie przy obciążeniu |
| PWR-002 | Dynamiczna integralność zasilania/USB-C | Nieudawana granica | Roadmap | Wymaga waveformów, PD negotiation, regulator models i pomiarów laboratoryjnych |
| THM-001 | Temperatura i miejsca nagrzewania | Lumped RC model per node | Implemented | Generuje estymowane temperatury i margines; parametry muszą być skalibrowane pomiarem |
| THM-002 | CFD/pełne pole temperatury | Nieudawana granica | Roadmap | Integracja z solverem CFD/FEA, geometrią, materiałami i warunkami brzegowymi |
| MECH-001 | Słabe punkty obudowy | Reguły grubości/otworów/hinge i FMEA | Working scaffold | Nadaje ostrzeżenia; nie zastępuje FEA ani testu upadku |
| HUMAN-001 | Instrukcja ruchów człowieka i kontrola poprawności | Human-use scenario, task steps i rule evaluation | Implemented | Sprawdza kolejność, wymagane narzędzia, warunki i możliwe błędy |
| HUMAN-002 | Symulacja biomechaniczna człowieka | Brak ukrytej implementacji | Roadmap | Potrzebny digital-human/ergonomics engine, antropometria i motion capture |
| FMEA-001 | Możliwe problemy, uszkodzenia i ryzyka | FMEA objects, severity/occurrence/detection i mitigations | Implemented as data/views | Każde ryzyko może być powiązane z obiektem, testem, ownerem i lifecycle gate |
| LC-001 | Etapy lifecycle produktu | Concept/design/verify/industrialize/release/operate/retire gates | Implemented as model/views | Gate ma kryteria, evidence, decyzję i audit trail |
| TEST-001 | Warstwa budowy oddzielona od warstwy testów | Requirements, build routes, test plans i evidence | Implemented | Artefakt budowy nie jest automatycznie „passed”; wynik testu jest osobnym rekordem |
| COM-001 | Specyfikacja handlowa i ecommerce | Offer, SKU, pricing placeholders, packaging data | Implemented as model | Konektory marketplace i approval ceny są kolejnym etapem |
| COM-002 | EAN/GTIN | Kalkulator i walidator cyfry kontrolnej | Implemented | Nie przydziela legalnego numeru; właściciel produktu musi otrzymać pulę od GS1 |
| EXP-001 | Łatwe pobranie całości | `.twinstudio.zip` oraz pojedyncze artefakty | Implemented | Bundle ma snapshot, eventy, specification, manifest i SHA-256 |
| OPS-001 | Docker-first | `compose.yaml` z 9 usługami i profilami | Implemented as deployment definition | Wymaga live build/test na serwerze z Dockerem |
| SEC-001 | Produkcyjne bezpieczeństwo | Jawna dokumentacja hardeningu | Roadmap | TLS, secure cookies, CSRF, rate limiting, external IdP/OAuth, backup, audit i secret rotation przed produkcją |

## Zasada akceptacji zmian geometrycznych

Zmiana może zostać wykonana automatycznie tylko wtedy, gdy jednocześnie:

1. zaznaczenie ma jednoznaczny zakres POA;
2. resolver wiąże evidence z wersją geometrii i stabilnym celem;
3. plan jest zgodny ze schematem;
4. wszystkie cele operacji należą do wybranego zakresu;
5. adapter zna daną operację i jej ograniczenia;
6. wynik przechodzi kontrolę bryły, hashów i reguł projektu;
7. użytkownik o odpowiedniej roli zatwierdził plan.

W przeciwnym razie system tworzy adnotację, pytanie lub zadanie review — nie modyfikuje niezaznaczonych ani niepewnych obszarów.

## Definition of Done dla wdrożenia produkcyjnego

Referencyjny MVP stanie się wdrożeniem produkcyjnym po wykonaniu co najmniej:

- testów Docker Compose i migracji na docelowej infrastrukturze;
- produkcyjnego IdP/OAuth, TLS, backupu, retencji i audytu;
- live testów Open WebUI, MCP i MQTT;
- kompilacji Protobuf przez Buf/protoc w CI;
- natywnego adaptera CAD z persistent naming i zestawem regresji geometrii;
- fizycznej walidacji obudowy, zasilania, termiki, kamery i ergonomii;
- procesu akceptacji wymagań, FMEA, release i zmian ecommerce;
- polityki odpowiedzialności za decyzje LLM oraz obowiązkowego human-in-the-loop dla zmian produkcyjnych.
