# Scoped B-Rep edit demonstration

This folder demonstrates the executable narrow selected-region CAD path.

Inputs:

- `selection.json`: 3D lasso/ray-hit evidence scoped to the base front wall.
- `operation.json`: typed `boolean_cut` operation with `feature_type=hole` and diameter 3 mm.
- source STEP: `../artifacts/3d/base.step`.

Outputs:

- `output/scoped-result.step`;
- `output/scoped-result.stl`;
- `output/operation-journal.json` with scope, hashes, validity and volume delta.

The result is a derived B-Rep revision. It is not a reconstructed native feature tree. The adapter also supports axis-aligned `local_box` add/cut operations; arbitrary free-form topology edits remain outside this demonstration.
