# EDA-SCH-EMPTY-001: Schemat nie zawiera symboli

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-SCH-EMPTY-001","version":1,"severity":"ERROR","category":"SAFETY","title":"Schemat nie zawiera symboli","meaning":"Nie można bezpiecznie planować zmiany ani synchronizować PCB bez umieszczonych symboli.","causes":["Plik jest pusty lub uszkodzony","Symbole są zapisane w nieobsługiwanej strukturze"],"remediation":["Otwórz plik w KiCad","Przywróć symbole z poprawnej rewizji","Ponownie uruchom analizę schematu"],"verification":["GET /api/v1/eda/schematic-state?path=<plik.kicad_sch>"],"doNot":["Nie generuj zmian LLM dla pustego schematu"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
