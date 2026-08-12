.PHONY: install install-llm dev generate test clean

install:
	python -m pip install -e .

install-llm:
	python -m pip install -e ".[llm]"

dev:
	uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

generate:
	python generator.py --config examples/rpi5_enclosure.json --out generated --job-id demo

test:
	pytest

clean:
	rm -rf generated .pytest_cache .ruff_cache
