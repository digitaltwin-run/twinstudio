# EDA-PCB-UNCONNECTED-001: Niepołączone elementy sieci

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-PCB-UNCONNECTED-001","version":1,"severity":"ERROR","category":"SAFETY","title":"Brak połączenia PCB","meaning":"Elementy należące do tej samej sieci nie są elektrycznie połączone.","causes":["Brak ścieżki","PCB nie zsynchronizowane ze schematem","Przelotka lub strefa nie łączy sieci"],"remediation":["Porównaj netlistę SCH i PCB","Poprowadź brakujące połączenie","Uruchom DRC"],"verification":["0 unconnected pads dla kandydata"],"doNot":["Nie uznawaj samego podobieństwa graficznego za połączenie"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
