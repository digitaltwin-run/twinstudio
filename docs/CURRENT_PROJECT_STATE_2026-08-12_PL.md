# TwinStudio — aktualny stan projektu (2026-08-12)

## 1. Werdykt

Bieżące drzewo robocze realizuje główną intencję rozwoju TwinStudio 0.5.0:

- kanoniczny pakiet został przeniesiony z `living_product_studio` do `twinstudio`, z warstwą zgodności dla starego namespace;
- dodano typowaną warstwę ewolucji projektu, TwinScript, katalogi działań i soczewek, lifecycle, REST, CLI, MCP, UI, schematy i artefakty demonstracyjne;
- `components/housing-studio` jest działającym komponentem parametrycznego CAD 2D/3D i został podłączony do obrazu `cad-worker`;
- rzeczywista aplikacja ASGI uruchamia się, seeduje projekt demonstracyjny i odpowiada przez HTTP.

Stan nie jest jednak gotowy do oznaczenia jako w pełni zielony build/release. Logika domenowa i CAD przechodzą dostępne testy, ale pełna ścieżka CI ma niespójny kontrakt zależności, testy HTTP zawieszają się na aktualnie rozwiązywanym stosie `TestClient`, lint ma błędy, a część dokumentacji release opisuje wcześniejszy zestaw 38 testów zamiast bieżących 65.

| Obszar | Ocena | Uzasadnienie |
|---|---|---|
| Migracja nazwy i zgodność wsteczna | zgodna z intencją | `twinstudio` jest źródłem kanonicznym, `lps` i `living_product_studio` pozostają aliasami migracyjnymi, `lps.v1` pozostaje namespace wire |
| DSL i ewolucja projektu | zgodne z intencją i działające | walidator, kompilacja trzech formatów i testy domenowe przeszły |
| Housing Studio / CAD | funkcjonalne, integracja nieuporządkowana | nowy komponent przechodzi testy, ale w repo nadal są równoległe starsze kopie |
| REST/ASGI | działa | Uvicorn wystartował, `/health`, lista projektów i katalog ewolucji odpowiedziały poprawnie |
| Pełny pytest/CI | niepotwierdzony jako zielony | 57 testów bez `TestClient` przeszło; testy HTTP zawieszają się na zgodności Starlette/httpx |
| Jakość statyczna | niezielona | Ruff zgłasza 23 błędy |
| Gotowość release | nie | wymagane jest domknięcie zależności, CI, duplikacji źródeł i aktualizacja dowodów release |

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
- `docker compose config --quiet`: poprawny, z ostrzeżeniem o równoległych `compose.yaml` i `docker-compose.yml`;
- `git diff --check`: passed;
- 57/57 testów niezależnych od FastAPI `TestClient`: passed w 17,18 s;
- 20/20 analogicznych testów uruchomionych bezpośrednio z `components/housing-studio`: passed w 16,50 s;
- smoke test prawdziwego Uvicorn: `/health` zwrócił `status=ok`, wersję `0.5.0` i 49 aktywnych soczewek; `/api/v1/projects` zwrócił `demo-rpi5`; katalog ewolucji zwrócił 34 wymiary, 17 operatorów i 3 lifecycle.

### 5.2. Kontrole niezielone lub nieukończone

#### Pełny pytest / TestClient

Pełny zestaw zbiera obecnie 65 testów, ale zatrzymuje się na pierwszym żądaniu przez `fastapi.testclient.TestClient`. Problem odtworzono na minimalnej aplikacji FastAPI, niezależnej od kodu TwinStudio:

```text
fastapi 0.141.1
starlette 1.6.0
httpx 0.28.1
StarletteDeprecationWarning: ... install httpx2 instead
before-client
before-get
<timeout>
```

Rzeczywisty serwer Uvicorn i te same ścieżki HTTP działają. Jest to problem kontraktu zależności testowych, ale blokuje wiarygodny pełny wynik CI.

#### Ruff

`ruff check --no-cache ...` zgłasza 23 błędy:

- 19 nieużywanych importów;
- 2 nieużywane zmienne;
- 1 przesłonięty import `field`;
- 1 dodatkowy przypadek nieużywanej zmiennej w kopii vendorowej.

#### Niewykonane w tym audycie

- pełny start wszystkich profili Docker Compose;
- `buf lint`/generacja klientów Protobuf;
- live MQTT, Open WebUI, MinIO, SMTP i zewnętrzny LiteLLM;
- fizyczna walidacja CAD, druku, termiki, zasilania i użyteczności.

## 6. Blokery i zalecana kolejność prac

### P0 — przed uznaniem CI/release za zielone

1. **Naprawić kontrakt zależności testowych.** Z CI usunięto instalację Housing Studio, ale główny `tests/` nadal importuje `cadquery`, `trimesh`, `ezdxf` i `housing_studio`. `.[dev]` tych zależności nie dostarcza. CI powinno instalować kanoniczny `components/housing-studio[dev]` albo projekt powinien mieć jawny agregujący extra testowy.
2. **Ustabilizować FastAPI/Starlette/http client.** Dodać lock/constraints i wybrać obsługiwany klient testowy (`httpx2` dla aktualnego Starlette albo kompatybilnie przypięty stos). Każdy test subprocess powinien mieć timeout, aby CI nie wisiał bez końca.
3. **Powtórzyć pełny pytest w czystym środowisku.** Dopiero kompletny wynik powinien nadpisać `docs/VERIFICATION.md`, `docs/verification-report.json` i `RELEASE_BUILD.json`.

### P1 — spójność repozytorium

4. **Wybrać jedno źródło Housing Studio.** Obraz CAD używa `components/housing-studio`; katalog główny i vendor nie powinny pozostać aktywnymi, rozbieżnymi kopiami.
5. **Usunąć 23 błędy Ruff** i dodać lint do wymaganych kroków CI.
6. **Rozstrzygnąć politykę artefaktów.** `.gitignore` przestał ignorować `*.egg-info` i wybrane ZIP-y, a do indeksu dodano metadane instalacji oraz duże artefakty generowane. Jeżeli mają być dowodem release, powinny mieć jawny manifest i proces odtworzenia; w przeciwnym razie nie powinny być źródłem.
7. **Usunąć dwuznaczność Compose.** W katalogu głównym są `compose.yaml` platformy i `docker-compose.yml` Housing Studio; Docker Compose ostrzega i wybiera pierwszy z nich.
8. **Zaktualizować dowody intencji.** Dodać kuratorowany task/ticket 0.5.0, powiązać wpisy changelogu z plikami/symbolami i wykluczyć wygenerowane artefakty z analizy `todo2code`.

## 7. Odtwarzalne uruchomienie

W czystym checkoutcie wymagane są zależności obu projektów:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]" -e "components/housing-studio[dev]"
```

Uruchomienie rdzenia z lokalnym SQLite:

```bash
TWINSTUDIO_DATA_DIR=./data \
DATABASE_URL=sqlite:///./data/twinstudio.db \
MQTT_ENABLED=false \
PYTHONPATH=src \
.venv/bin/python -m uvicorn twinstudio.api:app --host 127.0.0.1 --port 8000
```

Kontrola domenowa niezależna od problemu `TestClient`:

```bash
TWINSTUDIO_DATA_DIR=./data \
DATABASE_URL=sqlite:///./data/twinstudio.db \
MQTT_ENABLED=false \
PYTHONPATH=src \
.venv/bin/python scripts/verify_project.py
```

Nie należy obecnie interpretować historycznego wpisu „38 tests passed” jako dowodu dla bieżącego drzewa. Jest on dowodem wcześniejszego release build, podczas gdy aktualna kolekcja ma 65 testów i wymaga naprawy stosu klienta HTTP.
