# 01 — Product model and xBOM

## Canonical object graph

Each `ObjectNode` has a POA URI, parent URI, kind, quantity, revision, parameters, features, artifacts, manufacturing route and inclusion flags. Parent-child edges form an assembly tree without hiding cross-domain relationships in filenames.

Typical hierarchy:

```text
device
├── enclosure assembly
│   ├── lower base
│   ├── upper lid
│   └── hinge pin
├── electronics assembly
│   ├── Raspberry Pi 5
│   ├── Camera Module 3
│   └── power supply/cable
├── software assembly
│   ├── application source
│   └── runtime container
├── simulation models
├── packaging
└── ecommerce offer
```

## xBOM concept

“xBOM” means that several bills and work lists are generated from the same nodes:

- **eBOM:** everything physically delivered in the assembled product;
- **print job:** only items where `inclusion.print_job = true`;
- **CNC job:** only CNC-routed items;
- **purchase order:** commercial parts and fasteners;
- **PCB fabrication:** custom board and panel outputs;
- **software bill/release:** source, packages, container images and deployment configuration;
- **packaging view:** box, inserts, labels, manuals and bundled accessories;
- **reference-only view:** models used for fit or simulation but not manufactured or delivered.

A part can change route without changing identity. For example, the upper lid can remain `poa://.../part/lid` while its manufacturing process changes from FDM to CNC or an outsourced molded part.

## Feature and dimension catalog

A part’s `FeatureSpec` stores:

- feature URI and type;
- parameters and units;
- approval/measurement state and confidence;
- semantic face URIs;
- generator name;
- suppression state and notes.

This allows a natural-language request to target a feature or selected face rather than treating the part as an opaque STL.

## Purchased components

Raspberry Pi 5 and Camera Module 3 are modeled as purchased components. Their size, mounting pattern, interfaces, supplier part number and reference artifacts belong in the project, but their vendor geometry does not belong in the enclosure print job. A purchased component may still participate in:

- fit and collision checks;
- thermal and power models;
- human-use instructions;
- purchase and substitution workflows;
- ecommerce package completeness.

## Interfaces

The next production-strength extension should model interfaces explicitly rather than only in metadata:

- mechanical interface: mounting pattern, envelope, keep-out and fastener;
- electrical interface: voltage/current, connector and pinout;
- data interface: protocol and bandwidth;
- optical interface: field of view and aperture;
- thermal interface: power loss, heat path and airflow boundary;
- software interface: service, topic, file or API contract.

Explicit interface objects permit automated compatibility and impact analysis when a component is replaced.
