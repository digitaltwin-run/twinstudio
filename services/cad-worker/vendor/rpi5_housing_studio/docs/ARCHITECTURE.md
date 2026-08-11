# Architecture

## Data flow

```text
Natural-language request
        |
        v
LiteLLM structured output -------+
        |                         |
        +-> local fallback parser|
                                  v
                         ProjectConfig (Pydantic)
                                  |
                +-----------------+------------------+
                |                 |                  |
                v                 v                  v
          CadQuery 3D        2D drawing model    validation/metrics
                |                 |                  |
        STEP/STL/OBJ/GLB     DXF/SVG/PDF       JSON warnings
                +-----------------+------------------+
                                  |
                                  v
                           manifest + ZIP
                                  |
                                  v
                     FastAPI web preview/download
```

## Trust boundary

The LLM can only propose JSON. It cannot supply Python, CadQuery expressions, paths, shell commands, or arbitrary file names. `ProjectConfig` rejects additional keys and validates geometry ranges. The CAD generator consumes typed values only.

## Main modules

- `models.py`: complete persisted schema and defaults.
- `llm_config.py`: structured-output request, JSON validation, conservative fallback parser.
- `validation.py`: derived dimensions, board positions, warnings, hinge segments.
- `cad3d.py`: B-Rep construction and STEP/STL export.
- `draw2d.py`: analytical orthographic views, layer-aware DXF, SVG and PDF.
- `mesh_preview.py`: OBJ and GLB conversion plus open-lid scene.
- `artifacts.py`: output directory, checksums, manifest and ZIP.
- `app/main.py`: API and static-file delivery.

## Coordinate system

- X: left to right.
- Y: front/hinge side to rear.
- Z: bottom to top.
- Base datum: Z = 0.
- Base/lid mating plane: Z = `base_height`; this upper surface of the lower base is drawing Datum A.
- Hinge axis: parallel to X.
