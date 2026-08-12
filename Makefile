.PHONY: install run test lint compose-up compose-down compose-all seed schemas dsl-preview verify proto-lint package

install:
	python -m pip install -e ".[llm,dev]"

run:
	uvicorn twinstudio.api:app --reload --host 0.0.0.0 --port 8000

test:
	PYTHONPATH=src python -m pytest -q

lint:
	ruff check src tests

compose-up:
	docker compose up --build

compose-all:
	docker compose --profile cad --profile integration --profile openwebui --profile object-store --profile simulation up --build

compose-down:
	docker compose down -v

seed:
	twinstudio seed --example examples/rpi5-camera3/project.json

schemas:
	PYTHONPATH=src python scripts/generate_schemas.py

dsl-preview:
	twinstudio dsl-preview examples/evolution/rpi5-hinge-evolution.twin --project-id demo-rpi5

verify:
	PYTHONPATH=src python scripts/verify_project.py --run-tests --out docs/verification-report.json

proto-lint:
	docker run --rm -v "$(PWD):/workspace" -w /workspace bufbuild/buf:latest lint

package:
	twinstudio export --project-id demo-rpi5 --out data/artifacts/demo-rpi5.twinstudio.zip
