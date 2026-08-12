from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from twinstudio.dsl import compile_dsl, make_execution_record, parse_dsl, write_evolution_artifacts
from twinstudio.evolution import ProjectEvolutionEngine, graph_to_dot, graph_to_mermaid
from twinstudio.evolution_models import LifecycleStage, TwinDslDocument
from twinstudio.settings import settings

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "evolution" / "rpi5-hinge-evolution.twin"


def test_twinscript_yaml_and_json_are_semantically_equivalent() -> None:
    documents = []
    for suffix, source_format in [(".twin", "twin"), (".yaml", "yaml"), (".json", "json")]:
        parsed = parse_dsl(SOURCE.with_suffix(suffix).read_text(encoding="utf-8"), source_format=source_format)
        assert parsed.valid, [item.model_dump() for item in parsed.diagnostics]
        assert parsed.document is not None
        documents.append(parsed.document.model_dump(mode="json"))
    assert documents[0] == documents[1] == documents[2]


def test_dsl_compiles_to_evolution_graph_change_plans_and_lifecycle(project_snapshot) -> None:
    parsed = parse_dsl(SOURCE.read_text(encoding="utf-8"))
    assert parsed.document is not None
    engine = ProjectEvolutionEngine(replace(settings, litellm_model=""))
    compilation = compile_dsl(project_snapshot, parsed.document, engine, actor="creator@example.test")
    assert compilation.valid is True
    assert compilation.evolution_run is not None
    assert compilation.evolution_run.goal_variants
    assert compilation.evolution_run.resources
    assert compilation.evolution_run.candidates
    assert len(compilation.evolution_run.selected_candidate_ids) <= 5
    assert compilation.change_plans
    assert compilation.lifecycle_blueprint is not None
    assert compilation.lifecycle_blueprint.current_stage == LifecycleStage.DETAILED_DESIGN
    assert any(stage.stage == LifecycleStage.VERIFICATION for stage in compilation.lifecycle_blueprint.stages)
    assert "digraph" in graph_to_dot(compilation.evolution_run.graph)
    assert "flowchart" in graph_to_mermaid(compilation.evolution_run.graph)


def test_dsl_scope_and_project_mismatch_are_blocked(project_snapshot) -> None:
    payload = json.loads((ROOT / "examples" / "evolution" / "rpi5-hinge-evolution.json").read_text())
    payload["spec"]["targets"] = ["poa://other/elsewhere@main/part/base"]
    document = TwinDslDocument.model_validate(payload)
    compilation = compile_dsl(
        project_snapshot,
        document,
        ProjectEvolutionEngine(replace(settings, litellm_model="")),
        actor="creator@example.test",
    )
    assert compilation.valid is False
    assert any(item.severity == "blocking" for item in compilation.diagnostics)


def test_generated_schema_and_grammar_are_present_and_current() -> None:
    schema = json.loads((ROOT / "schemas" / "twin-dsl.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["api_version"]["const"] == "twinstudio.io/v1alpha1"
    assert schema["properties"]["kind"]["const"] == "EvolutionProgram"
    grammar_path = ROOT / "schemas" / "twinscript.ebnf"
    grammar = grammar_path.read_text(encoding="utf-8")
    assert "version-statement" in grammar
    assert "change-statement" in grammar
    assert (ROOT / "src" / "twinstudio" / "data" / "twinscript.ebnf").read_bytes() == grammar_path.read_bytes()
    assert (ROOT / "src" / "twinstudio" / "data" / "twin-dsl.schema.json").read_bytes() == (
        ROOT / "schemas" / "twin-dsl.schema.json"
    ).read_bytes()


def test_evolution_artifacts_are_auditable(project_snapshot, tmp_path: Path) -> None:
    source = SOURCE.read_text(encoding="utf-8")
    parsed = parse_dsl(source)
    assert parsed.document is not None
    engine = ProjectEvolutionEngine(replace(settings, litellm_model=""))
    compilation = compile_dsl(project_snapshot, parsed.document, engine, actor="creator@example.test")
    execution = make_execution_record(
        project_snapshot,
        source,
        parsed.source_format,
        parsed.document,
        compilation,
        actor="creator@example.test",
        dry_run=True,
    )
    records, keys = write_evolution_artifacts(tmp_path, project_snapshot, compilation, execution)
    assert records
    assert {"dsl.json", "run.json", "graph.dot", "graph.mmd", "report.md", "candidates.csv"} <= set(keys)
    for record in records:
        path = Path(record.path)
        assert path.is_file()
        assert record.sha256


def test_dsl_execution_projection_uses_canonical_field_and_accepts_legacy_event(project_snapshot) -> None:
    from twinstudio.domain import EventEnvelope
    from twinstudio.projector import apply_event

    source = SOURCE.read_text(encoding="utf-8")
    parsed = parse_dsl(source)
    assert parsed.document is not None
    compilation = compile_dsl(
        project_snapshot,
        parsed.document,
        ProjectEvolutionEngine(replace(settings, litellm_model="")),
        actor="creator@example.test",
    )
    execution = make_execution_record(
        project_snapshot,
        source,
        parsed.source_format,
        parsed.document,
        compilation,
        actor="creator@example.test",
        dry_run=False,
    )

    snapshot = project_snapshot.model_copy(deep=True)
    apply_event(
        snapshot,
        EventEnvelope(
            stream_id=snapshot.project_id,
            stream_version=snapshot.stream_version + 1,
            event_type="DslExecutionRecorded",
            data={"execution": execution.model_dump(mode="json")},
            actor="creator@example.test",
        ),
    )
    assert execution.execution_id in snapshot.dsl_executions
    assert snapshot.dsl_programs[execution.execution_id] == snapshot.dsl_executions[execution.execution_id]

    legacy_snapshot = project_snapshot.model_copy(deep=True)
    apply_event(
        legacy_snapshot,
        EventEnvelope(
            stream_id=legacy_snapshot.project_id,
            stream_version=legacy_snapshot.stream_version + 1,
            event_type="DslProgramRecorded",
            data={"execution": execution.model_dump(mode="json")},
            actor="creator@example.test",
        ),
    )
    assert execution.execution_id in legacy_snapshot.dsl_executions
