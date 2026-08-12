REPAIR 1.0
CODE "CAD-CHANGE-INVALID"
TITLE "Zmiana narusza ograniczenia geometrii CAD"

SYMPTOM
Plan zawiera poprawną operację parametryczną, ale `apply` zwraca 422 i nie tworzy
`ChangeApplied` ani zadania regeneracji CAD.

CHECK
1. Odczytaj `error.details.warnings` albo rekord TWINOBS `CAD-CHANGE-INVALID`.
2. Sprawdź `warning.code`, `message` i `suggestion`.
3. Potwierdź obiekt i komplet parametrów planu. Dla `AUX_BOSS_TOP_ABOVE_LID`
   obniżenie pokrywy wymaga zależnego przesunięcia górnego poziomu bossa pomocniczego.

REPAIR
1. Utwórz nowy plan NL dla bieżącej rewizji; planner automatycznie dodaje obsługiwaną
   zależność bossa do obniżenia pokrywy.
2. Dla bezpośredniego planu API jawnie dodaj wszystkie zależne parametry wskazane przez warning.
3. Nie wykonuj ręcznego rollbacku: preflight działa przed zapisem i projekt nie został zmieniony.

VERIFY
1. Odrzucona próba nie zwiększyła rewizji projektu i nie dodała `ChangeApplied`.
2. Poprawna próba tworzy `GenerationRequested`, a następnie `GenerationCompleted`.
3. Widoki 2D/3D odświeżają się automatycznie po zakończeniu nowego zadania.

END
