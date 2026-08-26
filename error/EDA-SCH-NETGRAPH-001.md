# EDA-SCH-NETGRAPH-001: Graf połączeń schematu nie został zweryfikowany

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-SCH-NETGRAPH-001","version":1,"severity":"WARNING","category":"SAFETY","title":"Brak deterministycznej analizy grafu sieci","meaning":"Adapter v1 odczytuje symbole i ich właściwości, ale nie dowodzi kompletności przewodów i etykiet sieci.","causes":["Eksporter netlisty/ERC nie został uruchomiony","Parser v1 nie interpretuje przewodów i etykiet"],"remediation":["Uruchom ERC w KiCad","Dołącz zweryfikowaną netlistę przed zmianą połączeń"],"verification":["Uruchom ERC w KiCad bez błędów","GET /api/v1/eda/schematic-state?path=<plik.kicad_sch>"],"doNot":["Nie traktuj listy symboli jako potwierdzenia połączeń"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
