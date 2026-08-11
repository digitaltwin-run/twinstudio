from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from living_product_studio.artifacts import export_project_bundle
from living_product_studio.bus import CommandBus, QueryService
from living_product_studio.change_planner import ChangePlanner
from living_product_studio.domain import Annotation, AuthPrincipal, CommandEnvelope, RegionSelection
from living_product_studio.mcp_protocol import (
    LEGACY_PROTOCOL_VERSION,
    body_protocol_version,
    modern_result,
    server_discover_result,
)
from living_product_studio.permissions import require_permission
from living_product_studio.selection_resolver import resolve_selection
from living_product_studio.simulations import (
    evaluate_human_scenario,
    mechanical_rule_checks,
    simulate_power,
    simulate_thermal,
)
from living_product_studio.specification import unified_specification


@dataclass(frozen=True, slots=True)
class McpProtocolError(Exception):
    code: int
    message: str
    data: Any | None = None


class McpGateway:
    """Small, auditable MCP surface over the same domain services as REST/CLI.

    The gateway supports the current stateless 2026-07-28 request/result shape
    and keeps an ``initialize`` compatibility path for older clients. It is a
    deliberately narrow subset: tools/resources are implemented, while prompts,
    subscriptions, MRTR and streaming responses are not advertised.
    """

    def __init__(
        self,
        queries: QueryService,
        commands: CommandBus,
        planner: ChangePlanner,
        export_root,
        project_root,
    ):
        self.queries = queries
        self.commands = commands
        self.planner = planner
        self.export_root = export_root
        self.project_root = project_root

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
            if method == "server/discover":
                result = server_discover_result()
            elif method == "initialize" and not modern:
                result = {
                    "protocolVersion": LEGACY_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False}},
                    "serverInfo": {"name": "twinstudio", "version": "0.3.0"},
                    "instructions": "All mutations are scoped by Product Object Addressing URIs and project roles.",
                }
            elif method == "tools/list":
                result = {"tools": self.tools()}
            elif method == "tools/call":
                if not isinstance(params, dict):
                    raise McpProtocolError(-32602, "Invalid params")
                result = self.call_tool(str(params.get("name", "")), params.get("arguments") or {}, principal)
            elif method == "resources/list":
                result = {"resources": self.resources(principal)}
            elif method == "resources/read":
                if not isinstance(params, dict):
                    raise McpProtocolError(-32602, "Invalid params")
                result = self.read_resource(str(params.get("uri", "")), principal)
            elif method == "ping":
                result = {}
            elif method == "notifications/initialized" and not modern:
                result = {}
            else:
                if request_id is None:
                    return {}
                return self._error(request_id, -32601, f"Method not found: {method}")

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

    @staticmethod
    def _modernize_result(method: str, result: dict[str, Any]) -> dict[str, Any]:
        if method == "server/discover":
            return result
        if method in {"tools/list", "resources/list", "resources/read"}:
            return modern_result(result, cacheable=True, ttl_ms=300_000, cache_scope="private")
        return modern_result(result)

    def tools(self) -> list[dict[str, Any]]:
        tools = [
            _tool("list_projects", "List accessible living-product projects.", {"type": "object", "properties": {}}),
            _tool("get_project_tree", "Read the object/assembly tree.", _project_schema()),
            _tool(
                "resolve_selection",
                "Resolve a 2D/3D screen selection to persistent object, feature, semantic-face and B-Rep identities.",
                {
                    "type": "object",
                    "required": ["project_id", "selection"],
                    "properties": {
                        "project_id": {"type": "string"},
                        "selection": RegionSelection.model_json_schema(),
                    },
                },
            ),
            _tool("get_specification", "Read the unified xBOM/specification.", _project_schema()),
            _tool(
                "create_annotation",
                "Attach a natural-language note to a 2D/3D selected region.",
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
                "Compile NL plus a selected region into a scope-checked declarative change plan.",
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
                "Apply immediately safe scalar patches and queue allow-listed CAD operations.",
                {
                    "type": "object",
                    "required": ["project_id", "plan_id"],
                    "properties": {"project_id": {"type": "string"}, "plan_id": {"type": "string"}},
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
                "Evaluate a declared human-use scenario for missing criteria, misuse cases and force thresholds.",
                {
                    "type": "object",
                    "required": ["project_id"],
                    "properties": {
                        "project_id": {"type": "string"},
                        "scenario_uri": {"type": "string", "description": "Optional; defaults to the first scenario."},
                    },
                },
            ),
            _tool("run_mechanical_rules", "Run simple mechanical/DFM review rules.", _project_schema()),
            _tool("export_project", "Create a downloadable .lps.zip project bundle.", _project_schema()),
        ]
        return sorted(tools, key=lambda item: item["name"])

    def call_tool(self, name: str, args: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        if not isinstance(args, dict):
            raise McpProtocolError(-32602, "Tool arguments must be an object")
        if name == "list_projects":
            visible = []
            for item in self.queries.projects():
                snapshot = self.queries.project(item["project_id"])
                role = snapshot.memberships.get(principal.email.lower())
                if role:
                    visible.append({**item, "role": role})
            return _content(visible)

        project_id = str(args.get("project_id", ""))
        if not project_id:
            raise McpProtocolError(-32602, "project_id is required")
        snapshot = self.queries.project(project_id)
        role = snapshot.memberships.get(principal.email.lower())

        if name == "get_project_tree":
            require_permission(role, "project.read")
            return _content(self.queries.tree(project_id))
        if name == "get_specification":
            require_permission(role, "project.read")
            return _content(unified_specification(snapshot))
        if name == "resolve_selection":
            require_permission(role, "change.plan")
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
        if name == "create_annotation":
            require_permission(role, "annotation.create")
            selection = RegionSelection.model_validate(args["selection"])
            annotation = Annotation(
                uri=selection.uri.replace("/region/", "/annotation/"),
                selection=selection.model_copy(update={"created_by": principal.email}),
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
        if name == "plan_change":
            require_permission(role, "change.plan")
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
            return _content(
                {"mode": result.mode, "message": result.message, "plan": result.plan.model_dump(mode="json")}
            )
        if name == "apply_change_plan":
            require_permission(role, "change.apply")
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
        if name == "run_power_simulation":
            require_permission(role, "simulation.run")
            if not snapshot.power_model:
                raise McpProtocolError(-32602, "Project has no power model")
            return _content(simulate_power(snapshot.power_model))
        if name == "run_thermal_simulation":
            require_permission(role, "simulation.run")
            if not snapshot.thermal_model:
                raise McpProtocolError(-32602, "Project has no thermal model")
            return _content(
                simulate_thermal(
                    snapshot.thermal_model,
                    {str(k): float(v) for k, v in args["power_by_uri_w"].items()},
                    duration_s=float(args.get("duration_s", 600)),
                )
            )
        if name == "evaluate_human_use":
            require_permission(role, "simulation.run")
            if not snapshot.human_scenarios:
                raise McpProtocolError(-32602, "Project has no human-use scenario")
            requested = str(args.get("scenario_uri", ""))
            scenario = next((item for item in snapshot.human_scenarios if item.uri == requested), None)
            if requested and scenario is None:
                raise McpProtocolError(-32602, "Human-use scenario not found")
            return _content(evaluate_human_scenario(scenario or snapshot.human_scenarios[0]))
        if name == "run_mechanical_rules":
            require_permission(role, "simulation.run")
            return _content(mechanical_rule_checks(snapshot.model_dump(mode="json")))
        if name == "export_project":
            require_permission(role, "artifact.download")
            path = self.export_root / f"{project_id}-{snapshot.revision}.lps.zip"
            export_project_bundle(snapshot, self.queries.events(project_id), path, project_root=self.project_root)
            return _content({"path": str(path), "download_url": f"/api/v1/projects/{project_id}/export"})
        raise McpProtocolError(-32602, f"Unknown MCP tool: {name}")

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
        from living_product_studio.uri import parse_poa_uri

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
            raise McpProtocolError(-32602, "POA resource not found")
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
