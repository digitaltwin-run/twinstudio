from __future__ import annotations

import json
import shutil
from pathlib import Path

from twinstudio.domain import (
    ChangeExecutionAuthority,
    ChangePlan,
    ChangePlanLlmRequest,
    ChangePlanProposal,
    DesignFixationReview,
    InvalidLlmResponseArtifact,
    ProjectionMap,
    ProjectSnapshot,
    RegionSelection,
    SelectionMap,
    TestPlan,
)
from twinstudio.eda_history import EdaHistoryEntry, TwinStudioProject
from twinstudio.evolution_models import (
    DslExecutionRecord,
    EvolutionCatalog,
    EvolutionRun,
    LifecycleBlueprint,
    TwinDslDocument,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas"
PACKAGE_DATA_ROOT = ROOT / "src" / "twinstudio" / "data"
SCHEMA_ROOT.mkdir(parents=True, exist_ok=True)
PACKAGE_DATA_ROOT.mkdir(parents=True, exist_ok=True)

MODELS = {
    "product-project.schema.json": ProjectSnapshot,
    "change-plan.schema.json": ChangePlan,
    "change-plan-request.schema.json": ChangePlanLlmRequest,
    "change-plan-proposal.schema.json": ChangePlanProposal,
    "change-authority.schema.json": ChangeExecutionAuthority,
    "invalid-llm-response.schema.json": InvalidLlmResponseArtifact,
    "design-fixation-review.schema.json": DesignFixationReview,
    "region-selection.schema.json": RegionSelection,
    "projection-map.schema.json": ProjectionMap,
    "selection-map.schema.json": SelectionMap,
    "test-plan.schema.json": TestPlan,
    "twin-dsl.schema.json": TwinDslDocument,
    "evolution-run.schema.json": EvolutionRun,
    "lifecycle-blueprint.schema.json": LifecycleBlueprint,
    "dsl-execution.schema.json": DslExecutionRecord,
    "evolution-catalog.schema.json": EvolutionCatalog,
    "twinstudio-project.schema.json": TwinStudioProject,
    "eda-history-entry.schema.json": EdaHistoryEntry,
}

for name, model in MODELS.items():
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://twinstudio.local/schemas/{name}"
    schema.setdefault("title", model.__name__)
    (SCHEMA_ROOT / name).write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

index = {
    "product": "TwinStudio",
    "schema_set_version": "0.5.0",
    "draft": "2020-12",
    "schemas": [
        {
            "file": name,
            "model": model.__name__,
            "id": f"https://twinstudio.local/schemas/{name}",
        }
        for name, model in MODELS.items()
    ],
    "text_dsl_grammar": "twinscript.ebnf",
}
(SCHEMA_ROOT / "index.json").write_text(
    json.dumps(index, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

# The REST/CLI fallback must use the same canonical schema and grammar as the source tree.
shutil.copy2(SCHEMA_ROOT / "twin-dsl.schema.json", PACKAGE_DATA_ROOT / "twin-dsl.schema.json")
grammar = SCHEMA_ROOT / "twinscript.ebnf"
if not grammar.is_file():
    raise FileNotFoundError(f"Canonical TwinScript grammar not found: {grammar}")
shutil.copy2(grammar, PACKAGE_DATA_ROOT / "twinscript.ebnf")

print(
    f"Wrote {len(MODELS)} JSON Schemas plus index to {SCHEMA_ROOT}; "
    "synchronized TwinScript schema and grammar into package data"
)
