# Verification record

## Live runtime and publication addendum

Additional live verification was performed on 2026-08-11 after the original package-build record below:

- the base Compose stack (`app`, PostgreSQL, MQTT and Mailpit) was built and started;
- the application, PostgreSQL and Mailpit healthchecks passed, and MQTT accepted a live TCP connection;
- the application returned HTTP 200 for the web UI, health endpoint and OpenAPI document;
- startup seeding reconstructed `demo-rpi5` with 15 objects and 58 events in PostgreSQL;
- project tree, unified specification, power simulation, human-use evaluation and mechanical checks were queried over live REST;
- MCP `tools/list` returned 12 tools using the modern 2026-07-28 request shape;
- Mailpit API and MQTT connectivity were checked;
- all 24 recorded example artifacts existed and their SHA-256 hashes matched;
- the unpacked LPS example contained all 27 files declared by its internal manifest, with matching sizes and hashes;
- local validation passed 52 tests with one Node-only test skipped in the CAD container; the skipped JavaScript check passed separately with Node;
- GitHub Actions passed all 53 tests with Node available;
- `buf lint` passed under the `STANDARD` profile and Compose configuration validation passed;
- the public CI run completed successfully: <https://github.com/digitaltwin-run/twinstudio/actions/runs/31529121492>.

The local host used alternate ports `8400` and `8425` because the documented defaults were already occupied.
The published Compose file retains defaults `8000` and `8025` and permits overrides through
`LPS_HOST_PORT` and `MAILPIT_HOST_PORT`.

See `docs/18_PUBLICATION_HARDENING_SUMMARY_PL.md` for the issues found, corrections made and remaining
production-hardening priorities.

## Original package-build record

The following section preserves the earlier build-environment record from 2026-08-11. Its “not executed”
statements describe that earlier environment and are superseded by the live addendum where applicable.

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
