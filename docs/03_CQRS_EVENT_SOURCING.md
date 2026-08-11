# 03 — CQRS and Event Sourcing

## Why CQRS+ES

A multidisciplinary product needs an auditable answer to “who changed what, from which evidence, and who approved it?” Replacing a JSON file in place cannot provide that history. Living Product Studio stores decisions as append-only events and reconstructs a current read model.

## Command side

A `CommandEnvelope` contains:

- command ID/type;
- project stream ID;
- expected stream version;
- actor;
- typed payload;
- correlation ID and issue time.

The command bus validates domain models, role permissions and optimistic concurrency, then emits one or more event envelopes.

## Event side

An `EventEnvelope` contains:

- immutable event ID;
- stream ID and ordered version;
- event type and schema version;
- data;
- actor;
- correlation and causation IDs;
- occurrence time.

Examples include `ProjectCreated`, `ObjectUpserted`, `SelectionMapResolved`, `ChangePlanCreated`, `ChangeApplied`, `ArtifactAttached`, `MembershipGranted` and lifecycle/test events.

## Query side

The projector reconstructs `ProjectSnapshot` and materialized views:

- tree;
- unified specification;
- manufacturing lists;
- feature catalog;
- lifecycle/FMEA/test view;
- software and commercial view.

The reference implementation replays a stream in process. Production deployments can add cached projections and dedicated read stores without changing command/event contracts.

## Concurrency

Every mutating command supplies `expected_version`. If another user or worker appends an event first, the write is rejected with a conflict. The client reloads, re-resolves selection if necessary, and rebases the intended change.

## Event compatibility

Production rules:

- never mutate historical event payloads;
- append fields with defaults;
- keep a schema version;
- add upcasters for old events;
- version Protobuf packages/services deliberately;
- keep artifact hashes and generator versions in generation results.

## Long-running processes

CAD regeneration, simulation, supplier quotation and approval are process managers/sagas:

```text
GenerationRequested
→ worker claims job
→ adapter produces artifacts/check results
→ GenerationCompleted or GenerationFailed
→ reviewer approval
→ lifecycle gate transition
```

MQTT is an integration transport, not the source of truth. The database event stream remains authoritative.
