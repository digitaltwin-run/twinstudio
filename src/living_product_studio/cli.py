from __future__ import annotations

import json
from pathlib import Path

import typer

from living_product_studio.artifacts import export_project_bundle
from living_product_studio.bus import CommandBus, QueryService
from living_product_studio.change_planner import ChangePlanner
from living_product_studio.domain import CommandEnvelope, RegionSelection
from living_product_studio.event_store import EventStore
from living_product_studio.gtin import complete_gtin, validate_gtin
from living_product_studio.mqtt_bus import publisher_from_settings
from living_product_studio.seed import seed_from_file
from living_product_studio.settings import settings
from living_product_studio.simulations import simulate_power


app = typer.Typer(help="Living Product Studio CLI. Uses the same command/query contracts as REST, MQTT and MCP.")


def services():
    store = EventStore(settings.database_url)
    publisher = publisher_from_settings(settings)
    return store, QueryService(store), CommandBus(store, publisher), ChangePlanner(settings), publisher


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Run the REST/web/MCP application."""
    import uvicorn

    uvicorn.run("living_product_studio.api:app", host=host, port=port, reload=reload)


@app.command()
def seed(
    example: Path = typer.Option(Path("examples/rpi5-camera3/project.json"), exists=True),
    force: bool = False,
) -> None:
    store, _, _, _, publisher = services()
    snapshot = seed_from_file(store, publisher, example, force=force)
    typer.echo(f"Seeded {snapshot.project_id}: {snapshot.name}")


@app.command("projects")
def projects_cmd() -> None:
    _, queries, _, _, _ = services()
    typer.echo(json.dumps(queries.projects(), indent=2, ensure_ascii=False))


@app.command()
def tree(project_id: str = "demo-rpi5") -> None:
    _, queries, _, _, _ = services()
    typer.echo(json.dumps(queries.tree(project_id), indent=2, ensure_ascii=False))


@app.command()
def command(
    project_id: str,
    command_type: str,
    payload: str = typer.Option("{}", help="JSON object"),
    actor: str = typer.Option("creator@example.test"),
    expected_version: int | None = None,
) -> None:
    store, _, commands, _, _ = services()
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
    typer.echo(json.dumps([event.model_dump(mode="json") for event in events], indent=2, ensure_ascii=False))


@app.command()
def plan(
    prompt: str,
    selection: Path = typer.Option(..., exists=True),
    project_id: str = "demo-rpi5",
    actor: str = "editor@example.test",
    record: bool = True,
) -> None:
    store, queries, commands, planner, _ = services()
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
    typer.echo(json.dumps({"mode": result.mode, "plan": result.plan.model_dump(mode="json")}, indent=2, ensure_ascii=False))


@app.command()
def power(project_id: str = "demo-rpi5") -> None:
    _, queries, _, _, _ = services()
    snapshot = queries.project(project_id)
    if not snapshot.power_model:
        raise typer.BadParameter("Project has no power model")
    typer.echo(json.dumps(simulate_power(snapshot.power_model), indent=2, ensure_ascii=False))


@app.command()
def export(project_id: str = "demo-rpi5", out: Path | None = None) -> None:
    _, queries, _, _, _ = services()
    snapshot = queries.project(project_id)
    output = out or settings.data_dir / "artifacts" / f"{project_id}-{snapshot.revision}.lps.zip"
    export_project_bundle(snapshot, queries.events(project_id), output, project_root=Path.cwd())
    typer.echo(str(output))


@app.command("gtin-complete")
def gtin_complete(body: str, length: int = 13) -> None:
    typer.echo(complete_gtin(body, total_length=length))


@app.command("gtin-validate")
def gtin_validate(value: str) -> None:
    raise typer.Exit(code=0 if validate_gtin(value) else 1)


@app.command()
def shell() -> None:
    """Start a small interactive shell around the same CLI commands."""
    typer.echo("Living Product Studio shell. Commands: projects, tree <id>, power <id>, quit")
    while True:
        try:
            line = input("lps> ").strip()
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
            else:
                typer.echo("Unknown command")
        except Exception as exc:
            typer.echo(f"Error: {exc}")


if __name__ == "__main__":
    app()
