from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from housing_studio.artifacts import generate_artifacts
from housing_studio.llm_config import interpret_with_litellm
from housing_studio.models import ProjectConfig, default_project_config
from housing_studio.validation import collect_warnings, design_metrics
from housing_studio.version import __version__


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATED_ROOT = Path(
    os.getenv("HOUSING_GENERATED_DIR", str(PROJECT_ROOT / "generated"))
).resolve()
GENERATED_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Housing Studio",
    version=__version__,
    description=(
        "Parametric 2D/3D housing generator with visual layer controls, "
        "auditable LiteLLM configuration changes, and downloadable artifacts."
    ),
)
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "app" / "static"), name="static")
app.mount("/generated", StaticFiles(directory=GENERATED_ROOT), name="generated")
templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InterpretRequest(ApiModel):
    prompt: str = Field(min_length=1, max_length=30_000)
    config: dict[str, Any] | None = None


class ValidateRequest(ApiModel):
    config: dict[str, Any]


class GenerateRequest(ApiModel):
    config: dict[str, Any]
    source_prompt: str | None = Field(default=None, max_length=30_000)
    interpretation_mode: str | None = Field(default=None, max_length=120)
    configuration_changes: list[dict[str, Any]] | None = Field(default=None, max_length=2_000)


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


def _layer_summary(config: ProjectConfig) -> dict[str, Any]:
    return {
        "feature_layers": {
            name: {
                "enabled": layer.enabled,
                "label": layer.label,
                "notes": layer.notes,
            }
            for name, layer in config.feature_layers
        },
        "drawing_layers": {
            name: layer.model_dump(mode="json")
            for name, layer in config.drawing.layers
        },
        "artifact_outputs": config.artifacts.model_dump(mode="json"),
    }


def _job_summaries(limit: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for manifest_path in GENERATED_ROOT.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            job_id = _safe_job_identifier(str(manifest.get("job_id", manifest_path.parent.name)))
        except (OSError, ValueError, TypeError, json.JSONDecodeError, HTTPException):
            continue
        jobs.append(
            {
                "job_id": job_id,
                "created_at": manifest.get("created_at"),
                "project": manifest.get("project", {}),
                "warning_count": len(manifest.get("warnings", [])),
                "artifact_count": len(manifest.get("artifacts", [])),
                "generator_version": manifest.get("generator", {}).get("version"),
                "change_count": manifest.get("interpretation", {}).get("change_count", 0),
                "bundle_url": (
                    _url_for(job_id, manifest["bundle"]) if manifest.get("bundle") else None
                ),
            }
        )
    jobs.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return jobs[:limit]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "litellm_configured": bool(os.getenv("LITELLM_MODEL", "").strip()),
            "app_version": app.version,
        },
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": app.version,
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
        "layers": _layer_summary(config),
    }


@app.post("/api/validate")
async def validate_config(body: ValidateRequest) -> dict[str, Any]:
    config = _validated_config(body.config)
    return {
        "config": config.model_dump(mode="json"),
        "warnings": [warning.to_dict() for warning in collect_warnings(config)],
        "metrics": design_metrics(config),
        "layers": _layer_summary(config),
    }


@app.post("/api/interpret")
async def interpret(body: InterpretRequest) -> dict[str, Any]:
    current = _validated_config(body.config)
    result = await run_in_threadpool(interpret_with_litellm, body.prompt, current)
    return {
        "config": result.config.model_dump(mode="json"),
        "mode": result.mode,
        "message": result.message,
        "changes": result.changes,
        "warnings": [warning.to_dict() for warning in collect_warnings(result.config)],
        "metrics": design_metrics(result.config),
        "layers": _layer_summary(result.config),
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
            interpretation_mode=body.interpretation_mode,
            configuration_changes=body.configuration_changes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Artifact generation failed: {exc}") from exc
    return _manifest_with_urls(manifest)


@app.get("/api/jobs")
async def list_jobs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    return {"jobs": _job_summaries(limit)}


@app.get("/api/jobs/{job_id}/config")
async def get_job_config(job_id: str) -> dict[str, Any]:
    safe_job = _safe_job_identifier(job_id)
    config_path = GENERATED_ROOT / safe_job / "project_config.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Job configuration not found")
    try:
        config = ProjectConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as exc:
        raise HTTPException(status_code=500, detail=f"Stored configuration is invalid: {exc}") from exc
    return {
        "job_id": safe_job,
        "config": config.model_dump(mode="json"),
        "warnings": [warning.to_dict() for warning in collect_warnings(config)],
        "metrics": design_metrics(config),
        "layers": _layer_summary(config),
    }


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    safe_job = _safe_job_identifier(job_id)
    manifest_path = GENERATED_ROOT / safe_job / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return _manifest_with_urls(manifest)
