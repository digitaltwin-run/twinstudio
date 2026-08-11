# ADR 0001 — Event-sourced product thread

- Status: accepted
- Decision: use one ordered event stream per project as the authoritative decision history; derive current snapshots/views.
- Rationale: multidisciplinary changes, approvals and generated artifacts require auditability and optimistic concurrency.
- Consequences: event compatibility/upcasting and projection rebuilding become operational responsibilities.
