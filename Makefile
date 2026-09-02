.PHONY: help install start restart recreate stop kill status health logs logs-follow run foreground test lint compose-up compose-down compose-all seed schemas dsl-preview dsl-conformance eda-history-check verify proto-lint package

DEV_SERVER := ./scripts/dev_server.sh

help:
	@printf '%s\n' \
	  'TwinStudio local controls:' \
	  '  make start       replace any local TwinStudio instance and start in background' \
	  '  make restart     stop and recreate the background instance' \
	  '  make stop        stop the local instance' \
	  '  make status      show PID, port and health' \
	  '  make health      print the /health response' \
	  '  make logs        print the latest local server log lines' \
	  '  make logs-follow follow local server logs' \
	  '  make run         replace the instance and run in the foreground' \
	  '  make dsl-conformance validate NL/DSL boundary with wellmanifest/dsl' \
	  '' \
	  'Host and port come from TWINSTUDIO_HOST/TWINSTUDIO_PORT (.env.local first).'

install:
	python -m pip install -e ".[llm,dev]"

start:
	@$(DEV_SERVER) start

restart recreate:
	@$(DEV_SERVER) restart

stop kill:
	@$(DEV_SERVER) stop

status:
	@$(DEV_SERVER) status

health:
	@$(DEV_SERVER) health

logs:
	@$(DEV_SERVER) logs

logs-follow:
	@$(DEV_SERVER) logs-follow

run foreground:
	@$(DEV_SERVER) foreground

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

dsl-conformance:
	PYTHONPATH=src python scripts/verify_dsl_conformance.py

eda-history-check:
	PYTHONPATH=src python scripts/verify_eda_history.py --allow-missing

verify:
	PYTHONPATH=src python scripts/verify_project.py --run-tests --out docs/verification-report.json

proto-lint:
	docker run --rm -v "$(PWD):/workspace" -w /workspace bufbuild/buf:latest lint

package:
	twinstudio export --project-id demo-rpi5 --out data/artifacts/demo-rpi5.twinstudio.zip
