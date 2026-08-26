# EDA-SCH-PCB-SYNC-001: Schemat i PCB nie są zsynchronizowane

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-SCH-PCB-SYNC-001","version":1,"severity":"WARNING","category":"SAFETY","title":"Niezgodne oznaczenia schematu i PCB","meaning":"Zestaw komponentów w schemacie różni się od sąsiedniej płytki, więc zmiany pinów lub sieci wymagają weryfikacji w KiCad.","causes":["PCB nie zostało zaktualizowane ze schematu","Element jest celowo DNP","Źródła pochodzą z różnych rewizji"],"remediation":["Porównaj listy Reference","Uaktualnij PCB ze schematu","Oznacz celowe DNP w dokumentacji"],"verification":["GET /api/v1/eda/schematic-state?path=<plik.kicad_sch>","Uruchom Update PCB from Schematic w KiCad"],"doNot":["Nie promuj automatycznie zmian połączeń"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
