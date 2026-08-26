# EDA-SCH-REFERENCE-001: Oznaczenia lub footprinty schematu są niejednoznaczne

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-SCH-REFERENCE-001","version":1,"severity":"ERROR","category":"SAFETY","title":"Niepoprawne oznaczenia lub footprinty schematu","meaning":"Automatyczna zmiana nie może jednoznacznie wskazać komponentu ani powiązać go z PCB.","causes":["Brakuje Reference","Reference występuje więcej niż raz","Brakuje przypisanego footprintu"],"remediation":["Uruchom annotację w KiCad","Nadaj każdemu symbolowi unikalne Reference","Przypisz footprinty i zaktualizuj PCB"],"verification":["GET /api/v1/eda/schematic-state?path=<plik.kicad_sch>"],"doNot":["Nie wybieraj elementu wyłącznie po Value"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
