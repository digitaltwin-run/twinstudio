# EDA-PCB-DRC-001: DRC PCB nie został uruchomiony

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-PCB-DRC-001","version":1,"severity":"ERROR","category":"SAFETY","title":"Brak wyniku DRC dla kandydata PCB","meaning":"Bez deterministycznego DRC nie można zatwierdzić zmiany w PCB.","causes":["KiCad DRC nie został wykonany","Środowisko walidacji nie jest dostępne"],"remediation":["Uruchom DRC w KiCad","Usuń nowe błędy i niepołączenia"],"verification":["Raport DRC dla dokładnego SHA-256 kandydata"],"doNot":["Nie omijaj bramki DRC"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
