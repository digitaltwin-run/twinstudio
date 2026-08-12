from __future__ import annotations

import csv
import hashlib
import json
import shlex
from importlib.resources import files as package_files
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import ValidationError

from twinstudio.artifacts import sha256_file
from twinstudio.domain import (
    ArtifactKind,
    ArtifactRecord,
    ChangeOperation,
    ChangeOperationKind,
    ChangePlan,
    LifecycleStage,
    ProjectSnapshot,
    Role,
)
from twinstudio.evolution import (
    ProjectEvolutionEngine,
    diagnostics_for_program,
    graph_to_dot,
    graph_to_mermaid,
)
from twinstudio.evolution_models import (
    DslCompilation,
    DslDiagnostic,
    DslExecutionRecord,
    DslMetadata,
    DslSeverity,
    EvaluationDimension,
    EvolutionGateSpec,
    EvolutionMethod,
    EvolutionOperatorSpec,
    EvolutionPhase,
    EvolutionProgramSpec,
    LifecycleBlueprint,
    MutationOperatorKind,
    RealizationMode,
    TwinDslDocument,
)


@dataclass(frozen=True, slots=True)
class ParsedDsl:
    document: TwinDslDocument | None
    diagnostics: list[DslDiagnostic]
    source_format: str

    @property
    def valid(self) -> bool:
        return self.document is not None and not any(
            item.severity in {DslSeverity.ERROR, DslSeverity.BLOCKING} for item in self.diagnostics
        )


def canonical_dsl_schema() -> dict[str, Any]:
    """Load the published Draft 2020-12 schema from source or installed package data."""
    source = Path(__file__).resolve().parents[2] / "schemas" / "twin-dsl.schema.json"
    if source.is_file():
        return json.loads(source.read_text(encoding="utf-8"))
    packaged = package_files("twinstudio").joinpath("data/twin-dsl.schema.json")
    if not packaged.is_file():
        raise FileNotFoundError("Canonical TwinStudio DSL schema was not packaged")
    return json.loads(packaged.read_text(encoding="utf-8"))


def canonical_dsl_grammar() -> str:
    """Load the canonical TwinScript EBNF from source or installed package data."""
    source = Path(__file__).resolve().parents[2] / "schemas" / "twinscript.ebnf"
    if source.is_file():
        return source.read_text(encoding="utf-8")
    packaged = package_files("twinstudio").joinpath("data/twinscript.ebnf")
    if not packaged.is_file():
        raise FileNotFoundError("Canonical TwinScript grammar was not packaged")
    return packaged.read_text(encoding="utf-8")


def detect_source_format(source_text: str, requested: str | None = None) -> str:
    if requested and requested != "auto":
        normalized = requested.lower()
        if normalized not in {"twin", "yaml", "json"}:
            raise ValueError("source_format must be auto, twin, yaml or json")
        return normalized
    stripped = source_text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    if stripped.startswith("apiVersion:") or stripped.startswith("api_version:") or "\nkind: EvolutionProgram" in source_text:
        return "yaml"
    return "twin"


def parse_dsl(source_text: str, *, source_format: str | None = None) -> ParsedDsl:
    resolved_format = detect_source_format(source_text, source_format)
    parse_diagnostics: list[DslDiagnostic] = []
    try:
        if resolved_format == "json":
            payload = json.loads(source_text)
        elif resolved_format == "yaml":
            payload = yaml.safe_load(source_text)
        else:
            payload, parse_diagnostics = _parse_twinscript(source_text)
            if any(
                item.severity in {DslSeverity.ERROR, DslSeverity.BLOCKING}
                for item in parse_diagnostics
            ):
                return ParsedDsl(
                    document=None,
                    diagnostics=parse_diagnostics,
                    source_format=resolved_format,
                )
        payload = _normalize_document_payload(payload)
        document = TwinDslDocument.model_validate(payload)
        diagnostics = [
            *parse_diagnostics,
            DslDiagnostic(
                severity=DslSeverity.INFO,
                code="dsl.parsed",
                message=f"Parsed {resolved_format} source into canonical TwinStudio DSL.",
            ),
        ]
        return ParsedDsl(document=document, diagnostics=diagnostics, source_format=resolved_format)
    except (ValueError, TypeError, json.JSONDecodeError, yaml.YAMLError, ValidationError) as exc:
        return ParsedDsl(
            document=None,
            diagnostics=[*parse_diagnostics, *_diagnostics_from_exception(exc)],
            source_format=resolved_format,
        )


def compile_dsl(
    snapshot: ProjectSnapshot,
    document: TwinDslDocument,
    engine: ProjectEvolutionEngine,
    *,
    actor: str,
) -> DslCompilation:
    diagnostics = diagnostics_for_program(snapshot, document, engine)
    if any(item.severity in {DslSeverity.ERROR, DslSeverity.BLOCKING} for item in diagnostics):
        return DslCompilation(document=document, diagnostics=diagnostics, valid=False)
    try:
        result = engine.run(snapshot, document, actor=actor)
        blueprint = engine.lifecycle_blueprint(document.spec, actor=actor)
        change_plans = _compile_change_plans(snapshot, document, result.run, engine, actor=actor)
    except (ValueError, ValidationError) as exc:
        diagnostics.extend(_diagnostics_from_exception(exc))
        return DslCompilation(document=document, diagnostics=diagnostics, valid=False)
    diagnostics.append(
        DslDiagnostic(
            severity=DslSeverity.INFO,
            code="evolution.compiled",
            message=(
                f"Generated {len(result.run.goal_variants)} goal variants, {len(result.run.resources)} resources, "
                f"{len(result.run.candidates)} candidates and {len(change_plans)} change plan(s)."
            ),
        )
    )
    event_previews = [
        {"event_type": "DslProgramRecorded", "summary": document.metadata.name},
        {"event_type": "EvolutionRunRecorded", "summary": result.run.run_id},
        {"event_type": "LifecycleBlueprintUpserted", "summary": blueprint.blueprint_id},
    ] + [
        {"event_type": "ChangePlanCreated", "summary": item.plan_id} for item in change_plans
    ]
    return DslCompilation(
        document=document,
        diagnostics=diagnostics,
        evolution_run=result.run,
        change_plans=[item.model_dump(mode="json") for item in change_plans],
        lifecycle_blueprint=blueprint,
        event_previews=event_previews,
        valid=True,
    )


def make_execution_record(
    snapshot: ProjectSnapshot,
    source_text: str,
    source_format: str,
    document: TwinDslDocument,
    compilation: DslCompilation,
    *,
    actor: str,
    dry_run: bool,
) -> DslExecutionRecord:
    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    warnings = [item.message for item in compilation.diagnostics if item.severity == DslSeverity.WARNING]
    errors = [
        item.message
        for item in compilation.diagnostics
        if item.severity in {DslSeverity.ERROR, DslSeverity.BLOCKING}
    ]
    execution_id = f"dsl-{digest[:16]}"
    return DslExecutionRecord(
        execution_id=execution_id,
        uri=f"poa://{snapshot.tenant}/{snapshot.project_id}@{snapshot.revision}/dsl-execution/{execution_id}",
        document_name=document.metadata.name,
        document_hash=digest,
        api_version=document.api_version,
        kind=document.kind,
        project_id=snapshot.project_id,
        base_revision=snapshot.revision,
        source_format=source_format,
        source_text=source_text,
        dry_run=dry_run,
        status="compiled" if compilation.valid else "rejected",
        command_types=[item["event_type"] for item in compilation.event_previews],
        warnings=warnings,
        errors=errors,
        created_by=actor,
    )


def write_evolution_artifacts(
    root: Path,
    snapshot: ProjectSnapshot,
    compilation: DslCompilation,
    execution: DslExecutionRecord,
) -> tuple[list[ArtifactRecord], dict[str, str]]:
    if not compilation.evolution_run or not compilation.lifecycle_blueprint or not compilation.document:
        return [], {}
    run = compilation.evolution_run
    output = root / snapshot.project_id / "evolution" / run.run_id
    output.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {
        "dsl.json": output / "evolution-program.json",
        "run.json": output / "evolution-run.json",
        "graph.dot": output / "evolution-graph.dot",
        "graph.mmd": output / "evolution-graph.mmd",
        "report.md": output / "evolution-report.md",
        "candidates.csv": output / "evolution-candidates.csv",
        "lifecycle.json": output / "lifecycle-blueprint.json",
        "execution.json": output / "dsl-execution.json",
    }
    paths["dsl.json"].write_text(compilation.document.model_dump_json(indent=2), encoding="utf-8")
    paths["run.json"].write_text(run.model_dump_json(indent=2), encoding="utf-8")
    paths["graph.dot"].write_text(graph_to_dot(run.graph), encoding="utf-8")
    paths["graph.mmd"].write_text(graph_to_mermaid(run.graph), encoding="utf-8")
    paths["lifecycle.json"].write_text(compilation.lifecycle_blueprint.model_dump_json(indent=2), encoding="utf-8")
    paths["execution.json"].write_text(execution.model_dump_json(indent=2), encoding="utf-8")
    paths["report.md"].write_text(_evolution_report(run, compilation.lifecycle_blueprint), encoding="utf-8")
    with paths["candidates.csv"].open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["candidate_id", "generation", "status", "overall_score", "title", "operators", "lenses"],
        )
        writer.writeheader()
        for candidate in run.candidates:
            writer.writerow(
                {
                    "candidate_id": candidate.candidate_id,
                    "generation": candidate.generation,
                    "status": candidate.status,
                    "overall_score": candidate.overall_score,
                    "title": candidate.title,
                    "operators": ",".join(_enum_value(item.operator) for item in candidate.operators),
                    "lenses": ",".join(candidate.lens_ids),
                }
            )
    records: list[ArtifactRecord] = []
    url_keys: dict[str, str] = {}
    media = {
        "dsl.json": (ArtifactKind.OTHER, "application/json"),
        "run.json": (ArtifactKind.SIMULATION_RESULT, "application/json"),
        "graph.dot": (ArtifactKind.OTHER, "text/vnd.graphviz"),
        "graph.mmd": (ArtifactKind.OTHER, "text/plain"),
        "report.md": (ArtifactKind.OTHER, "text/markdown"),
        "candidates.csv": (ArtifactKind.OTHER, "text/csv"),
        "lifecycle.json": (ArtifactKind.OTHER, "application/json"),
        "execution.json": (ArtifactKind.OTHER, "application/json"),
    }
    for key, path in paths.items():
        artifact_key = f"evolution-{run.run_id}-{path.name}"
        uri = f"poa://{snapshot.tenant}/{snapshot.project_id}@{snapshot.revision}/artifact/{artifact_key}"
        kind, media_type = media[key]
        record = ArtifactRecord(
            uri=uri,
            name=path.name,
            kind=kind,
            path=str(path),
            media_type=media_type,
            revision=snapshot.revision,
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
            generated=True,
            source=False,
            metadata={"evolution_run_id": run.run_id, "dsl_execution_id": execution.execution_id},
        )
        records.append(record)
        url_keys[key] = artifact_key
    manifest_path = output / "manifest.json"
    manifest = {
        "format": "twinstudio-evolution-artifacts",
        "version": 1,
        "project_id": snapshot.project_id,
        "run_id": run.run_id,
        "execution_id": execution.execution_id,
        "files": [
            {
                "path": record.path,
                "uri": record.uri,
                "size_bytes": record.size_bytes,
                "sha256": record.sha256,
                "media_type": record.media_type,
            }
            for record in records
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact_key = f"evolution-{run.run_id}-manifest.json"
    records.append(
        ArtifactRecord(
            uri=f"poa://{snapshot.tenant}/{snapshot.project_id}@{snapshot.revision}/artifact/{artifact_key}",
            name=manifest_path.name,
            kind=ArtifactKind.OTHER,
            path=str(manifest_path),
            media_type="application/json",
            revision=snapshot.revision,
            sha256=sha256_file(manifest_path),
            size_bytes=manifest_path.stat().st_size,
            generated=True,
            source=False,
            metadata={"evolution_run_id": run.run_id, "dsl_execution_id": execution.execution_id},
        )
    )
    url_keys["manifest.json"] = artifact_key
    return records, url_keys


def safe_parameter_patches(document: TwinDslDocument) -> list[dict[str, Any]]:
    patches: list[dict[str, Any]] = []
    for operation in document.spec.explicit_changes:
        if operation.kind != ChangeOperationKind.SET_PARAMETER:
            continue
        parameter = operation.arguments.get("parameter") or operation.selector.get("parameter")
        if not parameter or "value" not in operation.arguments:
            continue
        patches.append(
            {
                "object_uri": operation.target_uri,
                "parameter": str(parameter),
                "value": operation.arguments["value"],
                "unit": operation.arguments.get("unit"),
            }
        )
    return patches


def _compile_change_plans(
    snapshot: ProjectSnapshot,
    document: TwinDslDocument,
    run,
    engine: ProjectEvolutionEngine,
    *,
    actor: str,
) -> list[ChangePlan]:
    plans: list[ChangePlan] = []
    if document.spec.explicit_changes:
        plans.append(
            ChangePlan(
                project_id=snapshot.project_id,
                base_revision=snapshot.revision,
                prompt=f"Explicit changes from DSL program {document.metadata.name}",
                selection_uri=f"dsl://{run.run_id}/explicit",
                selected_scope_uris=document.spec.targets,
                operations=document.spec.explicit_changes,
                assumptions=document.spec.goal.assumptions,
                unresolved_questions=[
                    "Geometry-changing operations require an adapter-supported preview and approval before execution."
                ],
                requires_approval=document.spec.realization.require_approval,
                planner="twinstudio-dsl",
                created_by=actor,
            )
        )
    if document.spec.outputs.include_change_plans and document.spec.realization.max_change_plans:
        for candidate_id in run.selected_candidate_ids[: document.spec.realization.max_change_plans]:
            plans.append(engine.candidate_change_plan(snapshot, run, candidate_id, actor=actor))
    return plans


def _normalize_document_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("DSL document must be an object")
    normalized = dict(payload)
    if "apiVersion" in normalized and "api_version" not in normalized:
        normalized["api_version"] = normalized.pop("apiVersion")
    if "spec" in normalized and isinstance(normalized["spec"], Mapping):
        spec = dict(normalized["spec"])
        aliases = {
            "baseRevision": "base_revision",
            "actionSearch": "action_search",
            "validationSteps": "validation_steps",
            "explicitChanges": "explicit_changes",
        }
        for source, target in aliases.items():
            if source in spec and target not in spec:
                spec[target] = spec.pop(source)
        normalized["spec"] = spec
    return normalized


def _parse_twinscript(source_text: str) -> tuple[dict[str, Any], list[DslDiagnostic]]:
    diagnostics: list[DslDiagnostic] = []
    metadata: dict[str, Any] = {
        "name": "TwinStudio evolution program",
        "namespace": "default",
        "labels": {},
        "annotations": {},
    }
    spec: dict[str, Any] = {
        "project_id": "",
        "base_revision": "main",
        "targets": [],
        "goal": {
            "statement": "",
            "outcomes": [],
            "preserve": [],
            "avoid": [],
            "assumptions": [],
            "constraints": [],
        },
        "methods": [item.value for item in EvolutionMethod],
        "action_search": {},
        "resources": {},
        "lenses": {"source_lens_ids": [], "extension_dimension_ids": []},
        "evolution": {},
        "evaluation": {"weights": {}},
        "lifecycle": {},
        "gates": [],
        "explicit_changes": [],
        "validation_steps": [],
        "realization": {},
        "outputs": {},
        "notes": [],
    }
    version_seen = False
    end_seen = False

    for line_number, stripped in _logical_lines(source_text):
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError as exc:
            diagnostics.append(
                DslDiagnostic(
                    severity=DslSeverity.ERROR,
                    code="syntax.quote",
                    message=str(exc),
                    line=line_number,
                )
            )
            continue
        if not tokens:
            continue
        directive = tokens[0].upper()
        args = tokens[1:]
        if end_seen:
            diagnostics.append(
                DslDiagnostic(
                    severity=DslSeverity.WARNING,
                    code="statement.after_end",
                    message=f"Ignored statement after END: {directive}",
                    line=line_number,
                )
            )
            continue
        try:
            if directive in {"TWINDL", "TWINSCRIPT"}:
                version_seen = True
                if not args or args[0] not in {"1", "1.0", "v1"}:
                    raise ValueError("Supported TwinScript version is 1.0")
            elif directive == "NAME":
                metadata["name"] = _joined(args)
            elif directive == "NAMESPACE":
                metadata["namespace"] = _one(args, "namespace")
            elif directive == "LABEL":
                key, value = _assignment(_one(args, "label assignment"))
                metadata["labels"][key] = str(value)
            elif directive == "ANNOTATION":
                key, value = _assignment(_one(args, "annotation assignment"))
                metadata["annotations"][key] = str(value)
            elif directive == "PROJECT":
                spec["project_id"] = _one(args, "project_id")
                values = _keyword_values(args[1:])
                if "REVISION" in values:
                    spec["base_revision"] = values["REVISION"]
            elif directive in {"FOCUS", "TARGET"}:
                spec["targets"].extend(_csv_args(args))
            elif directive == "GOAL":
                values = _keyword_values(args)
                verb = values.get("VERB")
                object_phrase = values.get("OBJECT", "")
                outcome = values.get("OUTCOME", "")
                statement = values.get("STATEMENT") or " ".join(
                    part for part in [verb or "improve", object_phrase, outcome] if part
                )
                spec["goal"].update(
                    {"statement": statement, "verb": verb, "object_phrase": object_phrase}
                )
                if outcome:
                    spec["goal"]["outcomes"].append(outcome)
            elif directive == "OUTCOME":
                value = _joined(args)
                spec["goal"]["outcomes"].append(value)
                if not spec["goal"]["statement"]:
                    spec["goal"]["statement"] = value
            elif directive == "PRESERVE":
                spec["goal"]["preserve"].append(_joined(args))
            elif directive in {"AVOID", "PREVENT"}:
                spec["goal"]["avoid"].append(_joined(args))
            elif directive in {"ASSUME", "ASSUMPTION"}:
                spec["goal"]["assumptions"].append(_joined(args))
            elif directive == "CONSTRAINT":
                spec["goal"]["constraints"].append(_joined(args))
            elif directive == "METHODS":
                spec["methods"] = [EvolutionMethod(item.lower()).value for item in _csv_args(args)]
            elif directive == "SEED_VERBS":
                spec["action_search"]["seed_verbs"] = [item.lower() for item in _csv_args(args)]
            elif directive in {"LENS", "LENSES"}:
                spec["lenses"]["source_lens_ids"].extend(_csv_args(args))
            elif directive in {"DIMENSION", "DIMENSIONS"}:
                spec["lenses"]["extension_dimension_ids"].extend(_csv_args(args))
            elif directive == "LENS_OPTIONS":
                values = _keyword_values(args)
                mappings = {
                    "SOURCE": ("include_source_lenses", _boolean),
                    "EXTENSIONS": ("include_extension_dimensions", _boolean),
                    "ASSUMPTIONS": ("ask_hidden_assumptions", _boolean),
                    "MAX": ("max_lenses", int),
                }
                _apply_keyword_mapping(spec["lenses"], values, mappings)
            elif directive == "RESOURCE_OPTIONS":
                values = _keyword_values(args)
                mappings = {
                    "DESCENDANTS": ("include_descendants", _boolean),
                    "FEATURES": ("include_features", _boolean),
                    "PARAMETERS": ("include_parameters", _boolean),
                    "MATERIALS": ("include_materials", _boolean),
                    "PROCESSES": ("include_processes", _boolean),
                    "ARTIFACTS": ("include_artifacts", _boolean),
                    "REQUIREMENTS": ("include_requirements", _boolean),
                    "EVIDENCE": ("include_evidence", _boolean),
                    "HUMAN": ("include_human_actions", _boolean),
                    "ENVIRONMENT": ("include_environment", _boolean),
                    "MAX": ("max_resources", int),
                }
                _apply_keyword_mapping(spec["resources"], values, mappings)
            elif directive == "SEARCH":
                values = _keyword_values(args)
                mappings = {
                    "UP": ("up_depth", int),
                    "DOWN": ("down_depth", int),
                    "SIDEWAYS": ("sideways_depth", int),
                    "MAX": ("max_terms", int),
                    "OPPOSITES": ("include_opposites", _boolean),
                }
                _apply_keyword_mapping(spec["action_search"], values, mappings)
            elif directive == "EVOLVE":
                values = _keyword_values(args)
                mappings = {
                    "POPULATION": ("population_size", int),
                    "GENERATIONS": ("generations", int),
                    "OFFSPRING": ("offspring_per_candidate", int),
                    "MUTATION": ("mutation_rate", float),
                    "CROSSOVER": ("crossover_rate", float),
                    "SEED": ("deterministic_seed", int),
                    "ADJACENT_DEPTH": ("adjacent_possible_depth", int),
                }
                _apply_keyword_mapping(spec["evolution"], values, mappings)
            elif directive == "OPERATOR":
                if not args:
                    raise ValueError("OPERATOR requires an operator name")
                operator = MutationOperatorKind(args[0].lower())
                values = _keyword_values(args[1:])
                parameters: dict[str, Any] = {}
                for token in args[1:]:
                    if "=" in token and token.split("=", 1)[0].upper() not in _DSL_KEYWORDS:
                        key, value = _assignment(token)
                        parameters[key] = value
                entry = EvolutionOperatorSpec(
                    operator=operator,
                    weight=float(values.get("WEIGHT", 1.0)),
                    enabled=_boolean(values.get("ENABLED", "true")),
                    parameters=parameters,
                ).model_dump(mode="json")
                spec["evolution"].setdefault("operators", []).append(entry)
            elif directive == "WEIGHT":
                if len(args) != 2:
                    raise ValueError("WEIGHT syntax: WEIGHT <evaluation_dimension> <number>")
                dimension = EvaluationDimension(args[0].lower()).value
                spec["evaluation"]["weights"][dimension] = float(args[1])
            elif directive == "SELECT_TOP":
                spec["evaluation"]["select_top"] = int(_one(args, "select_top"))
            elif directive == "MIN_SCORE":
                spec["evaluation"]["minimum_overall_score"] = float(
                    _one(args, "minimum score")
                )
            elif directive == "LIFECYCLE":
                if not args:
                    raise ValueError("LIFECYCLE requires a template ID")
                spec["lifecycle"]["template_id"] = args[0]
                values = _keyword_values(args[1:])
                mappings = {
                    "START": ("start_stage", lambda value: LifecycleStage(value.lower()).value),
                    "TARGET": ("target_stage", lambda value: LifecycleStage(value.lower()).value),
                    "AUTO_ADVANCE": ("auto_advance", _boolean),
                    "APPROVAL": ("approval_required", _boolean),
                }
                _apply_keyword_mapping(spec["lifecycle"], values, mappings)
            elif directive == "ENABLE_STAGE":
                spec["lifecycle"].setdefault("enabled_stages", []).extend(
                    LifecycleStage(item.lower()).value for item in _csv_args(args)
                )
            elif directive == "DISABLE_STAGE":
                spec["lifecycle"].setdefault("disabled_stages", []).extend(
                    LifecycleStage(item.lower()).value for item in _csv_args(args)
                )
            elif directive == "GATE":
                if not args:
                    raise ValueError("GATE requires an evolution phase")
                phase = EvolutionPhase(args[0].lower())
                values = _keyword_values(args[1:])
                expressions = _split_gate_checks(values.get("CHECK", ""))
                roles = [Role(item.strip().lower()) for item in _split_csv(values.get("ROLE", "creator,admin"))]
                gate = EvolutionGateSpec(
                    phase=phase,
                    expressions=expressions,
                    approver_roles=roles,
                    blocking=_boolean(values.get("BLOCKING", "true")),
                    notes=values.get("NOTE", ""),
                )
                spec["gates"].append(gate.model_dump(mode="json"))
            elif directive == "CHANGE":
                spec["explicit_changes"].append(_parse_change(args, line_number))
            elif directive == "VERIFY":
                spec["validation_steps"].append(_joined(args))
            elif directive == "REALIZE":
                if not args:
                    raise ValueError(
                        "REALIZE requires analysis_only, change_plan or auto_apply_safe"
                    )
                spec["realization"]["mode"] = RealizationMode(args[0].lower()).value
                values = _keyword_values(args[1:])
                mappings = {
                    "DRY_RUN": ("dry_run", _boolean),
                    "APPROVAL": ("require_approval", _boolean),
                    "MAX_PLANS": ("max_change_plans", int),
                }
                _apply_keyword_mapping(spec["realization"], values, mappings)
            elif directive == "ALLOW_OPERATIONS":
                spec["realization"]["allowed_operations"] = [
                    ChangeOperationKind(item.lower()).value for item in _csv_args(args)
                ]
            elif directive == "OUTPUT":
                values = _keyword_values(args)
                if "GRAPHS" in values:
                    spec["outputs"]["graph_formats"] = _split_csv(values["GRAPHS"])
                if "REPORTS" in values:
                    spec["outputs"]["report_formats"] = _split_csv(values["REPORTS"])
            elif directive == "PERSIST_ARTIFACTS":
                spec["outputs"]["persist_artifacts"] = _boolean(
                    _one(args, "persist_artifacts")
                )
            elif directive == "INCLUDE_CHANGE_PLANS":
                spec["outputs"]["include_change_plans"] = _boolean(
                    _one(args, "include_change_plans")
                )
            elif directive == "NOTE":
                spec["notes"].append(_joined(args))
            elif directive == "END":
                end_seen = True
            else:
                diagnostics.append(
                    DslDiagnostic(
                        severity=DslSeverity.ERROR,
                        code="directive.unknown",
                        message=f"Unknown TwinScript directive: {directive}",
                        line=line_number,
                    )
                )
        except (ValueError, KeyError, ValidationError) as exc:
            diagnostics.append(
                DslDiagnostic(
                    severity=DslSeverity.ERROR,
                    code="directive.invalid",
                    message=f"{directive}: {exc}",
                    line=line_number,
                )
            )

    if not version_seen:
        diagnostics.append(
            DslDiagnostic(
                severity=DslSeverity.WARNING,
                code="version.assumed",
                message="No TWINDL/TWINSCRIPT version line was found; version 1.0 was assumed.",
            )
        )
    if not end_seen:
        diagnostics.append(
            DslDiagnostic(
                severity=DslSeverity.INFO,
                code="end.optional",
                message="END is optional; end of file terminated the program.",
            )
        )
    if not spec["project_id"]:
        diagnostics.append(
            DslDiagnostic(
                severity=DslSeverity.BLOCKING,
                code="project.missing",
                message="PROJECT is required.",
            )
        )
    if not spec["targets"]:
        diagnostics.append(
            DslDiagnostic(
                severity=DslSeverity.BLOCKING,
                code="focus.missing",
                message="FOCUS/TARGET is required.",
            )
        )
    if not spec["goal"]["statement"]:
        diagnostics.append(
            DslDiagnostic(
                severity=DslSeverity.BLOCKING,
                code="goal.missing",
                message="GOAL or OUTCOME is required.",
            )
        )
    if not spec["evaluation"]["weights"]:
        spec["evaluation"].pop("weights")
    spec["targets"] = _dedupe_text(spec["targets"])
    spec["lenses"]["source_lens_ids"] = _dedupe_text(
        spec["lenses"]["source_lens_ids"]
    )
    spec["lenses"]["extension_dimension_ids"] = _dedupe_text(
        spec["lenses"]["extension_dimension_ids"]
    )
    for key in ("enabled_stages", "disabled_stages"):
        if key in spec["lifecycle"]:
            spec["lifecycle"][key] = _dedupe_text(spec["lifecycle"][key])
    return {
        "api_version": "twinstudio.io/v1alpha1",
        "kind": "EvolutionProgram",
        "metadata": metadata,
        "spec": spec,
    }, diagnostics


def _logical_lines(source_text: str) -> list[tuple[int, str]]:
    """Return logical TwinScript lines with trailing-backslash continuation support."""
    result: list[tuple[int, str]] = []
    buffer: list[str] = []
    start_line = 1
    for line_number, raw_line in enumerate(source_text.splitlines(), start=1):
        value = raw_line.rstrip()
        if not buffer:
            start_line = line_number
        continued = value.endswith("\\") and not value.endswith("\\\\")
        if continued:
            value = value[:-1].rstrip()
        buffer.append(value)
        if not continued:
            result.append((start_line, " ".join(part.strip() for part in buffer).strip()))
            buffer = []
    if buffer:
        result.append((start_line, " ".join(part.strip() for part in buffer).strip()))
    return result


def _apply_keyword_mapping(
    destination: dict[str, Any],
    values: dict[str, str],
    mappings: dict[str, tuple[str, Any]],
) -> None:
    for source, (target, converter) in mappings.items():
        if source in values:
            destination[target] = converter(values[source])


def _assignment(token: str) -> tuple[str, Any]:
    if "=" not in token:
        raise ValueError(f"Expected key=value assignment, got {token!r}")
    key, raw = token.split("=", 1)
    key = key.strip()
    if not key:
        raise ValueError("Assignment key cannot be empty")
    return key, _scalar(raw)


def _split_gate_checks(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split("||") if item.strip()]


def _dedupe_text(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _parse_change(args: list[str], line_number: int) -> dict[str, Any]:
    if len(args) < 2:
        raise ValueError("CHANGE syntax: CHANGE <operation_kind> <target_uri> [key=value ...]")
    kind = ChangeOperationKind(args[0].lower()).value
    target_uri = args[1]
    selector: dict[str, Any] = {}
    arguments: dict[str, Any] = {}
    rationale = "Declared by TwinScript"
    confidence = 0.8
    for token in args[2:]:
        if "=" not in token:
            if token.startswith("rationale:"):
                rationale = token.split(":", 1)[1]
                continue
            raise ValueError(f"Expected key=value argument, got {token!r}")
        key, raw = token.split("=", 1)
        value = _scalar(raw)
        if key.startswith("selector."):
            selector[key.split(".", 1)[1]] = value
        elif key == "confidence":
            confidence = float(value)
        elif key == "rationale":
            rationale = str(value)
        else:
            arguments[key] = value
    return ChangeOperation(
        operation_id=f"dsl-op-{line_number}",
        kind=kind,
        target_uri=target_uri,
        selector=selector,
        arguments=arguments,
        rationale=rationale,
        confidence=confidence,
        validation_steps=["Validate this explicit DSL operation before applying it to source artifacts."],
    ).model_dump(mode="json")


_DSL_KEYWORDS = {
    "REVISION",
    "VERB",
    "OBJECT",
    "OUTCOME",
    "STATEMENT",
    "UP",
    "DOWN",
    "SIDEWAYS",
    "MAX",
    "OPPOSITES",
    "POPULATION",
    "GENERATIONS",
    "OFFSPRING",
    "MUTATION",
    "CROSSOVER",
    "SEED",
    "ADJACENT_DEPTH",
    "START",
    "TARGET",
    "AUTO_ADVANCE",
    "APPROVAL",
    "DRY_RUN",
    "MAX_PLANS",
    "GRAPHS",
    "REPORTS",
    "SOURCE",
    "EXTENSIONS",
    "ASSUMPTIONS",
    "DESCENDANTS",
    "FEATURES",
    "PARAMETERS",
    "MATERIALS",
    "PROCESSES",
    "ARTIFACTS",
    "REQUIREMENTS",
    "EVIDENCE",
    "HUMAN",
    "ENVIRONMENT",
    "WEIGHT",
    "ENABLED",
    "CHECK",
    "ROLE",
    "BLOCKING",
    "NOTE",
}


def _keyword_values(args: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    index = 0
    while index < len(args):
        key = args[index].upper()
        if key not in _DSL_KEYWORDS:
            index += 1
            continue
        index += 1
        values: list[str] = []
        while index < len(args) and args[index].upper() not in _DSL_KEYWORDS:
            values.append(args[index])
            index += 1
        if not values:
            raise ValueError(f"Missing value after {key}")
        result[key] = " ".join(values)
    return result


def _one(args: list[str], name: str) -> str:
    if not args:
        raise ValueError(f"Missing {name}")
    return args[0]


def _joined(args: list[str]) -> str:
    if not args:
        raise ValueError("Missing text")
    return " ".join(args)


def _csv_args(args: list[str]) -> list[str]:
    return _split_csv(",".join(args))


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "1", "on"}:
        return True
    if normalized in {"false", "no", "0", "off"}:
        return False
    raise ValueError(f"Expected boolean, got {value!r}")


def _scalar(value: str) -> Any:
    normalized = value.strip()
    if normalized.lower() in {"true", "false"}:
        return normalized.lower() == "true"
    try:
        return int(normalized)
    except ValueError:
        pass
    try:
        return float(normalized.replace(",", "."))
    except ValueError:
        return normalized


def _diagnostics_from_exception(exc: Exception) -> list[DslDiagnostic]:
    if isinstance(exc, ValidationError):
        result: list[DslDiagnostic] = []
        for error in exc.errors(include_url=False):
            path = ".".join(str(item) for item in error.get("loc", ()))
            result.append(
                DslDiagnostic(
                    severity=DslSeverity.BLOCKING,
                    code=f"schema.{error.get('type', 'invalid')}",
                    message=error.get("msg", str(exc)),
                    path=path,
                )
            )
        return result
    return [DslDiagnostic(severity=DslSeverity.BLOCKING, code="dsl.invalid", message=str(exc))]


def _evolution_report(run, blueprint: LifecycleBlueprint) -> str:
    lines = [
        f"# TwinStudio evolution report — {run.program.metadata.name}",
        "",
        f"- Project: `{run.project_id}`",
        f"- Base revision: `{run.base_revision}`",
        f"- Run: `{run.run_id}`",
        f"- Status: `{run.status}`",
        f"- Goal: {run.program.spec.goal.statement}",
        f"- Goal variants: {len(run.goal_variants)}",
        f"- Resources: {len(run.resources)}",
        f"- Candidates: {len(run.candidates)}",
        f"- Shortlisted: {len(run.selected_candidate_ids)}",
        "",
        "## Shortlisted candidates",
        "",
    ]
    for candidate in run.candidates:
        if candidate.candidate_id not in run.selected_candidate_ids:
            continue
        lines.extend(
            [
                f"### {candidate.title}",
                "",
                candidate.summary,
                "",
                f"- Score: **{candidate.overall_score:.3f}**",
                f"- Operators: {', '.join(_enum_value(item.operator) for item in candidate.operators)}",
                f"- Lenses/dimensions: {', '.join(candidate.lens_ids) or 'none'}",
                f"- Constraint findings: {', '.join(candidate.constraint_violations) or 'none recorded'}",
                "- Validation:",
                *[f"  - {step}" for step in candidate.validation_steps],
                "",
            ]
        )
    lines.extend(
        [
            "## Lifecycle",
            "",
            f"Template: **{blueprint.name}**; current stage: `{blueprint.current_stage}`.",
            "",
            "The evolution graph proposes possibilities. It does not prove that a design works; shortlisted ideas still require the recorded experiments and verification evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def _enum_value(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)
