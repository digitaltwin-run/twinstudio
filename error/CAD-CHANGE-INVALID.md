REPAIR 1.0
CODE "CAD-CHANGE-INVALID"
TITLE "Zmiana narusza ograniczenia geometrii CAD"

SYMPTOM
Plan zawiera poprawną operację parametryczną, ale `apply` zwraca 422 i nie tworzy
`ChangeApplied` ani zadania regeneracji CAD.

CHECK
1. Odczytaj `error.details.warnings` albo rekord TWINOBS `CAD-CHANGE-INVALID`.
2. Sprawdź `warning.code`, `message` i `suggestion`.
3. Potwierdź obiekt i parametr planu. Dla `AUX_BOSS_TOP_ABOVE_LID` wysokość pokrywy
   nie może być mniejsza od górnego poziomu bossa pomocniczego.

REPAIR
1. Podaj wartość zgodną z ograniczeniem opisanym w `suggestion` albo zmień zależną cechę.
2. Utwórz nowy plan dla bieżącej rewizji i zastosuj go ponownie.
3. Nie wykonuj ręcznego rollbacku: preflight działa przed zapisem i projekt nie został zmieniony.

VERIFY
1. Odrzucona próba nie zwiększyła rewizji projektu i nie dodała `ChangeApplied`.
2. Poprawna próba tworzy `GenerationRequested`, a następnie `GenerationCompleted`.
3. Widoki 2D/3D odświeżają się automatycznie po zakończeniu nowego zadania.

END
