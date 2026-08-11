# ADR 0003 — Typed LLM plans, not generated code

- Status: accepted
- Decision: LLM output is a strict schema-valid change plan with allow-listed operations and scope checks.
- Rationale: executing generated CAD/Python code would make selection boundaries, security and reproducibility difficult to enforce.
- Consequences: adapters must implement operation types; unsupported operations remain deferred/reviewable.
