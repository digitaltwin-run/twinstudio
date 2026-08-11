# Verification report

Verification date: 2026-08-11

## Automated checks

- Python modules compiled successfully with `compileall`.
- Editable package installation succeeded on Python 3.13 using the already installed build dependencies.
- Local `.env` loading for LiteLLM settings was verified.
- Test suite: 13 tests passed.
- Tests cover:
  - Pydantic configuration and derived dimensions;
  - explicit reporting of the PCB position-B clearance conflict;
  - deterministic Polish/English fallback parsing;
  - the LiteLLM strict JSON-Schema bridge with a mocked provider response;
  - CadQuery solid generation and STEP/STL export;
  - watertight, consistently wound base and lid STL meshes;
  - layered DXF, SVG and PDF generation;
  - optional front/top/side view switches;
  - complete ZIP artifact bundles;
  - FastAPI health, configuration and interpretation endpoints;
  - unsafe job identifier rejection.

## End-to-end smoke check

The FastAPI application was started locally and the following flow completed successfully:

1. `GET /health`;
2. `GET /api/default-config`;
3. `POST /api/interpret` in local fallback mode;
4. `POST /api/generate`;
5. download of the generated ZIP;
6. reload of the job manifest through `GET /api/jobs/{job_id}`.

The generated ZIP returned a valid ZIP header and the manifest contained links to STL, GLB, 2D drawings and the complete bundle.

## Geometry checks for the bundled default example

- Lower base STL: one connected component, watertight, consistent winding.
- Upper lid STL: one connected component, watertight, consistent winding.
- Base and lid CadQuery shapes: valid single solids.
- STEP files are exported from the CadQuery B-Rep model, not converted from STL.

## 2D documentation check

The base, lid and assembly PDF sheets were rendered to PNG at 180 DPI and visually checked for clipping, broken glyphs and obvious layout overlaps. The final sheets contain front, top and side views and technical notes.

## Checks not performed

- No physical FDM prototype was printed.
- No production fit test was performed with a real Raspberry Pi 5, cables, screws or hinge pin.
- No live external LiteLLM provider was called because no provider model/API key was configured in the verification environment. The integration path is covered with a mocked structured-output response, and fallback mode is covered directly.
- Chromium in the verification environment blocks access to local HTTP servers by administrator policy, so the complete GPU/browser interaction could not be exercised there. The HTML was served, JavaScript syntax was checked, and the backend generation/download flow was exercised directly.
- Docker image build was not executed in this environment.

These limitations are intentionally reflected in generated validation warnings. A physical prototype remains required before production.
