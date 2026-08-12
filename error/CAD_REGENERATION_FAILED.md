REPAIR 1.0
CODE "CAD_REGENERATION_FAILED"
TITLE "Nie udało się zregenerować widoków CAD po zmianie"

SYMPTOM
Parametry projektu zostały zapisane, ale zdarzenie `GenerationCompleted` nie powstało,
a klient nadal pokazuje poprzednią rewizję STL/SVG.

CHECK
1. Pobierz logi DSL i znajdź rekord z kodem `CAD_REGENERATION_FAILED` oraz jego `CORRELATION`/`job_id`.
2. Sprawdź, czy katalog `TWINSTUDIO_DATA_DIR/cad-jobs` jest zapisywalny.
3. Odczytaj `DETAILS.exception_type` i komunikat walidacji geometrii. Niektóre kombinacje wymiarów
   (np. wysokość podstawy większa od wysokości całkowitej) nie tworzą poprawnej bryły.
4. Sprawdź, czy środowisko aplikacji zawiera pakiet `housing-studio` i biblioteki systemowe CadQuery.

REPAIR
1. Popraw niezgodne parametry albo cofnij zmianę w historii.
2. Uruchom ponownie aplikację przez `make restart` lub odbuduj usługę `docker compose up -d --build app`.
3. Ponów zmianę. Nowe zadanie ma otrzymać własny `job_id`, po czym powinny pojawić się zdarzenia
   `GenerationRequested` i `GenerationCompleted`.

VERIFY
1. `GET /api/v1/projects/{project_id}` wskazuje artefakty z `metadata.cad_job_id` równym ostatniemu zadaniu.
2. Hashy `base-stl`, `lid-stl` i rzutów SVG nie są puste.
3. UI zapisuje akcję `artifacts.regenerated` i przeładowuje 3D/2D bez ręcznego odświeżenia.

END
