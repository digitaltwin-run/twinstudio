# EDA-PCB-VIA-001: Niepodłączona przelotka

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-PCB-VIA-001","version":1,"severity":"WARNING","category":"SAFETY","title":"Przelotka bez połączenia na obu warstwach","meaning":"Przelotka może nie mieć ciągłości elektrycznej.","causes":["Urwana ścieżka","Nieaktualna strefa miedzi"],"remediation":["Zweryfikuj połączenie na obu warstwach","Usuń zbędną przelotkę","Przelicz strefy"],"verification":["DRC bez via_dangling"],"doNot":["Nie ignoruj ostrzeżenia bez sprawdzenia warstw"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
