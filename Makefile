.PHONY: install run test lint compose-up compose-down compose-all seed schemas proto-lint package
install:
	python -m pip install -e ".[llm,dev]"
run:
	uvicorn living_product_studio.api:app --reload --host 0.0.0.0 --port 8000
test:
	pytest
lint:
	ruff check src tests
compose-up:
	docker compose up --build
compose-all:
	docker compose --profile cad --profile integration --profile openwebui --profile object-store --profile simulation up --build
compose-down:
	docker compose down -v
seed:
	lps seed --example examples/rpi5-camera3/project.json
schemas:
	python scripts/generate_schemas.py
proto-lint:
	docker run --rm -v "$(PWD):/workspace" -w /workspace bufbuild/buf:latest lint
package:
	python scripts/export_project.py --project demo-rpi5 --out data/artifacts/demo-rpi5.lps.zip
