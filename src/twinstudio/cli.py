from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from twinstudio.artifacts import export_project_bundle
from twinstudio.bus import CommandBus, QueryService
from twinstudio.change_planner import ChangePlanner
from twinstudio.domain import ChangePlan, CommandEnvelope, RegionSelection
from twinstudio.dsl import (
    canonical_dsl_grammar,
    canonical_dsl_schema,
    compile_dsl,
    make_execution_record,
    parse_dsl,
    safe_parameter_patches,
    write_evolution_artifacts,
)
from twinstudio.event_store import EventStore
from twinstudio.evolution import ProjectEvolutionEngine, graph_to_dot, graph_to_mermaid
from twinstudio.evolution_models import EvolutionRun, RealizationMode
from twinstudio.feature_lenses import FeatureLensEngine
from twinstudio.gtin import complete_gtin, validate_gtin
from twinstudio.mqtt_bus import publisher_from_settings
from twinstudio.seed import seed_from_file
from twinstudio.settings import settings
from twinstudio.simulations import simulate_power

app = typer.Typer(
    help=(
        "TwinStudio CLI. Uses the same typed command/query contracts as REST, MQTT and MCP. "
        "The legacy executable name 'lps' remains a compatibility alias in version 0.5.0."
    )
)


def services() -> tuple[
    EventStore,
    QueryService,
    CommandBus,
    ChangePlanner,
    FeatureLensEngine,
    Any,
]:
    store = EventStore(settings.database_url)
    publisher = publisher_from_settings(settings)
    return (
        store,
        QueryService(store),
        CommandBus(store, publisher),
        ChangePlanner(settings),
        FeatureLensEngine(settings),
        publisher,
    )


def _evolution_engine() -> ProjectEvolutionEngine:
    return ProjectEvolutionEngine(settings)


def _emit_json(payload: object, out: Path | None = None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        typer.echo(str(out))
    else:
        typer.echo(text, nl=False)


def _record_command(
    store: EventStore,
    commands: CommandBus,
    project_id: str,
    command_type: str,
    actor: str,
    payload: dict[str, Any],
):
    return commands.execute(
        CommandEnvelope(
            command_type=command_type,
            project_id=project_id,
            expected_version=store.current_version(project_id),
            actor=actor,
            payload=payload,
        )
    )


@app.command()
def serve(host: str = settings.host, port: int = settings.port, reload: bool = False) -> None:
    """Run the REST, web and MCP application."""
    import uvicorn

    uvicorn.run("twinstudio.api:app", host=host, port=port, reload=reload)


@app.command()
def seed(
    example: Path = typer.Option(Path("examples/rpi5-camera3/project.json"), exists=True),
    force: bool = False,
) -> None:
    """Create or recreate the example project in the configured event store."""
    store, _, _, _, _, publisher = services()
    snapshot = seed_from_file(store, publisher, example, force=force)
    typer.echo(f"Seeded {snapshot.project_id}: {snapshot.name}")


@app.command("projects")
def projects_cmd() -> None:
    """List projects available in the configured event store."""
    _, queries, _, _, _, _ = services()
    _emit_json(queries.projects())


@app.command()
def tree(project_id: str = "demo-rpi5") -> None:
    """Print the hierarchical product object tree."""
    _, queries, _, _, _, _ = services()
    _emit_json(queries.tree(project_id))


@app.command()
def command(
    project_id: str,
    command_type: str,
    payload: str = typer.Option("{}", help="JSON object"),
    actor: str = typer.Option("creator@example.test"),
    expected_version: int | None = None,
) -> None:
    """Execute one typed CQRS command."""
    store, _, commands, _, _, _ = services()
    if expected_version is None:
        expected_version = 0 if command_type == "project.create" else store.current_version(project_id)
    events = commands.execute(
        CommandEnvelope(
            command_type=command_type,
            project_id=project_id,
            expected_version=expected_version,
            actor=actor,
            payload=json.loads(payload),
        )
    )
    _emit_json([event.model_dump(mode="json") for event in events])


@app.command()
def plan(
    prompt: str,
    selection: Path = typer.Option(..., exists=True),
    project_id: str = "demo-rpi5",
    actor: str = "editor@example.test",
    record: bool = True,
) -> None:
    """Compile a scoped natural-language change request into a typed ChangePlan."""
    _, queries, commands, planner, _, _ = services()
    snapshot = queries.project(project_id)
    selected = RegionSelection.model_validate_json(selection.read_text(encoding="utf-8"))
    result = planner.plan(prompt, selected, snapshot, actor)
    if record:
        commands.execute(
            CommandEnvelope(
                command_type="change.plan.record",
                project_id=project_id,
                expected_version=snapshot.stream_version,
                actor=actor,
                payload={"plan": result.plan.model_dump(mode="json")},
            )
        )
    _emit_json(
        {
            "mode": result.mode,
            "message": result.message,
            "plan": result.plan.model_dump(mode="json"),
        }
    )


@app.command("lenses")
def lenses_cmd(include_disabled: bool = False) -> None:
    """Print the source-grounded Feature Type Spectrum catalog."""
    _, _, _, _, engine, _ = services()
    payload = engine.catalog.model_dump(mode="json")
    if not include_disabled:
        payload["lenses"] = [item for item in payload["lenses"] if item["enabled"]]
    _emit_json(payload)


@app.command("fixation")
def fixation_cmd(
    target_uri: str,
    challenge: str = "",
    project_id: str = "demo-rpi5",
    actor: str = "editor@example.test",
    lens: list[str] | None = typer.Option(None, "--lens", help="Repeat to select lens IDs."),
    max_alternatives: int = typer.Option(8, min=1, max=20),
    use_llm: bool = True,
    record: bool = True,
) -> None:
    """Run a design-fixation review and optionally record it."""
    _, queries, commands, _, engine, _ = services()
    snapshot = queries.project(project_id)
    result = engine.scan(
        snapshot,
        target_uri=target_uri,
        challenge=challenge,
        actor=actor,
        lens_ids=lens or None,
        max_alternatives=max_alternatives,
        use_llm=use_llm,
    )
    if record:
        commands.execute(
            CommandEnvelope(
                command_type="design_fixation.review.record",
                project_id=project_id,
                expected_version=snapshot.stream_version,
                actor=actor,
                payload={"review": result.review.model_dump(mode="json")},
            )
        )
    _emit_json(
        {
            "mode": result.mode,
            "message": result.message,
            "review": result.review.model_dump(mode="json"),
        }
    )


@app.command("dsl-schema")
def dsl_schema_cmd(out: Path | None = typer.Option(None, help="Optional output JSON file.")) -> None:
    """Print or write the canonical EvolutionProgram JSON Schema."""
    _emit_json(canonical_dsl_schema(), out)


@app.command("dsl-grammar")
def dsl_grammar_cmd() -> None:
    """Print the EBNF grammar for TwinScript 1.0."""
    try:
        typer.echo(canonical_dsl_grammar(), nl=False)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("dsl-parse")
def dsl_parse_cmd(
    source: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    source_format: str = typer.Option("auto", "--format", help="auto, twin, yaml or json"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Parse TwinScript/YAML/JSON and emit canonical validated JSON."""
    parsed = parse_dsl(source.read_text(encoding="utf-8"), source_format=source_format)
    payload = {
        "valid": parsed.valid,
        "source_format": parsed.source_format,
        "diagnostics": [item.model_dump(mode="json") for item in parsed.diagnostics],
        "document": parsed.document.model_dump(mode="json") if parsed.document else None,
    }
    _emit_json(payload, out)
    if not parsed.valid:
        raise typer.Exit(code=2)


@app.command("dsl-preview")
def dsl_preview_cmd(
    source: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    project_id: str = typer.Option("demo-rpi5", "--project-id"),
    source_format: str = typer.Option("auto", "--format"),
    actor: str = typer.Option("creator@example.test", "--actor"),
    out: Path | None = typer.Option(None, "--out"),
    artifact_dir: Path | None = typer.Option(
        None,
        "--artifact-dir",
        help="Optionally write the dry-run graph, report and candidate files.",
    ),
) -> None:
    """Compile a DSL program into an evolution run without writing project events."""
    _, queries, _, _, _, _ = services()
    source_text = source.read_text(encoding="utf-8")
    parsed = parse_dsl(source_text, source_format=source_format)
    if not parsed.document:
        _emit_json(
            {
                "valid": False,
                "source_format": parsed.source_format,
                "diagnostics": [item.model_dump(mode="json") for item in parsed.diagnostics],
            },
            out,
        )
        raise typer.Exit(code=2)
    if parsed.document.spec.project_id != project_id:
        raise typer.BadParameter("DSL project_id does not match --project-id")
    snapshot = queries.project(project_id)
    compilation = compile_dsl(snapshot, parsed.document, _evolution_engine(), actor=actor)
    execution = make_execution_record(
        snapshot,
        source_text,
        parsed.source_format,
        parsed.document,
        compilation,
        actor=actor,
        dry_run=True,
    )
    artifact_keys: dict[str, str] = {}
    if artifact_dir and compilation.valid:
        records, artifact_keys = write_evolution_artifacts(
            artifact_dir,
            snapshot,
            compilation,
            execution,
        )
        artifact_keys["record_count"] = str(len(records))
    payload = compilation.model_dump(mode="json")
    payload.update(
        {
            "source_format": parsed.source_format,
            "execution": execution.model_dump(mode="json"),
            "artifact_keys": artifact_keys,
        }
    )
    _emit_json(payload, out)
    if not compilation.valid:
        raise typer.Exit(code=2)


@app.command("dsl-apply")
def dsl_apply_cmd(
    source: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    project_id: str = typer.Option("demo-rpi5", "--project-id"),
    source_format: str = typer.Option("auto", "--format"),
    actor: str = typer.Option("creator@example.test", "--actor"),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Append typed events. Without this flag the command is a dry-run preview.",
    ),
    generate_artifacts: bool = typer.Option(True, "--generate-artifacts/--no-artifacts"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Preview or record a validated DSL program through the CQRS event stream."""
    store, queries, commands, _, _, _ = services()
    source_text = source.read_text(encoding="utf-8")
    parsed = parse_dsl(source_text, source_format=source_format)
    if not parsed.document:
        _emit_json(
            {
                "valid": False,
                "diagnostics": [item.model_dump(mode="json") for item in parsed.diagnostics],
                "events": [],
            },
            out,
        )
        raise typer.Exit(code=2)
    if parsed.document.spec.project_id != project_id:
        raise typer.BadParameter("DSL project_id does not match --project-id")

    snapshot = queries.project(project_id)
    compilation = compile_dsl(snapshot, parsed.document, _evolution_engine(), actor=actor)
    execution = make_execution_record(
        snapshot,
        source_text,
        parsed.source_format,
        parsed.document,
        compilation,
        actor=actor,
        dry_run=not execute,
    )
    if not execute or not compilation.valid:
        payload = compilation.model_dump(mode="json")
        payload.update({"execution": execution.model_dump(mode="json"), "events": []})
        _emit_json(payload, out)
        if not compilation.valid:
            raise typer.Exit(code=2)
        return

    stored = []
    if compilation.evolution_run:
        stored.extend(
            _record_command(
                store,
                commands,
                project_id,
                "evolution.run.record",
                actor,
                {"run": compilation.evolution_run.model_dump(mode="json")},
            )
        )
    if compilation.lifecycle_blueprint:
        stored.extend(
            _record_command(
                store,
                commands,
                project_id,
                "lifecycle.blueprint.upsert",
                actor,
                {"blueprint": compilation.lifecycle_blueprint.model_dump(mode="json")},
            )
        )
    for raw_plan in compilation.change_plans:
        plan_model = ChangePlan.model_validate(raw_plan)
        stored.extend(
            _record_command(
                store,
                commands,
                project_id,
                "change.plan.record",
                actor,
                {"plan": plan_model.model_dump(mode="json")},
            )
        )

    safe_patches = safe_parameter_patches(parsed.document)
    auto_apply = (
        parsed.document.spec.realization.mode == RealizationMode.AUTO_APPLY_SAFE
        and not parsed.document.spec.realization.dry_run
        and not parsed.document.spec.realization.require_approval
        and bool(safe_patches)
        and len(safe_patches) == len(parsed.document.spec.explicit_changes)
    )
    if auto_apply:
        current = queries.project(project_id)
        stored.extend(
            _record_command(
                store,
                commands,
                project_id,
                "change.apply",
                actor,
                {
                    "new_revision": f"{current.revision}-dsl-{execution.execution_id[-8:]}",
                    "parameter_patches": safe_patches,
                    "approval_state": "approved",
                    "dsl_execution_id": execution.execution_id,
                },
            )
        )

    artifact_keys: dict[str, str] = {}
    if generate_artifacts and parsed.document.spec.outputs.persist_artifacts:
        artifacts, artifact_keys = write_evolution_artifacts(
            settings.data_dir / "artifacts",
            snapshot,
            compilation,
            execution,
        )
        for artifact in artifacts:
            stored.extend(
                _record_command(
                    store,
                    commands,
                    project_id,
                    "artifact.attach",
                    actor,
                    {"artifact": artifact.model_dump(mode="json")},
                )
            )

    execution = execution.model_copy(
        update={
            "status": "executed" if not compilation.change_plans or auto_apply else "partially_executed",
            "event_ids": [item.event_id for item in stored],
        }
    )
    stored.extend(
        _record_command(
            store,
            commands,
            project_id,
            "dsl.execution.record",
            actor,
            {"execution": execution.model_dump(mode="json")},
        )
    )
    payload = compilation.model_dump(mode="json")
    payload.update(
        {
            "execution": execution.model_dump(mode="json"),
            "events": [item.model_dump(mode="json") for item in stored],
            "artifact_keys": artifact_keys,
            "auto_applied_parameter_patches": safe_patches if auto_apply else [],
        }
    )
    _emit_json(payload, out)


@app.command("evolution-runs")
def evolution_runs_cmd(project_id: str = "demo-rpi5") -> None:
    """List recorded evolution runs."""
    _, queries, _, _, _, _ = services()
    _emit_json(list(queries.project(project_id).evolution_runs.values()))


@app.command("evolution-show")
def evolution_show_cmd(
    run_id: str,
    project_id: str = "demo-rpi5",
    graph_format: str = typer.Option("json", "--graph", help="json, dot or mermaid"),
) -> None:
    """Show one recorded evolution run or a graph representation."""
    _, queries, _, _, _, _ = services()
    raw = queries.project(project_id).evolution_runs.get(run_id)
    if not raw:
        raise typer.BadParameter("Evolution run not found")
    run = EvolutionRun.model_validate(raw)
    normalized = graph_format.lower()
    if normalized == "dot":
        typer.echo(graph_to_dot(run.graph))
    elif normalized == "mermaid":
        typer.echo(graph_to_mermaid(run.graph))
    elif normalized == "json":
        _emit_json(run.model_dump(mode="json"))
    else:
        raise typer.BadParameter("--graph must be json, dot or mermaid")


@app.command("lifecycles")
def lifecycles_cmd(project_id: str = "demo-rpi5") -> None:
    """Show lifecycle blueprints and transition history."""
    _, queries, _, _, _, _ = services()
    snapshot = queries.project(project_id)
    _emit_json(
        {
            "current_project_stage": snapshot.lifecycle_stage,
            "blueprints": list(snapshot.lifecycle_blueprints.values()),
            "history": snapshot.lifecycle_history,
        }
    )


@app.command()
def power(project_id: str = "demo-rpi5") -> None:
    """Run the reduced-order power and voltage-drop model."""
    _, queries, _, _, _, _ = services()
    snapshot = queries.project(project_id)
    if not snapshot.power_model:
        raise typer.BadParameter("Project has no power model")
    _emit_json(simulate_power(snapshot.power_model))


@app.command()
def export(project_id: str = "demo-rpi5", out: Path | None = None) -> None:
    """Export a portable .twinstudio.zip project bundle."""
    _, queries, _, _, _, _ = services()
    snapshot = queries.project(project_id)
    output = out or settings.data_dir / "artifacts" / (
        f"{project_id}-{snapshot.revision}{settings.export_extension}"
    )
    export_project_bundle(snapshot, queries.events(project_id), output, project_root=Path.cwd())
    typer.echo(str(output))


@app.command("gtin-complete")
def gtin_complete(body: str, length: int = 13) -> None:
    """Calculate a GTIN check digit; this does not allocate a GS1 identifier."""
    typer.echo(complete_gtin(body, total_length=length))


@app.command("gtin-validate")
def gtin_validate(value: str) -> None:
    """Exit with status 0 only when the GTIN check digit is valid."""
    raise typer.Exit(code=0 if validate_gtin(value) else 1)


@app.command()
def shell() -> None:
    """Start a small interactive shell around the same service layer."""
    typer.echo(
        "TwinStudio shell. Commands: projects, tree <id>, power <id>, lenses, "
        "evolution-runs <id>, lifecycles <id>, quit"
    )
    while True:
        try:
            line = input("twinstudio> ").strip()
        except (EOFError, KeyboardInterrupt):
            typer.echo()
            break
        if not line:
            continue
        if line in {"quit", "exit"}:
            break
        tokens = line.split()
        try:
            if tokens[0] == "projects":
                projects_cmd()
            elif tokens[0] == "tree":
                tree(tokens[1] if len(tokens) > 1 else "demo-rpi5")
            elif tokens[0] == "power":
                power(tokens[1] if len(tokens) > 1 else "demo-rpi5")
            elif tokens[0] == "lenses":
                lenses_cmd()
            elif tokens[0] == "evolution-runs":
                evolution_runs_cmd(tokens[1] if len(tokens) > 1 else "demo-rpi5")
            elif tokens[0] == "lifecycles":
                lifecycles_cmd(tokens[1] if len(tokens) > 1 else "demo-rpi5")
            else:
                typer.echo("Unknown command")
        except Exception as exc:  # pragma: no cover - interactive boundary
            typer.echo(f"Error: {exc}")


if __name__ == "__main__":
    app()
