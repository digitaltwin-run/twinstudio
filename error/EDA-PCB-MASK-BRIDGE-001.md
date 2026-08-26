# EDA-PCB-MASK-BRIDGE-001: Mostek maski lutowniczej

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-PCB-MASK-BRIDGE-001","version":1,"severity":"ERROR","category":"SAFETY","title":"Mostek otworów maski różnych sieci","meaning":"Maska lutownicza nie rozdziela elementów różnych sieci.","causes":["Ścieżka zbyt blisko pada","Niewłaściwa reguła maski"],"remediation":["Zwiększ odstęp","Zweryfikuj parametry maski","Uruchom DRC"],"verification":["Brak solder_mask_bridge dla kandydata"],"doNot":["Nie promuj PCB przed usunięciem mostka"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
