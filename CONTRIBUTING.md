# Contributing

## Change workflow

1. Create an issue or project annotation describing the requirement/evidence.
2. Work on a branch; do not rewrite released event fixtures.
3. Add/update domain schema and Protobuf together.
4. Add tests for permissions, POA scope, event replay and adapter behavior.
5. Regenerate JSON schemas.
6. Run `python scripts/verify_project.py --run-tests`.
7. Submit a pull request with screenshots/artifacts and explicit implementation limitations.
8. Require review from the owning engineering domain and an admin/creator for lifecycle/commercial changes.

## Adapter requirements

An engineering adapter must:

- accept typed operations only;
- verify project/revision and selected POA scope;
- map stable native IDs to POA;
- be idempotent or use a job idempotency key;
- run tool-native checks after modification;
- return generator/tool versions, diagnostics and artifact hashes;
- never silently broaden a selected region;
- fail closed when topology/UUID mapping is stale.

## Style

- Python 3.11–3.13, type hints and Pydantic validation.
- Keep domain models independent from individual CAD/PCB tools.
- State assumptions and confidence; do not convert provisional evidence into approved facts automatically.
