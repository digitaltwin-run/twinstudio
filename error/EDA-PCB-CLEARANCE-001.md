# EDA-PCB-CLEARANCE-001: Brak odstępu między różnymi sieciami

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-PCB-CLEARANCE-001","version":1,"severity":"ERROR","category":"SAFETY","title":"Naruszenie clearance PCB","meaning":"Miedź różnych sieci styka się lub jest bliżej niż pozwala reguła płytki.","causes":["Błędnie poprowadzona ścieżka","Zmiana footprintu albo netlisty"],"remediation":["Przeprowadź ścieżkę ponownie","Nie przypisuj automatycznie netów","Uruchom DRC"],"verification":["DRC dla SHA-256 kandydata bez błędów clearance"],"doNot":["Nie akceptuj kandydata z tym błędem"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
