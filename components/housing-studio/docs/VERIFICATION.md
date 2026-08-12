# Verification report

Verification date: 2026-08-11  
Verified release: **1.2.1**

## Automated checks

- Python modules compiled successfully with `compileall`.
- Frontend JavaScript passed `node --check` on Node.js 22.
- Test suite: **27 tests passed**.
- The tests cover:
  - Pydantic configuration validation and derived dimensions;
  - explicit reporting of the PCB position-B clearance conflict;
  - deterministic Polish/English fallback parsing;
  - the LiteLLM strict JSON-Schema bridge with a mocked provider response;
  - auditable natural-language configuration diffs;
  - CadQuery solid generation and STEP/STL export;
  - watertight, consistently wound base and lid STL meshes;
  - layered DXF, SVG and PDF generation;
  - optional front/top/side view switches;
  - retention of disabled SVG layers for interactive preview;
  - reproducible rebuild script generation;
  - manifest/artifact SHA-256 integrity and byte-identical manifest copies inside and outside the ZIP;
  - FastAPI health, configuration, interpretation, generation-history and configuration-reload endpoints;
  - unsafe job identifier rejection;
  - exact parity between HTML element IDs and JavaScript bindings;
  - JavaScript syntax and non-blocking degradation when Three.js/WebGL is unavailable;
  - synchronization of `pyproject.toml`, FastAPI and generator versions.

`ruff` was not installed in the verification environment, so a Ruff lint pass was not performed. Compilation, JavaScript syntax checks and the complete automated test suite passed.

## Demonstration artifact check

The bundled `sample_output/demo` revision was regenerated with Housing Studio 1.2.1.

- Manifest generator version: `1.2.1`.
- Manifest artifact records: 37.
- ZIP entries: 38.
- `ZipFile.testzip()` returned no damaged member.
- Every artifact listed in `manifest.json` exists and matches its recorded SHA-256 hash.
- The manifest copied into `housing_project_bundle.zip` contains the same generator version and configuration provenance.

## Geometry checks for the bundled default example

- Lower base STL: one connected component, watertight and consistently wound.
- Upper lid STL: one connected component, watertight and consistently wound.
- Base and lid CadQuery shapes: valid single solids.
- STEP files are exported from the CadQuery B-Rep model, not converted from STL.

## 2D documentation check

The base, lid and assembly PDF sheets were rendered to PNG at 200 DPI using the PDF verification workflow and visually inspected.

- All three PDFs rendered successfully as single-page drawings.
- Front, top and side orthographic views are present.
- The sheets show 2 mm general wall thickness and the configured main dimensions.
- No clipped headings, black boxes, broken glyphs or obvious view overlaps were observed.

## Web application checks

- `GET /health` returned `status=ok` and version `1.2.1` from a locally started Uvicorn process.
- The HTML template and JavaScript bindings have exact element-ID parity.
- Three.js is now loaded through guarded dynamic imports. A failed CDN/WebGL initialization is caught and reported inside the viewer while configuration editing, 2D documentation, backend generation and downloads remain available.
- Chromium is installed, but local HTTP navigation is blocked by an administrator browser policy in this environment (`ERR_BLOCKED_BY_ADMINISTRATOR`). Therefore, a complete automated pointer/GUI interaction run could not be completed in Chromium. This is an environment restriction rather than an application HTTP error; direct HTTP and API checks succeeded.

## Checks not performed

- No physical FDM prototype was printed.
- No production fit test was performed with a real Raspberry Pi 5, cables, screws or hinge pin.
- No live external LiteLLM provider was called because no provider model/API key was configured. The integration path is covered with a mocked structured-output response, and fallback mode is covered directly.
- Docker image build was not executed in this environment.

A physical prototype remains required before production, especially for the hinge, moving clearances, connector access, standoff screw fit and printer-specific FDM tolerances.
