# Configuration reference

The canonical schema is generated at runtime from `ProjectConfig` and is also included in every artifact bundle as `project_config.schema.json`.

## Main sections

| Section | Purpose |
|---|---|
| `metadata` | Project name, revision and units |
| `dimensions` | External envelope, wall thickness and lid profile |
| `mating` | Fit clearance and optional internal locating lip |
| `hinge` | Diameter, pin, position, opening angle and relief values |
| `board` | Raspberry Pi reference, hole pattern and two positions |
| `connector_openings` | Configurable wall cut-outs |
| `camera_mounts` | Two-column, three-row camera pattern |
| `auxiliary_lid_bosses` | Four additional internal bosses |
| `rear_tabs` | Simplified internal rear tabs |
| `feature_layers` | Enable or disable geometry features |
| `drawing` | Projection, sheet and CAD layer styles |
| `artifacts` | Output formats and tessellation settings |

## Editing rule

When the natural-language compiler receives a change request, it must return the complete configuration and preserve all values not explicitly changed. Ambiguous instructions are deliberately ignored rather than guessed.

## Luz otworu zawiasu

`hinge.pin_diameter` opisuje nominalną średnicę sworznia, a `hinge.pin_bore_clearance` jest luzem średnicowym dodawanym do otworu. Domyślnie sworzeń 3,0 mm otrzymuje otwór 3,2 mm.

## Punkt odniesienia 14 mm

`auxiliary_lid_bosses.top_z_from_base_mating_plane` oznacza położenie górnej powierzchni dodatkowych punktów montażowych względem górnej powierzchni podstawy, czyli płaszczyzny łączenia podstawy i klapy (Datum A). Domyślnie jest to 14 mm powyżej tej płaszczyzny.
