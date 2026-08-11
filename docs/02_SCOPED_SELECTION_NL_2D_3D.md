# 02 — Scoped selection and NL → 2D → 3D

## Problem

A sentence such as “make this wall 0.5 mm thicker” is unsafe without a precise definition of **this**. Screen pixels, STL triangle indices and CAD faces also have different stability properties. The platform therefore stores selection as evidence and resolves it before planning a change.

## Selection evidence

`RegionSelection` contains:

- project and revision;
- source view: 3D, 2D drawing, photo, PCB or schematic;
- tool: pointer, pencil, lasso, rectangle or brush;
- selected object POA scopes;
- screen path;
- camera/projection and viewport state;
- ray intersections and world-space AABB;
- mesh hash and triangle index;
- semantic face URI and optional native B-Rep face ID;
- source artifact and 2D projection entity IDs.

The browser can reproduce the annotation and the backend can detect stale selections after regeneration.

## Selection resolution

`SelectionMap` separates ephemeral evidence from persistent identifiers:

```text
screen pixels / ray hits
        ↓
mesh hash + object URI
        ↓
semantic face / feature URI
        ↓
native CAD B-Rep face or sketch entity
```

Resolution statuses:

- `resolved`: sufficient stable geometry identity;
- `partial`: object/feature is known, but topology needs adapter resolution;
- `unresolved`: source cannot be tied safely to geometry;
- `stale`: selection references an older incompatible revision.

A triangle index alone is never treated as a stable CAD identity.

## 2D and photograph mapping

A drawing entity can map directly to a generated feature/face when the drawing exporter preserves IDs. A photograph needs calibration: reference dimensions, camera model, pose, distortion and the plane/surface represented by the marked area.

Without a projection map, the platform stores the note and asks for calibration. It must not infer an arbitrary 3D cut from an uncalibrated photograph.

## Natural-language compiler

The compiler receives only:

- the prompt;
- selection evidence and resolved scope;
- selected object/feature context;
- allowed operation types;
- JSON Schema for the result.

Allowed examples:

- set a named parameter;
- add/suppress/transform a feature;
- boolean cut/add;
- replace a component;
- update manufacturing route;
- attach a requirement/test/annotation.

Every `target_uri` must be inside one of the selected POA scopes. The core rejects a plan that reaches another part or subassembly.

## Application modes

### Immediately safe in the core

Scalar parameter patches on a selected object, followed by event recording and a regeneration request.

### Executable allow-listed derived B-Rep operations

`services/cad-worker/scoped_brep_adapter.py` provides a deliberately narrow local-edit path for STEP input:

- directional cylindrical hole cut from a ray-hit point and normal;
- axis-aligned local-box cut from the selected world-space AABB;
- axis-aligned local-box add from the selected world-space AABB.

The worker rejects an operation when its target is outside `target_object_uris` or when ray hits cross the selected scope. A successful operation writes:

- `scoped-result.step`;
- `scoped-result.stl`;
- `operation-journal.json`, including input/output hashes, selection evidence, typed operation, validity, solid count and volume delta.

The output is a **derived B-Rep revision**. It does not reconstruct native sketches, dimensions or feature history from an imported STEP.

### Still deferred to a richer CAD adapter

- arbitrary local wall-thickness patch;
- free-form regional pad or cut;
- chamfer on a selected topological boundary;
- local face move/offset;
- topology-sensitive fillet or shell edit;
- stable edit propagation through arbitrary topology changes;
- native SolidWorks feature-tree reconstruction.

A richer adapter must resolve semantic/native IDs, apply the operation, regenerate the part, rerun collision/manufacturing checks and publish new artifacts. A failed topology match must become a review question, not an uncontrolled model change.

## Conflict handling

Event stream versioning prevents silent overwrites. A plan records its base revision. Applying it against a newer stream requires rebase/re-resolution. Planned collaborative enhancements are:

- region-level soft locks;
- side-by-side 2D/3D diff;
- semantic conflict detection;
- merge of independent parameter changes;
- mandatory re-pick when topology has changed.
