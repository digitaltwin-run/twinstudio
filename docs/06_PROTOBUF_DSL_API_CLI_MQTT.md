# 06 — Protobuf DSL, REST, CLI, shell and MQTT

## One domain language

The canonical Pydantic models and `proto/lps/v1/*.proto` describe the same concepts. JSON is convenient for browser/LLM work; Protobuf is the strongly typed contract for workers, integrations and future generated clients.

Main files:

- `common.proto`: POA references, quantities, parameters, diagnostics;
- `geometry.proto`: selections, projection maps and geometry operations;
- `project.proto`: objects, features, artifacts and unified project;
- `collaboration.proto`: memberships, access requests, annotations and approvals;
- `simulation.proto`: power, thermal, human-use, failure modes and runs;
- `commands.proto`: command envelope and scoped change plan;
- `events.proto`: event envelope/batches;
- `services.proto`: command, query and simulation service definitions.

## REST

REST is the primary browser interface. Mutations still go through the same command bus. Generic `/commands` is useful for automation, while dedicated endpoints provide validation and discoverability for selections, change plans and simulations.

## CLI and shell

`twinstudio` uses the same local command/query services. It supports project listing/tree, raw commands, scoped planning from a saved selection, power simulation, export, GTIN utilities and an interactive shell.

For remote production administration, add a thin CLI transport that sends the same Protobuf/JSON commands to REST or gRPC rather than opening the database directly.

## MQTT

MQTT topics are a bridge for workers, test benches and device telemetry:

```text
twinstudio/v1/{project}/commands/{command}
twinstudio/v1/{project}/events/{event}
twinstudio/v1/{project}/responses/{correlation}
twinstudio/v1/{project}/telemetry/{channel}
```

QoS and retained-message policies must be chosen per message type. Commands/results should include IDs and be idempotent; high-rate telemetry should be separated from immutable product events.

## Code generation

With Buf installed:

```bash
buf lint
buf generate
```

Generated code is intentionally not committed in the reference package. The source `.proto` files are the reviewed contract.
