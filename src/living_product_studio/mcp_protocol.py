from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Mapping

MODERN_PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_MODERN_VERSIONS = (MODERN_PROTOCOL_VERSION,)
SUPPORTED_LEGACY_VERSIONS = (LEGACY_PROTOCOL_VERSION,)

PROTOCOL_VERSION_META = "io.modelcontextprotocol/protocolVersion"
CLIENT_INFO_META = "io.modelcontextprotocol/clientInfo"
CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities"
SERVER_INFO_META = "io.modelcontextprotocol/serverInfo"
SERVER_INFO = {"name": "twinstudio", "version": "0.3.0"}


@dataclass(frozen=True, slots=True)
class McpHttpError(Exception):
    status_code: int
    code: int
    message: str
    data: Any | None = None

    def as_response(self, request_id: Any = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}


def request_params(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    params = payload.get("params") or {}
    return params if isinstance(params, Mapping) else {}


def request_meta(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    meta = request_params(payload).get("_meta") or {}
    return meta if isinstance(meta, Mapping) else {}


def body_protocol_version(payload: Mapping[str, Any]) -> str | None:
    value = request_meta(payload).get(PROTOCOL_VERSION_META)
    return str(value) if value is not None else None


def classify_mcp_era(payload: Mapping[str, Any], headers: Mapping[str, str]) -> str:
    """Return ``modern`` or ``legacy`` for the incoming request.

    A modern request is identified by per-request protocol metadata, the modern
    protocol header, or the modern-only ``server/discover`` method. An
    ``initialize`` request without modern metadata intentionally selects the
    compatibility path for legacy clients.
    """

    method = payload.get("method")
    body_version = body_protocol_version(payload)
    header_version = headers.get("MCP-Protocol-Version") or headers.get("mcp-protocol-version")
    if method == "initialize" and body_version is None and header_version != MODERN_PROTOCOL_VERSION:
        return "legacy"
    if method == "server/discover" or body_version is not None or header_version == MODERN_PROTOCOL_VERSION:
        return "modern"
    return "legacy"


def decode_mcp_header_value(value: str) -> str:
    """Decode MCP's ``=?base64?...?=`` header sentinel when present."""

    if value.startswith("=?base64?") and value.endswith("?="):
        encoded = value[len("=?base64?") : -2]
        try:
            return base64.b64decode(encoded, validate=True).decode("utf-8")
        except Exception as exc:  # pragma: no cover - exact base64 exception varies
            raise McpHttpError(400, -32020, "Header mismatch: malformed Base64 MCP header value") from exc
    return value


def validate_modern_http_request(payload: Mapping[str, Any], headers: Mapping[str, str]) -> None:
    """Validate the core 2026-07-28 Streamable HTTP request contract.

    This validates the parts used by this application: JSON-RPC shape,
    per-request protocol metadata, protocol/method/name mirror headers, and the
    required client-capabilities field. The project does not advertise custom
    ``x-mcp-header`` tool parameters, so no ``Mcp-Param-*`` validation is needed.
    """

    if payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
        raise McpHttpError(400, -32600, "Invalid Request: expected a JSON-RPC 2.0 request")

    request_id = payload.get("id")
    _ = request_id  # retained for parity with the JSON-RPC validation contract
    method = str(payload["method"])
    params = payload.get("params")
    if not isinstance(params, Mapping):
        raise McpHttpError(400, -32602, "Invalid params: modern MCP requests require an object params field")
    meta = params.get("_meta")
    if not isinstance(meta, Mapping):
        raise McpHttpError(400, -32602, "Invalid params: modern MCP requests require params._meta")

    body_version = meta.get(PROTOCOL_VERSION_META)
    header_version = headers.get("MCP-Protocol-Version") or headers.get("mcp-protocol-version")
    if not header_version:
        raise McpHttpError(400, -32020, "Header mismatch: MCP-Protocol-Version header is required")
    if body_version is None:
        raise McpHttpError(400, -32602, f"Invalid params: missing _meta.{PROTOCOL_VERSION_META}")
    if str(header_version) != str(body_version):
        raise McpHttpError(
            400,
            -32020,
            "Header mismatch: MCP-Protocol-Version does not match request metadata",
        )
    if str(body_version) not in SUPPORTED_MODERN_VERSIONS:
        raise McpHttpError(
            400,
            -32022,
            "Unsupported protocol version",
            {"supported": list(SUPPORTED_MODERN_VERSIONS), "requested": str(body_version)},
        )

    capabilities = meta.get(CLIENT_CAPABILITIES_META)
    if not isinstance(capabilities, Mapping):
        raise McpHttpError(400, -32602, f"Invalid params: missing _meta.{CLIENT_CAPABILITIES_META}")

    header_method = headers.get("Mcp-Method") or headers.get("mcp-method")
    if not header_method:
        raise McpHttpError(400, -32020, "Header mismatch: Mcp-Method header is required")
    if header_method != method:
        raise McpHttpError(400, -32020, "Header mismatch: Mcp-Method does not match JSON-RPC method")

    name_source: Any | None = None
    if method == "tools/call":
        name_source = params.get("name")
    elif method == "resources/read":
        name_source = params.get("uri")
    elif method == "prompts/get":
        name_source = params.get("name")

    if method in {"tools/call", "resources/read", "prompts/get"}:
        if not isinstance(name_source, str) or not name_source:
            field = "uri" if method == "resources/read" else "name"
            raise McpHttpError(400, -32602, f"Invalid params: {field} is required for {method}")
        raw_header_name = headers.get("Mcp-Name") or headers.get("mcp-name")
        if raw_header_name is None:
            raise McpHttpError(400, -32020, "Header mismatch: Mcp-Name header is required")
        decoded = decode_mcp_header_value(raw_header_name)
        if decoded != str(name_source):
            raise McpHttpError(400, -32020, "Header mismatch: Mcp-Name does not match request body")


def modern_result(
    payload: Mapping[str, Any] | None = None,
    *,
    cacheable: bool = False,
    ttl_ms: int = 300_000,
    cache_scope: str = "private",
) -> dict[str, Any]:
    result = dict(payload or {})
    result.setdefault("resultType", "complete")
    meta = dict(result.get("_meta") or {})
    meta.setdefault(SERVER_INFO_META, dict(SERVER_INFO))
    result["_meta"] = meta
    if cacheable:
        result.setdefault("ttlMs", ttl_ms)
        result.setdefault("cacheScope", cache_scope)
    return result


def server_discover_result() -> dict[str, Any]:
    return modern_result(
        {
            "supportedVersions": list(SUPPORTED_MODERN_VERSIONS),
            "capabilities": {"tools": {}, "resources": {}},
            "instructions": (
                "Use POA URIs to address product objects. Mutations require project roles, a resolved "
                "selection scope, and a typed change plan; request human approval before applying changes."
            ),
        },
        cacheable=True,
        ttl_ms=3_600_000,
        cache_scope="private",
    )


def origin_is_allowed(origin: str, allowed_origins: tuple[str, ...]) -> bool:
    normalized = origin.rstrip("/")
    return "*" in allowed_origins or normalized in {entry.rstrip("/") for entry in allowed_origins}
