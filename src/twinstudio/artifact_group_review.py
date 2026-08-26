"""Read-only, bounded LLM review for one project artifact group."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from twinstudio.kicad_dsl import DslModel, KicadDslError, eda_litellm_route

logger = logging.getLogger(__name__)

MAX_FILES = 40
MAX_FILE_BYTES = 48_000
TEXT_SUFFIXES = {
    ".py", ".c", ".h", ".cpp", ".hpp", ".js", ".ts", ".json", ".toml", ".yaml", ".yml",
    ".md", ".txt", ".ini", ".cfg", ".sh", ".kicad_pro", ".kicad_sch", ".kicad_pcb",
}


class GroupReviewFile(DslModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    included: bool
    note: str = ""


class GroupReviewFinding(DslModel):
    severity: Literal["info", "warning", "error"] = "info"
    message: str = Field(min_length=1, max_length=2_000)
    files: list[str] = Field(default_factory=list, max_length=20)


class ArtifactGroupReview(DslModel):
    schema_id: Literal["twinstudio.artifact-group-review/v1"] = "twinstudio.artifact-group-review/v1"
    # These values are immutable Viewer context and are overwritten by the
    # service after parsing. Keeping them optional in the LLM response avoids
    # rejecting an otherwise useful review merely because it did not echo them.
    group: str = Field(default="nieokreślona grupa", min_length=1, max_length=2_000)
    prompt: str = Field(default="brak promptu", min_length=1, max_length=30_000)
    files: list[GroupReviewFile] = Field(default_factory=list)
    mode: str = "subllm"
    summary: str = Field(min_length=1, max_length=4_000)
    findings: list[GroupReviewFinding] = Field(default_factory=list, max_length=40)
    next_steps: list[str] = Field(default_factory=list, max_length=20)
    requires_human_review: bool = True


def _safe_file(root: Path, relative: str) -> Path:
    if not relative or "\x00" in relative or Path(relative).is_absolute():
        raise KicadDslError("artifact path must be a relative project file")
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise KicadDslError(f"artifact is outside the project root or unavailable: {relative}")
    return path


def _local_review(group: str, prompt: str, files: list[GroupReviewFile]) -> ArtifactGroupReview:
    names = ", ".join(item.path for item in files[:8])
    omitted = sum(not item.included for item in files)
    return ArtifactGroupReview(
        group=group,
        prompt=prompt,
        files=files,
        mode="local-fallback",
        summary=f"Grupa zawiera {len(files)} plików. Zadanie: {prompt}",
        findings=[GroupReviewFinding(
            severity="info",
            message=("Analiza lokalna obejmuje metadane i ograniczony kontekst tekstowy. "
                     f"Pliki: {names or 'brak'}"),
            files=[item.path for item in files[:8]],
        )],
        next_steps=[
            "Przejrzyj wskazane pliki i wykonaj testy właściwe dla tej grupy.",
            *( [f"{omitted} plików nie przekazano w całości do modelu; otwórz je przed zmianą."] if omitted else [] ),
        ],
    )


def _parse_review_response(content: Any) -> ArtifactGroupReview:
    """Accept JSON returned directly or wrapped in a Markdown code fence."""
    text = str(content).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    return ArtifactGroupReview.model_validate_json(text)


def _llm_routes(settings: Any) -> list[tuple[dict[str, Any], str, bool]]:
    """Return every permitted SubLLM route, ordered by the shared policy."""
    if getattr(settings, "subllm_enabled", False):
        from subllm import available_routes

        routes = available_routes(
            settings.subllm_application,
            getattr(settings, "subllm_audit_function", "eda-firmware-audit"),
        )
        return [
            (route.litellm_kwargs(), f"subllm:{route.provider}/{route.model}", route.provider != "zai")
            for route in routes
            if route.transport == "openai-compatible"
        ]
    resolved = eda_litellm_route(
        settings, getattr(settings, "subllm_audit_function", "eda-firmware-audit")
    )
    return [resolved] if resolved is not None else []


def review_artifact_group(
    root: Path, group: str, paths: list[str], prompt: str, settings: Any
) -> ArtifactGroupReview:
    if not paths or len(paths) > MAX_FILES:
        raise KicadDslError(f"group review requires 1 to {MAX_FILES} files")
    context: list[dict[str, str]] = []
    files: list[GroupReviewFile] = []
    for relative in paths:
        path = _safe_file(root, relative)
        raw = path.read_bytes()
        included = path.suffix.casefold() in TEXT_SUFFIXES and len(raw) <= MAX_FILE_BYTES
        note = ""
        if not included:
            note = "binary, unsupported or larger than review limit"
        else:
            context.append({"path": relative, "content": raw.decode("utf-8", errors="replace")})
        files.append(GroupReviewFile(
            path=relative, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw), included=included, note=note,
        ))
    fallback = _local_review(group, prompt, files)
    try:
        routes = _llm_routes(settings)
    except Exception as exc:
        logger.warning("artifact-group review could not resolve SubLLM route: %s", exc)
        return fallback.model_copy(update={"mode": f"local-fallback:{type(exc).__name__}"})
    if not routes:
        return fallback
    failures: list[Exception] = []
    for route_kwargs, mode, supports_response_schema in routes:
        try:
            from litellm import completion

            schema = ArtifactGroupReview.model_json_schema()
            kwargs: dict[str, Any] = {
                **route_kwargs,
                "timeout": 45,
                "num_retries": 0,
                "max_tokens": 1_200,
                "messages": [
                    {"role": "system", "content": (
                        "Review only the supplied project artifact group. Return one JSON object matching the schema. "
                        "Do not claim that code was edited, do not execute commands, and clearly separate evidence from suggestions."
                    )},
                    {"role": "user", "content": json.dumps({
                        "group": group, "prompt": prompt, "files": [item.model_dump(mode="json") for item in files],
                        "source_context": context, "output_schema": schema,
                    }, ensure_ascii=False)},
                ],
            }
            if supports_response_schema:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "artifact_group_review", "strict": True, "schema": schema},
                }
            response = completion(**kwargs)
            content = response.choices[0].message.content
            if isinstance(content, list):
                content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
            if not str(content or "").strip():
                raise ValueError("LLM-EMPTY-RESPONSE-001: provider returned an empty completion")
            review = _parse_review_response(content)
            return review.model_copy(update={"group": group, "prompt": prompt, "files": files, "mode": mode})
        except Exception as exc:
            failures.append(exc)
            logger.warning("artifact-group review route %s rejected: %s", mode, exc)
    last = failures[-1] if failures else RuntimeError("no LLM route was attempted")
    return fallback.model_copy(update={"mode": f"local-fallback:{type(last).__name__}"})
