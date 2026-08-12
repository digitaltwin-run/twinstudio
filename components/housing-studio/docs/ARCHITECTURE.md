# Architecture

## Data flow

```text
Natural-language request
        |
        v
LiteLLM structured output --------+
        |                          |
        +-> local fallback parser |
                                   v
                         Candidate ProjectConfig
                                   |
                                   v
                        leaf-level configuration diff
                                   |
                          user review / apply / discard
                                   |
                                   v
                         ProjectConfig (Pydantic)
                                   |
                +------------------+------------------+
                |                  |                  |
                v                  v                  v
          CadQuery 3D         2D drawing model    validation/metrics
                |                  |                  |
        STEP/STL/OBJ/GLB      DXF/SVG/PDF       JSON warnings
                +------------------+------------------+
                                   |
                                   v
                 BOM + change audit + rebuild script
                                   |
                                   v
                         manifest + reproducible ZIP
                                   |
                                   v
             FastAPI web preview/download + revision history
```

## Trust boundary

The language model can only propose JSON. It cannot supply Python, CadQuery expressions, filesystem paths, shell commands or arbitrary output names. `ProjectConfig` rejects additional keys and validates numeric ranges. The UI displays a field-level diff and does not apply a proposal until the user explicitly accepts it. The CAD generator consumes typed values only.

API keys stay on the server. The browser never receives provider credentials.

## Main modules

- `models.py`: complete persisted schema and defaults.
- `llm_config.py`: structured-output request, JSON validation and conservative fallback parser.
- `config_diff.py`: deterministic leaf-level comparison used by review and audit.
- `validation.py`: derived dimensions, board positions, warnings and hinge segments.
- `cad3d.py`: B-Rep construction and STEP/STL export.
- `draw2d.py`: analytical orthographic views and layer-aware DXF, SVG and PDF.
- `mesh_preview.py`: OBJ and GLB conversion plus open-lid scene.
- `artifacts.py`: reproducible output tree, BOM, audit reports, checksums, manifest and ZIP.
- `app/main.py`: API, job history and static-file delivery.
- `app/static/app.js`: proposal review, quick controls, previews and downloads.

## Revisions and reproducibility

Each generated job is an immutable directory identified by a safe job ID. It contains the validated JSON, JSON Schema, semantic layer configuration, warnings, metrics and a standalone rebuild script. Previous jobs can be listed and their configuration can be loaded as the starting point for another revision.

The manifest lists checksums for every non-self-referential artifact. `manifest.json` and the ZIP are excluded from their own checksum list; the finalized manifest stored in the job directory is byte-identical to the copy inside the ZIP.

## Coordinate system

- X: left to right.
- Y: front/hinge side to rear.
- Z: bottom to top.
- Base datum: Z = 0.
- Base/lid mating plane: Z = `base_height`; this upper surface of the lower base is drawing Datum A.
- Hinge axis: parallel to X.
