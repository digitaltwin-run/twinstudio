# TwinStudio 0.5.0 implementation status

Legend: **Implemented**, **Working scaffold**, **Roadmap**.

| Capability | Status | Notes |
|---|---|---|
| Object/component tree | Implemented | Web UI, REST and CLI tree projection |
| xBOM/manufacturing views | Implemented | Print, CNC, purchase, PCB, software, packaging and reference routes |
| 3D pointer/pencil/lasso/rectangle | Implemented | Screen path, ray hits, AABB and camera state |
| 2D drawing annotations | Implemented | Screen-space selection with source-artifact linkage |
| Persistent semantic selection | Working scaffold | Semantic face/feature mapping works when IDs exist; native B-Rep identities depend on the adapter |
| Calibrated photo → 3D mapping | Roadmap | Schema and example exist; calibration UI/solver is not implemented |
| Source-grounded feature-lens catalog | Implemented | 49 active identifiable lenses, duplicate External Relations retained, one unresolved disabled source slot |
| Design-fixation review | Implemented | Evidence scan, overlooked assumptions, alternatives, local deterministic mode and optional LiteLLM mode |
| Goal-fixation/verb hierarchy | Implemented | Controlled synonyms, hypernyms, hyponyms, opposites and adjacent actions |
| Bidirectional goal-resource graph | Implemented | Goal variants descend; objects, parts, features and evidence grow upward |
| BrainSwarming-style idea lineage | Implemented | Candidate ancestry, mutations, crossovers and graph exports are recorded |
| Adjacent-possible exploration | Implemented | Controlled association expansion; proposals remain hypotheses |
| Evolution population and selection | Implemented | Seeded deterministic population, generations, scoring weights and shortlist |
| Evolution experiment planning | Implemented | Verification tasks and candidate-specific validation recommendations |
| TwinScript 1.0 text DSL | Implemented | Line-oriented parser with diagnostics and line continuation |
| Canonical YAML/JSON DSL | Implemented | All forms validate as one `TwinDslDocument` model |
| DSL JSON Schema and EBNF | Implemented | Draft 2020-12 schemas plus canonical grammar, synchronized into package data |
| DSL via REST/API | Implemented | Parse, preview, apply, run graph, lifecycle and candidate-to-plan endpoints |
| DSL via CLI | Implemented | Schema, grammar, parse, preview, apply, run and lifecycle commands |
| DSL via MCP | Working scaffold | Six evolution tools within a 21-tool MCP surface; no full conformance suite/SSE |
| Browser Evolution DSL workspace | Implemented | Editor, preview, shortlist, diagnostics, history and explicit persistence confirmation |
| Lifecycle templates | Implemented | Hardware, digital-product and continuous-evolution templates |
| Lifecycle stage gates | Implemented | Entry/exit evidence, approvers, transitions and blocking checks as typed data/workflow |
| 34 TwinStudio engineering dimensions | Implemented | Manufacturability, serviceability, testability, security, sustainability and other lifecycle concerns |
| 17 declarative evolution operators | Implemented | Reframe, repurpose, shift, invert, split/combine, substitute, modularize, make reversible and crossover |
| LiteLLM structured planner | Implemented | Optional; schema validation and scope checks; no generated Python/shell execution |
| Local deterministic planner | Implemented | Thickness, hole, chamfer, move and annotation patterns plus evolution fallback |
| Scalar parameter apply | Implemented | Event-sourced and allow-listed |
| Allow-listed selected B-Rep edit | Implemented | STEP input; directional hole cut and axis-aligned local-box add/cut; derived STEP/STL and journal |
| Arbitrary selected B-Rep edit | Roadmap | Free-form/topology-sensitive operations require persistent semantic/native identity and richer CAD adapters |
| Parametric housing regeneration | Working scaffold | CadQuery generator for the housing is included as a component |
| 2D/3D artifact download/export | Implemented | Individual artifacts and portable project bundle |
| Portable `.twinstudio.zip` | Implemented | Snapshot, EDA event stream, project descriptor, previews, content-addressed objects and SHA-256 manifest |
| CQRS + Event Sourcing | Implemented | Append-only events, projector and optimistic concurrency |
| Protobuf contracts | Implemented as source contract | `.proto` sources; generated clients are not bundled; namespace retained for compatibility |
| REST / CLI / shell | Implemented | Shared domain services |
| MQTT event publishing | Implemented | Optional broker path |
| MQTT command gateway | Working scaffold | Optional service forwards typed JSON to REST |
| MCP tools/resources | Working scaffold | Modern discovery/tools/resources core plus legacy initialize; no request-scoped SSE/MRTR/full suite |
| Open WebUI deployment | Working scaffold | Compose profile; live provider/OAuth configuration remains deployment work |
| Roles reader/editor/admin/creator | Implemented | Per-project permission checks |
| Email approval onboarding | Implemented for reference deployment | Mailpit/file outbox; production hardening required |
| HTTP Basic email:PAT | Implemented | TLS required in production |
| Power/voltage-drop estimate | Implemented | Lumped resistance, not transient power integrity |
| Thermal estimate | Implemented | Lumped RC, not CFD |
| Camera sample replay | Implemented | Synthetic images and deterministic container output |
| Raspberry Pi hardware emulation | Roadmap | Current container validates software/data flow only |
| Human task/checklist evaluation | Implemented | Logic/rule review, not biomechanical simulation |
| FMEA and lifecycle evidence | Implemented as data/views | Automated evidence ingestion can be expanded |
| Mechanical rules | Working scaffold | Simple thresholds, not FEA |
| PCB/SCH product objects | Implemented vertical slice | Native UUID/reference import, typed EDA DSL, candidate validation, event-backed accept/reject/promote/revert and content-addressed history; routing and full SCH connectivity remain out of scope |
| EDA Digital Twin history | Implemented | `twinstudio.project/v1`, optimistic stream version, portable NDJSON, wellmanifest projection and legacy `change.json`/`approval.json` migration |
| KiCad CLI check/export adapter | Working scaffold | Requires `kicad-cli` and real source files |
| PCB synthesis/autorouting | Roadmap | Not claimed |
| GTIN check digit | Implemented | Does not allocate an authorized GS1 identifier |
| Ecommerce offer model | Implemented | Marketplace connectors and publication approvals remain roadmap |
| Production security | Roadmap | Reference defaults are development-oriented |
