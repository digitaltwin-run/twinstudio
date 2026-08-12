from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from twinstudio.artifacts import export_project_bundle
from twinstudio.bus import CommandBus, QueryService
from twinstudio.change_planner import ChangePlanner
from twinstudio.domain import Annotation, AuthPrincipal, ChangePlan, CommandEnvelope, RegionSelection
from twinstudio.dsl import canonical_dsl_schema, compile_dsl, make_execution_record, parse_dsl
from twinstudio.evolution import ProjectEvolutionEngine
from twinstudio.evolution_models import EvolutionRun, TwinDslDocument
from twinstudio.feature_lenses import FeatureLensEngine
from twinstudio.mcp_protocol import (
    LEGACY_PROTOCOL_VERSION,
    body_protocol_version,
    modern_result,
    server_discover_result,
)
from twinstudio.permissions import require_permission
from twinstudio.selection_resolver import resolve_selection
from twinstudio.simulations import (
    evaluate_human_scenario,
    mechanical_rule_checks,
    simulate_power,
    simulate_thermal,
)
from twinstudio.specification import unified_specification


@dataclass(frozen=True, slots=True)
class McpProtocolError(Exception):
    code: int
    message: str
    data: Any | None = None


ToolHandler = Callable[[dict[str, Any], AuthPrincipal], dict[str, Any]]


class McpGateway:
    """Auditable MCP surface over the same TwinStudio domain services as REST/CLI."""

    def __init__(
        self,
        queries: QueryService,
        commands: CommandBus,
        planner: ChangePlanner,
        feature_lenses: FeatureLensEngine,
        evolution_engine: ProjectEvolutionEngine,
        export_root,
        project_root,
    ):
        self.queries = queries
        self.commands = commands
        self.planner = planner
        self.feature_lenses = feature_lenses
        self.evolution_engine = evolution_engine
        self.export_root = export_root
        self.project_root = project_root
        self._tool_handlers: dict[str, ToolHandler] = {
            "list_projects": self._list_projects,
            "list_feature_lenses": self._list_feature_lenses,
            "get_evolution_catalog": self._get_evolution_catalog,
            "get_dsl_schema": self._get_dsl_schema,
            "preview_dsl": self._preview_dsl,
            "list_evolution_runs": self._list_evolution_runs,
            "get_lifecycle_blueprints": self._get_lifecycle_blueprints,
            "candidate_to_change_plan": self._candidate_to_change_plan,
            "get_project_tree": self._get_project_tree,
            "get_specification": self._get_specification,
            "get_design_fixation_reviews": self._get_design_fixation_reviews,
            "resolve_selection": self._resolve_selection,
            "create_annotation": self._create_annotation,
            "plan_change": self._plan_change,
            "apply_change_plan": self._apply_change_plan,
            "run_design_fixation_scan": self._run_design_fixation_scan,
            "run_power_simulation": self._run_power_simulation,
            "run_thermal_simulation": self._run_thermal_simulation,
            "evaluate_human_use": self._evaluate_human_use,
            "run_mechanical_rules": self._run_mechanical_rules,
            "export_project": self._export_project,
        }

    def handle(
        self,
        request: dict[str, Any],
        principal: AuthPrincipal,
        *,
        modern: bool | None = None,
    ) -> dict[str, Any]:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if modern is None:
            modern = method == "server/discover" or body_protocol_version(request) is not None
        try:
            result = self._dispatch_protocol(method, params, principal, modern=modern)
            if request_id is None:
                return {}
            if modern:
                result = self._modernize_result(str(method), result)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except McpProtocolError as exc:
            if request_id is None:
                return {}
            return self._error(request_id, exc.code, exc.message, exc.data)
        except (KeyError, TypeError, ValueError) as exc:
            if request_id is None:
                return {}
            return self._error(request_id, -32602, f"Invalid params: {exc}")
        except Exception as exc:  # pragma: no cover - defensive protocol boundary
            if request_id is None:
                return {}
            return self._error(request_id, -32603 if modern else -32000, f"Internal error: {exc}")

    def _dispatch_protocol(
        self,
        method: Any,
        params: Any,
        principal: AuthPrincipal,
        *,
        modern: bool,
    ) -> dict[str, Any]:
        if method == "server/discover":
            return server_discover_result()
        if method == "initialize" and not modern:
            return {
                "protocolVersion": LEGACY_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False}},
                "serverInfo": {"name": "twinstudio", "version": "0.5.0"},
                "instructions": (
                    "Mutations are role-controlled and scoped by Product Object Addressing URIs. "
                    "Design-fixation alternatives are review records, not automatic CAD edits."
                ),
            }
        if method == "tools/list":
            return {"tools": self.tools()}
        if method == "tools/call":
            if not isinstance(params, dict):
                raise McpProtocolError(-32602, "Invalid params")
            return self.call_tool(str(params.get("name", "")), params.get("arguments") or {}, principal)
        if method == "resources/list":
            return {"resources": self.resources(principal)}
        if method == "resources/read":
            if not isinstance(params, dict):
                raise McpProtocolError(-32602, "Invalid params")
            return self.read_resource(str(params.get("uri", "")), principal)
        if method in {"ping", "notifications/initialized"}:
            return {}
        raise McpProtocolError(-32601, f"Method not found: {method}")

    @staticmethod
    def _modernize_result(method: str, result: dict[str, Any]) -> dict[str, Any]:
        if method == "server/discover":
            return result
        if method in {"tools/list", "resources/list", "resources/read"}:
            return modern_result(result, cacheable=True, ttl_ms=300_000, cache_scope="private")
        return modern_result(result)

    def tools(self) -> list[dict[str, Any]]:
        tools = [
            _tool("list_projects", "List accessible TwinStudio projects.", {"type": "object", "properties": {}}),
            _tool(
                "list_feature_lenses",
                "Read the source-grounded design-fixation feature-lens catalog.",
                {"type": "object", "properties": {"include_disabled": {"type": "boolean", "default": False}}},
            ),
            _tool(
                "get_evolution_catalog",
                "Read the controlled goal-ladder, mutation-operator, extension-dimension and lifecycle-template catalog.",
                {"type": "object", "properties": {}},
            ),
            _tool(
                "get_dsl_schema",
                "Read the JSON Schema for TwinStudio EvolutionProgram DSL documents.",
                {"type": "object", "properties": {}},
            ),
            _tool(
                "preview_dsl",
                "Parse and compile TwinScript/YAML/JSON into a reviewable evolution run without mutating the project.",
                {
                    "type": "object",
                    "required": ["project_id", "source"],
                    "properties": {
                        "project_id": {"type": "string"},
                        "source": {"type": "string"},
                        "source_format": {"type": "string", "enum": ["auto", "twin", "yaml", "json"], "default": "auto"},
                    },
                },
            ),
            _tool(
                "list_evolution_runs",
                "Read recorded project-evolution runs and their candidate lineages.",
                _project_schema(),
            ),
            _tool(
                "get_lifecycle_blueprints",
                "Read tailored lifecycle blueprints and transition history.",
                _project_schema(),
            ),
            _tool(
                "candidate_to_change_plan",
                "Compile one recorded evolution candidate into a scope-checked change plan.",
                {
                    "type": "object",
                    "required": ["project_id", "run_id", "candidate_id"],
                    "properties": {
                        "project_id": {"type": "string"},
                        "run_id": {"type": "string"},
                        "candidate_id": {"type": "string"},
                        "record": {"type": "boolean", "default": True},
                    },
                },
            ),
            _tool("get_project_tree", "Read the object/assembly tree.", _project_schema()),
            _tool("get_specification", "Read the unified xBOM/specification.", _project_schema()),
            _tool(
                "get_design_fixation_reviews",
                "Read recorded design-fixation reviews for a project.",
                _project_schema(),
            ),
            _tool(
                "resolve_selection",
                "Resolve a 2D/3D selection to persistent object, feature, semantic-face and B-Rep identities.",
                {
                    "type": "object",
                    "required": ["project_id", "selection"],
                    "properties": {
                        "project_id": {"type": "string"},
                        "selection": RegionSelection.model_json_schema(),
                    },
                },
            ),
            _tool(
                "create_annotation",
                "Attach a natural-language note to a selected 2D/3D region.",
                {
                    "type": "object",
                    "required": ["project_id", "text", "selection"],
                    "properties": {
                        "project_id": {"type": "string"},
                        "text": {"type": "string"},
                        "selection": RegionSelection.model_json_schema(),
                    },
                },
            ),
            _tool(
                "plan_change",
                "Compile natural language plus a selected region into a scope-checked declarative change plan.",
                {
                    "type": "object",
                    "required": ["project_id", "prompt", "selection"],
                    "properties": {
                        "project_id": {"type": "string"},
                        "prompt": {"type": "string"},
                        "selection": RegionSelection.model_json_schema(),
                    },
                },
            ),
            _tool(
                "apply_change_plan",
                "Apply safe scalar patches and queue allow-listed CAD operations.",
                {
                    "type": "object",
                    "required": ["project_id", "plan_id"],
                    "properties": {"project_id": {"type": "string"}, "plan_id": {"type": "string"}},
                },
            ),
            _tool(
                "run_design_fixation_scan",
                "Use feature lenses to surface overlooked assumptions and record reviewable alternatives.",
                {
                    "type": "object",
                    "required": ["project_id", "target_uri"],
                    "properties": {
                        "project_id": {"type": "string"},
                        "target_uri": {"type": "string"},
                        "challenge": {"type": "string", "default": ""},
                        "lens_ids": {"type": "array", "items": {"type": "string"}},
                        "max_alternatives": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
                        "use_llm": {"type": "boolean", "default": True},
                        "record": {"type": "boolean", "default": True},
                    },
                },
            ),
            _tool("run_power_simulation", "Run the project's lumped DC power model.", _project_schema()),
            _tool(
                "run_thermal_simulation",
                "Run a lumped RC thermal estimate.",
                {
                    "type": "object",
                    "required": ["project_id", "power_by_uri_w"],
                    "properties": {
                        "project_id": {"type": "string"},
                        "power_by_uri_w": {"type": "object", "additionalProperties": {"type": "number"}},
                        "duration_s": {"type": "number", "default": 600},
                    },
                },
            ),
            _tool(
                "evaluate_human_use",
                "Evaluate a declared human-use scenario for missing criteria and misuse cases.",
                {
                    "type": "object",
                    "required": ["project_id"],
                    "properties": {
                        "project_id": {"type": "string"},
                        "scenario_uri": {"type": "string"},
                    },
                },
            ),
            _tool("run_mechanical_rules", "Run simple mechanical/DFM review rules.", _project_schema()),
            _tool("export_project", "Create a downloadable .twinstudio.zip project bundle.", _project_schema()),
        ]
        return sorted(tools, key=lambda item: item["name"])

    def call_tool(self, name: str, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        if not isinstance(args, dict):
            raise McpProtocolError(-32602, "Tool arguments must be an object")
        handler = self._tool_handlers.get(name)
        if not handler:
            raise McpProtocolError(-32602, f"Unknown MCP tool: {name}")
        return handler(args, principal)

    def _project_context(
        self,
        args: dict[str, Any],
        principal: AuthPrincipal,
        permission: str,
    ):
        project_id = str(args.get("project_id", ""))
        if not project_id:
            raise McpProtocolError(-32602, "project_id is required")
        snapshot = self.queries.project(project_id)
        role = snapshot.memberships.get(principal.email.lower())
        require_permission(role, permission)
        return project_id, snapshot

    def _list_projects(self, _: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        visible = []
        for item in self.queries.projects():
            snapshot = self.queries.project(item["project_id"])
            role = snapshot.memberships.get(principal.email.lower())
            if role:
                visible.append({**item, "role": role})
        return _content(visible)

    def _list_feature_lenses(self, args: dict[str, Any], _: AuthPrincipal) -> dict[str, Any]:
        catalog = self.feature_lenses.catalog
        include_disabled = bool(args.get("include_disabled", False))
        payload = catalog.model_dump(mode="json")
        if not include_disabled:
            payload["lenses"] = [lens for lens in payload["lenses"] if lens["enabled"]]
        return _content(payload)

    def _get_evolution_catalog(self, _: dict[str, Any], __: AuthPrincipal) -> dict[str, Any]:
        return _content(self.evolution_engine.catalog.model_dump(mode="json"))

    def _get_dsl_schema(self, _: dict[str, Any], __: AuthPrincipal) -> dict[str, Any]:
        return _content(canonical_dsl_schema())

    def _preview_dsl(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        project_id, snapshot = self._project_context(args, principal, "change.plan")
        source = str(args.get("source", ""))
        if not source:
            raise McpProtocolError(-32602, "source is required")
        parsed = parse_dsl(source, source_format=str(args.get("source_format", "auto")))
        if not parsed.document:
            return _content(
                {
                    "valid": False,
                    "source_format": parsed.source_format,
                    "diagnostics": [item.model_dump(mode="json") for item in parsed.diagnostics],
                },
                is_error=True,
            )
        if parsed.document.spec.project_id != project_id:
            raise McpProtocolError(-32602, "DSL project_id does not match project_id")
        compilation = compile_dsl(snapshot, parsed.document, self.evolution_engine, actor=principal.email)
        execution = make_execution_record(
            snapshot,
            source,
            parsed.source_format,
            parsed.document,
            compilation,
            actor=principal.email,
            dry_run=True,
        )
        payload = compilation.model_dump(mode="json")
        payload["execution"] = execution.model_dump(mode="json")
        payload["source_format"] = parsed.source_format
        return _content(payload, is_error=not compilation.valid)

    def _list_evolution_runs(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        _, snapshot = self._project_context(args, principal, "project.read")
        return _content(list(snapshot.evolution_runs.values()))

    def _get_lifecycle_blueprints(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        _, snapshot = self._project_context(args, principal, "project.read")
        return _content(
            {
                "current_project_stage": snapshot.lifecycle_stage,
                "blueprints": list(snapshot.lifecycle_blueprints.values()),
                "history": snapshot.lifecycle_history,
            }
        )

    def _candidate_to_change_plan(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        project_id, snapshot = self._project_context(args, principal, "change.plan")
        raw = snapshot.evolution_runs.get(str(args.get("run_id", "")))
        if not raw:
            raise McpProtocolError(-32602, "Evolution run not found")
        run = EvolutionRun.model_validate(raw)
        plan = self.evolution_engine.candidate_change_plan(
            snapshot, run, str(args.get("candidate_id", "")), actor=principal.email
        )
        if bool(args.get("record", True)):
            self.commands.execute(
                CommandEnvelope(
                    command_type="change.plan.record",
                    project_id=project_id,
                    expected_version=snapshot.stream_version,
                    actor=principal.email,
                    payload={"plan": plan.model_dump(mode="json")},
                )
            )
        return _content({"plan": plan.model_dump(mode="json")})

    def _get_project_tree(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        project_id, _ = self._project_context(args, principal, "project.read")
        return _content(self.queries.tree(project_id))

    def _get_specification(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        _, snapshot = self._project_context(args, principal, "project.read")
        return _content(unified_specification(snapshot))

    def _get_design_fixation_reviews(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        _, snapshot = self._project_context(args, principal, "project.read")
        return _content([review.model_dump(mode="json") for review in snapshot.design_fixation_reviews.values()])

    def _resolve_selection(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        project_id, snapshot = self._project_context(args, principal, "change.plan")
        selection = RegionSelection.model_validate(args["selection"]).model_copy(
            update={"project_id": project_id, "created_by": principal.email}
        )
        mapping = resolve_selection(selection, snapshot, actor=principal.email)
        self.commands.execute(
            CommandEnvelope(
                command_type="selection_map.record",
                project_id=project_id,
                expected_version=snapshot.stream_version,
                actor=principal.email,
                payload={"selection_map": mapping.model_dump(mode="json")},
            )
        )
        return _content(mapping.model_dump(mode="json"))

    def _create_annotation(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        project_id, snapshot = self._project_context(args, principal, "annotation.create")
        selection = RegionSelection.model_validate(args["selection"])
        annotation = Annotation(
            uri=selection.uri.replace("/region/", "/annotation/"),
            selection=selection.model_copy(update={"created_by": principal.email, "project_id": project_id}),
            text=str(args["text"]),
            created_by=principal.email,
        )
        self.commands.execute(
            CommandEnvelope(
                command_type="annotation.create",
                project_id=project_id,
                expected_version=snapshot.stream_version,
                actor=principal.email,
                payload={"annotation": annotation.model_dump(mode="json")},
            )
        )
        return _content(annotation.model_dump(mode="json"))

    def _plan_change(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        project_id, snapshot = self._project_context(args, principal, "change.plan")
        selection = RegionSelection.model_validate(args["selection"])
        result = self.planner.plan(str(args["prompt"]), selection, snapshot, principal.email)
        self.commands.execute(
            CommandEnvelope(
                command_type="change.plan.record",
                project_id=project_id,
                expected_version=snapshot.stream_version,
                actor=principal.email,
                payload={"plan": result.plan.model_dump(mode="json")},
            )
        )
        return _content({"mode": result.mode, "message": result.message, "plan": result.plan.model_dump(mode="json")})

    def _apply_change_plan(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        project_id, snapshot = self._project_context(args, principal, "change.apply")
        plan = snapshot.change_plans[str(args["plan_id"])]
        payload = self.planner.compile_apply_payload(plan, snapshot)
        self.commands.execute(
            CommandEnvelope(
                command_type="change.apply",
                project_id=project_id,
                expected_version=snapshot.stream_version,
                actor=principal.email,
                payload=payload,
            )
        )
        return _content(payload)

    def _run_design_fixation_scan(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        project_id, snapshot = self._project_context(args, principal, "change.plan")
        result = self.feature_lenses.scan(
            snapshot,
            target_uri=str(args["target_uri"]),
            challenge=str(args.get("challenge", "")),
            actor=principal.email,
            lens_ids=[str(item) for item in args.get("lens_ids", [])] or None,
            max_alternatives=int(args.get("max_alternatives", 8)),
            use_llm=bool(args.get("use_llm", True)),
        )
        if bool(args.get("record", True)):
            self.commands.execute(
                CommandEnvelope(
                    command_type="design_fixation.review.record",
                    project_id=project_id,
                    expected_version=snapshot.stream_version,
                    actor=principal.email,
                    payload={"review": result.review.model_dump(mode="json")},
                )
            )
        return _content(
            {"mode": result.mode, "message": result.message, "review": result.review.model_dump(mode="json")}
        )

    def _run_power_simulation(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        _, snapshot = self._project_context(args, principal, "simulation.run")
        if not snapshot.power_model:
            raise McpProtocolError(-32602, "Project has no power model")
        return _content(simulate_power(snapshot.power_model))

    def _run_thermal_simulation(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        _, snapshot = self._project_context(args, principal, "simulation.run")
        if not snapshot.thermal_model:
            raise McpProtocolError(-32602, "Project has no thermal model")
        return _content(
            simulate_thermal(
                snapshot.thermal_model,
                {str(key): float(value) for key, value in args["power_by_uri_w"].items()},
                duration_s=float(args.get("duration_s", 600)),
            )
        )

    def _evaluate_human_use(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        _, snapshot = self._project_context(args, principal, "simulation.run")
        if not snapshot.human_scenarios:
            raise McpProtocolError(-32602, "Project has no human-use scenario")
        requested = str(args.get("scenario_uri", ""))
        scenario = next((item for item in snapshot.human_scenarios if item.uri == requested), None)
        if requested and scenario is None:
            raise McpProtocolError(-32602, "Human-use scenario not found")
        return _content(evaluate_human_scenario(scenario or snapshot.human_scenarios[0]))

    def _run_mechanical_rules(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        _, snapshot = self._project_context(args, principal, "simulation.run")
        return _content(mechanical_rule_checks(snapshot.model_dump(mode="json")))

    def _export_project(self, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        project_id, snapshot = self._project_context(args, principal, "artifact.download")
        extension = self.feature_lenses.settings.export_extension
        path = self.export_root / f"{project_id}-{snapshot.revision}{extension}"
        export_project_bundle(snapshot, self.queries.events(project_id), path, project_root=self.project_root)
        return _content({"path": str(path), "download_url": f"/api/v1/projects/{project_id}/export"})

    def resources(self, principal: AuthPrincipal) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        for item in self.queries.projects():
            snapshot = self.queries.project(item["project_id"])
            if principal.email.lower() not in snapshot.memberships:
                continue
            resources.append(
                {
                    "uri": f"poa://{snapshot.tenant}/{snapshot.project_id}@{snapshot.revision}",
                    "name": snapshot.name,
                    "description": snapshot.description,
                    "mimeType": "application/json",
                }
            )
        return sorted(resources, key=lambda item: item["uri"])

    def read_resource(self, uri: str, principal: AuthPrincipal) -> dict[str, Any]:
        from twinstudio.uri import parse_poa_uri

        try:
            parsed = parse_poa_uri(uri)
        except Exception as exc:
            raise McpProtocolError(-32602, "Invalid POA resource URI") from exc
        snapshot = self.queries.project(parsed.project)
        role = snapshot.memberships.get(principal.email.lower())
        require_permission(role, "project.read")
        if not parsed.segments:
            data: Any = snapshot.model_dump(mode="json")
        elif uri in snapshot.objects:
            data = snapshot.objects[uri].model_dump(mode="json")
        elif uri in snapshot.artifacts:
            data = snapshot.artifacts[uri].model_dump(mode="json")
        elif uri in snapshot.annotations:
            data = snapshot.annotations[uri].model_dump(mode="json")
        else:
            review = next((item for item in snapshot.design_fixation_reviews.values() if item.uri == uri), None)
            if not review:
                raise McpProtocolError(-32602, "POA resource not found")
            data = review.model_dump(mode="json")
        return {
            "contents": [
                {"uri": uri, "mimeType": "application/json", "text": json.dumps(data, ensure_ascii=False)}
            ]
        }

    @staticmethod
    def _error(request_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _tool(name: str, description: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "description": description, "inputSchema": schema}


def _project_schema() -> dict[str, Any]:
    return {"type": "object", "required": ["project_id"], "properties": {"project_id": {"type": "string"}}}


def _content(value: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}],
        "structuredContent": value,
        "isError": is_error,
    }
