# Granice własności i audyt duplikacji

Stan pomiaru: 2026-08-28. Powtarzalny skan wykonuje polecenie:

```bash
redup scan . --format json --ext .py,.js --min-lines 8 --min-sim 0.9
```

Katalogi ignorowane przez repozytorium i kod zależności nie wchodzą do wyniku.

## Wynik

Na początku bieżącego audytu TwinStudio obejmował 65 plików i 24 489 linii.
Skan znalazł 9 grup w 23 fragmentach, o potencjale 148 linii. Po refaktoryzacji
obejmuje 69 plików i 24 502 linie: 4 grupy w 8 fragmentach, o potencjale 46
linii. Produkcyjna logika wskazana przez skan została scentralizowana; potencjał
pozostałych podobieństw spadł o 69%.

Tym samym poleceniem sprawdzono granice zależności. `twinapi` ma 0 grup
(11 plików, 1 870 linii), a Viewer po własnej refaktoryzacji ma 0 grup
(63 pliki, 23 773 linie).

## Jedno źródło dla każdego obszaru

- `src/twinstudio/` jest właścicielem orkiestracji, CQRS, zdarzeń, DSL, API i MCP.
- `src/living_product_studio/` jest wyłącznie tymczasową przestrzenią zgodności.
  Pliki importują `twinstudio` i nie mogą zawierać własnej logiki.
- `digitaltwin-run/housing-studio` jest jedynym źródłem generatora obudowy,
  jego UI, modeli, zasobów i testów. TwinStudio instaluje wersję przypiętą do
  commita; repozytorium platformy nie przechowuje kopii źródeł komponentu.
- `twin-kicad` jest przypiętą zależnością odpowiedzialną za bezstratny parser,
  geometrię trasowania i router; TwinStudio nie kopiuje tych implementacji.
- `artifact_source.py` jest wspólnym właścicielem haszowania tekstu i ochrony
  ścieżki oraz budowy deskryptora źródła dla DSL SVG/OpenSCAD.
- `hashing.py` jest właścicielem strumieniowego SHA-256 pliku dla API, historii,
  eksportu i narzędzi weryfikacyjnych TwinStudio.
- `lens_catalog_io.py` ładuje każdy wersjonowany katalog soczewek; moduły domenowe
  nadają tylko znaczenie konkretnemu zasobowi.
- `model_validation.py` utrzymuje wspólne niezmienniki ID i wag bez wymuszania
  połączenia dwóch jeszcze różnych wersji modeli ewolucji.
- `housing_studio/layout.py` jest jednym źródłem punktów kamer i bossów zarówno
  dla modelu 3D, jak i dokumentacji 2D.

Testy komponentu uruchamiają się osobno po testach platformy. Zapobiega to
zarówno kopiowaniu testów, jak i przypadkowemu importowaniu innego kodu lokalnie
niż w Dockerze.

## Pozostałe cztery grupy

1. `examples/.../software/vision_app.py` i jego kopia w
   `demo-rpi5.lps/artifacts/` świadomie pokazują, że pakiet projektu materializuje
   dokładną rewizję źródła. Import między nimi unieważniłby test przenośności.
2. Dwa `sample_output/.../rebuild_project.py` są wygenerowanymi uruchamiaczami,
   nie źródłem logiki produktu. Ich usuwanie należy do polityki retencji wyników.
3. SHA-256 w `services/cad-worker` i `housing-studio` należy do dwóch
   niezależnie pakowanych i wdrażanych artefaktów. Zależność od głównego runtime
   tylko dla dziewięciu linii zwiększyłaby sprzężenie wdrożeniowe.
4. `inspect_svg` i `inspect_scad` są cienkimi, symetrycznymi adapterami różnych
   parserów. Wspólny jest już niezmiennik content-addressed source; kolekcje
   `elements` i `variables` pozostają jawnie typowane.

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

Semantyczne podobieństwo `api.py` i `mcp_gateway.py` również nie oznacza wspólnej
sygnatury transportu. Jeśli pojawi się w nich ta sama logika biznesowa, należy
wydzielić usługę aplikacyjną i pozostawić dwa cienkie adaptery.
