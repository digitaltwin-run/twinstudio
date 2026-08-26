# EDA-PCB-FOOTPRINT-LIB-001: Brak biblioteki footprintów

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-PCB-FOOTPRINT-LIB-001","version":1,"severity":"WARNING","category":"SAFETY","title":"Niedostępna biblioteka footprintów","meaning":"Bieżące środowisko nie może odtworzyć footprintu z konfiguracji projektu.","causes":["Brak wpisu w fp-lib-table","Lokalna biblioteka nie została dołączona"],"remediation":["Dodaj bibliotekę do projektu","Zapisz footprint lokalnie"],"verification":["DRC bez lib_footprint_issues w docelowym środowisku"],"doNot":["Nie zamieniaj footprintu bez porównania padów i mechaniki"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
