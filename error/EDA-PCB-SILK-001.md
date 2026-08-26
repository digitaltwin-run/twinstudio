# EDA-PCB-SILK-001: Silk nad miedzią

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-PCB-SILK-001","version":1,"severity":"WARNING","category":"SAFETY","title":"Opis silk koliduje z miedzią","meaning":"Nadruk może zostać obcięty przez maskę lub utrudnić montaż.","causes":["Opis zbyt blisko pada"],"remediation":["Przesuń lub skróć opis"],"verification":["DRC bez silk_over_copper"],"doNot":["Nie traktuj jako zwarcia elektrycznego"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
