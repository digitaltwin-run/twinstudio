from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from housing_studio.artifacts import generate_artifacts
from housing_studio.llm_config import interpret_with_litellm
from housing_studio.models import ProjectConfig, default_project_config
from housing_studio.validation import collect_warnings, design_metrics


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATED_ROOT = Path(
    os.getenv("HOUSING_GENERATED_DIR", str(PROJECT_ROOT / "generated"))
).resolve()
GENERATED_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Housing Studio",
    version="1.0.0",
    description="Parametric 2D/3D housing generator with LiteLLM-assisted configuration.",
)
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "app" / "static"), name="static")
app.mount("/generated", StaticFiles(directory=GENERATED_ROOT), name="generated")
templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InterpretRequest(ApiModel):
    prompt: str = Field(min_length=1, max_length=30_000)
    config: dict[str, Any] | None = None


class GenerateRequest(ApiModel):
    config: dict[str, Any]
    source_prompt: str | None = Field(default=None, max_length=30_000)


def _validated_config(data: dict[str, Any] | None) -> ProjectConfig:
    try:
        return ProjectConfig.model_validate(data) if data is not None else default_project_config()
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc


def _safe_job_identifier(value: str) -> str:
    identifier = value.strip()
    if (
        not identifier
        or identifier in {".", ".."}
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", identifier)
    ):
        raise HTTPException(status_code=400, detail="Invalid job identifier")
    return identifier


def _url_for(job_id: str, relative_path: str) -> str:
    safe_job = _safe_job_identifier(job_id)
    parts = [quote(part) for part in Path(relative_path).parts]
    return f"/generated/{quote(safe_job)}/" + "/".join(parts)


def _manifest_with_urls(manifest: dict[str, Any]) -> dict[str, Any]:
    job_id = manifest["job_id"]
    result = json.loads(json.dumps(manifest))
    for artifact in result.get("artifacts", []):
        artifact["url"] = _url_for(job_id, artifact["path"])
    preview = result.get("preview", {})
    for key in ("base_stl", "lid_stl", "closed_glb", "open_glb"):
        if preview.get(key):
            preview[f"{key}_url"] = _url_for(job_id, preview[key])
    if result.get("bundle"):
        result["bundle_url"] = _url_for(job_id, result["bundle"])
    return result


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "litellm_configured": bool(os.getenv("LITELLM_MODEL", "").strip()),
        },
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "generated_root": str(GENERATED_ROOT),
        "litellm_configured": bool(os.getenv("LITELLM_MODEL", "").strip()),
    }


@app.get("/api/default-config")
async def default_config() -> dict[str, Any]:
    config = default_project_config()
    return {
        "config": config.model_dump(mode="json"),
        "warnings": [warning.to_dict() for warning in collect_warnings(config)],
        "metrics": design_metrics(config),
    }


@app.post("/api/interpret")
async def interpret(body: InterpretRequest) -> dict[str, Any]:
    current = _validated_config(body.config)
    result = await run_in_threadpool(interpret_with_litellm, body.prompt, current)
    return {
        "config": result.config.model_dump(mode="json"),
        "mode": result.mode,
        "message": result.message,
        "warnings": [warning.to_dict() for warning in collect_warnings(result.config)],
        "metrics": design_metrics(result.config),
    }


@app.post("/api/generate")
async def generate(body: GenerateRequest) -> dict[str, Any]:
    config = _validated_config(body.config)
    try:
        manifest = await run_in_threadpool(
            generate_artifacts,
            config,
            GENERATED_ROOT,
            source_prompt=body.source_prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Artifact generation failed: {exc}") from exc
    return _manifest_with_urls(manifest)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    safe_job = _safe_job_identifier(job_id)
    manifest_path = GENERATED_ROOT / safe_job / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return _manifest_with_urls(manifest)
