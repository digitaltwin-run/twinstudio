# 13 — Security model and hardening checklist

## Threat boundaries

- browser and external collaborators;
- LLM provider;
- CAD/PCB/simulation workers;
- MQTT broker and device telemetry;
- artifact storage;
- email invitation links;
- Open WebUI/MCP clients;
- downloaded project bundles.

## LLM safety

- do not execute generated code;
- require JSON Schema validation;
- allow-list operation kinds;
- verify every target against selected POA scope;
- treat prompts and uploaded artifacts as untrusted data;
- redact secrets before sending context to external providers;
- keep model/provider/version and prompt hash in plan metadata;
- require approval for destructive or commercial actions.

## Artifact safety

- limit size/type and scan uploads;
- keep source and generated artifacts separate;
- verify hashes;
- prevent path traversal;
- sandbox converters and CAD workers;
- do not preview active HTML/SVG from untrusted users without sanitization;
- use signed short-lived download URLs for object storage.

## Authentication checklist

- `DEV_AUTH_BYPASS=false`;
- TLS at ingress;
- `Secure`, `HttpOnly`, suitable `SameSite` cookies;
- CSRF tokens;
- rate limit and audit invitation/token endpoints;
- token expiration/revocation/rotation;
- separate service-account permissions;
- tenant-aware database and object-store controls;
- protect WebSockets and MQTT with authentication/authorization;
- secret manager rather than `.env` in production.

## Event integrity

For higher-assurance deployment, add append-only database controls, event signatures/hash chaining, trusted timestamping, off-site backup and independent artifact-hash verification.
