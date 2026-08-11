# 00 — Executive overview

## Product vision

Living Product Studio treats a product as a continuously evolving, versioned system rather than a folder of unrelated CAD files, photos, spreadsheets and source code. One project contains the physical decomposition, geometry, purchased components, software, power/thermal assumptions, manufacturing choices, test evidence, human-use instructions, lifecycle approvals and commercial package.

The platform is intended to answer five questions at any revision:

1. **What is the product?** Object tree, interfaces, features, dimensions and software.
2. **Why is it like this?** Requirements, source evidence, decisions, annotations and event history.
3. **How is each item obtained?** Print, CNC, PCB fabrication, purchase, outsource, software build or reference-only.
4. **Does it work and remain safe?** Simulations, checks, FMEA, human-use scenarios and verification evidence.
5. **What can be released or sold?** Approved manufacturing package, software release, documentation, packaging, SKU and GTIN state.

## Core design principles

- **Selection first:** natural-language instructions are constrained by an explicit 2D/3D selection and object-tree scope.
- **Typed intent, not generated code:** the LLM emits schema-validated operations, never executable CAD/Python code.
- **Persistent identities:** POA URIs identify projects, objects, features, faces, artifacts, requirements, tests and commercial items.
- **Append-only decisions:** CQRS and Event Sourcing retain who requested, approved and applied every change.
- **One graph, many views:** eBOM, print job, CNC job, purchase list, software bill, test view and ecommerce package are projections of the same canonical project.
- **Evidence and uncertainty are explicit:** measurements extracted from images can remain proposed with confidence until approved.
- **Simulation is never confused with validation:** every result identifies its model and limitations.
- **Adapters isolate engineering tools:** CadQuery, SolidWorks, KiCad, slicers, CFD/FEA, test equipment and ecommerce systems connect through typed commands and artifacts.

## Working MVP versus target platform

The repository provides a working vertical slice for the enclosure example: web selection, object tree, scoped planning, event storage, sharing, specification, export and reduced-order simulations. The target architecture is broader than the implemented engines. Free-form local solid modeling, production PCB editing, CFD/FEA, hardware-in-the-loop and digital-human biomechanics remain adapter work packages.

## Recommended delivery phases

### Phase 1 — governed enclosure workflow

- stabilize semantic feature and face IDs in the housing generator;
- map generated 2D entities back to the same IDs;
- make selected hole/chamfer/pad/offset operations executable in CadQuery;
- add artifact comparison, slicer checks and review approvals;
- deploy collaboration securely.

### Phase 2 — complete device definition

- component catalog and approved supplier data;
- interface/control-document objects;
- software build and image-replay test pipelines;
- measured power and thermal calibration;
- packaging, installation instructions and FMEA expansion.

### Phase 3 — PCB/SCH and multidisciplinary optimization

- native KiCad UUID mapping and controlled edit adapter;
- ERC/DRC and manufacturing exports as lifecycle gates;
- electrical network simulation adapters;
- enclosure/PCB clearance and connector alignment checks;
- thermal/airflow and mechanical analysis adapters.

### Phase 4 — industrialization and commerce

- supplier quotations and change control;
- production routing, quality plans and serial/lot traceability;
- GS1-assigned identifiers and channel-specific product listings;
- warranty, maintenance and end-of-life workflows.
