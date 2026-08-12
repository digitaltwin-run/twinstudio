from __future__ import annotations

import base64

import pytest

from twinstudio.mcp_protocol import (
    CLIENT_CAPABILITIES_META,
    MODERN_PROTOCOL_VERSION,
    PROTOCOL_VERSION_META,
    McpHttpError,
    classify_mcp_era,
    decode_mcp_header_value,
    validate_modern_http_request,
)


def _payload(method: str, *, request_id: int = 1, params: dict | None = None) -> dict:
    value = dict(params or {})
    value["_meta"] = {
        PROTOCOL_VERSION_META: MODERN_PROTOCOL_VERSION,
        CLIENT_CAPABILITIES_META: {},
        "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1"},
    }
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": value}


def _headers(method: str, name: str | None = None) -> dict[str, str]:
    headers = {
        "MCP-Protocol-Version": MODERN_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


def test_modern_request_validation_and_classification() -> None:
    payload = _payload("tools/list")
    headers = _headers("tools/list")
    assert classify_mcp_era(payload, headers) == "modern"
    validate_modern_http_request(payload, headers)


def test_modern_header_mismatch_is_protocol_error() -> None:
    payload = _payload("tools/list")
    with pytest.raises(McpHttpError) as captured:
        validate_modern_http_request(payload, {"MCP-Protocol-Version": MODERN_PROTOCOL_VERSION})
    assert captured.value.status_code == 400
    assert captured.value.code == -32020


def test_unsupported_modern_version_lists_supported_versions() -> None:
    payload = _payload("tools/list")
    payload["params"]["_meta"][PROTOCOL_VERSION_META] = "1900-01-01"
    headers = {"MCP-Protocol-Version": "1900-01-01", "Mcp-Method": "tools/list"}
    with pytest.raises(McpHttpError) as captured:
        validate_modern_http_request(payload, headers)
    assert captured.value.code == -32022
    assert MODERN_PROTOCOL_VERSION in captured.value.data["supported"]


def test_encoded_mcp_name_header_is_decoded_before_comparison() -> None:
    uri = "poa://demo/demo-rpi5@main/part/pokrywa-ą"
    payload = _payload("resources/read", params={"uri": uri})
    encoded = base64.b64encode(uri.encode("utf-8")).decode("ascii")
    headers = _headers("resources/read", f"=?base64?{encoded}?=")
    validate_modern_http_request(payload, headers)
    assert decode_mcp_header_value(headers["Mcp-Name"]) == uri


def test_initialize_without_modern_metadata_selects_legacy() -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    assert classify_mcp_era(payload, {}) == "legacy"
