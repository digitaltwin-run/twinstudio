# ADR 0004 — Adapter-based engineering tools

- Status: accepted
- Decision: isolate CadQuery/SolidWorks/KiCad/slicer/simulation/ecommerce tools behind commands, artifacts and result events.
- Rationale: tools differ in native topology and licensing; the core product model should remain independent.
- Consequences: persistent identity and adapter conformance tests are required for reliable local edits.
