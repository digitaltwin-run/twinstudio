# TwinStudio — aktualny stan projektu (2026-08-12)

## 1. Werdykt

Bieżące drzewo robocze realizuje główną intencję rozwoju TwinStudio 0.5.0:

- kanoniczny pakiet został przeniesiony z `living_product_studio` do `twinstudio`, z warstwą zgodności dla starego namespace;
- dodano typowaną warstwę ewolucji projektu, TwinScript, katalogi działań i soczewek, lifecycle, REST, CLI, MCP, UI, schematy i artefakty demonstracyjne;
- `components/housing-studio` jest działającym komponentem parametrycznego CAD 2D/3D i został podłączony do obrazu `cad-worker`;
- rzeczywista aplikacja ASGI uruchamia się, seeduje projekt demonstracyjny i odpowiada przez HTTP.

Po rundzie naprawczej z 2026-08-12 lokalny build jest zielony: pełne 80 testów przechodzi, Ruff i `buf lint` nie zgłaszają błędów, Compose jest jednoznaczny, a bieżący obraz działa z PostgreSQL i zachowaną bazą demonstracyjną. Test Playwright potwierdza nie tylko odpowiedź API, lecz także załadowanie projektu, drzewa oraz obu brył STL w WebGL. CI instaluje jawnie zależności Housing Studio oraz uruchamia lint. Gotowość produkcyjna nadal wymaga wskazania docelowego hosta, zarządzania sekretami i polityki migracji bazy, ale lokalna ścieżka single-host Docker Compose ma kontrolowany rollout, health-check rewizji i rollback obrazu.

| Obszar | Ocena | Uzasadnienie |
|---|---|---|
| Migracja nazwy i zgodność wsteczna | zgodna z intencją | `twinstudio` jest źródłem kanonicznym, `lps` i `living_product_studio` pozostają aliasami migracyjnymi, `lps.v1` pozostaje namespace wire |
| DSL i ewolucja projektu | zgodne z intencją i działające | walidator, kompilacja trzech formatów i testy domenowe przeszły |
| Housing Studio / CAD | funkcjonalne, integracja częściowo uporządkowana | kanoniczny komponent jest instalowany w CI i przechodzi testy; starsze kopie pozostają długiem konsolidacyjnym |
| REST/ASGI | działa | `/health` potwierdza wersję i rewizję obrazu, lista projektów i katalog ewolucji odpowiadają poprawnie |
| Pełny pytest/CI | lokalnie zielony | 80/80 testów przechodzi z `httpx2`; workflow instaluje pełne zależności obu projektów |
| Jakość statyczna | zielona | Ruff i `buf lint` przechodzą, lint jest wymaganym krokiem CI |
| Gotowość release | warunkowa | gotowy lokalny rollout Compose; produkcja wymaga jawnego targetu, sekretów i procedury migracji danych |

## 2. Zakres ocenianej zmiany

Porównanie wykonano względem commita `68ae15e86f02dee011bbbce5546d51d0088c6073` (`refaktor v3`). W chwili uruchomienia `todo2code` workspace zawierał 254 zmienione ścieżki: 177 nowych plików dodanych do indeksu i 77 zmodyfikowanych plików.

Największe workstreamy:

1. migracja produktu do nazwy TwinStudio 0.5.0;
2. Feature Type Spectrum i przegląd design fixation;
3. TwinScript oraz JSON/YAML DSL ewolucji;
4. silnik wariantów celu i zasobów, adjacent possible, mutacje, rekombinacje i selekcja;
5. lifecycle blueprints i bramki evidence;
6. REST, CLI, MCP i przeglądarkowy workspace ewolucji;
7. wydzielenie `components/housing-studio` i podłączenie go do `cad-worker`;
8. nowe schematy, przykłady, paczki demonstracyjne i dokumentacja release.

## 3. Aktualna architektura wykonawcza

### 3.1. Rdzeń TwinStudio

`src/twinstudio` jest kanoniczną implementacją. Zawiera:

- modele Pydantic projektu, obiektów, xBOM, selekcji, planów zmian, evidence i lifecycle;
- CQRS, append-only Event Store, projekcję snapshotu i optimistic concurrency;
- planowanie zmian ograniczone zakresem POA i zaznaczenia;
- symulacje zasilania, termiki, human-use i reguły mechaniczne;
- eksport przenośnego `.twinstudio.zip` z manifestem SHA-256;
- REST/FastAPI, CLI/Typer, MCP, MQTT i przeglądarkowy interfejs statyczny.

Warstwa obserwowalności ma wspólny kontrakt dla człowieka i LLM:

- każde żądanie aplikacyjne emituje JSON/NDJSON z osadzonym DSL `TWINOBS 1.0` i `correlation_id`;
- błędy REST zwracają kompatybilne pole `detail` oraz typowany `ProblemEnvelope` z kodem, kontekstem ekranu, artefaktami i adresem registry;
- przeglądarka publikuje `UIContext`: aktywną kartę i narzędzie, zaznaczenie, stan renderera, liczbę siatek i trójkątów oraz listę użytych artefaktów;
- ostatnie 40 akcji UI jest widoczne jako uporządkowane parametry `args` w URL; rekord zawiera sekwencję, czas, rodzaj akcji, kliknięty element, współrzędne kursora i zwięzły kontekst semantyczny, ale dla pól tekstowych ujawnia tylko długość;
- autoryzowany `GET /api/v1/projects/{project_id}/logs.dsl` udostępnia ostatnie projektowe rekordy z ograniczonego bufora TWINOBS; przycisk `Kopiuj logi DSL` łączy je ze śladem `UiAction` z URL i zapisuje całość w schowku;
- LLM może odczytać ostatni `UIContext` i playbook `error/<CODE>.md` przez REST lub dwa kontrolowane narzędzia MCP;
- playbooki używają prostego, deklaratywnego `REPAIR 1.0`; nie dają LLM swobodnego wykonania powłoki ani ominięcia autoryzacji.

`src/living_product_studio` jest warstwą kompatybilności, która przekierowuje importy do `twinstudio` i emituje `DeprecationWarning`. Polecenie `lps` pozostaje aliasem `twinstudio`. Namespace Protobuf `lps.v1` jest zachowany celowo jako kontrakt wire.

### 3.2. Ewolucja i TwinScript

Warstwa ewolucji zawiera:

- 20 kontrolowanych czasowników i ich relacje;
- 34 rozszerzenia inżynierskie TwinStudio;
- 17 operatorów ewolucji;
- 50 zadeklarowanych slotów feature-lens, z czego 49 jest aktywnych, a jeden pozostaje jawnie nierozwiązany;
- trzy szablony lifecycle: hardware (30 etapów), digital product (19) i continuous evolution (10);
- jeden kanoniczny model `TwinDslDocument` dla TwinScript, YAML i JSON;
- deterministyczny silnik populacji, scoringu, shortlisty, planów eksperymentów i typowanych `ChangePlan`;
- zapis grafów DOT/Mermaid, raportów Markdown, CSV, JSON i manifestów SHA-256.

Walidowany przykład `rpi5-hinge-evolution` generuje 48 wariantów celu, 26 zasobów, 48 kandydatów, shortlistę 5 kandydatów i 3 plany zmian.

### 3.3. Housing Studio

`components/housing-studio` generuje parametryczne STEP/STL/OBJ/GLB, rysunki SVG/DXF/PDF, BOM, raport techniczny, diff konfiguracji i paczkę projektu. Ma własne API FastAPI i opcjonalny most LiteLLM z deterministycznym fallbackiem.

Obraz `services/cad-worker/Dockerfile` korzysta już z `components/housing-studio`. Repo nadal zawiera jednak starsze `housing_studio/`, `app/` oraz `services/cad-worker/vendor/rpi5_housing_studio`. Te kopie różnią się treścią. Dopóki nie zostanie wskazane jedno źródło kanoniczne i usunięte albo zamrożone pozostałe, testy lokalne mogą nieświadomie sprawdzać inną kopię niż obraz CAD.

## 4. Porównanie intencji przez todo2code

Analizę wykonano deterministycznie przez `todo2code 0.5.0`, względem `HEAD`, bez wysyłania źródeł do LLM. Historia Git została ograniczona do jednego commita, ponieważ domyślne dziesięć commitów obejmuje pierwszy commit o diffie większym niż limit bufora `todo2code` i pierwotny przebieg zakończył się `ERR_CHILD_PROCESS_STDIO_MAXBUFFER`.

| Metryka | HEAD | Workspace | Zmiana |
|---|---:|---:|---:|
| Alignment | 12,26% | 9,09% | -3,17 pp |
| Pokrycie zadeklarowanej intencji implementacją | 16,52% | 12,46% | -4,06 pp |
| Kod powiązany z planem | 48,10% | 24,14% | -23,96 pp |
| Kod powiązany z dokumentacją | 53,16% | 20,00% | -33,16 pp |
| Luki | 272 | 350 | +78 |
| Diagnostyki `blocking` | 23 | 23 | 0 |
| Diagnostyki `review_required` | 114 | 14 | -100 |

Werdykt narzędzia: **mixed**.

Interpretacja wyniku:

- spadek pokrycia jest realnym sygnałem, że duża liczba nowych modułów nie ma jednoznacznego planu/ticketu rozpoznawanego przez `todo2code`;
- 23 blokery nie są sprzecznością produktu — wszystkie pochodzą z wygenerowanego przez `prefact` `TODO.md`, gdzie dwa opisy tego samego ostrzeżenia (`Relative import ...` oraz `Relative import not allowed`) zostały błędnie potraktowane jako intencje o przeciwnej polaryzacji;
- 14 wpisów changelogu nie zostało jednoznacznie połączonych z symbolem, plikiem lub commitem, mimo że wiele odpowiadających im elementów istnieje w kodzie;
- wynik jest obciążony duplikacją Housing Studio oraz tym, że źródłem intencji jest jakościowy backlog `prefact`, a nie osobny, kuratorowany plik zadania dla workstreamu 0.5.0;
- kierunek funkcjonalny zmian jest zgodny z dokumentami 0.5.0, ale dowody intencji nie są jeszcze dostatecznie spięte, by `todo2code` potwierdził pełną zgodność.

## 5. Weryfikacja wykonana 2026-08-12

### 5.1. Kontrole zakończone powodzeniem

- `scripts/verify_project.py` bez pytest: **passed**, wszystkie 13 kontroli przeszło;
- walidacja snapshotu: 15 obiektów i 24 artefakty bez braków lub błędów SHA-256;
- demo scoped B-Rep: poprawne STEP/STL, ubytek objętości około 14,137 mm³;
- 8 plików Protobuf: poprawna kontrola strukturalna;
- 12 schematów domenowych plus `schemas/index.json`, zsynchronizowane schema/EBNF w package data;
- równoważność TwinScript/YAML/JSON i kompilacja przykładu ewolucji;
- paczka demonstracyjna: 37 wpisów ZIP, poprawny manifest, rozmiary i SHA-256;
- `compileall`, składnia JavaScript, DOM contract i discovery CLI;
- `docker compose config --quiet`: poprawny bez niejednoznacznego drugiego pliku Compose i bez ręcznie rezerwowanej podsieci;
- `git diff --check`: passed;
- pełny pytest: **80/80 passed**, łącznie z testami API przez FastAPI `TestClient`, kontraktem `ProblemEnvelope`/`UIContext`, eksportem logów TWINOBS, kontrolą procesu lokalnego, mapowaniem zaznaczenia SVG 2D i kolejnością `.env.local`/`.env`;
- `ruff check .`: passed;
- `buf lint`: passed z zachowaniem kompatybilnego namespace `lps.v1`;
- smoke test nowego obrazu: `/health` zwrócił `status=ok`, wersję `0.5.0`, rewizję obrazu i 49 aktywnych soczewek; `/api/v1/projects` zwrócił zachowany `demo-rpi5`;
- `app`, `postgres`, `mqtt` i `mailpit` działają w Compose; aplikacja i PostgreSQL są healthy.
- health-check PostgreSQL wykonuje uwierzytelnione `SELECT 1`; usunięto fałszywie dodatni `pg_isready -U twinstudio`, który przy odziedziczonym wolumenie generował `FATAL: role "twinstudio" does not exist` mimo statusu healthy;
- artefakty 3D i 2D są pobierane przez autoryzowany registry endpoint, zamiast przez nieaudytowany bezpośredni mount ścieżki;
- karta 2D pokazuje wszystkie rzuty z `default_2d_views` jako jedną przewijaną listę; każdy rzut zachowuje własną warstwę zaznaczeń i link SVG, a autoryzowany endpoint `/drawings.pdf` składa wszystkie SVG w jeden wektorowy, wielostronicowy PDF A4;
- oznaczony region SVG z `data-projection-entity` jest automatycznie wiązany z encją `projection-map` i obiektem POA; prostokąt na dolnej części rzutu Front wybiera `part/base` / `front.base.outer-wall` bez wcześniejszego kliknięcia drzewa. Metadane projekcji są pobierane bez cache, starszy SVG ma kontrolowany fallback przez kolejność polygonów, a rzeczywisty brak mapowania czyści mylącą nakładkę i emituje `selection.rejected`;
- test Playwright na wdrożeniu `http://127.0.0.1:8400` potwierdził projekt `demo-rpi5`, 15 wierszy drzewa, **2/2 załadowane siatki STL**, **20 096 trójkątów** oraz trzy kolejne rzuty Front/Top/Side bez błędów konsoli i sieci;
- aktualizacje `UIContext` są sekwencjonowane, więc końcowy stan dla LLM zawiera komplet pięciu widocznych artefaktów (dwa STL i trzy SVG), niezależnie od kolejności zakończenia żądań przeglądarki;
- test Chromium potwierdził 11 kolejnych rekordów `args`, współrzędne i identyfikatory klikniętych elementów, zapis pełnej trasy diagnostycznej w `UIContext.route` oraz skopiowanie ponad 8 tys. znaków DSL z rekordami `UiAction` i `HTTP_REQUEST_COMPLETED`;
- lokalny lifecycle przez Makefile udostępnia `start`, `restart`/`recreate`, `stop`/`kill`, `status`, `health`, `logs`, `logs-follow` i `run`; `start` zastępuje istniejącą instancję TwinStudio z bieżącego workspace, ale odmawia zabicia obcego procesu na tym samym porcie;
- zrzut kontrolny testu UI jest zapisywany domyślnie jako `/tmp/twinstudio-ui.png`; test jest odtwarzalny poleceniem `python scripts/verify_ui.py --url <adres>`.

### 5.2. Kontrole nadal niewykonane

- pełny start wszystkich profili Docker Compose;
- `buf lint`/generacja klientów Protobuf;
- live MQTT, Open WebUI, MinIO, SMTP i zewnętrzny LiteLLM;
- fizyczna walidacja CAD, druku, termiki, zasilania i użyteczności.

## 6. Pozostałe ryzyka i zalecana kolejność prac

1. **Potwierdzić target produkcyjny.** Skrypt `scripts/deploy_compose.sh` obsługuje lokalny/single-host Compose, ale nie zastępuje konfiguracji konkretnego hosta, rejestru obrazów, TLS, backupów i sekretów.
2. **Wybrać jedno źródło Housing Studio.** Obraz CAD i CI używają `components/housing-studio`; katalog główny i vendor nadal są rozbieżnymi kopiami wymagającymi konsolidacji.
3. **Dodać lock/constraints zależności.** `httpx2` naprawia obecny TestClient, lecz otwarte zakresy wersji nadal mogą zmienić środowisko bez zmiany źródeł.
4. **Rozstrzygnąć politykę dużych artefaktów.** Dowody release powinny mieć jawny manifest i proces odtworzenia; artefakty instalacyjne `*.egg-info` zostały usunięte ze źródeł i ponownie ignorowane.
5. **Zaktualizować dowody intencji.** Dodać kuratorowany task/ticket 0.5.0, powiązać changelog z plikami/symbolami i wykluczyć wygenerowane artefakty z analizy `todo2code`.
6. **Usunąć runtime CDN dla Three.js.** Bieżący test potwierdza działanie, ale import map nadal pobiera Three.js z jsDelivr; dla instalacji odciętych od Internetu zależności przeglądarkowe powinny zostać przypięte i dostarczone z obrazem.
7. **Wynieść `UIContext` i bufor TWINOBS do współdzielonego store dla wielu replik.** Aktualne magazyny są świadomie procesowe i ograniczone (bufor: 2000 rekordów), co wystarcza dla wdrożenia single-host/single-worker; deployment wieloreplikowy powinien użyć Redis lub trwałego strumienia z TTL.

## 7. Odtwarzalne uruchomienie

W czystym checkoutcie wymagane są zależności obu projektów:

```bash
python3.12 -m venv --clear .venv
.venv/bin/python --version
.venv/bin/python -m pip install -e ".[dev]" -e "./components/housing-studio[dev]"
test -f .env.local || cp .env.local.example .env.local
```

Opcja `--clear` jest istotna przy ponownym użyciu nazwy `.venv`: samo wykonanie
`python3.12 -m venv .venv` nad istniejącym środowiskiem może pozostawić dowiązania
do wcześniejszego interpretera. Plik `.env.local` oddziela lokalny SQLite od ustawień
Compose (`/data`, `postgres`, `mqtt`, `mailpit`) zapisanych w `.env`.

Uruchomienie rdzenia z lokalnym SQLite:

```bash
.venv/bin/twinstudio seed
.venv/bin/twinstudio serve
```

Kontrola domenowa niezależna od problemu `TestClient`:

```bash
TWINSTUDIO_DATA_DIR=./data \
DATABASE_URL=sqlite:///./data/twinstudio.db \
MQTT_ENABLED=false \
PYTHONPATH=src \
.venv/bin/python scripts/verify_project.py
```

Pełna kontrola lokalna:

```bash
ruff check .
python scripts/verify_project.py --run-tests
docker run --rm -v "$PWD:/workspace" -w /workspace bufbuild/buf:latest lint
.venv/bin/python scripts/verify_ui.py --url http://127.0.0.1:8500
```

Chroniony deployment aktualnego, wypchniętego commita po zielonym CI:

```bash
scripts/deploy_compose.sh
```

Skrypt odmawia pracy dla brudnego drzewa, commita różnego od `origin/main` albo czerwonego CI. Obraz zawiera etykietę rewizji, `/health` ją zwraca, a brak potwierdzenia po wdrożeniu uruchamia rollback do poprzedniego obrazu aplikacji.
