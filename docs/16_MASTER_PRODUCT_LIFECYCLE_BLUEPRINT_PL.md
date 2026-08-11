# 16 — Główny plan platformy „Living Product Studio”

## 1. Cel produktu

Living Product Studio ma być wspólną, wersjonowaną przestrzenią dla całego urządzenia, a nie tylko repozytorium pojedynczego modelu STL. Jeden projekt łączy:

- źródła i dowody: fotografie, szkice, rysunki, pomiary, PDF, modele CAD, dane katalogowe;
- wymagania i decyzje;
- geometrię 2D/3D oraz przyszłe PCB/SCH;
- strukturę urządzenia i zależności między częściami;
- warianty technologii wykonania: FDM/SLA, CNC, zakup, PCB, oprogramowanie, opakowanie;
- symulacje, testy, FMEA, instrukcje i ocenę użycia przez człowieka;
- artefakty produkcyjne, wydania oprogramowania i dane handlowe;
- historię wszystkich zmian, akceptacji i odpowiedzialności.

Kanonicznym elementem projektu nie jest „plik”, lecz adresowany obiekt produktu z trwałym URI, cechami, relacjami, źródłami, artefaktami i testami.

## 2. Warstwy architektury

### 2.1. Evidence layer

Warstwa dowodów przechowuje materiały wejściowe bez ich cichego „poprawiania”:

- zdjęcia i wycinki zdjęć;
- filmy, skany i rysunki techniczne;
- tabele wymiarów;
- modele STEP/STL/DXF/SVG;
- karty katalogowe podzespołów;
- wyniki pomiarów fizycznych i elektrycznych;
- logi działania oprogramowania;
- decyzje mailowe i komentarze użytkowników.

Każdy wniosek powinien posiadać źródło, autora, datę, poziom pewności i zakres, którego dotyczy. Niepewny wymiar pozostaje oznaczony jako założenie, dopóki nie zostanie potwierdzony pomiarem lub decyzją.

### 2.2. Product graph i xBOM

Drzewo obiektów opisuje urządzenie jako wielodomenowy graf. Przykładowe gałęzie:

```text
Device
├── Mechanical assembly
│   ├── Base                 [FDM]
│   ├── Lid                  [CNC albo FDM]
│   └── Hinge pin            [purchased]
├── Electronics
│   ├── Raspberry Pi 5       [purchased]
│   ├── Camera Module 3      [purchased]
│   ├── Custom PCB           [PCB fabrication]
│   └── Power supply         [purchased]
├── Software
│   ├── Vision application   [container image]
│   ├── Configuration        [release artifact]
│   └── Test data            [dataset]
├── Documentation
│   ├── Assembly drawing
│   ├── User manual
│   └── Service procedure
└── Commercial
    ├── Packaging
    ├── GTIN/EAN data
    └── Ecommerce offer
```

Każdy obiekt ma niezależny status w poszczególnych widokach BOM. Część może być uwzględniona w BOM produktu, lecz wyłączona z zadania druku 3D. Element kupowany może posiadać model referencyjny i parametry gabarytowe, ale nie może zostać błędnie wysłany do slicera.

### 2.3. Geometry and design layer

Warstwa projektowa obejmuje:

- części, złożenia, cechy i parametry;
- semantyczne powierzchnie i krawędzie;
- mapy projekcji pomiędzy 2D, zdjęciem i 3D;
- wskazania użytkownika wykonane kursorem, ołówkiem, prostokątem lub lassem;
- typed `ChangePlan` zamiast wykonywania dowolnego kodu wygenerowanego przez LLM;
- artefakty pochodne: STEP, STL, DXF, SVG, PDF i podgląd webowy.

### 2.4. Verification and simulation layer

Każdy obiekt i wymaganie może mieć metodę weryfikacji:

- inspekcja wymiarowa;
- test kolizji i pasowania;
- reguły DFM;
- test elektryczny;
- symulacja zasilania i temperatury;
- uruchomienie kontenera oprogramowania;
- analiza przykładowych obrazów kamery;
- scenariusz użycia człowieka;
- test transportowy, montażowy, serwisowy i trwałościowy.

### 2.5. Lifecycle and commercial layer

Projekt obejmuje cały cykl życia: od koncepcji i prototypu do produkcji, użytkowania, serwisu, aktualizacji, wycofania oraz danych ecommerce.

## 3. Edycja wskazanego fragmentu: NL → 2D → 3D

### 3.1. Zaznaczenie nie jest jeszcze zmianą

Użytkownik wskazuje obszar na widoku 3D, rysunku 2D albo zdjęciu. System zapisuje:

- ścieżkę kursora/lassa;
- kamerę, projekcję i rozmiar viewportu;
- przecięcia promienia z geometrią;
- URI obiektu;
- hash siatki i indeks trójkąta;
- semantyczną powierzchnię;
- opcjonalny identyfikator B-Rep;
- world-space AABB;
- źródłowy artefakt i identyfikatory elementów projekcji 2D.

Indeks trójkąta STL jest traktowany wyłącznie jako nietrwały dowód. Zmiana jest dozwolona dopiero po rozwiązaniu zaznaczenia do trwałego obiektu, cechy albo powierzchni.

### 3.2. Resolver zaznaczenia

Resolver tworzy wersjonowany `SelectionMap`:

```text
piksele / ray hits
    → obiekt POA
    → semantyczna powierzchnia
    → cecha projektu
    → opcjonalna powierzchnia/sketch encja natywnego CAD
```

Możliwe stany to `resolved`, `partial`, `unresolved` i `stale`. Zaznaczenie z poprzedniej, niezgodnej rewizji nie może być automatycznie użyte.

### 3.3. Kompilator języka naturalnego

LiteLLM lub parser lokalny przekształca polecenie użytkownika w walidowany `ChangePlan`. LLM otrzymuje tylko:

- opis zmiany;
- dozwolony zakres zaznaczenia;
- parametry i cechy wskazanych obiektów;
- listę dozwolonych operacji;
- JSON Schema odpowiedzi.

Przykład:

```text
„W zaznaczonym miejscu wykonaj otwór 3 mm prostopadle do tej ściany.”
```

zostaje przekształcony w operację typu:

```json
{
  "target_uri": "poa://demo/demo-rpi5@main/part/base",
  "kind": "boolean_cut",
  "arguments": {
    "feature_type": "hole",
    "diameter_mm": 3.0
  }
}
```

Backend odrzuca cel poza zaznaczonym poddrzewem POA.

### 3.4. Aktualnie wykonywalny lokalny adapter B-Rep

W paczce działa ograniczony adapter dla wejściowego STEP:

- otwór cylindryczny według punktu i normalnej z ray hit;
- axis-aligned local-box cut według AABB zaznaczenia;
- axis-aligned local-box add według AABB zaznaczenia.

Adapter generuje nowy STEP, STL i dziennik operacji z hashami, wynikiem walidacji, liczbą brył i zmianą objętości. Jest to kontrolowana, pochodna rewizja B-Rep — nie odzyskanie drzewa operacji SolidWorks.

### 3.5. Operacje wymagające kolejnego etapu

Następujące operacje pozostają świadomie poza automatycznym wykonaniem:

- dowolna lokalna zmiana grubości powłoki;
- fillet/chamfer na niestabilnej topologii;
- swobodny face move;
- powierzchnie organiczne;
- automatyczna rekonstrukcja natywnego drzewa historii;
- modyfikacja 3D z niekalibrowanego zdjęcia;
- automatyczne rozwiązywanie sprzecznych wymiarów.

Takie polecenia są zachowywane jako typed plan/deferred operation i wymagają adaptera konkretnego systemu CAD albo przeglądu konstruktora.

## 4. Widok drzewa i praca na składnikach

Interfejs powinien pozwalać:

- rozwijać złożenia, części, cechy, powierzchnie, wymagania i testy;
- ukrywać/pokazywać obiekty;
- zaznaczać cały element albo jego fragment;
- przełączać warianty i konfiguracje;
- sprawdzać kto, kiedy i dlaczego zmienił parametr;
- widzieć artefakty wejściowe i wynikowe przypięte do obiektu;
- filtrować według technologii, dostawcy, statusu, rewizji i gate lifecycle;
- porównywać dwie rewizje 2D/3D i ich xBOM.

## 5. Współpraca i autoryzacja

### 5.1. Role

- `reader`: odczyt projektu, podgląd i pobieranie dozwolonych artefaktów;
- `editor`: komentarze, zaznaczenia, plany zmian i edycja obiektów w zakresie uprawnień;
- `admin`: zarządzanie członkami, rolami i ustawieniami projektu;
- `creator`: właściciel projektu i ostateczne decyzje dostępu.

### 5.2. Dostęp przez akceptację mailową

Przepływ referencyjny:

1. Osoba zewnętrzna podaje email, projekt i żądaną rolę.
2. Decydent/creator otrzymuje mail z approve/reject.
3. Akceptacja tworzy jednorazowy link.
4. Osoba zewnętrzna odbiera link; system tworzy konto, membership, sesję i personal API token.
5. Automatyzacja może użyć HTTP Basic: email jako username, token jako password.

Produkcja wymaga TLS, bezpiecznych cookies, CSRF, ograniczeń prób, revocation, audytu, polityki sekretów i zaufanego dostawcy poczty/IdP.

### 5.3. Wspólna edycja

CQRS i Event Sourcing zapewniają append-only historię. Każde polecenie ma expected stream version. Dzięki temu konkurencyjna zmiana nie nadpisuje po cichu pracy innej osoby.

Dalszy etap powinien dodać:

- soft lock dla obszaru/cechy;
- komentarze i mention;
- review request i approval gate;
- semantyczny diff geometrii;
- merge niezależnych zmian parametrów;
- obowiązkowe ponowne wskazanie po zmianie topologii.

## 6. Wspólny format projektu

### 6.1. Snapshot i zdarzenia

Snapshot JSON jest wygodnym read model. Kanoniczna historia to event stream. Protobuf definiuje kontrakt między usługami, a POA URI identyfikuje każdy element.

### 6.2. Portable `.lps.zip`

Eksport projektu zawiera:

- snapshot projektu;
- event stream;
- unified specification/xBOM;
- manifest artefaktów;
- źródła i wyniki;
- hash SHA-256;
- dokumentację wymaganych testów i lifecycle.

Taki pakiet może być przechowywany w repozytorium, storage S3/MinIO albo przekazany wykonawcy bez utraty struktury projektu.

## 7. Interfejsy i integracje

Ta sama semantyka poleceń i URI jest dostępna przez:

- REST/OpenAPI;
- CLI i shell;
- MQTT;
- MCP;
- UI webowe;
- Protobuf jako międzyusługowy DSL.

MQTT nadaje się do integracji z urządzeniem testowym, workerem CAD, telemetrią i automatyzacją. MCP udostępnia narzędzia oraz zasoby projektowe klientom LLM/Open WebUI bez otwierania dowolnego dostępu do systemu plików. Paczka zawiera przetestowany rdzeń stateless MCP 2026-07-28: `server/discover`, tools/resources, per-request `_meta`, wymagane nagłówki HTTP, `resultType`, cache metadata i kontrolę Origin. Pozostawiono także legacy `initialize` 2025-11-25. SSE, subscriptions, MRTR i własny OAuth 2.1 server nie są zaimplementowane; produkcyjny Open WebUI powinien łączyć się przez OAuth-capable gateway/reverse proxy albo przez OpenAPI.

## 8. Routing technologii i dostaw

Każdy obiekt posiada manufacturing route i flagi włączenia:

- `fdm`, `sla`, `cnc`, `laser`, `pcb_fabrication`;
- `purchased`;
- `software`;
- `packaging`;
- `reference_only`.

Przykład:

- base: FDM, wchodzi do print job;
- lid: CNC, nie wchodzi do print job;
- RPi5: purchased, wchodzi do procurement BOM;
- camera: purchased, model referencyjny do kontroli kolizji;
- vision app: software, wchodzi do release manifest;
- karton: packaging, wchodzi do fulfillment BOM.

System powinien generować osobne paczki dla dostawców bez ujawniania niepotrzebnych źródeł innych części.

## 9. PCB i SCH — docelowy model

PCB/SCH powinny być obiektami tego samego grafu, z tymi samymi URI, wymaganiami, eventami i review. Docelowa ścieżka:

1. Import projektu KiCad i mapowanie UUID symboli, footprintów, netów i warstw.
2. Zaznaczenie fragmentu schematu albo PCB.
3. Polecenie NL ograniczone do wybranego zakresu.
4. Generacja typed operation, np. zmiana wartości, przesunięcie footprintu, dodanie test point.
5. Adapter KiCad modyfikuje źródło, uruchamia ERC/DRC i eksportuje artefakty.
6. Projekt urządzenia ponownie sprawdza kolizje mechaniczne, termiczne i zasilanie.

Obecna paczka zawiera schemat danych i bezpieczny scaffold sprawdzania/eksportu przez `kicad-cli`, nie syntezę schematów ani autorouter produkcyjny.

## 10. Oprogramowanie jako część urządzenia

Oprogramowanie ma być wersjonowanym obiektem produktu z:

- źródłem i licencją;
- obrazem kontenera i digestem;
- konfiguracją;
- datasetem testowym;
- wymaganiami sprzętowymi;
- protokołami wejść/wyjść;
- wynikami testów;
- zależnością od rewizji hardware.

Przykładowy pipeline kamery:

```text
sample image / camera replay
    → containerized vision application
    → deterministic result JSON
    → expected-result assertion
    → power/temperature telemetry
    → lifecycle test result
```

Kontener nie emuluje sprzętu RPi5. Weryfikuje powtarzalny przepływ danych i oprogramowania. Pełniejszy poziom wymaga hardware-in-the-loop.

## 11. Symulacje i warstwy wiarygodności

### 11.1. Zasilanie

Model podstawowy oblicza:

- sumaryczny prąd;
- spadek napięcia na przewodzie i złączach;
- moc na odbiornikach;
- margines zasilacza.

Wymagane dane wejściowe to napięcie, rezystancja toru i profile obciążenia. Model nie zastępuje transient power integrity ani pomiaru oscyloskopem.

### 11.2. Termika

Model RC szacuje wzrost temperatury i przebieg w czasie. Parametry muszą być skalibrowane pomiarem. CFD i conjugate heat transfer pozostają osobnym backendem.

### 11.3. Mechanika

Reguły MVP wykrywają proste problemy: minimalną grubość, niebezpieczne przewężenia, luzy, niepodparte zwisy. FEA, zmęczenie, udar i analiza transportowa wymagają solverów i rzeczywistych własności materiału.

### 11.4. Człowiek i użycie

Scenariusz opisuje aktora, instrukcję, kroki, oczekiwane obserwacje, możliwe błędy oraz kryteria zakończenia. System może sprawdzić kompletność i sprzeczności, ale nie symuluje biomechaniki dłoni ani ergonomii bez dodatkowego modelu.

### 11.5. Poziomy walidacji

Każdy wynik powinien posiadać poziom:

- `estimate` — obliczenie redukowane;
- `simulation` — model numeryczny;
- `software_replay` — deterministyczny test kontenera;
- `hardware_in_loop` — rzeczywiste urządzenie;
- `bench_measurement` — pomiar laboratoryjny;
- `field_evidence` — dane z eksploatacji.

## 12. FMEA, słabe punkty i uszkodzenia

Projekt przechowuje failure modes z:

- przyczyną;
- skutkiem;
- severity, occurrence, detection;
- obecną kontrolą;
- działaniem redukującym ryzyko;
- właścicielem i terminem;
- wymaganym dowodem zamknięcia.

Dla obudowy i urządzenia przykładowe klasy problemów to:

- pęknięcie zawiasu;
- odkształcenie cieplne;
- złamanie słupka montażowego;
- niedostępny port;
- uszkodzenie kabla przy otwieraniu;
- przegrzanie RPi;
- spadek napięcia i restart;
- błędny montaż płytki;
- uszkodzenie transportowe;
- błędna interpretacja instrukcji;
- niekompatybilna wersja software/hardware.

## 13. Lifecycle produktu

Zalecane gates:

1. **Discovery** — źródła, problem, użytkownik, założenia.
2. **Requirements baseline** — wymagania mierzalne i właściciele.
3. **Concept review** — warianty architektury i make/buy.
4. **Detailed design** — geometry/PCB/software i interface contracts.
5. **Prototype release** — artefakty do wykonania i test plan.
6. **Verification** — zgodność z wymaganiami.
7. **Validation** — użycie przez docelowego człowieka w kontekście.
8. **Production readiness** — DFM, dostawcy, koszt, kontrola jakości.
9. **Commercial release** — GTIN/EAN, packaging, instrukcja, oferta.
10. **Operation** — telemetria, incydenty, poprawki, aktualizacje.
11. **Service and repair** — części, procedury i kompatybilność rewizji.
12. **End of life** — wycofanie, dane, recykling i migracja klientów.

Każdy gate ma wymagane artefakty, testy, decydenta i wynik approve/reject/conditional.

## 14. Ecommerce i identyfikatory

Oferta ecommerce jest pochodną zatwierdzonej konfiguracji produktu. Powinna zawierać:

- SKU i wariant;
- zatwierdzony GTIN/EAN, gdy właściciel posiada odpowiednią alokację GS1;
- nazwę, opis, zdjęcia i parametry;
- zawartość zestawu;
- masę i wymiary opakowania;
- instrukcję i ostrzeżenia;
- warranty/service terms;
- kompatybilną rewizję hardware/software;
- cenę, walutę, podatki i kanał sprzedaży.

Narzędzie w paczce oblicza cyfrę kontrolną GTIN, ale nie przydziela legalnego prefiksu ani numeru.

## 15. Docker i topologia wdrożenia

Compose rozdziela usługi na profile:

- core: API/UI, PostgreSQL, MQTT, Mailpit;
- `cad`: worker CadQuery;
- `integration`: MQTT command gateway;
- `simulation`: device/camera simulator;
- `openwebui`: interfejs LLM po MCP;
- `object-store`: MinIO.

W produkcji należy rozdzielić sieci, sekrety, storage i domeny zaufania. Worker CAD oraz symulatory nie powinny mieć nieograniczonego dostępu do hosta ani dowolnego wykonywania kodu LLM.

## 16. Proponowany plan dalszego rozwoju

### Faza A — twardy MVP współpracy i geometrii

- trwałe semantyczne ID generatora CAD;
- diff 2D/3D i review;
- obsługa kolejnych allow-listed operacji;
- region locks i komentarze;
- production auth/IdP;
- test Compose w CI.

### Faza B — native CAD i PCB/SCH

- adapter FreeCAD/CadQuery z trwałymi feature IDs;
- wybrany adapter natywnego komercyjnego CAD;
- pełny round-trip KiCad UUID/ERC/DRC;
- mapowanie mechanika ↔ PCB ↔ złącza;
- warianty i konfiguracje produktu.

### Faza C — digital twin i HIL

- agent urządzenia RPi;
- sterowane profile obciążenia;
- pomiary prądu, napięcia i temperatury;
- kamera fizyczna oraz replay datasetów;
- kalibracja modeli redukowanych;
- porównanie symulacja ↔ pomiar.

### Faza D — produkcja i handel

- dostawcy, RFQ, ceny i lead time;
- release signatures i approval workflow;
- QA/traceability/serial numbers;
- packaging/label generation;
- konektory ecommerce i fulfillment;
- field telemetry, incident workflow i EOL.

## 17. Granice odpowiedzialności obecnej paczki

Paczka jest działającą architekturą referencyjną i MVP procesu. Nie należy interpretować jej jako potwierdzenia, że:

- każdy fragment dowolnego STEP da się bezpiecznie edytować jednym poleceniem;
- zdjęcie automatycznie dostarcza dokładną geometrię bez kalibracji;
- modele termiczne i elektryczne są już skalibrowane dla realnego urządzenia;
- kontener jest emulatorem Raspberry Pi;
- PCB/SCH są automatycznie projektowane i zatwierdzane;
- wygenerowany GTIN jest numerem przydzielonym przez GS1;
- referencyjne ustawienia uwierzytelniania są gotowe do Internetu publicznego.

Każde z tych twierdzeń wymaga osobnego backendu, danych wejściowych i planu walidacji. Architektura przechowuje te granice jawnie, dzięki czemu wynik LLM nie jest mylony z potwierdzonym dowodem inżynierskim.
