# TwinStudio 0.5.0 — verification record

Verification was performed in the release build environment on **2026-08-12**. The machine-readable result is stored in `docs/verification-report.json`.

## Result

Overall status: **passed**.

## Passed checks

- The complete `demo-rpi5` source snapshot passed Pydantic validation and contains **15 product/object nodes**.
- All **24 source/example artifacts** referenced by `project.json` exist; no recorded SHA-256 mismatch was found.
- The selected-region B-Rep demonstration produced valid STEP/STL output and an auditable operation journal. Its 3 mm directional hole cut reduced volume by approximately **14.137 mm³**.
- `compose.yaml` parsed successfully with **9 services**: application, PostgreSQL, MQTT, Mailpit, CAD worker, object store, Open WebUI, MQTT gateway and device simulator.
- The static structural check passed for all **8 Protobuf source files**. The `lps.v1` package remains intentionally unchanged as a wire-compatibility namespace.
- The package contains **12 JSON Schema documents plus `schemas/index.json`** and a TwinScript EBNF grammar. The packaged schema and grammar copies match the canonical files.
- The evolution catalogs contain:
  - **20 controlled verbs**;
  - **34 TwinStudio engineering dimensions**;
  - **17 evolution operators**;
  - three lifecycle templates with **30**, **19** and **10** stages;
  - **50 declared feature-lens slots**, of which **49 are active** and one remains explicitly unresolved from the supplied source material.
- TwinScript, YAML and JSON examples parse to the same canonical DSL document.
- A direct source-snapshot compile generated **48 goal variants, 26 resources, 48 candidates, 5 shortlisted candidates and 3 typed change plans**. A seeded event-sourced runtime adds derived resources; the packaged demonstration run contains **30 resources**.
- The portable demonstration bundle passed ZIP, manifest, file-size and SHA-256 verification. It contains **37 ZIP entries**, a project at stream version **73**, **15 objects**, **33 artifacts**, one evolution run, three change plans and one DSL execution, with no missing artifact.
- The browser DOM contract passed: no duplicate HTML IDs and no unresolved JavaScript element references.
- Python sources passed `compileall`.
- Browser JavaScript passed `node --check`.
- CLI discovery passed and exposed the DSL/evolution commands.
- **38 automated Python tests passed** in one regression run. One test launches the API in an isolated subprocess to verify startup, REST and MCP behavior without sharing application state.

The automated tests cover, among other things:

- POA parsing and scope enforcement;
- permissions, onboarding and optimistic concurrency;
- event reconstruction and CQRS commands;
- 2D/3D selection resolution and projection maps;
- scoped change planning and rejection outside the selected scope;
- allow-listed B-Rep edits;
- feature-lens and design-fixation analysis;
- TwinScript parsing, YAML/JSON equivalence, schema-backed compilation, evolution runs, lifecycle blueprints and generated artifacts;
- REST and web application paths, structured `ProblemEnvelope` errors and browser `UIContext` state;
- MCP discovery, 23-tool listing (including UI context and error playbooks), modern/legacy protocol flows and Origin rejection;
- power, thermal, human-use and mechanical evaluations;
- portable project export and manifest integrity.

## Live browser and Compose verification (2026-08-12 follow-up)

- The current full Python suite passes: **90 tests**.
- PostgreSQL health now performs an authenticated `SELECT 1` with the credentials of the initialized volume. The previous false-positive `pg_isready` check and repeated missing-role log entries are gone.
- A real headless Chromium session loaded `demo-rpi5`, 15 product-tree rows, both declared STL meshes and all three ordered 2D drawings (Front, Top, Side) in one scrollable view.
- The combined drawing download is a valid three-page vector A4 PDF; per-view 2D selection remains functional without the former view selector. A marked SVG projection region now infers `part/base` and `front.base.outer-wall` without a prior product-tree click, and the resulting selection successfully creates a scoped change plan. Projection metadata bypasses the browser cache, and a Playwright run with the metadata intentionally removed verified the ordered-polygon compatibility fallback.
- Every workspace tab has an authorized PDF export. Playwright downloaded all seven files: 3D embeds the current WebGL frame, selection overlay and selected POA object; 2D remains a three-page vector document; Specification/xBOM, Lifecycle, Tests, Feature lenses and Evolution/DSL contain the currently visible text. The download lifecycle is also recorded as `tab.pdf.*` URL/TWINOBS actions.
- The 3D viewer reported **2/2 meshes** and **20,096 rendered triangles**; the browser had no relevant console, page or failed-request errors.
- REST artifact downloads returned the full `base.stl` (406,084 bytes), and serialized UI-context updates exposed all five visible artifact URIs (two STL and three SVG) to REST and MCP without request-order races.
- Application request logs are emitted as JSON records with an embedded `TWINOBS 1.0` DSL and correlation identifier. Errors link to guarded `error/<CODE>.md` repair playbooks.
- Browser actions are retained in ordered, repeated URL `args` parameters with target and cursor coordinates. Text contents are excluded; only field lengths are recorded.
- The authorized project `logs.dsl` endpoint and top-bar clipboard action combine recent server TWINOBS records with URL-derived `UiAction` DSL. A rejected modern Clipboard API call falls back to the compatibility copy path, while a separate direct download remains independent of clipboard permission. Chromium verified both the actual clipboard payload and the rejected-permission fallback.
- The planner panel reports whether requests use the deterministic local planner or LiteLLM, displays elapsed and typical wait time, and tells the user that other tabs and fields remain usable while the captured selection is processed. A non-executable `add_annotation` plan is explicitly marked as not changing geometry, keeps Apply disabled, and explains that refreshing cannot regenerate STL/SVG artifacts.
- Saving an actionable annotation immediately creates a scoped plan and auto-applies allow-listed scalar parameter changes. The deterministic planner resolves an explicit relative instruction such as `zmniejsz wysokosc o 4mm` against the selected object's current value. The event-backed history lists annotations, plans, applications and compensating reverts; Chromium verified `height` changing from 25 to 21 mm and an undo back to the complete previous `ParameterValue`. Deferred CAD geometry remains queued rather than being reported as executed.
- Clicking an object row in the product tree highlights the corresponding mesh (or descendant meshes for an assembly) in 3D and all SVG regions carrying the same stable object URI in the Front, Top and Side drawings. Chromium verifies one highlighted `part/base` mesh and one mapped region on each drawing without replacing a compatible editable selection overlay; switching to an unrelated object clears the stale actionable selection.
- The event-backed change queue separates active work from audit history. Persisted plans are classified as ready, needing detail or waiting for CAD; transient planning/apply/undo states are merged in the browser. Chromium verified that an ambiguous task appears in the queue and marks the matching `Lower base` tree row, and that the persisted task can reopen its plan after a page refresh.
- Makefile lifecycle controls replace a stale TwinStudio process from the same workspace, persist PID/log state under ignored `.run/`, verify `/health`, and refuse to kill an unrelated process bound to the configured port.

## Source-archive and Python-package checks

- The source ZIP was extracted into a clean directory.
- All **319** entries in its internal `PACKAGE_MANIFEST.sha256` matched.
- The archive excludes the runtime SQLite database, `.pytest_cache`, `__pycache__` and Python bytecode.
- The complete **38-test** suite passed again from the extracted source archive.
- The extracted source built successfully as `twinstudio-0.5.0-py3-none-any.whl`.
- The wheel contains the browser assets, evolution and feature-lens catalogs, canonical DSL schema and EBNF grammar.
- Importing from the unpacked wheel confirmed that the packaged schema/grammar fallback works without the repository-level `schemas/` directory.
- A separate nested-venv editable-install attempt could not start because that container-created venv did not inherit `setuptools.build_meta`. This was treated as an environment limitation and replaced by the successful wheel build/import check; it is not claimed as an editable-install pass.

## Not executed for this 0.5.0 build

- A complete live Docker Compose deployment after adding the 0.5.0 evolution layer.
- A real LiteLLM provider request, because provider credentials and an external model endpoint were not used.
- `buf generate`/`protoc` code generation in this environment. Protobuf files received the included static check; compiler validation belongs in CI.
- A live MQTT/Open WebUI integration session or production SMTP delivery.
- KiCad CLI execution against a real PCB source project.
- Physical 3D printing, Raspberry Pi/Camera assembly, hinge cycling, cable/connector measurement, thermal/electrical bench validation, transport tests or a usability study.
- Arbitrary free-form B-Rep editing or reconstruction of native SolidWorks feature history. The included CAD adapter remains limited to allow-listed hole and local-box operations.

These exclusions are capability boundaries, not hidden pass claims. Evolution candidates are hypotheses until supported by simulation, prototype and test evidence.
