# Podsumowanie dopracowania po uruchomieniu i publikacji

Stan na: **2026-08-11**.

Repozytorium publiczne: [digitaltwin-run/twinstudio](https://github.com/digitaltwin-run/twinstudio).

Referencyjny przebieg CI: [31529121492](https://github.com/digitaltwin-run/twinstudio/actions/runs/31529121492).

## Wynik końcowy

Podstawowy stos Docker (`app`, PostgreSQL, MQTT i Mailpit) został uruchomiony i sprawdzony na żywo.
Aplikacja poprawnie zainicjalizowała projekt `demo-rpi5`, odtworzyła 15 obiektów z 58 zdarzeń i
udostępniła interfejs webowy, OpenAPI, REST, symulacje oraz 12 narzędzi MCP. Sprawdzono również
połączenie z brokerem MQTT i API Mailpit.

Publiczny pipeline zakończył się powodzeniem:

- 53 testy Python przeszły w GitHub Actions;
- `buf lint` przeszedł dla 8 kontraktów Protobuf;
- `docker compose config --quiet` przeszedł;
- generowanie schematów nie pozostawiło niezapisanych różnic;
- 24 artefakty przykładowe istnieją i mają zgodne sumy SHA-256;
- rozpakowany eksport LPS ma 27 plików opisanych w swoim manifeście, bez braków i niezgodnych hashy.

## Co wymagało dopracowania

| Obszar | Objaw | Przyczyna | Wprowadzona korekta |
|---|---|---|---|
| Obraz aplikacji | Healthcheck działał, ale `/api/v1/projects` zwracał pustą listę | Pakiet instalowano jako zwykły wheel. `PROJECT_ROOT` wskazywał wtedy katalog `site-packages`, więc aplikacja nie widziała `/app/examples` i nie wykonywała seeda | Instalacja aplikacji w obrazie została zmieniona na editable, dzięki czemu kod działa z `/app/src` i widzi przykłady w `/app/examples` |
| Sieć Docker | Compose nie mógł utworzyć kolejnej sieci | Lokalny daemon wyczerpał automatyczne pule adresowe Dockera | Dla projektu ustawiono jawną podsieć `10.250.58.0/24` |
| Porty hosta | Porty `8000` i `8025` były zajęte przez inne usługi | Współdzielone środowisko uruchamiało wiele projektów | Mapowania aplikacji i Mailpit zostały sparametryzowane przez `LPS_HOST_PORT` i `MAILPIT_HOST_PORT`; lokalnie użyto `8400` i `8425` |
| Wersjonowanie | Jeden test porównywał wersję platformy `0.3.0` z wersją generatora obudowy `1.2.1` | Test odziedziczony po komponencie zakładał jeden wspólny pakiet | Test rozdziela wersję TwinStudio od wersji Housing Studio i kontroluje spójność obu aplikacji osobno |
| Testy CI | Pełny zestaw testów wymagał CadQuery i zależności generatora, których workflow nie instalował | Główny `pyproject.toml` nie deklaruje ciężkiego stosu CAD jako zależności podstawowej | Workflow instaluje osobno zależności projektu i vendored Housing Studio |
| Protobuf | Pierwszy job `buf lint` zakończył się błędem | Niespójne opcje namespace, enumy bez prefiksu, nieużywane importy i współdzielone typy RPC niezgodne z profilem `STANDARD` | Ujednolicono opcje Java/C#, nazwy enumów i komunikaty request/response oraz usunięto zbędne importy |
| Publikacja artefaktów | Repozytorium zawierało dwa ZIP-y oraz ich rozpakowane odpowiedniki | Pakiety były przygotowane do przekazania jako archiwa, a nie do przeglądania w Git | Eksport LPS rozpakowano do `examples/rpi5-camera3/demo-rpi5.lps/`; drugi ZIP okazał się dokładną kopią istniejącego `sample_output/demo`. ZIP-y zachowano lokalnie, ale wykluczono z Git |
| Integralność paczki | `PACKAGE_MANIFEST.sha256` zawierał 7 nieaktualnych sum | Pliki zmieniły się po przygotowaniu pierwotnego manifestu | Manifest przeliczono, rozszerzono o rozpakowany eksport i ponownie zweryfikowano przez `sha256sum -c` |
| Higiena repozytorium | Do pierwszego stagingu weszły wygenerowane metadane `*.egg-info` | Brak reguły ignorowania artefaktów instalacji editable | Dodano `*.egg-info/` do `.gitignore`; `.env`, bazy, cache i lokalne archiwa również pozostają poza Git |

## Co nadal warto wziąć pod uwagę

### Priorytet P0 — przed wdrożeniem produkcyjnym

1. **Bezpieczeństwo i tożsamość**

   - wyłączyć `DEV_AUTH_BYPASS`;
   - zastąpić przykładowe sekrety losowymi wartościami z secret managera;
   - uruchomić TLS, bezpieczne cookies, CSRF, rate limiting i kontrolę zaufanego proxy;
   - dodać rotację oraz unieważnianie tokenów, pełny audit log i produkcyjnego dostawcę tożsamości;
   - przetestować proces zaproszeń z rzeczywistym SMTP, odbiciami wiadomości i ochroną przed nadużyciami.

2. **Pakowanie aplikacji**

   Tryb editable rozwiązuje obecny problem ścieżek, ale nie powinien być docelowym mechanizmem obrazu
   produkcyjnego. Lepszym rozwiązaniem jest wheel instalowany w obrazie wieloetapowym oraz jawna
   konfiguracja katalogu projektu albo użycie zasobów pakietu. Test obrazu powinien sprawdzać nie tylko
   `/health`, lecz również obecność i odczyt projektu startowego.

3. **Migracje i trwałość danych**

   - wprowadzić wersjonowane migracje bazy, na przykład Alembic;
   - zdefiniować backup, odtwarzanie, retencję eventów i test disaster recovery;
   - sprawdzić aktualizację schematu na kopii danych zamiast polegać wyłącznie na tworzeniu tabel przy starcie.

4. **Pełna walidacja profili opcjonalnych**

   Podstawowy stos przeszedł test live, a obraz CAD został użyty do testów. Nadal trzeba wykonać
   długotrwały test całych profili `cad`, `integration`, `simulation`, `object-store` i `openwebui`,
   łącznie z przepływem MQTT → REST → event store → artefakt oraz rzeczywistym klientem MCP/Open WebUI.

### Priorytet P1 — stabilizacja utrzymania

1. **Jedna struktura Compose**

   W katalogu istnieją równocześnie `compose.yaml` i starszy `docker-compose.yml`. Docker wybiera
   `compose.yaml`, ale za każdym razem wyświetla ostrzeżenie. Starszą konfigurację warto usunąć,
   przenieść do przykładu albo jednoznacznie nazwać i opisać.

2. **Konfigurowalna sieć**

   Jawna podsieć rozwiązała problem konkretnego hosta, lecz `10.250.58.0/24` może kolidować w innym
   środowisku. Warto pozwolić na ustawienie podsieci przez zmienną, zapewnić wariant korzystający z
   automatycznej sieci Dockera oraz opisać `LPS_HOST_PORT` i `MAILPIT_HOST_PORT` w `.env.example`.

3. **Konsolidacja generatora obudowy**

   Kod Housing Studio występuje w głównym katalogu i jako vendored kopia workera CAD. Należy ustalić
   jedno źródło prawdy, ograniczyć duplikację oraz opisać niezależne wersjonowanie platformy i generatora.

4. **Dług lint i ostrzeżenia deprecacyjne**

   Ruff zgłasza obecnie 63 problemy, przede wszystkim dotyczące importów, szerokich `Exception`, reguły
   `B008` dla FastAPI/Typer oraz drobnych uproszczeń. Testy pokazują też:

   - migrację FastAPI z `on_event` do lifespan;
   - zapowiadaną zmianę integracji `TestClient`/`httpx`;
   - wycofywaną funkcję `cadquery.save`;
   - ostrzeżenia GitHub Actions dotyczące akcji opartych na Node.js 20.

   Reguły specyficzne dla FastAPI/Typer należy świadomie skonfigurować, a pozostałe problemy naprawiać
   etapami, z osobnym jobem lint w CI.

5. **Kontrakty Protobuf jako produkt**

   Poza `buf lint` warto dodać generowanie klientów, publikację modułu Buf oraz `buf breaking` względem
   ostatniego wydania. Zmiana nazw enumów i wrapperów RPC wykonana przed ustabilizowaniem publicznego API
   powinna zostać uznana za punkt bazowy dla dalszej kompatybilności.

6. **Obserwowalność**

   Potrzebne są ustrukturyzowane logi z correlation ID, metryki, tracing, alerty, dashboard zdrowia
   integracji oraz healthchecki dla usług, które obecnie mają tylko stan procesu.

7. **Polityka artefaktów binarnych**

   Rozpakowane pliki mieszczą się w limitach GitHuba; największy ma około 2,3 MB. Przy większej liczbie
   rewizji STEP/STL/GLB/PNG zwykły Git zacznie jednak szybko rosnąć. Należy wybrać Git LFS, GitHub Releases
   albo magazyn obiektowy, zachowując w repozytorium manifest, metadane, hash i niewielkie przykłady.

8. **Łańcuch dostaw**

   Warto przypiąć obrazy i akcje do wersji lub digestów, dodać Dependabot/Renovate, SBOM, skan podatności,
   skan sekretów, podpisy obrazów i artefaktów oraz sprawdzić licencje materiałów referencyjnych i vendored kodu.

### Priorytet P2 — walidacja inżynierska produktu

- skalibrować modele elektryczne i termiczne pomiarami;
- wykonać testy HIL na Raspberry Pi i rzeczywistej kamerze;
- zweryfikować druk, montaż, zawias, tolerancje, transport i ergonomię;
- rozszerzyć trwałą identyfikację ścian/cech B-Rep przed ogólnymi zmianami geometrii;
- przetestować adapter KiCad na rzeczywistym projekcie i jasno oddzielić DRC/export od syntezy oraz autoroutingu;
- ustanowić kryteria zatwierdzania wyników symulacji, FMEA i lifecycle gates przez odpowiedzialnego inżyniera.

## Zalecana kolejność dalszych prac

1. Utwardzić konfigurację bezpieczeństwa i wdrożyć migracje/backup bazy.
2. Zastąpić editable install produkcyjnym obrazem oraz dodać test seeda obrazu.
3. Uruchomić test end-to-end wszystkich profili opcjonalnych.
4. Skonsolidować Compose i Housing Studio oraz uporządkować wersjonowanie.
5. Dodać lint do CI, usunąć deprecacje i ustalić baseline `buf breaking`.
6. Wdrożyć obserwowalność i politykę przechowywania artefaktów binarnych.
7. Dopiero potem rozszerzać swobodne operacje CAD, PCB i modele symulacyjne.

## Kryterium gotowości produkcyjnej

Za gotowy produkcyjnie należy uznać nie sam zielony pipeline, lecz wydanie, które łącznie spełnia:

- brak deweloperskiego bypassu i przykładowych sekretów;
- odtwarzalny, nie-editable obraz z migracjami;
- udokumentowany backup i udany test restore;
- zielone testy, lint, Buf lint/breaking i skany bezpieczeństwa;
- zielony test integracyjny wszystkich używanych profili;
- monitoring, alerty i procedury operacyjne;
- potwierdzoną fizycznie walidację tych właściwości, na których opierają się decyzje produkcyjne.

## ZIP a postać rozpakowana

Format `.lps.zip` pozostaje właściwym formatem wymiany i eksportu z aplikacji. W repozytorium przykład jest
celowo przechowywany w postaci rozpakowanej, aby umożliwić przegląd, diff i kontrolę hashy. Archiwum można
w każdej chwili wygenerować ponownie z API lub CLI; nie powinno być równolegle wersjonowane obok identycznej
zawartości, chyba że jest załącznikiem konkretnego GitHub Release.
