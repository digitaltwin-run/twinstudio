# Changelog

## 1.2.1 - 2026-08-11

### Added

- Shared package version used by Python metadata, FastAPI and generated manifests.
- Frontend contract tests that synchronize HTML element IDs with JavaScript and check JavaScript syntax.
- Non-blocking Three.js dependency loading: CAD generation, 2D documentation and downloads remain available when the external 3D viewer modules cannot be loaded.
- Base/lid/grid/axes switches in the 3D preview.
- End-to-end revision reload and reproducible rebuild smoke verification.

### Changed

- Expanded deterministic export parsing to understand commands such as `wyłącz eksport OBJ`, `bez eksportu PDF`, `enable export STEP` and equivalent variants.
- Regenerated the demonstration artifact package with the current generator version.
- Updated verification documentation for the complete 1.2.1 workflow.

### Fixed

- Synchronized project, API and artifact-generator version reporting.
- Prevented failure of the entire web application when browser-side 3D dependencies are unavailable.
- Synchronized every JavaScript `getElementById()` reference with the HTML template.

## 1.2.0 - 2026-08-11

### Added

- Review-before-apply workflow for natural-language changes.
- Leaf-level configuration diff returned by LiteLLM and the local parser.
- Quick dimension controls, 3D feature-layer switches, 2D layer switches and output-format controls in the web UI.
- Interactive visibility of semantic layers in generated SVG drawings.
- Configuration validation endpoint.
- Revision history with stored configuration reload.
- Human-readable and JSON configuration-change reports.
- Bill of materials in CSV format.
- Reproducible `rebuild_project.py` embedded in every generated revision.
- Generated-revision README.
- Manifest consistency and artifact checksum tests.

### Changed

- Expanded Polish and English fallback parsing for dimensions, standoffs, hinge details, mounting options, views, layers and output formats.
- Manifest/ZIP generation stores a byte-identical final manifest inside and outside the archive.
- Sample generator writes a deterministic baseline to `sample_output/demo`.
- Documentation updated for the layer-aware and auditable workflow.

### Fixed

- Removed stale self-referential manifest and ZIP checksum records.
- Added recognition of Polish grammatical variants such as `średnicę` in manufacturing instructions.

## 1.0.0 - 2026-08-11

- Initial parametric CadQuery generator for the base and lid.
- STEP, STL, OBJ and GLB export.
- Layered DXF, SVG and PDF documentation for base, lid and assembly.
- FastAPI web application and LiteLLM configuration bridge.
