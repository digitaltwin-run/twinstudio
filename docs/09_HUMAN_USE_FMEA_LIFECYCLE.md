# 09 — Human use, FMEA and lifecycle

## Build layer versus use/test layer

The platform intentionally separates:

- **build definition:** parts, software, manufacturing, assembly and configuration;
- **use definition:** actor, task, sequence, expected action/force/time, feedback and recovery;
- **test definition:** method, inputs, expected result, evidence and approval;
- **risk definition:** failure mode, cause, effect, controls and residual risk;
- **lifecycle definition:** stage and gate criteria.

A complete product is not “done” when CAD exports successfully.

## Human-use scenario

Each step records:

- instruction and action;
- target object;
- preconditions;
- success criteria;
- possible errors and hazards;
- expected duration and force;
- recovery steps.

The MVP checks missing criteria, missing misuse cases, ordering assumptions and declared high-force steps. Physical usability testing remains required.

## FMEA

Failure modes target a POA object and include severity, occurrence and detection values with controls. RPN is a prioritization aid, not an acceptance decision by itself.

Example concerns for the enclosure/device:

- hinge cracking or pin loss;
- PCB shorting on unused posts;
- connector misalignment causing plug damage;
- thermal accumulation with insufficient airflow;
- power cable voltage drop and reset;
- camera cable pinch;
- user forcing the lid beyond the designed path;
- transport shock and boss fracture;
- wrong software/configuration shipped.

## Lifecycle stages

The model includes evidence intake, requirements, concept, architecture, detailed design, prototype, verification, validation, industrialization, production, fulfillment, operation, maintenance and end-of-life.

Each gate has entry/exit criteria, approving roles and evidence artifacts. Recommended minimum release gates:

- design inputs approved;
- interfaces and critical dimensions verified;
- manufacturability check passed;
- electrical/thermal budget measured;
- software tests passed on target hardware;
- usability and foreseeable misuse reviewed;
- FMEA controls implemented;
- manufacturing and inspection package approved;
- ecommerce claims traceable to evidence.
