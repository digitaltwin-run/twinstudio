# Verification record

Verification performed in the build environment on 2026-08-11.

## Passed checks

- Pydantic validation of the complete example project.
- 15 product/object nodes reconstructed.
- 24 example source/generated artifacts found; all recorded hashes matched.
- Selected-region B-Rep demonstration generated a valid single-solid STEP/STL result; the 3 mm hole cut reduced volume by approximately 14.137 mm³ and produced an auditable JSON journal.
- Compose YAML parsed with 9 services.
- Static structural check of 8 Protobuf source files: syntax declaration, package, local imports and balanced braces.
- Browser JavaScript passed `node --check`.
- Python source compiled with `compileall`.
- 26 automated tests passed.
- Tests cover POA parsing/scope, role permissions, GTIN check digit, event reconstruction, optimistic concurrency, selection resolution, 2D projection mapping, local scoped planning, scope rejection, allow-listed derived B-Rep hole editing, CAD scope rejection, deferred unsupported geometry, power/thermal/human/mechanical evaluation, project export, primary REST paths, email approval onboarding, modern MCP discovery and mirrored-header validation, unsupported-version handling, Base64 `Mcp-Name`, legacy initialization fallback and Origin rejection.
- Editable package installation and CLI discovery worked with `pip --no-build-isolation --no-deps -e .` in the offline environment.
- CLI seed, power simulation and project export completed.
- Example `.lps.zip` export contained 28 files/entries and reported no missing artifacts.
- Synthetic camera-image analysis ran and produced deterministic JSON output.

Machine-readable details: `docs/verification-report.json`.

## Not executed in this environment

- Docker image builds and live Compose orchestration, because Docker was unavailable.
- `buf lint`, `buf generate` or `protoc` compiler validation, because Buf/protoc were unavailable and the environment had no package-network access. The `.proto` files passed only the included static structural check.
- A real LiteLLM provider request, because no provider credentials/network were used.
- Live MQTT broker interoperability, MCP client/Open WebUI connection or production SMTP delivery.
- KiCad CLI adapter execution, because no KiCad source project or `kicad-cli` was installed.
- Physical 3D printing, Raspberry Pi/Camera assembly, cable/connector measurement, thermal calibration, transport testing, usability study or bench electrical validation.
- Arbitrary/free-form local B-Rep editing and native parametric history reconstruction. The included adapter was exercised for a selected directional hole cut and scope rejection, but only allow-listed hole/local-box operations are implemented.

These exclusions are capability boundaries, not hidden pass claims.
