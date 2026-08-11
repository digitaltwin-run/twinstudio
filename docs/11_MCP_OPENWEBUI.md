# 11 — MCP and Open WebUI

## Scope of the included endpoint

`POST /mcp` exposes the same project permissions and domain services as REST/CLI. The implementation is a **tested core subset**, not a claim of full MCP SDK conformance.

Implemented for the modern stateless MCP revision `2026-07-28`:

- `server/discover`;
- `tools/list` and `tools/call`;
- `resources/list` and `resources/read`;
- mandatory per-request `_meta` protocol version and client capabilities;
- `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` mirror headers;
- Base64 sentinel decoding for a non-ASCII `Mcp-Name`;
- `resultType: complete` on successful modern results;
- server identity in result `_meta`;
- `ttlMs` and `cacheScope` on cacheable list/read results;
- HTTP 404 plus JSON-RPC `-32601` for an unknown modern method;
- HTTP 400 errors for invalid metadata, unsupported version and header mismatch;
- Origin allow-list validation before processing the request;
- HTTP 202 with an empty body for accepted JSON-RPC notifications.

A compatibility path also answers a legacy `initialize` request and reports revision `2025-11-25`. It is intended only as a migration aid. The package does not implement the complete old session/SSE behavior.

Not implemented or advertised:

- prompts;
- request-scoped SSE streaming;
- subscriptions/listen;
- multi round-trip requests (sampling, elicitation or roots);
- custom `x-mcp-header` tool parameters;
- an OAuth 2.1 authorization server;
- a full protocol conformance suite.

The modern protocol is stateless: every request carries its version and capabilities. The current HTTP transport uses one POST per request; it does not expose the removed standalone GET stream or protocol-level MCP sessions.

## Exposed tools

The current tool catalogue includes:

- project listing and object tree;
- unified specification/xBOM;
- region-selection resolution;
- selected-region annotation;
- scoped NL change planning;
- applying safe plan portions;
- power and thermal estimates;
- human-use evaluation;
- mechanical review rules;
- portable project export.

Mutations still pass through project roles, POA scope checks, typed plans and event-sourced commands. An MCP caller cannot bypass the selection scope or call arbitrary CAD code.

## Resources

Project snapshots and addressed project objects are exposed as JSON resources identified by POA URIs, for example:

```text
poa://demo/demo-rpi5@main
poa://demo/demo-rpi5@main/part/base
```

Large STEP/STL/image files remain normal authenticated downloads. MCP resources return metadata, structured project content and stable identifiers rather than copying every binary into model context.

## Modern discovery request

```bash
curl -u 'creator@example.test:YOUR_API_TOKEN' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: server/discover' \
  --data '{
    "jsonrpc":"2.0",
    "id":"discover-1",
    "method":"server/discover",
    "params":{
      "_meta":{
        "io.modelcontextprotocol/protocolVersion":"2026-07-28",
        "io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1"},
        "io.modelcontextprotocol/clientCapabilities":{}
      }
    }
  }' \
  http://localhost:8000/mcp
```

For `tools/call`, the HTTP request also needs `Mcp-Name` matching `params.name`. For `resources/read`, `Mcp-Name` must match `params.uri`.

## Authentication boundary

The application implements the requested email approval flow and HTTP Basic automation credential:

```text
username = user email
password = personal API token
```

This credential must be sent only over TLS. It is suitable for CLI, scripts and an authenticated reverse proxy.

Open WebUI's current native MCP integration is Streamable HTTP and its documented authentication options are oriented around none, bearer tokens and OAuth 2.1. Therefore, production integration should use one of these patterns:

1. Put `/mcp` behind an OAuth 2.1-capable API gateway/identity provider and translate the resulting identity to an application principal.
2. Put a narrow authenticated reverse proxy in front of `/mcp` that injects the internal Basic credential for a dedicated service account.
3. Use the application's `/openapi.json` integration instead of MCP when existing gateway, SSO, quotas and audit controls are more important than MCP-native behavior.

Do not publish a creator's personal API token in a shared Open WebUI configuration. Create a dedicated least-privilege service account or per-user token mapping.

## Open WebUI Compose profile

Start the optional UI:

```bash
docker compose --profile openwebui up --build
```

Then configure either:

- an OpenAPI connection to `http://app:8000/openapi.json`; or
- an MCP Streamable HTTP connection to the externally reachable `/mcp` URL through the chosen authentication gateway.

The Compose file starts Open WebUI but does not silently configure an OAuth provider or store a project API token. Those are deployment-specific security decisions.

## Origin and reverse-proxy configuration

Set allowed browser origins explicitly:

```dotenv
MCP_ALLOWED_ORIGINS=https://studio.example.com,https://chat.example.com
```

Server-to-server clients commonly omit `Origin`; they are still authenticated. When an `Origin` header is present and is not allow-listed, the endpoint returns HTTP 403. At the edge, also configure TLS, host validation, rate limits, request-size limits and audit logging.

## Recommended approval policy

Read tools can be broadly available according to project role. The following should require explicit user review or a lifecycle approval gate:

- applying geometry changes;
- changing manufacturing routes or supplier data;
- granting project membership;
- advancing a lifecycle gate;
- generating public/commercial artifacts;
- changing power limits or software release inputs.

The assistant should first show the typed `ChangePlan`, selected POA scope, affected artifacts, verification steps and unresolved questions. The user approves the plan; the system then emits an auditable command/event.

## Verification status

Automated tests cover modern discovery, tool listing, cache/result fields, required headers, unsupported protocol versions, Base64 `Mcp-Name`, legacy initialization and Origin rejection. A live connection to a specific Open WebUI release was not executed in the build environment and remains a deployment acceptance test.
