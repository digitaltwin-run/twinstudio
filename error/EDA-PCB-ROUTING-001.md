# EDA-PCB-ROUTING-001: Zmiana sieci wymaga routingu

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-PCB-ROUTING-001","version":1,"severity":"ERROR","category":"SAFETY","title":"Zmiana przypisania sieci bez routingu","meaning":"Zmiana padów PCB może pozostawić ścieżki na poprzednich fizycznych pinach.","causes":["LLM zmienił przypisania padów","Nie wykonano ponownego routingu"],"remediation":["Przeprowadź ścieżki zgodnie z nowym pinoutem","Uruchom DRC i sprawdź różnicę"],"verification":["KiCad DRC bez nowych błędów"],"doNot":["Nie akceptuj samej zmiany netu jako gotowej płytki"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
