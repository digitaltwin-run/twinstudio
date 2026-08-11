# 07 — Manufacturing and supply

## Per-object manufacturing route

Every object carries `make_buy`, process, material, finish, machine profile, supplier, supplier part number, lead time and unit cost. The route is independent from the object identity.

Example routes:

- lower base: make → FDM print;
- upper lid: make → FDM now, possibly CNC later;
- hinge pin: buy → purchase;
- Raspberry Pi 5: buy → purchase;
- Camera Module 3: buy → purchase;
- application source/container: make → software build;
- retail box: outsource → packaging.

## Manufacturing package

A release package should contain:

- approved source model and neutral exchange format;
- process-specific output (STL/toolpath/Gerber/etc.);
- 2D drawing and critical characteristics;
- material, finish and tolerance;
- machine/process profile;
- inspection/test plan;
- revision and event-stream reference;
- artifact hashes;
- supplier/quotation approval where relevant.

## Printability layer

The current mechanical rules are lightweight. A production print adapter should add:

- mesh manifold/orientation checks;
- minimum wall and feature size by machine/material;
- overhang/support analysis;
- fit compensation and hole compensation;
- build orientation;
- slicing profile and estimated time/material;
- first-article measurement results.

## Make/buy changes

Replacing a made part with a purchased part should trigger impact on:

- dimensions/interfaces and assembly;
- supplier risk, lead time and cost;
- warranty and replacement instructions;
- compliance declarations;
- packaging and ecommerce claims;
- obsolescence and second-source plan.

## Traceability

The target industrialization model should add supplier lots, serial ranges, machine/material batches, operator/test-station IDs and nonconformance records as POA-addressed lifecycle objects.
