from __future__ import annotations

import json
from pathlib import Path

from living_product_studio.domain import ChangePlan, ProjectSnapshot, ProjectionMap, RegionSelection, SelectionMap, TestPlan


root = Path(__file__).resolve().parents[1] / "schemas"
root.mkdir(parents=True, exist_ok=True)
for name, model in {
    "product-project.schema.json": ProjectSnapshot,
    "change-plan.schema.json": ChangePlan,
    "region-selection.schema.json": RegionSelection,
    "projection-map.schema.json": ProjectionMap,
    "selection-map.schema.json": SelectionMap,
    "test-plan.schema.json": TestPlan,
}.items():
    (root / name).write_text(json.dumps(model.model_json_schema(), indent=2), encoding="utf-8")
print(f"Wrote schemas to {root}")
