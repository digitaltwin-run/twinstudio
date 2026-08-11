#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from housing_studio.artifacts import generate_artifacts
from housing_studio.llm_config import interpret_with_litellm
from housing_studio.models import ProjectConfig, default_project_config


def load_config(path: Path | None) -> ProjectConfig:
    if path is None:
        return default_project_config()
    return ProjectConfig.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a parametric two-part housing in 2D and 3D."
    )
    parser.add_argument("--config", type=Path, help="Input ProjectConfig JSON file")
    parser.add_argument("--prompt", help="Natural-language change request interpreted through LiteLLM")
    parser.add_argument("--prompt-file", type=Path, help="Read natural-language changes from a text file")
    parser.add_argument("--out", type=Path, default=Path("generated"), help="Generated jobs directory")
    parser.add_argument("--job-id", help="Optional deterministic job directory name")
    parser.add_argument("--print-config", action="store_true", help="Print the validated final config")
    parser.add_argument("--serve", action="store_true", help="Start the FastAPI web application")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.serve:
        import uvicorn

        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
        return 0

    config = load_config(args.config)
    prompt = args.prompt
    if args.prompt_file:
        prompt = args.prompt_file.read_text(encoding="utf-8")
    if prompt:
        interpretation = interpret_with_litellm(prompt, config)
        config = interpretation.config
        print(f"Interpretation mode: {interpretation.mode}")
        print(interpretation.message)

    if args.print_config:
        print(config.model_dump_json(indent=2))

    manifest = generate_artifacts(
        config,
        args.out,
        job_id=args.job_id,
        source_prompt=prompt,
    )
    job_dir = args.out.resolve() / manifest["job_id"]
    print(json.dumps({
        "job_id": manifest["job_id"],
        "job_dir": str(job_dir),
        "artifact_count": len(manifest["artifacts"]),
        "bundle": str(job_dir / manifest["bundle"]) if manifest.get("bundle") else None,
        "warnings": manifest["warnings"],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
