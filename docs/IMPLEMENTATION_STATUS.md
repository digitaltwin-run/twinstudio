# Implementation status

Legend: **Implemented**, **Working scaffold**, **Roadmap**.

| Capability | Status | Notes |
|---|---|---|
| Object/component tree | Implemented | Web UI, REST and CLI tree projection |
| xBOM/manufacturing views | Implemented | Print, CNC, purchase, PCB, software, packaging, reference |
| 3D pointer/pencil/lasso/rectangle | Implemented | Screen path, ray hits, AABB, camera state |
| 2D drawing annotations | Implemented | Screen-space selection and source artifact |
| Persistent semantic selection | Working scaffold | Semantic face/feature mapping works when IDs exist; native B-Rep IDs depend on adapter |
| Calibrated photo → 3D mapping | Roadmap | Schema/example present; calibration UI/solver not implemented |
| LiteLLM structured planner | Implemented | Optional; schema validation and scope check |
| Local deterministic planner | Implemented | Thickness, hole, chamfer, move and annotation patterns |
| Scalar parameter apply | Implemented | Event-sourced |
| Allow-listed selected B-Rep edit | Implemented | STEP input; directional hole cut and axis-aligned local-box add/cut; derived STEP/STL plus operation journal |
| Arbitrary selected B-Rep edit | Roadmap | Free-form/topology-sensitive operations require persistent semantic/native identity and a richer CAD adapter |
| Parametric housing regeneration | Working scaffold | Existing CadQuery worker and generator are included |
| 2D/3D artifact download/export | Implemented | Project bundle and sample outputs |
| CQRS + Event Sourcing | Implemented | Append-only events, projector, optimistic concurrency |
| Protobuf DSL | Implemented as source contract | `.proto` sources; generated clients not bundled |
| REST / CLI / shell | Implemented | Same core services |
| MQTT event publishing | Implemented | Optional broker path |
| MQTT command gateway | Working scaffold | Optional service forwards typed JSON to REST |
| MCP tools/resources | Working scaffold | Tested 2026-07-28 discovery/tools/resources core with metadata/header/Origin validation plus legacy initialize; no SSE/MRTR/full conformance suite |
| Open WebUI deployment | Working scaffold | Compose profile; use OpenAPI or an authenticated MCP gateway. Live interop and OAuth provider configuration were not run |
| Roles reader/editor/admin/creator | Implemented | Per-project permission checks |
| Email approval onboarding | Implemented for reference deployment | Mailpit/file outbox; production hardening required |
| HTTP Basic email:PAT | Implemented | TLS required in production |
| Power/voltage-drop estimate | Implemented | Lumped resistance, not transient power integrity |
| Thermal estimate | Implemented | Lumped RC, not CFD |
| Camera sample replay | Implemented | Synthetic images and deterministic container output |
| Raspberry Pi hardware emulation | Roadmap | Current container validates software/data flow only |
| Human task/checklist evaluation | Implemented | Logic/rule review, not digital-human biomechanics |
| FMEA and lifecycle gates | Implemented as data/views | Workflow automation can be expanded |
| Mechanical rules | Working scaffold | Simple thresholds, not FEA |
| PCB/SCH product objects | Implemented in schema | Native project editing not implemented |
| KiCad CLI check/export adapter | Working scaffold | Requires installed `kicad-cli` and real source files |
| PCB synthesis/autorouting | Roadmap | Not claimed |
| GTIN check digit | Implemented | Does not allocate an authorized identifier |
| Ecommerce offer model | Implemented | Marketplace connectors and approval workflow are roadmap |
| Production security | Roadmap | Reference defaults are development-oriented |
