# TwinStudio 0.5.0 — informacje o wydaniu

Data wydania: 2026-08-12.

## Cel

Wydanie 0.5.0 rozwija istniejący cyfrowy wątek produktu o kontrolowaną **ewolucję projektu**. System nie ogranicza się do modyfikowania obecnej geometrii: rozdziela cel od rozwiązania, rozwija czasowniki celu, dekomponuje dostępne obiekty i cechy, buduje graf dwukierunkowy, tworzy warianty i wymaga planu eksperymentów.

## Najważniejsze zmiany

- pełna nazwa produktu i pakietu: **TwinStudio**;
- TwinScript 1.0 wraz z reprezentacjami YAML i JSON;
- JSON Schema Draft 2020-12 i EBNF;
- REST, CLI, MCP i zakładka webowa Evolution DSL;
- katalog akcji oraz goal ladder: synonimy, hiperonimy, hiponimy, działania przeciwne i sąsiednie;
- graf celów i zasobów, BrainSwarming, adjacent possible, mutacje, rekombinacja i planowanie eksperymentów;
- 34 dodatkowe wymiary inżynierskie TwinStudio;
- 17 operatorów ewolucji;
- rozszerzony lifecycle od opportunity/discovery do reuse, remanufacture i recycling;
- artefakty ewolucji: JSON, DOT, Mermaid, Markdown, CSV, blueprint i manifest;
- 21 narzędzi MCP, w tym katalog ewolucji, schema DSL, podgląd programu, runy, lifecycle i konwersja kandydata do `ChangePlan`;
- zachowana kompatybilność importu `living_product_studio`, komendy `lps` i wybranych zmiennych `LPS_*` przez okres migracyjny.

## Przykład demonstracyjny

`examples/evolution/rpi5-hinge-evolution.twin` generuje deterministyczny podgląd dla zawiasu obudowy RPi5. Bieżący zapis demonstracyjny, uruchomiony na odtworzonym strumieniu zdarzeń, zawiera 48 wariantów celu, 30 zasobów, 48 kandydatów, pięć pozycji na shortliście i trzy typowane plany zmian. Bezpośrednia kompilacja statycznego `project.json` wykrywa 26 zasobów; dodatkowe cztery wynikają z odtworzonego modelu runtime. Są to propozycje do weryfikacji, nie automatycznie zatwierdzona konstrukcja.

## Weryfikacja wydania

- 38 testów Python zostało zebranych i zakończyło się powodzeniem;
- źródła Python przeszły `compileall`;
- JavaScript przeszedł `node --check`;
- TwinScript, YAML i JSON dają równoważny dokument kanoniczny;
- schema i EBNF są dostępne z API i w paczce;
- podgląd DSL działa bez mutowania strumienia;
- artefakty ewolucji mają manifest i sumy SHA-256;
- lista MCP zawiera 21 narzędzi, a nowoczesny i legacy flow protokołu pozostają objęte testami.
- archiwum źródłowe zostało ponownie rozpakowane, zweryfikowane manifestem i przetestowane pełnym zestawem 38 testów;
- z rozpakowanych źródeł zbudowano koło Python `twinstudio-0.5.0-py3-none-any.whl`, sprawdzając dane pakietu oraz fallback schema/EBNF.

Szczegóły i granice: `docs/VERIFICATION.md`.

## Ograniczenia

- W tym etapie nie wykonano ponownie pełnego live testu Docker Compose po dodaniu warstwy 0.5.0.
- Nie użyto rzeczywistego dostawcy LiteLLM ani kluczy API.
- Nie przeprowadzono fizycznego wydruku, montażu RPi5, pomiarów termicznych/elektrycznych ani badań użytkowników.
- Wynik ewolucji nie jest FEA, CFD ani dowodem spełnienia wymagań.
- Dowolna, swobodna edycja B-Rep i natywna historia SolidWorks pozostają poza zakresem.
