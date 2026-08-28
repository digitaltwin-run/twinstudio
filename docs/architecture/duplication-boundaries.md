# Granice własności i audyt duplikacji

Stan pomiaru: 2026-08-28. Skan wykonano przez MCP reDUP dla funkcji Python/JS/TS,
bez testów i kodu zależności. Analiza `code2llm` została użyta pomocniczo, ale jej
wyniku ilościowego nie traktujemy jako miary projektu: narzędzie weszło również
do lokalnego katalogu `.venv.backup-*`.

## Wynik

Przed refaktoryzacją skan semantyczny obejmował 111 plików i 30 555 linii. Znalazł
91 grup o potencjale 3 081 linii, z czego 2 565 linii pochodziło z pełnej kopii
Housing Studio. Po refaktoryzacji obejmuje 99 plików i 25 861 linii: 36 grup i
557 linii potencjału. Spadek wynosi 82% dla łącznego potencjału oraz 4 694 linii
źródłowych.

Skan składniowy o progu 0,90 zostawia 177 linii. Największe pozycje to wspólna
struktura operacji SVG/OpenSCAD w `twinstudio.api`, trzy adaptery zapisu stanu
schematu, przykładowy artefakt będący celową kopią źródła demonstracyjnego oraz
dwa modele polityki ewolucji.

Skan granic zależności nie znalazł grup duplikacji w `twinapi` (13 plików,
1 933 linie), `twin-kicad` (7 plików, 1 786 linii), `wellmanifest/sch`
(1 plik, 188 linii) ani `wellmanifest/pcb` (1 plik, 330 linii). Łączny skan
katalogu `digitaltwin-run` również nie wykazał kopii implementacji pomiędzy
TwinStudio, TwinAPI i twin-kicad. Trafienia z tych trzech projektów pozostają
wewnątrz TwinStudio i są opisane poniżej.

## Jedno źródło dla każdego obszaru

- `src/twinstudio/` jest właścicielem orkiestracji, CQRS, zdarzeń, DSL, API i MCP.
- `src/living_product_studio/` jest wyłącznie tymczasową przestrzenią zgodności.
  Pliki importują `twinstudio` i nie mogą zawierać własnej logiki.
- `components/housing-studio/` jest jedynym źródłem generatora obudowy, jego UI,
  modeli, zasobów i testów. Usunięto kopie `housing_studio/` oraz `app/` z katalogu
  głównego. `generator.py` jest tylko uruchamiaczem komponentu.
- `twin-kicad` jest przypiętą zależnością odpowiedzialną za bezstratny parser,
  geometrię trasowania i router; TwinStudio nie kopiuje tych implementacji.
- `artifact_source.py` jest wspólnym właścicielem haszowania tekstu i ochrony
  ścieżki dla DSL SVG/OpenSCAD.

Testy komponentu uruchamiają się osobno po testach platformy. Zapobiega to
zarówno kopiowaniu testów, jak i przypadkowemu importowaniu innego kodu lokalnie
niż w Dockerze.

## Pozostałe grupy

Semantyczne podobieństwo `api.py` i `mcp_gateway.py` nie zawsze jest duplikacją:
to różne adaptery transportowe. Nie należy scalać ich sygnatur ani modeli
odpowiedzi. Jeśli ciało wykonuje logikę biznesową, kolejny krok to wydzielenie
usługi aplikacyjnej i pozostawienie dwóch cienkich adapterów.

Modele ewolucji w `domain.py` i `evolution_models.py` nie są jeszcze równoważne:
drugi ma m.in. operator `CROSSOVER`, a pierwszy nie. Ich mechaniczne połączenie
zmieniłoby kontrakty. Najpierw trzeba wskazać model kanoniczny i przygotować
migrację serializowanych dokumentów.

## Wspólny cykl kandydatów SVG/OpenSCAD

Cykl planowania i utrwalania tekstowych kandydatów współdzieli teraz trzy jawnie
typowane operacje aplikacyjne: budowę wyniku planu, wynik `dry_run` oraz zapis
obiektu, rewizji, deskryptora i zdarzenia historii. Parser, translator, aplikator,
walidator i writer pozostają własnością danego formatu. Publiczne endpointy są
dzięki temu nadal cienkimi, osobnymi adapterami i zachowują dotychczasowe schema
ID oraz odpowiedzi HTTP.

Porównywalny skan dwóch izolowanych worktree, wykonany tą samą wersją reDUP i
parametrami (`py,js,ts`, minimum 8 linii, fuzzy 0,86, semantic 0,90), zmniejszył
wynik z 36 do 35 grup, z 551 do 493 potencjalnie odzyskiwalnych linii oraz ze
120 do 65 linii w grupach actionable. Grupa fuzzy `_apply_svg`/`_apply_scad`
(44 linie) zniknęła, a grupa `_plan_svg`/`_plan_scad` zmalała z 24 do 13 linii.
Pozostałe podobieństwo `_plan_*` i `*2dsl` jest zamierzoną symetrią adapterów;
ich mechaniczne połączenie przeniosłoby typowanie formatów do konfiguracji
callbacków i pogorszyło czytelność granicy.
