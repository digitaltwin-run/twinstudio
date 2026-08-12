# 18 — Ewolucja projektu i przeciwdziałanie fiksacji

## 1. Cel warstwy ewolucji

TwinStudio rozdziela **cel** od pierwszego sposobu jego sformułowania oraz od aktualnej geometrii. Polecenie „przyklej”, „przykręć” albo „zrób zawias” może nieświadomie ograniczyć przestrzeń rozwiązań. Warstwa ewolucji traktuje czasownik i istniejący model jako punkty startowe, a nie jako obowiązkową odpowiedź.

Program ewolucji przechodzi przez następujący przepływ:

```text
problem / potrzeba
    ↓
cel, wyniki, elementy zachowywane, elementy zakazane, założenia
    ↓
hierarchia działań: synonimy, hiperonimy, hiponimy, przeciwieństwa, sąsiednie działania
    ↓
dekompozycja obiektów, części, cech, parametrów, procesów i evidence
    ↓
graf dwukierunkowy celu i zasobów
    ↓
warianty: adjacent possible, mutacje, rekombinacje, analogie
    ↓
ocena wielokryterialna i shortlista
    ↓
plan eksperymentów, bramki lifecycle i typowane ChangePlan
    ↓
CQRS / Event Sourcing / artefakty / evidence
```

Wynik grafu jest hipotezą. Nie zastępuje prototypu, testu, symulacji, pomiaru ani akceptacji człowieka.

## 2. Feature Type Spectrum

Katalog źródłowy zachowuje terminologię przekazanego materiału. W widocznych tabelach dało się jednoznacznie zidentyfikować 49 aktywnych pozycji, a „External Relations” występuje dwa razy. Ponieważ materiał nazywa zestaw „fifty viewing lenses”, TwinStudio zachowuje pięćdziesiąty slot jako jawnie nierozwiązany zamiast dopisywać brakującą nazwę.

Kategorie aktywnych soczewek:

- cechy statyczne: części, materiał, kształt, rozmiar, kolor, stan materii, połączenia, relacje przestrzenne, masa, waga, liczba, symetria, jednorodność, wnętrze/zewnętrze, tekstura, smak i aromat;
- cechy dynamiczne: termiczne, optyczne, siłowe, trwałościowe, akustyczne, chemiczne, elektryczne, magnetyczne, radioaktywne i płynowe;
- cechy relacyjne: skutki uboczne, synonimy użycia, partnerzy środowiskowi, użycie przez człowieka, miejsce, okazja, energia, siły, bliskość, orientacja, czas, ruch, trwałość, perspektywa użytkownika, warunki środowiskowe, reakcja emocjonalna, relacje przyczynowe, klasyfikacje i estetyka.

Przegląd design fixation oznacza każdą soczewkę jako `observed`, `partly_observed`, `unknown` albo `not_applicable` i tworzy alternatywy bez automatycznej mutacji CAD.

## 3. Rozszerzenia inżynierskie TwinStudio

Poza katalogiem źródłowym platforma zawiera 34 jawnie oznaczone rozszerzenia. Nie są one przedstawiane jako część źródłowej tabeli. Obejmują między innymi:

- funkcję, zachowanie i logikę sterowania;
- interfejsy, interoperacyjność, modułowość i konfigurowalność;
- manufacturability, assemblability, serviceability i testability;
- reliability, resilience i upgradeability;
- koszt, wartość, lead time i ryzyko dostaw;
- observability, jakość danych i utrzymywalność software;
- cyberbezpieczeństwo, prywatność i functional safety;
- dostępność, sustainability, circularity i compliance;
- provenance, uncertainty, reversibility i koszt eksperymentu;
- adjacent possible.

## 4. Katalog działań

Kontrolowany katalog 20 czasowników opisuje relacje semantyczne i typowe założenia. Podstawowe hasła to:

```text
fasten, connect, improve, reduce, increase, protect, support, mount,
open, close, cool, seal, move, separate, inspect, maintain, prevent,
manufacture, simplify, observe
```

Przykładowo `mount` może rozwinąć się do `screw`, `snap`, `slide`, `clamp`, `press-fit`, `key` albo `pin`. System może też przejść poziom wyżej do bardziej ogólnej funkcji i następnie zejść do innej gałęzi szczegółowych mechanizmów.

Polskie czasowniki są mapowane do kontrolowanych rdzeni, np. `popraw` → `improve`, `zamocuj` → `mount`, `uszczelnij` → `seal` i `uprość` → `simplify`.

## 5. Operatory ewolucji

Katalog wydania 0.5.0 zawiera 17 operatorów:

```text
reframe_goal
repurpose_feature
parameter_shift
invert_relation
combine_parts
split_part
remove_part
duplicate_feature
substitute_material
substitute_process
change_energy
move_function
modularize
make_reversible
add_observability
adjacent_association
crossover
```

Operator tworzy propozycję z zakresem POA, uzasadnieniem, ryzykami, kryteriami walidacji i deklaratywnymi operacjami. Nie uruchamia dowolnego kodu wygenerowanego przez model językowy.

## 6. Lifecycles

Katalog ma trzy szablony:

- `hardware-product` — 30 etapów, od opportunity, discovery i evidence intake do production, monitoring, service, retirement, reuse i recycling;
- `digital-product` — 19 etapów dla produktu programowego;
- `continuous-evolution` — 10 etapów dla iteracyjnego uczenia się z evidence terenowego.

Blueprint może być dostosowany przez włączenie lub wyłączenie etapów. Przejście przechowuje:

- etap źródłowy i docelowy;
- kryteria wejścia i wyjścia;
- wymagane artefakty i typy testów;
- role zatwierdzające;
- evidence użyte do decyzji;
- niespełnione kryteria;
- status `requested`, `approved`, `blocked` albo `rejected`.

Automatyczne przejście nie omija bramek evidence ani uprawnień.

## 7. Generowanie wariantów

Silnik buduje:

1. warianty celu i czasownika;
2. zasoby z drzewa projektu, cech, parametrów, materiałów, procesów, wymagań i evidence;
3. krawędzie możliwych mechanizmów;
4. populację kandydatów;
5. potomków tworzonych przez operatory;
6. oceny w dziesięciu wymiarach: feasibility, novelty, manufacturability, evidence, risk control, reversibility, sustainability, cost/value, user value i lifecycle fit;
7. shortlistę oraz plan eksperymentów.

Deterministyczny seed umożliwia reprodukcję podglądu przy niezmienionym snapshotcie, konfiguracji i katalogu.

## 8. Realizacja zmian

Dostępne tryby:

- `analysis_only` — tylko graf i raport;
- `change_plan` — generowanie typowanych planów do zatwierdzenia;
- `auto_apply_safe` — wyłącznie jawne, allow-listowane patche parametrów, gdy DSL wyłącza wymóg zatwierdzenia i wszystkie operacje kwalifikują się jako bezpieczne.

Operacje topologiczne, niejednoznaczne i poza zakresem trafiają do przeglądu lub adaptera domenowego. Zaznaczenie nie daje modelowi prawa do zmiany innej części projektu.

## 9. Artefakty

Każdy zapisany run może wygenerować:

```text
evolution-program.json
evolution-run.json
evolution-graph.dot
evolution-graph.mmd
evolution-report.md
evolution-candidates.csv
lifecycle-blueprint.json
dsl-execution.json
manifest.json
```

Manifest zapisuje rozmiary i SHA-256. Event stream przechowuje autora, wersję bazową, plan i identyfikatory powstałych zdarzeń.
