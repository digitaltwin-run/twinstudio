# EDA-PCB-SILK-EDGE-001: Silk przy krawędzi

```log-error-dsl
{"schema":"wellmanifest.logs/error/v1","code":"EDA-PCB-SILK-EDGE-001","version":1,"severity":"WARNING","category":"SAFETY","title":"Opis silk zbyt blisko Edge.Cuts","meaning":"Nadruk może zostać obcięty w produkcji.","causes":["Opis poza bezpiecznym obrysem"],"remediation":["Przesuń opis do środka płytki"],"verification":["DRC bez silk_edge_clearance"],"doNot":["Nie zmieniaj Edge.Cuts wyłącznie dla ukrycia ostrzeżenia"],"owner":"unresolved:human","relatedEventTypes":["validation_failed","error_raised"]}
```
