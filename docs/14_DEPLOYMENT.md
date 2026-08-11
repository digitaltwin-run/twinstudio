# 14 — Deployment

## Compose profiles

Base stack:

- `app`: FastAPI/web/MCP;
- `postgres`: event/auth storage;
- `mqtt`: integration broker;
- `mailpit`: development mail review.

Optional profiles:

- `cad`: CadQuery housing generation worker;
- `integration`: MQTT command-to-REST gateway;
- `simulation`: device/camera telemetry simulator;
- `openwebui`: conversational front end;
- `object-store`: MinIO placeholder for future artifact backend.

## Development

```bash
cp .env.example .env
docker compose up --build
```

Mail approval messages are visible in Mailpit. Development auth bypass is enabled by default for the local demonstration.

## Production topology

Recommended separation:

- reverse proxy/WAF and TLS;
- stateless app replicas;
- managed PostgreSQL with backups;
- authenticated MQTT broker;
- object storage with versioning;
- isolated job queue and sandboxed workers;
- production email service;
- identity provider or hardened magic-link service;
- telemetry/metrics/logging and audit alerting.

## Database migration

The MVP creates tables directly through SQLAlchemy metadata. Production must introduce Alembic migrations and controlled event/read-model migration procedures.

## Artifact storage

The reference implementation uses local files. A production backend should abstract:

- upload initiation;
- content-addressed hash;
- antivirus/scanner state;
- immutable source version;
- generated-artifact lineage;
- signed download URL;
- retention and legal hold.

## Scaling workers

Each generation/simulation command requires an idempotency key. Workers should claim jobs, renew leases, write artifacts to temporary paths, verify output, then publish completion exactly once from the process manager’s perspective.
