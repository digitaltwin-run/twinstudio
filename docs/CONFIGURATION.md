# Configuration reference

The canonical schema is generated at runtime from `ProjectConfig` and is included in every artifact bundle as `project_config.schema.json`.

## Main sections

| Section | Purpose |
|---|---|
| `metadata` | Project name, revision, units and description |
| `dimensions` | External envelope, wall thickness and lid profile |
| `mating` | Fit clearance and optional internal locating lip |
| `hinge` | Diameter, pin, position, opening angle and relief values |
| `board` | Raspberry Pi reference, hole pattern, standoffs and two positions |
| `connector_openings` | Configurable wall cut-outs |
| `camera_mounts` | Two-column, three-row camera pattern |
| `auxiliary_lid_bosses` | Four additional internal bosses |
| `rear_tabs` | Simplified internal rear tabs |
| `feature_layers` | Enable or disable functional 3D geometry |
| `drawing` | Projection, sheet, views and CAD layer styles |
| `artifacts` | Output formats and tessellation settings |

## Editing and review rule

The natural-language compiler receives the current full configuration and must return a complete candidate configuration while preserving values not explicitly changed. The backend validates the candidate and computes a leaf-level diff. The web interface shows the old and new value for every changed path and requires explicit acceptance. Ambiguous instructions are ignored rather than guessed.

Manual UI edits are validated through `/api/validate` before generation. A generated revision can contain the natural-language source, interpretation mode and applied diff in both JSON and Markdown form.

## Feature layers and drawing layers

Feature layers control whether geometry such as the second PCB mounting pattern, camera mounts, hinge or connector cut-outs is generated. Drawing layers control representation only and have their own enabled state, DXF name, line type, line width and colour index.

Generated SVG files preserve all semantic groups with `data-layer-key` and `data-default-enabled` attributes. This allows the browser to change visibility without altering the source CAD configuration.

## Hinge bore clearance

`hinge.pin_diameter` is the nominal hinge-pin diameter. `hinge.pin_bore_clearance` is the diametral clearance added to the bore. With the defaults, a 3.0 mm pin receives a 3.2 mm bore.

## 14 mm datum clarification

`auxiliary_lid_bosses.top_z_from_base_mating_plane` defines the top surface of the four additional lid bosses relative to the upper surface of the lower base, which is the base/lid mating plane (Datum A). The default is 14 mm above this plane.

## Output and reproducibility settings

The `artifacts` section controls STEP, STL, OBJ, GLB, open-preview and ZIP output. Each revision always includes the validated configuration, schema, layer configuration, metrics, warnings, technical specification, BOM and rebuild script. Source-description and change-report files are included when an interpretation/audit payload is supplied.
