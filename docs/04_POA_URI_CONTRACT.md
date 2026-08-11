# 04 — POA URI contract

## Definition

This project defines **POA = Product Object Addressing**.

```text
poa://{tenant}/{project}@{revision}/{segment}/{segment}/...
```

It is not related to CORBA Portable Object Adapter or blockchain Proof of Authority.

## Rules

- `tenant`, `project` and `revision` are mandatory.
- Path segments are immutable identity atoms, not UI labels.
- Human-readable names can change without changing URI.
- Revisions may be logical names (`main`) or immutable release IDs.
- A child URI is scoped under its parent path.
- Scope checks may ignore revision when rebasing the same logical object, but must never ignore tenant/project.

## Recommended segment vocabulary

```text
device/{id}
assembly/{id}
part/{id}
feature/{id}
face/{id}
sketch/{id}
interface/{id}
purchased-component/{id}
pcb/{id}
schematic/{id}
software/{id}
container-image/{id}
artifact/{id}
region/{id}
projection-map/{id}
selection-map/{id}
requirement/{id}
test-plan/{id}/case/{id}
simulation-run/{id}
ecommerce-offer/{id}
```

## API/CLI/MQTT usage

The same URI must appear unchanged in:

- JSON and Protobuf payloads;
- REST command data;
- CLI output/input files;
- MQTT messages;
- MCP resource identifiers;
- artifact manifests;
- generated 2D entity metadata;
- CAD semantic tagging;
- requirements and test results.

## Identity versus location

An artifact’s POA URI is its logical identity; `path` or object-store URL is its current location. Export bundles may rename files for filesystem safety without changing artifact identity.
